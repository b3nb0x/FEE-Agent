"""FEE-Agent paperless – Bridge zu Paperless-ngx (lokales Dokumentenarchiv).

Zwei Wege, beide lokal auf dem NAS:
1. Upload an Paperless: Dokument zusätzlich ins Paperless-Consume-Verzeichnis
   legen (Paperless macht OCR + Archiv + Volltextsuche dort).
2. Import aus Paperless: archivierte Dokumente (mit Volltext) als Mandats-
   dokumente übernehmen.

Konfiguration per Env: PAPERLESS_CONSUME (Default /paperless-consume),
PAPERLESS_MEDIA (Default /paperless/media).
"""
import os
import shutil
from pathlib import Path

CONSUME = Path(os.environ.get("PAPERLESS_CONSUME", "/paperless-consume"))
MEDIA = Path(os.environ.get("PAPERLESS_MEDIA", "/paperless/media"))


def an_paperless_senden(src: Path) -> dict:
    """Original-Dokument an Paperless-ngx übergeben (Consume-Ordner)."""
    if not CONSUME.exists():
        return {"ok": False, "fehler": f"Consume-Ordner fehlt: {CONSUME} "
                                       "(Volume in docker-compose mounten)"}
    ziel = CONSUME / src.name
    shutil.copy2(src, ziel)
    return {"ok": True, "ziel": str(ziel)}


def aus_paperless_importieren(mandate_dir: Path, textdatei: Path) -> dict:
    """Paperless-Volltext (.txt aus dem Media-Ordner) ins Mandat übernehmen."""
    ziel = mandate_dir / "dokumente" / textdatei.name
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(textdatei, ziel)
    return {"ok": True, "datei": str(ziel)}
