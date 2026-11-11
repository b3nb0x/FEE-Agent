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
        """)


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
