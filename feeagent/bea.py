"""FEE-Agent beA-Bridge – Postausgang/Posteingang ohne eigene Signatur.

beA (besonderes elektronisches Anwaltspostfach) läuft über das zertifizierte
SAFE/OSCI-Protokoll der BRAK – dafür ist der offizielle beA-Client nötig
(BRAK-Zulassung + Software-Zertifikat). FEE-Agent übernimmt die Kanzlei-Seite:

- Postausgang: Entwurf (PDF + Metadaten) als beA-Nachricht in die Outbox
  (Default: ~/FEE-Mandate/<slug>/postausgang/bea-outbox/), bereit für den
  beA-Client zum Signieren/Senden.
- Posteingang: Ordner des beA-Clients (Default: ~/bea-inbox/) importieren –
  .eml/.pdf/.xml/.txt landen als Dokumente im Mandat (inkl. Auto-Fristen/AZ).
"""
import json
import time
from pathlib import Path

BEA_INBOX = Path.home() / "bea-inbox"


def outbox_dir(mandate_dir: Path) -> Path:
    d = mandate_dir / "postausgang" / "bea-outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def entwurf_erstellen(mandate_dir: Path, titel: str, pdf_text: str,
                     empfaenger: str = "", sachbearbeiter: str = "") -> dict:
    """beA-Postausgang-Entwurf anlegen (JSON-Metadaten + Text als PDF-Platzhalter)."""
    out = outbox_dir(mandate_dir)
    nr = time.strftime("%Y%m%d-%H%M%S")
    meta = {
        "bea": True, "status": "entwurf", "nr": nr,
        "titel": titel[:200], "empfaenger": empfaenger[:200],
        "sachbearbeiter": sachbearbeiter[:100],
        "erstellt": time.strftime("%Y-%m-%d %H:%M"),
    }
    (out / f"{nr}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (out / f"{nr}.txt").write_text(pdf_text, encoding="utf-8")
    return meta


def outbox_liste(mandate_dir: Path) -> list:
    out = outbox_dir(mandate_dir)
    return sorted([json.loads(p.read_text(encoding="utf-8"))
                   for p in out.glob("*.json")], reverse=True)


def posteingang_importieren(mandate_dir: Path, inbox: Path = None) -> dict:
    """beA-Client-Posteingang importieren (einmalig, dann als gelesen markiert)."""
    from . import ocr
    inbox = inbox or BEA_INBOX
    if not inbox.exists():
        return {"ok": False, "fehler": f"Posteingang nicht gefunden: {inbox}"}
    neu = 0
    for f in sorted(inbox.iterdir()):
        if f.suffix.lower() not in (".eml", ".pdf", ".txt", ".xml", ".msg"):
            continue
        ziel = mandate_dir / "eingang" / f.name
        if ziel.exists():
            continue
        import shutil
        shutil.copy2(f, ziel)
        r = ocr.process_document(ziel, mandate_dir)
        if r.get("ok"):
            neu += 1
        # als gelesen markieren
        f.rename(inbox / ("_gelesen_" + f.name))
    return {"ok": True, "neu": neu}
