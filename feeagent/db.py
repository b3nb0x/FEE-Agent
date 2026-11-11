"""FEE-Agent db – SQLite als zentrale Ablage.

Einstellungen, Nutzer/Rollen und Mandats-Memory liegen in einer
Einzeldatenbank unter ~/.config/fee-agent/feeagent.db (außerhalb des
Repos → überlebt Updates). Bestehende JSON-/JSONL-Dateien werden beim
ersten Zugriff importiert und als .bak liegen gelassen.

Mandat-Ordner (Dokumente, MANDAT.md, Fristen) bleiben im Dateisystem –
PDFs/Scans gehören nicht in die DB.
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path.home() / ".config" / "fee-agent" / "feeagent.db"


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(
            name TEXT PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandate TEXT NOT NULL, t REAL, typ TEXT,
            inhalt TEXT, quelle TEXT);
        CREATE INDEX IF NOT EXISTS idx_memory_mandate ON memory(mandate);
        CREATE TABLE IF NOT EXISTS fristen(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandate TEXT NOT NULL, datum TEXT NOT NULL,
            text TEXT NOT NULL, erledigt INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_fristen_mandate ON fristen(mandate, datum);
        CREATE TABLE IF NOT EXISTS kontakte(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandate TEXT NOT NULL, rolle TEXT NOT NULL,
            name TEXT NOT NULL, kontakt TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_kontakte_mandate ON kontakte(mandate);
        """)
    # Einmalige Migration alter JSON-Dateien (werden zu .bak)
    _import_json_file(DB_PATH.parent / "config.json", "settings", ("key", "value"))
    _import_json_file(DB_PATH.parent / "users.json", "users", ("name", "role"))


def _import_json_file(pfad: Path, tabelle: str, spalten: tuple) -> None:
    """Einmalige Migration einer JSON-Datei in die DB (danach .bak)."""
    if not pfad.exists():
        return
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    with conn() as c:
        have = c.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]
        if have == 0:
            if tabelle == "users":
                c.executemany("INSERT INTO users VALUES(?,?)",
                              [(k, v["role"]) for k, v in daten.items()])
            elif tabelle == "settings":
                c.executemany("INSERT INTO settings VALUES(?,?)", daten.items())
    pfad.rename(pfad.with_suffix(pfad.suffix + ".bak"))


# ------------------------------------------------------------------ Settings

def get_settings(defaults: dict) -> dict:
    init()
    _import_json_file(DB_PATH.parent / "config.json", "settings", ("key", "value"))
    with conn() as c:
        return {**defaults, **dict(c.execute("SELECT key, value FROM settings"))}


