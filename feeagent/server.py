"""F.E.E. Agent – Web-Server (FastAPI).

Start:  python -m feeagent.server   (oder ./run.sh)
GUI:    http://localhost:8765
"""
import json
import os
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agent
from . import auth
from . import graph as fee_graph
from . import headroom
from . import memory as fee_memory
from . import netconfig
from . import ocr

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = BASE / "web"
# Konfiguration außerhalb des Repos – überlebt git pull / Updates
CONFIG_DIR = Path.home() / ".config" / "fee-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Alte Lage (im Repo) migrieren, falls vorhanden
_OLD_CONFIG = BASE / "feeagent" / "config.json"
if _OLD_CONFIG.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _OLD_CONFIG.rename(CONFIG_FILE)

DEFAULT_CONFIG = {
    "endpoint": "http://localhost:8080/v1",
    "model": "local-model",
    "api_key": "",
}

app = FastAPI(title="F.E.E. Agent", version="0.2.0")
LAN = netconfig.lan_info()

# Kein Login nötig: GUI (zeigt selbst das Login-Overlay) und Login-Endpunkt
OFFEN = ("/", "/api/login")


@app.middleware("http")
async def guard(request, call_next):
    client = request.client.host if request.client else ""
    if not netconfig.client_allowed(client, LAN["ip"]):
        return JSONResponse(status_code=403,
                            content={"detail": "Netzwerk nicht erlaubt"})
    if request.url.path not in OFFEN:
        sess = auth.session(request.cookies.get("fee_session", ""))
        if not sess:
            return JSONResponse(status_code=401,
                                content={"detail": "Nicht angemeldet"})
        request.state.user = sess
    return await call_next(request)


def require_admin(request) -> dict:
    s = getattr(request.state, "user", None)
    if not s or s["role"] != "admin":
        raise HTTPException(403, "Admin-Rechte erforderlich")
    return s


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

class LoginRequest(BaseModel):
    username: str
    password: str


class UserRole(BaseModel):
    username: str
    role: str


@app.post("/api/login")
def do_login(l: LoginRequest):
    sess = auth.login(l.username, l.password)
    if not sess:
        raise HTTPException(401, "Anmeldung fehlgeschlagen (PC-Konto prüfen)")
    resp = JSONResponse(content={"user": sess["user"], "role": sess["role"]})
    resp.set_cookie("fee_session", sess["token"], httponly=True,
                    samesite="strict")
    return resp


@app.post("/api/logout")
def do_logout():
    # Token steckt im Cookie; Ausloggen = Cookie löschen + Sitzung verwerfen
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie("fee_session")
    return resp


@app.get("/api/me")
def me(request: Request):
    return getattr(request.state, "user",
                   {"user": "", "role": ""})


@app.get("/api/users")
def users_list(request: Request):
    require_admin(request)
    return auth.load_users()


@app.post("/api/users")
def users_register(request: Request, u: UserRole):
    require_admin(request)
    if not auth.register(u.username, u.role):
        raise HTTPException(400, "Nutzer/Rolle ungültig")
    return {"ok": True}


@app.post("/api/users/role")
def users_role(request: Request, u: UserRole):
    require_admin(request)
    if not auth.set_role(u.username, u.role):
        raise HTTPException(404, "Nutzer nicht gefunden")
    return {"ok": True}


@app.post("/api/users/remove")
def users_remove(request: Request, u: UserRole):
    require_admin(request)
    if not auth.remove(u.username):
        raise HTTPException(404, "Nutzer nicht gefunden")
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return load_config()


@app.post("/api/models")
def list_models(request: Request, s: Settings):
    """Modelle eines OpenAI-kompatiblen Endpoints für die Dropdown-Auswahl."""
    require_admin(request)
    url = s.endpoint.rstrip("/") + "/models"
    headers = {}
    if s.api_key:
        headers["Authorization"] = f"Bearer {s.api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Endpoint nicht erreichbar: {e}")
    modelle = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    if not modelle:
        raise HTTPException(502, "Endpoint lieferte keine Modelle")
    return modelle


@app.post("/api/settings")
def set_settings(s: Settings, request: Request):
    require_admin(request)
    save_config(s.model_dump())
    return {"ok": True}


@app.get("/api/mandates")
def mandates():
    return agent.list_mandates()


@app.delete("/api/mandates/{slug}")
def delete_mandate(slug: str, request: Request):
    """Mandat archivieren (nach _archiv/), nicht löschen – Rechtsdaten."""
    require_admin(request)
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    archiv = agent.MANDATE_DIR / "_archiv"
    archiv.mkdir(exist_ok=True)
    ziel = archiv / f"{slug}-{int(__import__('time').time())}"
    p.rename(ziel)
    return {"ok": True, "archiv": str(ziel)}


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
    # filename sanitizen: "../../x" darf nicht aus /tmp ausbrechen
    safe_name = Path(file.filename or "upload").name
    tmp = Path("/tmp") / safe_name
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
    # Browser-Cache sperren: die GUI ändert sich mit jedem Update
    return FileResponse(WEB_DIR / "index.html",
                        headers={"Cache-Control": "no-store"})


def main():
    import uvicorn
    port = int(os.environ.get("FEE_AGENT_PORT", "8765"))
    # An alle Interfaces binden – Zugriff regelt die Middleware (Subnetz-Sperre)
    print(f"GUI im Netzwerk: http://{LAN['ip']}:{port}  (Subnetz {LAN['subnetz']})")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
