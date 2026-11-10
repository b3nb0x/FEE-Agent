"""FEE-Agent graph – Mandats-Wissensgraph.

Vorbild: Graphify. Extrahiert Entitäten (Normen, Daten, Beträge, Beteiligte)
aus Dokumenten-Volltexten und stellt sie als abfragbaren Graph bereit –
Subagenten lesen den Graph statt ganzer Dokumente (Token-Ersparnis).
"""
import json
import re
from collections import defaultdict
from pathlib import Path

RE_NORM = re.compile(r"§\s?\d+[a-z]?(?:\s?(?:Abs\.|Absatz)\s?\d+)?"
                     r"(?:\s?S\.\s?\d+)?\s?(?:BGB|StGB|SGB\s?[IVX]+|AO|ZPO|StPO|"
                     r"KSchG|BUrlG|ArbZG|AGG|BetrVG|UWG|GWB|RVG|GKG|MiLoG|EGBGB)\b")
RE_DATE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2})\b")
RE_AMOUNT = re.compile(r"(\d[\d.,]*)\s?(?:€|EUR|Euro)(?![A-Za-z])")
RE_AZ = re.compile(r"\b([A-Z]{2,8}\s?[A-Z]{0,3}\s?\d{1,3}\s?\/\s?\d{2,4})\b")


def build(mandate_dir: Path) -> dict:
    """Extrahiert Entitäten aus allen Volltexten des Mandats."""
    nodes: dict = {"normen": set(), "daten": set(), "betraege": set(),
                   "aktenzeichen": set(), "dokumente": set()}
    edges: list = []
    dok_dir = mandate_dir / "dokumente"
    if not dok_dir.exists():
        return {"nodes": {k: sorted(v) for k, v in nodes.items()}, "edges": edges}

    for doc in sorted(dok_dir.glob("*.txt")) + sorted(dok_dir.glob("*.csv")):
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        nodes["dokumente"].add(doc.stem)
        found_norms = set(RE_NORM.findall(text))
        found_dates = set(RE_DATE.findall(text))
        found_amounts = set(RE_AMOUNT.findall(text))
        found_az = set(RE_AZ.findall(text))
        nodes["normen"].update(found_norms)
        nodes["daten"].update(found_dates)
        nodes["betraege"].update(found_amounts)
        nodes["aktenzeichen"].update(found_az)
        for n in found_norms:
            edges.append({"von": doc.stem, "nach": f"Norm:{n}", "art": "erwähnt"})
        for d in found_dates:
            edges.append({"von": doc.stem, "nach": f"Datum:{d}", "art": "datiert"})
        for a in found_amounts:
            edges.append({"von": doc.stem, "nach": f"Betrag:{a} €", "art": "beträgt"})

    return {"nodes": {k: sorted(v) for k, v in nodes.items()}, "edges": edges}


def summary(graph: dict, max_chars: int = 2500) -> str:
    """Kompakte Text-Sicht des Graphen als Subagenten-Kontext."""
    n = graph.get("nodes", {})
    lines = ["Mandats-Wissensgraph (aus Dokumenten extrahiert):"]
    if n.get("dokumente"):
        lines.append("Dokumente: " + ", ".join(n["dokumente"]))
    if n.get("normen"):
        lines.append("Erwähnte Normen: " + ", ".join(dict.fromkeys(n["normen"])))
    if n.get("daten"):
        lines.append("Daten: " + ", ".join(sorted(set(n["daten"]))[:15]))
    if n.get("betraege"):
        lines.append("Beträge (€): " + ", ".join(sorted(set(n["betraege"]))[:15]))
    if n.get("aktenzeichen"):
        lines.append("Aktenzeichen: " + ", ".join(n["aktenzeichen"]))
    out = "\n".join(lines)
    return out[:max_chars]


def save(mandate_dir: Path) -> dict:
    g = build(mandate_dir)
    (mandate_dir / "graph.json").write_text(
        json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    return g
