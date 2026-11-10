"""FEE-Agent memory – sitzungsübergreifendes Mandats-Gedächtnis.

Vorbild: Hermes memory. Fakten, Fristen und Entscheidungen werden als
JSONL je Mandat gespeichert; Master und Subagenten lesen/schreiben sie.
"""
import json
import re
import time
from pathlib import Path


def _memfile(mandate_dir: Path) -> Path:
    return mandate_dir / "memory.jsonl"


def add(mandate_dir: Path, eintragstyp: str, inhalt: str,
        quelle: str = "master") -> dict:
    """Fügt einen Memory-Eintrag hinzu (typ: fakt|frist|entscheidung|notiz)."""
    p = _memfile(mandate_dir)
    eintrag = {
        "t": round(time.time(), 2),
        "typ": eintragstyp,
        "inhalt": inhalt.strip()[:2000],
        "quelle": quelle,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
    return eintrag


def all_entries(mandate_dir: Path) -> list:
    p = _memfile(mandate_dir)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def search(mandate_dir: Path, begriff: str, limit: int = 20) -> list:
    rx = re.compile(re.escape(begriff), re.I)
    hits = [e for e in all_entries(mandate_dir) if rx.search(e["inhalt"])]
    return hits[-limit:]


def context(mandate_dir: Path, max_chars: int = 3000) -> str:
    """Kompakte Memory-Sicht als Subagenten-Kontext."""
    entries = all_entries(mandate_dir)
    if not entries:
        return ""
    lines = ["Mandats-Memory (frühere Sitzungen):"]
    for e in entries[-25:]:
        lines.append(f"- [{e['typ']}] {e['inhalt'][:200]}")
    return "\n".join(lines)[:max_chars]


def distill(mandate_dir: Path, phase_name: str, phase_output: str,
            llm_fn=None) -> list:
    """Destilliert ein Subagenten-Ergebnis in Memory-Einträge.

    Ohne LLM: heuristisch (Fristen-/Norm-Zeilen). Mit LLM: das Modell
    formuliert 1–3 kompakte Fakteneinträge.
    """
    neue = []
    if llm_fn is None:
        for line in phase_output.splitlines():
            s = line.strip().lstrip("-*•0123456789. ")
            if re.match(r"⚠|Frist|§|\d{1,2}\.\d{1,2}\.", s, re.I) and 8 < len(s) < 400:
                typ = "frist" if re.match(r"⚠|Frist", s) else "fakt"
                neue.append(add(mandate_dir, typ, s, quelle=f"subagent:{phase_name}"))
            if len(neue) >= 3:
                break
    else:
        try:
            prompt = ("Formuliere aus folgendem Ergebnis maximal 3 kompakte "
                      "Fakten/Fristen als Liste (je eine Zeile, keine Einleitung). "
                      "Beginne Fristen mit 'FRIST:'.\n\n" + phase_output[:4000])
            out = llm_fn(prompt)
            for line in out.splitlines():
                s = line.strip().lstrip("-*•0123456789. ")
                if not s or len(s) < 8:
                    continue
                typ = "frist" if s.upper().startswith("FRIST") else "fakt"
                s = s[5:].strip() if typ == "frist" else s
                neue.append(add(mandate_dir, typ, s[:400],
                                quelle=f"subagent:{phase_name}"))
        except Exception:  # noqa: BLE001
            pass
    return neue