def set_settings(cfg: dict) -> None:
    init()
    with conn() as c:
        c.executemany("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      cfg.items())


# ------------------------------------------------------------------ Nutzer

def load_users() -> dict:
    init()
    _import_json_file(DB_PATH.parent / "users.json", "users", ("name", "role"))
    with conn() as c:
        return {name: {"role": role} for name, role in
                c.execute("SELECT name, role FROM users")}


def save_users(users: dict) -> None:
    init()
    with conn() as c:
        c.execute("DELETE FROM users")
        c.executemany("INSERT INTO users VALUES(?,?)",
                      [(k, v["role"]) for k, v in users.items()])


# ------------------------------------------------------------------ Memory

def _mandat_key(mandate_dir: Path) -> str:
    return mandate_dir.name


def add(mandate_dir: Path, typ: str, inhalt: str, quelle: str = "master") -> dict:
    init()
    eintrag = {"t": round(time.time(), 2), "typ": typ,
               "inhalt": inhalt.strip()[:2000], "quelle": quelle}
    with conn() as c:
        cur = c.execute(
            "INSERT INTO memory(mandate,t,typ,inhalt,quelle) VALUES(?,?,?,?,?)",
            (_mandat_key(mandate_dir), eintrag["t"], typ, eintrag["inhalt"], quelle))
        eintrag["id"] = cur.lastrowid
    return eintrag


def all_entries(mandate_dir: Path) -> list:
    init()
    _import_memory_jsonl(mandate_dir)
    with conn() as c:
        return [dict(zip(("id", "t", "typ", "inhalt", "quelle"), row)) for row in
                c.execute("SELECT id,t,typ,inhalt,quelle FROM memory WHERE mandate=? "
                          "ORDER BY id", (_mandat_key(mandate_dir),))]


def _import_memory_jsonl(mandate_dir: Path) -> None:
    """Alte memory.jsonl des Mandats einmalig in die DB übernehmen."""
    p = mandate_dir / "memory.jsonl"
    if not p.exists():
        return
    key = _mandat_key(mandate_dir)
    with conn() as c:
        for zeile in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(zeile)
                c.execute("INSERT INTO memory(mandate,t,typ,inhalt,quelle) "
                          "VALUES(?,?,?,?,?)",
                          (key, e.get("t", 0), e.get("typ", "fakt"),
                           e.get("inhalt", ""), e.get("quelle", "import")))
            except json.JSONDecodeError:
                continue
    p.rename(p.with_suffix(".jsonl.bak"))


def search(mandate_dir: Path, begriff: str, limit: int = 20) -> list:
    hits = [e for e in all_entries(mandate_dir)
            if begriff.lower() in e["inhalt"].lower()]
    return hits[-limit:]


def delete_note(mandate_dir: Path, note_id: int) -> None:
    """Handnotiz entfernen (nur eigene Handnotizen, keine Workflow-Einträge)."""
    init()
    with conn() as c:
        c.execute("DELETE FROM memory WHERE id=? AND mandate=? AND quelle='handnotiz'",
                  (note_id, _mandat_key(mandate_dir)))


def delete_note(mandate_dir: Path, note_id: int) -> None:
    """Handnotiz entfernen (nur eigene Handnotizen, keine Workflow-Einträge)."""
    init()
    with conn() as c:
        c.execute("DELETE FROM memory WHERE id=? AND mandate=? AND quelle='handnotiz'",
                  (note_id, _mandat_key(mandate_dir)))


# ------------------------------------------------------------------ Fristen

def add_frist(mandate: str, datum: str, text: str) -> dict:
    init()
    with conn() as c:
        cur = c.execute("INSERT INTO fristen(mandate,datum,text,erledigt) "
                        "VALUES(?,?,?,0)", (mandate, datum, text))
    return {"id": cur.lastrowid, "mandate": mandate, "datum": datum,
            "text": text, "erledigt": 0}


def fristen(mandate: str) -> list:
    init()
    with conn() as c:
        rows = c.execute("SELECT id,datum,text,erledigt FROM fristen "
                         "WHERE mandate=? ORDER BY datum", (mandate,)).fetchall()
    heute = time.strftime("%Y-%m-%d")
    return [{"id": r[0], "mandate": mandate, "datum": r[1], "text": r[2],
             "erledigt": r[3], "ueberfaellig": r[1] < heute} for r in rows]


def frist_erledigt(fid: int, mandate: str) -> None:
    with conn() as c:
        c.execute("UPDATE fristen SET erledigt=1 WHERE id=? AND mandate=?",
                  (fid, mandate))


def delete_note(mandate_dir: Path, note_id: int) -> None:
    """Handnotiz entfernen (nur eigene Handnotizen, keine Workflow-Einträge)."""
    init()
    with conn() as c:
        c.execute("DELETE FROM memory WHERE id=? AND mandate=? AND quelle='handnotiz'",
                  (note_id, _mandat_key(mandate_dir)))


# ------------------------------------------------------------------ Kontakte

def kontakte(mandate: str) -> list:
    """Kontakte eines Mandats (Mandant, Gegner, Gericht, Zeugen)."""
    init()
    with conn() as c:
        return [dict(zip(("id", "mandate", "rolle", "name", "kontakt"), row))
                for row in c.execute(
                    "SELECT id,mandate,rolle,name,kontakt FROM kontakte "
                    "WHERE mandate=? ORDER BY rolle, name", (mandate,))]


def kontakt_add(mandate: str, rolle: str, name: str, kontakt: str) -> dict:
    init()
    with conn() as c:
        cur = c.execute("INSERT INTO kontakte(mandate,rolle,name,kontakt) "
                        "VALUES(?,?,?,?)", (mandate, rolle, name, kontakt))
    return {"id": cur.lastrowid, "mandate": mandate, "rolle": rolle,
            "name": name, "kontakt": kontakt}


def kontakt_del(kid: int, mandate: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM kontakte WHERE id=? AND mandate=?",
                  (kid, mandate))


def delete_note(mandate_dir: Path, note_id: int) -> None:
    """Handnotiz entfernen (nur eigene Handnotizen, keine Workflow-Einträge)."""
    init()
    with conn() as c:
        c.execute("DELETE FROM memory WHERE id=? AND mandate=? AND quelle='handnotiz'",
                  (note_id, _mandat_key(mandate_dir)))
