"""F.E.E. Agent – Web-Server (FastAPI).

Start:  python -m feeagent.server   (oder ./run.sh)
GUI:    http://localhost:8765
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agent
from . import graph as fee_graph
from . import headroom
from . import memory as fee_memory
from . import ocr

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = BASE / "web"
CONFIG_FILE = BASE / "feeagent" / "config.json"

DEFAULT_CONFIG = {
    "endpoint": "http://localhost:8080/v1",
    "model": "local-model",
    "api_key": "",
}

app = FastAPI(title="F.E.E. Agent", version="0.1.0")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ Modelle

class Settings(BaseModel):
    endpoint: str
    model: str
    api_key: str = ""


class ChatRequest(BaseModel):
    mandate: str
    question: str


class MandateCreate(BaseModel):
    slug: str
    anzeigename: str


# ------------------------------------------------------------------ API

@app.get("/api/settings")
def get_settings():
    return load_config()


@app.post("/api/settings")
def set_settings(s: Settings):
    save_config(s.model_dump())
    return {"ok": True}


@app.get("/api/mandates")
def mandates():
    return agent.list_mandates()


@app.post("/api/mandates")
def new_mandate(m: MandateCreate):
    if not m.slug:
        raise HTTPException(400, "slug fehlt")
    p = agent.create_mandate(m.slug, m.anzeigename)
    return {"ok": True, "slug": p.name, "pfad": str(p)}


@app.get("/api/mandates/{slug}")
def mandate_detail(slug: str):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    ctx = ""
    md = p / "MANDAT.md"
    if md.exists():
        ctx = md.read_text(encoding="utf-8")[:8000]
    fristen = ""
    fr = p / "fristen.md"
    if fr.exists():
        fristen = fr.read_text(encoding="utf-8")
    return {"slug": slug, "mandat_md": ctx, "fristen_md": fristen,
            "pfad": str(p)}


@app.post("/api/mandates/{slug}/documents")
async def upload_document(slug: str, file: UploadFile = File(...)):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    tmp = Path("/tmp") / file.filename
    tmp.write_bytes(await file.read())
    try:
        result = headroom.run_heavy(ocr.process_document, tmp, p)
        if result.get("ok"):
            fee_graph.save(p)  # Wissensgraph nach neuem Dokument aktualisieren
    except RuntimeError as e:
        result = {"ok": False, "fehler": str(e)}
    tmp.unlink(missing_ok=True)
    if not result.get("ok"):
        return JSONResponse(status_code=422, content=result)
    return result


@app.post("/api/mandates/{slug}/chat")
def chat(slug: str, req: ChatRequest):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    ctx = ""
    md = p / "MANDAT.md"
    if md.exists():
        ctx = md.read_text(encoding="utf-8")[:8000]
    # Dokumenten-Volltexte als Kontext (max. 3 neueste)
    dok_dir = p / "dokumente"
    if dok_dir.exists():
        for doc in sorted(dok_dir.glob("*.txt"), reverse=True)[:3]:
            ctx += f"\n\n--- Dokument {doc.stem} ---\n" + \
                doc.read_text(encoding="utf-8", errors="replace")[:6000]
    result = agent.run_workflow(req.question, ctx, load_config(),
                                mandate_dir=p)
    return result


@app.get("/api/mandates/{slug}/graph")
def mandate_graph(slug: str):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return fee_graph.save(p)


@app.get("/api/mandates/{slug}/memory")
def mandate_memory(slug: str, q: str = ""):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    if q:
        return fee_memory.search(p, q)
    return fee_memory.all_entries(p)


class MemoryAdd(BaseModel):
    typ: str
    inhalt: str


@app.post("/api/mandates/{slug}/memory")
def mandate_memory_add(slug: str, m: MemoryAdd):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return fee_memory.add(p, m.typ, m.inhalt, quelle="gui")


@app.get("/api/headroom")
def headroom_status():
    return headroom.status()


# ------------------------------------------------------------------ GUI

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def main():
    import uvicorn
    port = int(os.environ.get("FEE_AGENT_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
