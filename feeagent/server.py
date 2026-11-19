"""F.E.E. Agent – Web-Server (FastAPI).

Start:  python -m feeagent.server   (oder ./run.sh)
GUI:    http://localhost:8765
"""
import json
import os
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agent
from . import auth
from . import db
from . import graph as fee_graph
from . import headroom
from . import memory as fee_memory
from . import netconfig
from . import ocr

db.init()  # SQLite-DB + Migration alter JSON-Dateien beim Start

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = BASE / "web"
# Einstellungen liegen in der SQLite-DB (~/.config/fee-agent/feeagent.db)
# – überlebt Updates. Alte config.json wird beim ersten Zugriff importiert.

DEFAULT_CONFIG = {
    "endpoint": "http://localhost:8080/v1",
    "model": "local-model",
    "api_key": "",
}

app = FastAPI(title="F.E.E. Agent", version="0.3.0")
LAN = netconfig.lan_info()

# Kein Login nötig: GUI (zeigt selbst das Login-Overlay) und Login-Endpunkt
OFFEN = ("/", "/api/login")


@app.middleware("http")
async def guard(request, call_next):
    client = request.client.host if request.client else ""
    if not netconfig.client_allowed(client, LAN["ip"]):
        return JSONResponse(status_code=403,
                            content={"detail": "Netzwerk nicht erlaubt"})
    if request.url.path not in OFFEN and not request.url.path.startswith("/portal/"):
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
    return db.get_settings(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    db.set_settings(cfg)


# ------------------------------------------------------------------ Modelle

class Settings(BaseModel):
    endpoint: str
    model: str
    api_key: str = ""
    stundensatz: str = ""   # €/h für Rechnungen


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


@app.post("/api/test")
def test_verbindung(request: Request, s: Settings):
    """Mini-Chat an den Endpoint – zeigt sofort, ob Token/Modell stimmen."""
    require_admin(request)
    try:
        antwort = agent.llm_chat(s.endpoint, s.model or "test",
                                 "Du bist ein Verbindungstest.",
                                 "Antworte nur mit: ok", s.api_key, timeout=30)
        return {"ok": True, "antwort": antwort.strip()[:60]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "fehler": str(e)[:200]}


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
    # filename sanitizen: "../../x" darf nicht aus der Temp-Datei ausbrechen
    # shortcut: tempfile statt /tmp/shared-name, sonst Race bei gleichen Namen
    import tempfile
    safe_name = Path(file.filename or "upload").name
    with tempfile.NamedTemporaryFile(prefix="fee_", suffix="_" + safe_name,
                                     delete=False) as tf:
        tf.write(await file.read())
        tmp = Path(tf.name)
    try:
        result = headroom.run_heavy(ocr.process_document, tmp, p)
        if result.get("ok"):
            fee_graph.save(p)  # Wissensgraph nach neuem Dokument aktualisieren
            # Fristen automatisch aus allen Dokumenten erkennen und eintragen
            from . import fristen as fee_fristen
            fee_fristen.auto_eintragen(p, slug, db)
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


class MemoryAdd(BaseModel):
    typ: str
    inhalt: str


@app.post("/api/mandates/{slug}/notes")
def add_note(slug: str, m: MemoryAdd):
    """Handnotiz (Telefonat/Gedanke) zum Mandat – in der DB, mit Datum."""
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    if m.typ not in ("telefonat", "notiz", "aufgabe"):
        raise HTTPException(400, "Typ ungültig (telefonat|notiz|aufgabe)")
    return fee_memory.add(p, m.typ, m.inhalt, quelle="handnotiz")


@app.get("/api/mandates/{slug}/notes")
def list_notes(slug: str):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return [e for e in fee_memory.all_entries(p) if e["quelle"] == "handnotiz"]



class Kontakt(BaseModel):
    rolle: str   # mandant|gegner|gericht|zeuge|sonstiges
    name: str
    kontakt: str = ""


@app.delete("/api/mandates/{slug}/notes/{note_id}")
def del_note(slug: str, note_id: int):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    db.delete_note(p, note_id)
    return {"ok": True}


# ------------------------------------------------------------------ Fristen

class Frist(BaseModel):
    datum: str   # JJJJ-MM-TT
    text: str
    vorfrist_tage: int = 0


@app.get("/api/fristen")
def alle_fristen_api():
    """Wiedervorlage: Fristen über alle Mandate, sortiert."""
    return db.alle_fristen()


@app.get("/api/mandates/{slug}/fristen")
def fristen_liste(slug: str):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return db.fristen(slug)


@app.post("/api/mandates/{slug}/fristen")
def frist_neu(slug: str, f: Frist):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    import re as _re
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", f.datum) or not f.text.strip():
        raise HTTPException(400, "Datum (JJJJ-MM-TT) und Text erforderlich")
    return db.add_frist_mit_vorfrist(slug, f.datum, f.text.strip()[:500],
                                     f.vorfrist_tage)


@app.post("/api/mandates/{slug}/fristen/{fid}/erledigt")
def frist_erledigt(slug: str, fid: int):
    db.frist_erledigt(fid, slug)
    return {"ok": True}


# ------------------------------------------------------------------ Kontakte

@app.get("/api/mandates/{slug}/kontakte")
def kontakte_liste(slug: str):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return db.kontakte(slug)


@app.post("/api/mandates/{slug}/kontakte")
def kontakt_neu(slug: str, k: Kontakt):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    if k.rolle not in ("mandant", "gegner", "gericht", "zeuge", "sonstiges") \
            or not k.name.strip():
        raise HTTPException(400, "Rolle oder Name ungültig")
    r = db.kontakt_add(slug, k.rolle, k.name.strip(), k.kontakt.strip()[:300])
    if k.rolle == "gegner":
        r["kollision"] = db.kollisionspruefung(slug, k.name.strip())
    return r


@app.delete("/api/mandates/{slug}/kontakte/{kid}")
def kontakt_weg(slug: str, kid: int):
    db.kontakt_del(kid, slug)
    return {"ok": True}


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


# ------------------------------------------------------------------ Zeiten

class Zeit(BaseModel):
    datum: str   # JJJJ-MM-TT
    minuten: int
    text: str


@app.get("/api/mandates/{slug}/zeiten")
def zeiten_liste(slug: str):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return {"eintraege": db.zeiten(slug), "summe": db.zeiten_summe(slug)}


@app.post("/api/mandates/{slug}/zeiten")
def zeit_neu(slug: str, z: Zeit):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    import re as _re
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", z.datum) or not z.text.strip() \
            or not (1 <= z.minuten <= 24 * 60):
        raise HTTPException(400, "Datum (JJJJ-MM-TT), Minuten (1-1440) und Text erforderlich")
    return db.zeit_add(slug, z.datum, z.minuten, z.text.strip()[:500])


@app.delete("/api/mandates/{slug}/zeiten/{zid}")
def zeit_weg(slug: str, zid: int):
    db.zeit_del(zid, slug)
    return {"ok": True}


@app.post("/api/mandates/{slug}/zeiten/abrechnen")
def zeiten_abrechnen(slug: str):
    """Alle offenen Zeiten als abgerechnet markieren (Rechnungsvorbereitung)."""
    n = db.zeiten_abrechnen(slug)
    return {"ok": True, "abgerechnet": n, "summe": db.zeiten_summe(slug)}


# ------------------------------------------------------------------ Rechnungen

@app.get("/api/mandates/{slug}/rechnungen")
def rechnungen_liste(slug: str):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return db.rechnungen(slug)


@app.post("/api/mandates/{slug}/rechnungen")
def rechnung_neu(slug: str, request: Request):
    """Rechnung aus abgerechneten, noch nicht fakturierten Zeiten erstellen."""
    require_admin(request)
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    stundensatz = float(load_config().get("stundensatz", 0) or 0)
    if stundensatz <= 0:
        raise HTTPException(400, "Erst einen Stundensatz in den Einstellungen festlegen")
    r = db.rechnung_erstellen(slug, stundensatz)
    if not r:
        raise HTTPException(400, "Keine offenen (abgerechneten) Zeiten vorhanden")
    return r


@app.get("/api/mandates/{slug}/rechnungen/{rid}")
def rechnung_detail(slug: str, rid: int):
    r = db.rechnung(rid, slug)
    if not r:
        raise HTTPException(404, "Rechnung nicht gefunden")
    return r


# ------------------------------------------------------------------ Vorlagen

class Vorlage(BaseModel):
    name: str
    text: str


@app.get("/api/vorlagen")
def vorlagen_liste():
    return db.vorlagen()


@app.post("/api/vorlagen")
def vorlage_speichern_api(request: Request, v: Vorlage):
    require_admin(request)
    if not v.name.strip() or not v.text.strip():
        raise HTTPException(400, "Name und Text erforderlich")
    db.vorlage_speichern(v.name.strip()[:100], v.text[:5000])
    return {"ok": True}


@app.delete("/api/vorlagen/{name}")
def vorlage_weg(name: str, request: Request):
    require_admin(request)
    db.vorlage_weg(name)
    return {"ok": True}


# ------------------------------------------------------------------ Druckansicht

@app.get("/api/mandates/{slug}/rechnungen/{rid}/druck")
def rechnung_druck(slug: str, rid: str):
    """Druckoptimierte Rechnung (Browser-Druck → PDF speichern)."""
    r = db.rechnung(int(rid), slug)
    if not r:
        raise HTTPException(404, "Rechnung nicht gefunden")
    pos = "\n".join(
        f"<tr><td>{p['datum']}</td><td style='text-align:right'>{p['minuten']} Min.</td>"
        f"<td>{p['text']}</td></tr>" for p in r["positionen"])
    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<title>Rechnung {r['nummer']}</title>
<style>body{{font-family:Georgia,serif;max-width:700px;margin:40px auto;color:#111}}
h1{{font-size:20px;border-bottom:2px solid #111}} table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{padding:6px;border-bottom:1px solid #ccc;text-align:left}}
.summe{{font-weight:bold;font-size:16px;border-top:2px solid #111}}
.hinweis{{color:#666;font-size:12px;margin-top:30px}}</style></head>
<body onload="window.print()">
<h1>Rechnung {r['nummer']}</h1>
<p>Mandat: {r['mandate']} &nbsp;·&nbsp; Datum: {r['datum']} &nbsp;·&nbsp;
Stundensatz: {r['stundensatz']:.2f} €</p>
<table><tr><th>Datum</th><th>Zeit</th><th>Leistung</th></tr>{pos}
<tr class="summe"><td colspan="2">Summe: {r['summe_min']//60} h {r['summe_min']%60} Min.</td>
<td>{r['betrag']:.2f} €</td></tr></table>
<p class="hinweis">Vorlage – keine Umsatzsteuerrechnung im Sinne des UStG.
Bitte steuerlich prüfen lassen.</p>
</body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


# ------------------------------------------------------------------ Portal

@app.post("/api/mandates/{slug}/portal")
def portal_link(request: Request, slug: str):
    """Portal-Link für ein Mandat erzeugen (Admin)."""
    require_admin(request)
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    token = db.portal_token(slug)
    return {"ok": True, "url": f"/portal/{token}"}


@app.get("/portal/{token}")
def portal(token: str):
    """Read-only Statusseite für den Mandanten (ohne Login)."""
    from fastapi.responses import HTMLResponse
    slug = db.portal_mandat(token)
    if not slug:
        return HTMLResponse("<h1>Link ungültig</h1>", status_code=404)
    p = agent.mandate_path(slug)
    fristen = db.fristen(slug)
    offen = [f for f in fristen if not f["erledigt"]]
    notizen = [e for e in fee_memory.all_entries(p) if e["quelle"] == "handnotiz"][-10:]
    mand = p / "MANDAT.md"
    sachverhalt = mand.read_text(encoding="utf-8")[:1500] if mand.exists() else ""
    fr_rows = "".join(
        f"<tr class='{'ueber' if f['ueberfaellig'] else ''}'><td>{f['datum']}</td>"
        f"<td>{'⚠️ ' if f['ueberfaellig'] else ''}{f['text']}</td></tr>"
        for f in offen) or "<tr><td colspan=2>Keine offenen Fristen</td></tr>"
    no_rows = "".join(
        f"<li><b>{time.strftime('%d.%m.%Y', time.localtime(n['t']))}:</b> {n['inhalt']}</li>"
        for n in notizen) or "<li>Keine Notizen</li>"
    import time as _t
    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<title>Mandat {slug}</title>
<style>body{{font-family:Georgia,serif;max-width:700px;margin:40px auto;color:#111}}
h1{{font-size:20px;border-bottom:2px solid #111}} h2{{font-size:16px;margin-top:28px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{padding:6px;border-bottom:1px solid #ccc;text-align:left}}
.ueber{{background:#fde8e8}} .hinweis{{color:#666;font-size:12px;margin-top:30px}}
pre{{white-space:pre-wrap;font-size:13px}}</style></head>
<body>
<h1>Mandat: {slug}</h1>
<h2>Sachverhalt</h2><pre>{sachverhalt}</pre>
<h2>Offene Fristen</h2><table>{fr_rows}</table>
<h2>Aktuelle Notizen</h2><ul>{no_rows}</ul>
<p class="hinweis">Diese Seite zeigt einen Auszug Ihres Mandats und ist keine
Rechtsberatung im Sinne des RDG. Bei Fristen: bitte umgehend Kontakt aufnehmen.</p>
</body></html>"""
    return HTMLResponse(html)


# ------------------------------------------------------------------ RVG

class RvgRequest(BaseModel):
    streitwert: float
    satz: float
    ust: bool = False


@app.post("/api/rvg")
def rvg_rechnen(r: RvgRequest):
    """Gebührenrechner nach RVG (Tabelle 1, § 13 RVG)."""
    from . import rvg as fee_rvg
    g = fee_rvg.gebuehr(r.streitwert, r.satz)
    if not g:
        raise HTTPException(400, "Streitwert muss zwischen 1 und 5.000.000 € liegen "
                                 "(darüber: manuell nach § 13 Abs. 3 RVG)")
    if r.ust:
        g["betrag_inkl_ust"] = round(g["betrag"] * 1.19, 2)
    return g


# ------------------------------------------------------------------ Meta/Termine/Zahlung

class Meta(BaseModel):
    aktenzeichen: str = ""
    bemerkung: str = ""


class Termin(BaseModel):
    mandate: str = ""
    datum: str
    uhrzeit: str = ""
    titel: str


@app.get("/api/mandates/{slug}/meta")
def meta_get(slug: str):
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return db.meta(slug)


@app.post("/api/mandates/{slug}/meta")
def meta_post(slug: str, m: Meta, request: Request):
    require_admin(request)
    if not agent.mandate_path(slug).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    db.meta_set(slug, m.aktenzeichen.strip()[:50] or None, m.bemerkung.strip()[:500] or None)
    return db.meta(slug)


@app.post("/api/mandates/{slug}/meta/az-auto")
def az_auto(slug: str, request: Request):
    """Aktenzeichen automatisch aus Dokumenten-Volltexten erkennen (Graph)."""
    require_admin(request)
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    g = fee_graph.build(p)
    az = g.get("nodes", {}).get("aktenzeichen", [])
    if az:
        db.meta_set(slug, az[0])
    return {"aktenzeichen": az}


@app.get("/api/termine")
def termine_api(bis: str = "2100-12-31", mandate: str = ""):
    return db.termine_bis(bis, mandate or None)


@app.post("/api/termine")
def termin_api(t: Termin):
    import re as _re
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", t.datum) or not t.titel.strip():
        raise HTTPException(400, "Datum (JJJJ-MM-TT) und Titel erforderlich")
    if t.mandate and not agent.mandate_path(t.mandate).exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    return db.termin_add(t.mandate or None, t.datum, t.uhrzeit[:5], t.titel.strip()[:200])


@app.delete("/api/termine/{tid}")
def termin_del_api(tid: int):
    db.termin_del(tid)
    return {"ok": True}


@app.post("/api/mandates/{slug}/rechnungen/{rid}/zahlung")
def zahlung_api(slug: str, rid: int, request: Request, status: str = "bezahlt", gezahlt_am: str = ""):
    require_admin(request)
    import time as _t
    db.rechnung_zahlstatus(rid, slug, status, gezahlt_am or _t.strftime("%Y-%m-%d"))
    return db.rechnung(rid, slug)


# ------------------------------------------------------------------ beA-Bridge

class BeaEntwurf(BaseModel):
    titel: str
    text: str
    empfaenger: str = ""


@app.post("/api/mandates/{slug}/bea/outbox")
def bea_outbox_neu(slug: str, b: BeaEntwurf, request: Request):
    """beA-Postausgang-Entwurf anlegen (zum beA-Client senden)."""
    require_admin(request)
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    from . import bea
    meta = db.meta(slug)
    return bea.entwurf_erstellen(p, b.titel, b.text, b.empfaenger,
                                 meta.get("aktenzeichen", ""))


@app.get("/api/mandates/{slug}/bea/outbox")
def bea_outbox_liste(slug: str):
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    from . import bea
    return bea.outbox_liste(p)


@app.post("/api/mandates/{slug}/bea/inbox")
def bea_inbox(slug: str, request: Request):
    """beA-Posteingang des beA-Clients importieren (~/bea-inbox/)."""
    require_admin(request)
    p = agent.mandate_path(slug)
    if not p.exists():
        raise HTTPException(404, "Mandat nicht gefunden")
    from . import bea, fristen as fee_fristen
    r = bea.posteingang_importieren(p)
    if r.get("ok") and r.get("neu"):
        r["fristen_neu"] = fee_fristen.auto_eintragen(p, slug, db)
    return r


# ------------------------------------------------------------------ Suche/Export/Kollision

@app.get("/api/suche")
def suche_api(q: str = ""):
    """Globale Volltextsuche über alle Mandats-Dokumente + DB-Einträge."""
    if len(q) < 3:
        return []
    import re as _re
    rx = _re.compile(_re.escape(q), _re.I)
    treffer = []
    root = agent.MANDATE_DIR
    if root.exists():
        for txt in root.rglob("dokumente/*.txt"):
            mandate = txt.relative_to(root).parts[0]
            try:
                inhalt = txt.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            for m in rx.finditer(inhalt):
                treffer.append({"mandate": mandate, "datei": txt.name,
                                "kontext": inhalt[max(0, m.start()-80):m.end()+80].replace("\n", " ")})
                if len(treffer) >= 50:
                    return treffer
    return treffer


@app.get("/api/export")
def export_api(request: Request):
    """Vollständiger Datenexport (offenes Format: JSON + Mandatsordner als ZIP-Pfad)."""
    require_admin(request)
    import time as _t
    with db.conn() as c:
        daten = {}
        for t in ("settings", "users", "fristen", "kontakte", "zeiten",
                  "rechnungen", "vorlagen", "memory", "portal", "termine", "mandate_meta"):
            try:
                cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
                daten[t] = [dict(zip(cols, row)) for row in c.execute(f"SELECT * FROM {t}")]
            except Exception:  # noqa: BLE001
                daten[t] = []
    return {"export_datum": _t.strftime("%Y-%m-%d %H:%M"),
            "mandatsverzeichnis": str(agent.MANDATE_DIR), "daten": daten}


@app.post("/api/mandates/{slug}/kollision")
def kollision_api(slug: str, request: Request, gegner: str = ""):
    """Kollisionsprüfung: andere Mandate mit gleichem Gegner."""
    require_admin(request)
    return db.kollisionspruefung(slug, gegner)
