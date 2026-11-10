"""F.E.E. Agent – OCR-/Dokumentenverarbeitung (Skill 16 als Code)."""
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "Werkzeug nicht installiert: " + cmd[0]


def ocr_pdf(pdf: Path, out_txt: Path) -> str:
    """PDF → Text. Erst Text-Layer (pdftotext), sonst OCR (pdftoppm + tesseract)."""
    rc, _, err = _run(["pdftotext", "-layout", str(pdf), str(out_txt)])
    if rc == 0 and out_txt.exists() and out_txt.stat().st_size > 50:
        return "pdftotext (Text-Layer)"
    out_txt.unlink(missing_ok=True)
    tmp = out_txt.parent / (out_txt.stem + "_ocr")
    rc, _, err = _run(["pdftoppm", "-r", "300", "-png", str(pdf), str(tmp)])
    if rc != 0:
        raise RuntimeError(f"pdftoppm fehlgeschlagen: {err}")
    pages = sorted(out_txt.parent.glob(tmp.name + "-*.png"))
    texts = []
    for page in pages:
        r = subprocess.run(["tesseract", str(page), "stdout", "-l", "deu"],
                            capture_output=True, text=True)
        if r.returncode == 0:
            texts.append(r.stdout)
        page.unlink(missing_ok=True)
    out_txt.write_text("\n\n".join(texts), encoding="utf-8")
    return f"OCR (tesseract, {len(pages)} Seiten)"


def ocr_image(img: Path, out_txt: Path) -> str:
    r = subprocess.run(["tesseract", str(img), str(out_txt.with_suffix("")),
                        "-l", "deu"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("tesseract fehlgeschlagen: " + r.stderr)
    # tesseract schreibt <stem>.txt
    produced = out_txt.with_suffix(".txt") if out_txt.suffix != ".txt" else out_txt
    if produced != out_txt and produced.exists():
        shutil.move(str(produced), str(out_txt))
    return "OCR (tesseract)"


def convert_office(doc: Path, outdir: Path) -> Path:
    """DOC(X)/ODT/RTF/XLS(X)/ODS → txt/csv per LibreOffice headless."""
    r = subprocess.run(
        ["libreoffice", "--headless", "--convert-to",
         "csv" if doc.suffix.lower() in (".xlsx", ".xls", ".ods") else "txt:Text",
         "--outdir", str(outdir), str(doc)],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("libreoffice fehlgeschlagen: " + r.stderr)
    produced = outdir / (doc.stem + (".csv" if doc.suffix.lower() in
                                     (".xlsx", ".xls", ".ods") else ".txt"))
    if not produced.exists():
        raise RuntimeError("Konvertierung erzeugte keine Datei")
    return produced


def process_document(src: Path, mandate_dir: Path) -> dict:
    """Nimmt ein Dokument ins Mandat auf: Original → eingang/, Volltext → dokumente/."""
    eingang = mandate_dir / "eingang"
    dokumente = mandate_dir / "dokumente"
    eingang.mkdir(exist_ok=True), dokumente.mkdir(exist_ok=True)
    dst = eingang / src.name
    if not dst.exists():
        shutil.copy2(src, dst)

    out_txt = dokumente / (src.stem + ".txt")
    suffix = src.suffix.lower()
    methode = ""
    try:
        if suffix == ".pdf":
            methode = ocr_pdf(src, out_txt)
        elif suffix in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
            methode = ocr_image(src, out_txt)
        elif suffix in (".doc", ".docx", ".odt", ".rtf", ".txt"):
            methode = "LibreOffice"
            produced = convert_office(src, dokumente)
            if produced != out_txt:
                shutil.move(str(produced), str(out_txt))
        elif suffix in (".xls", ".xlsx", ".ods"):
            methode = "LibreOffice (csv)"
            convert_office(src, dokumente)  # bleibt als .csv
            out_txt = dokumente / (src.stem + ".csv")
        else:
            return {"ok": False, "fehler": f"Nicht unterstützter Typ: {suffix}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "fehler": str(e), "original": str(dst)}

    volltext = ""
    if out_txt.exists():
        volltext = out_txt.read_text(encoding="utf-8", errors="replace")[:200000]
    return {"ok": True, "original": str(dst), "volltext_datei": str(out_txt),
            "methode": methode, "volltext": volltext}
