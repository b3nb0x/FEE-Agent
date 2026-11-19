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
        CREATE TABLE IF NOT EXISTS zeiten(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandate TEXT NOT NULL, datum TEXT NOT NULL,
            minuten INTEGER NOT NULL, text TEXT NOT NULL,
            abgerechnet INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_zeiten_mandate ON zeiten(mandate, datum);
        CREATE TABLE IF NOT EXISTS rechnungen(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandate TEXT NOT NULL, nummer TEXT NOT NULL,
            datum TEXT NOT NULL, stundensatz REAL NOT NULL,
            summe_min INTEGER NOT NULL, betrag REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS vorlagen(
            name TEXT PRIMARY KEY, text TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS portal(
            mandate TEXT PRIMARY KEY, token TEXT NOT NULL);
        """)
    # Migration bestehender DBs: Spalte rechnung_id nachrüsten
    with conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(zeiten)")]
        if 'rechnung_id' not in cols:
            c.execute("ALTER TABLE zeiten ADD COLUMN rechnung_id INTEGER")
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


# ------------------------------------------------------------------ Zeiten

def zeiten(mandate: str) -> list:
    init()
    with conn() as c:
        rows = c.execute("SELECT id,datum,minuten,text,abgerechnet FROM zeiten "
                         "WHERE mandate=? ORDER BY datum, id", (mandate,)).fetchall()
    return [{"id": r[0], "mandate": mandate, "datum": r[1], "minuten": r[2],
             "text": r[3], "abgerechnet": r[4]} for r in rows]


def zeit_add(mandate: str, datum: str, minuten: int, text: str) -> dict:
    init()
    with conn() as c:
        cur = c.execute("INSERT INTO zeiten(mandate,datum,minuten,text,abgerechnet) "
                        "VALUES(?,?,?,?,0)", (mandate, datum, minuten, text))
    return {"id": cur.lastrowid, "mandate": mandate, "datum": datum,
            "minuten": minuten, "text": text, "abgerechnet": 0}


def zeit_del(zid: int, mandate: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM zeiten WHERE id=? AND mandate=? AND abgerechnet=0",
                  (zid, mandate))


def zeiten_summe(mandate: str) -> dict:
    """Offene und abgerechnete Minuten des Mandats."""
    init()
    with conn() as c:
        offen = c.execute("SELECT COALESCE(SUM(minuten),0) FROM zeiten "
                          "WHERE mandate=? AND abgerechnet=0", (mandate,)).fetchone()[0]
        abrech = c.execute("SELECT COALESCE(SUM(minuten),0) FROM zeiten "
                           "WHERE mandate=? AND abgerechnet=1", (mandate,)).fetchone()[0]
    return {"offen_min": offen, "abgerechnet_min": abrech}


def zeiten_abrechnen(mandate: str) -> int:
    """Alle offenen Zeiten als abgerechnet markieren. Rückgabe: Anzahl."""
    init()
    with conn() as c:
        cur = c.execute("UPDATE zeiten SET abgerechnet=1 "
                        "WHERE mandate=? AND abgerechnet=0", (mandate,))
    return cur.rowcount


# ------------------------------------------------------------------ Rechnungen

def rechnung_erstellen(mandate: str, stundensatz: float) -> dict | None:
    """Rechnung aus abgerechneten, noch nicht fakturierten Zeiten."""
    init()
    with conn() as c:
        rows = c.execute("SELECT id, minuten, text FROM zeiten "
                         "WHERE mandate=? AND abgerechnet=1 AND rechnung_id IS NULL",
                         (mandate,)).fetchall()
        if not rows:
            return None
        nummer = "R" + time.strftime("%Y%m%d") + "-" + str(c.execute(
            "SELECT COUNT(*) FROM rechnungen WHERE mandate=?",
            (mandate,)).fetchone()[0] + 1)
        summe_min = sum(r[1] for r in rows)
        betrag = round(summe_min / 60 * stundensatz, 2)
        cur = c.execute("INSERT INTO rechnungen(mandate,nummer,datum,stundensatz,"
                        "summe_min,betrag) VALUES(?,?,?,?,?,?)",
                        (mandate, nummer, time.strftime("%Y-%m-%d"),
                         stundensatz, summe_min, betrag))
        rid = cur.lastrowid
        c.executemany("UPDATE zeiten SET rechnung_id=? WHERE id=?",
                      [(rid, r[0]) for r in rows])
    return {"id": rid, "mandate": mandate, "nummer": nummer,
            "datum": time.strftime("%Y-%m-%d"), "stundensatz": stundensatz,
            "summe_min": summe_min, "betrag": betrag,
            "positionen": [{"text": r[2], "minuten": r[1]} for r in rows]}


def rechnungen(mandate: str) -> list:
    init()
    with conn() as c:
        return [dict(zip(("id", "mandate", "nummer", "datum", "stundensatz",
                          "summe_min", "betrag"), row))
                for row in c.execute(
                    "SELECT id,mandate,nummer,datum,stundensatz,summe_min,betrag "
                    "FROM rechnungen WHERE mandate=? ORDER BY id DESC", (mandate,))]


def rechnung(rid: int, mandate: str) -> dict | None:
    """Rechnung mit Positionen (die zugehörigen Zeiten)."""
    init()
    with conn() as c:
        row = c.execute("SELECT id,mandate,nummer,datum,stundensatz,summe_min,betrag "
                        "FROM rechnungen WHERE id=? AND mandate=?",
                        (rid, mandate)).fetchone()
        if not row:
            return None
        pos = c.execute("SELECT datum,minuten,text FROM zeiten "
                        "WHERE rechnung_id=? ORDER BY datum", (rid,)).fetchall()
    return {"id": row[0], "mandate": row[1], "nummer": row[2], "datum": row[3],
            "stundensatz": row[4], "summe_min": row[5], "betrag": row[6],
            "positionen": [{"datum": p[0], "minuten": p[1], "text": p[2]} for p in pos]}


# ------------------------------------------------------------------ Vorlagen

def vorlagen() -> list:
    """Kanzleiweite Schriftsatz-Vorlagen (Name → Text)."""
    init()
    with conn() as c:
        return [{"name": r[0], "text": r[1]} for r in
                c.execute("SELECT name, text FROM vorlagen ORDER BY name")]


def vorlage_speichern(name: str, text: str) -> None:
    init()
    with conn() as c:
        c.execute("INSERT INTO vorlagen(name,text) VALUES(?,?) "
                  "ON CONFLICT(name) DO UPDATE SET text=excluded.text",
                  (name, text))


def vorlage_weg(name: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM vorlagen WHERE name=?", (name,))


# ------------------------------------------------------------------ Portal

def portal_token(mandate: str) -> str:
    """Portal-Token für ein Mandat holen (oder erzeugen)."""
    init()
    import secrets
    with conn() as c:
        row = c.execute("SELECT token FROM portal WHERE mandate=?",
                        (mandate,)).fetchone()
        if row:
            return row[0]
        token = secrets.token_urlsafe(24)
        c.execute("INSERT INTO portal(mandate,token) VALUES(?,?)", (mandate, token))
    return token


def portal_mandat(token: str) -> str | None:
    """Mandat zu einem Portal-Token (oder None)."""
    init()
    with conn() as c:
        row = c.execute("SELECT mandate FROM portal WHERE token=?",
                        (token,)).fetchone()
    return row[0] if row else None


def alle_fristen() -> list:
    """Wiedervorlage über alle Mandate, sortiert nach Datum."""
    init()
    with conn() as c:
        rows = c.execute("SELECT id,mandate,datum,text,erledigt FROM fristen "
                         "ORDER BY datum").fetchall()
    heute = time.strftime("%Y-%m-%d")
    return [{"id": r[0], "mandate": r[1], "datum": r[2], "text": r[3],
             "erledigt": r[4], "ueberfaellig": r[2] < heute} for r in rows]
