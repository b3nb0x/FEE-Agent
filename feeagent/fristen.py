"""FEE-Agent fristen – automatische Fristen-Erkennung aus Dokumenttexten.

Erkennt absolute Daten ("bis 15.03.2027", "zum 31.12.2026") und relative
gesetzliche Fristen ("innerhalb von 2 Wochen ab Zugang") bezogen auf das
Dokumentdatum (E-Mail-Datum bzw. Upload-Datum).
"""
import re
from datetime import date, timedelta

RE_DATUM_DE = re.compile(
    r"\b(?:bis\s+(?:zum\s+)?|zum\s+|spätestens\s+(?:am\s+)?|Frist:?\s*(?:bis\s+)?|"
    r"innerhalb\s+von\s+)?(\d{1,2})\.(0?\d|1[0-2])\.(20\d{2})\b", re.I)
RE_DATUM_ISO = re.compile(
    r"\b(?:bis\s+(?:zum\s+)?|zum\s+|spätestens\s+(?:am\s+)?|Frist:?\s*(?:bis\s+)?|"
    r"innerhalb\s+von\s+)?(20\d{2})-(\d{2})-(\d{2})\b", re.I)
RE_RELATIV = re.compile(
    r"innerhalb\s+von\s+(\d{1,3})\s+(Tag(?:en)?|Woche(?:n)?|Monat(?:en)?|Jahr(?:en)?)"
    r"(?:\s+ab\s+(?:Zugang|Datum|Erhalt))?",
    re.I)

MONAT = {"januar":1,"februar":2,"märz":3,"maerz":3,"april":4,"mai":5,"juni":6,
         "juli":7,"august":8,"september":9,"oktober":10,"november":11,"dezember":12}
RE_DATUM_TEXT = re.compile(
    r"\b(\d{1,2})\.\s*(?:" + "|".join(MONAT) + r")\s+(20\d{2})\b", re.I)

_EINHEIT = {"tag":1, "tage":1, "woche":7, "wochen":7,
             "monat":30, "monate":30, "jahr":365, "jahre":365}


def _quelle_datum(text: str, fallback: date) -> date:
    """Erstes Datum im Text als Dokumentdatum (heuristisch), sonst fallback."""
    for m in RE_DATUM_DE.finditer(text):
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
    for m in RE_DATUM_ISO.finditer(text):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return fallback


def extrahieren(text: str, quell_datum: date | None = None) -> list:
    """Liefert [{datum, text}] – erkannte Fristen aus einem Dokumenttext."""
    if quell_datum is None:
        quell_datum = date.today()
    out, gesehene = [], set()
    basis = _quelle_datum(text[:2000], quell_datum)

    def _add(d: date, kontext: str):
        if d in gesehene or d.year < 2020:
            return
        gesehene.add(d)
        out.append({"datum": d.isoformat(), "text": kontext.strip()[:300]})

    for m in RE_DATUM_DE.finditer(text):
        try:
            _add(date(int(m.group(3)), int(m.group(2)), int(m.group(1))),
                 text[max(0, m.start() - 60):m.end() + 40].replace("\n", " "))
        except ValueError:
            pass
    for m in RE_DATUM_ISO.finditer(text):
        try:
            _add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                 text[max(0, m.start() - 60):m.end() + 40].replace("\n", " "))
        except ValueError:
            pass
    for m in RE_DATUM_TEXT.finditer(text):
        try:
            monat = MONAT.get(m.group(2).lower())
            if monat is None:
                continue
            _add(date(int(m.group(3)), monat, int(m.group(1))),
                 text[max(0, m.start() - 60):m.end() + 40].replace("\n", " "))
        except ValueError:
            pass
    RE_ZUGANG = re.compile(r"(?:Zugang|Datum|Erhalt)[:\s]*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)
    for m in RE_RELATIV.finditer(text):
        zahl, einheit = int(m.group(1)), m.group(2).lower()
        tage = zahl * _EINHEIT.get(einheit, 0)
        if not tage:
            continue
        # Basis: Datum nach "ab Zugang:" im Umfeld, sonst Dokumentdatum
        umfeld = text[m.end():m.end()+40]
        zm = RE_ZUGANG.search(umfeld)
        if zm:
            try:
                b = date(int(zm.group(3)), int(zm.group(2)), int(zm.group(1)))
            except ValueError:
                b = basis
        else:
            b = basis
        _add(b + timedelta(days=tage),
             text[max(0, m.start() - 60):m.end() + 60].replace("\n", " "))
    return out
