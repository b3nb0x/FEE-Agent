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


def _email_import(src: Path, out_txt: Path) -> None:
    """E-Mail (.eml) → Text: Kopf (Von/An/Datum/Betreff) + Body."""
    import email
    from email import policy
    msg = email.message_from_bytes(src.read_bytes(), policy=policy.default)
    kopf = (f"Von: {msg.get('From','')}\nAn: {msg.get('To','')}\n"
            f"Datum: {msg.get('Date','')}\nBetreff: {msg.get('Subject','')}\n\n")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        body = msg.get_content()
    # verschachtelte E-Mails: Body kann base64-kodiert ankommen → dekodieren
    import base64
    b = body.strip()
    if b and "\n" in b and not b.startswith(("Von:", "An:")):
        try:
            dekodiert = base64.b64decode("".join(b.split()), validate=True).decode("utf-8")
            if sum(c.isprintable() or c in "\n\r\t" for c in dekodiert) / max(len(dekodiert), 1) > 0.9:
                body = dekodiert
                if body.startswith(("Subject:", "From:")):
                    # dekodiert = komplette innere E-Mail → sauber neu parsen
                    inner_msg = email.message_from_string(body, policy=policy.default)
                    kopf = (f"Von: {inner_msg.get('From','')}\nAn: {inner_msg.get('To','')}\n"
                            f"Datum: {inner_msg.get('Date','')}"
                            f"\nBetreff: {inner_msg.get('Subject','')}\n\n")
                    body = (inner_msg.get_body(preferencelist=("plain",)).get_content()
                            if not inner_msg.is_multipart() else body)
        except Exception:  # noqa: BLE001 – dann war es echter Text
            pass
    out_txt.write_text(kopf + body, encoding="utf-8")


def _email_anhaenge(src: Path, eingang: Path) -> list:
    doc = "Anhänge aus .eml extrahieren (Originale nach eingang/)."
    import email
    from email import policy
    msg = email.message_from_bytes(src.read_bytes(), policy=policy.default)
    out = []
    for part in msg.walk():
        fn = part.get_filename()
        daten = part.get_payload(decode=True)
        if not fn:
            continue
        if not daten and part.get_content_type() == "message/rfc822":
            # verschachtelte E-Mail: Payload ist das innere Message-Objekt
            inner = part.get_payload()
            daten = (inner[0] if isinstance(inner, list) else inner).as_bytes()
        if not daten:
            continue
        dst = eingang / Path(fn).name
        i = 1
        while dst.exists():
            dst = eingang / f"{Path(fn).stem}_{i}{Path(fn).suffix}"
            i += 1
        dst.write_bytes(daten)
        out.append(dst)
    return out


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
    anhaenge: list = []
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
        elif suffix in (".eml",):
            methode = "E-Mail (.eml)"
            _email_import(src, out_txt)
            anhaenge = _email_anhaenge(src, eingang)
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

    # Anhänge automatisch durch dieselbe Pipeline (Original → eingang/, Text → dokumente/)
    ergebnisse = [process_document(a, mandate_dir) for a in anhaenge]
    ok_anh = [r for r in ergebnisse if r.get("ok")]

    return {"ok": True, "original": str(dst), "volltext_datei": str(out_txt),
            "methode": methode + (f" ({len(ok_anh)} Anhang/Anhänge verarbeitet)"
                                  if ok_anh else ""),
            "volltext": volltext,
            "anhaenge": [{"datei": r["original"], "methode": r["methode"]}
                         for r in ok_anh],
            "anhaenge_fehler": [r.get("fehler", "") for r in ergebnisse
                                if not r.get("ok")]}
