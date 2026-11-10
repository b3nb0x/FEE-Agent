"""F.E.E. Master Agent – eigenständiger Agenten-Kern.

Orchestriert Subagenten (Analyse → Planung → Recherche → Prüfung → Darstellung)
über einen OpenAI-kompatiblen Endpoint (z. B. lokaler llama.cpp-Server).
"""
import json
import os
import re
import urllib.request
from pathlib import Path

from . import graph as fee_graph
from . import memory as fee_memory

BASE = Path(__file__).resolve().parent.parent
SUBAGENTS_DIR = BASE / "subagents"
MANDATE_DIR = Path(os.environ.get("FEE_MANDATE_DIR", Path.home() / "FEE-Mandate"))

DISCLAIMER = (
    "> ⚠️ Diese Ausarbeitung ist eine unverbindliche, automatisierte Vorab-Information "
    "und **keine Rechtsberatung** im Sinne des Rechtsdienstleistungsgesetzes (RDG). "
    "Für eine verbindliche Einschätzung – insbesondere bei laufenden Fristen, hohem "
    "Streitwert oder Straf-/Verwaltungsverfahren – konsultiere eine Anwältin oder einen "
    "Anwalt. Bei geringem Einkommen: Beratungshilfe (§ 1 BerHG) über die örtliche "
    "Rechtsantragsstelle."
)

# Phasen des Master-Workflows (WORKFLOW.md)
PHASES = [
    ("analyse", "Strukturiere den folgenden Sachverhalt: Fakten chronologisch, "
               "Beteiligte mit Rollen, Dokumente, offene Lücken, Risikokennzeichnung. "
               "Keine rechtliche Bewertung."),
    ("planung", "Erstelle Prüf-/Verfahrensplan: zu prüfende Ansprüche und Normen "
                "(Prüfreihenfolge), relevante Fristen (⚠️ immer mit Warnhinweis), "
                "zuständiger Rechtsweg, Arbeitspakete, Dringlichkeit."),
    ("recherche", "Recherchiere und verifiziere die zentralen Normen und die relevante "
                  "Rechtsprechung zu dem geplanten Prüfungsgegenstand mit exakten "
                  "Fundstellen. Kennzeichne alles Unverifizierte."),
    ("pruefung", "Prüfe die zentralen Ansprüche im Gutachtenstil (Obersatz, Definition, "
                 "Subsumtion, Ergebnis) auf Basis von Analyse, Plan und Recherche. "
                 "Zeige bei Streitfragen die Gegenansicht."),
    ("darstellung", "Erstelle die finale rechtliche Darstellung: Zusammenfassung → "
                    "Sachverhalt → rechtliche Würdigung → Handlungsempfehlungen "
                    "(nach Dringlichkeit) → offene Fragen. Beende wörtlich mit dem "
                    "Haftungshinweis."),
]


def load_soul(name: str) -> str:
    p = SUBAGENTS_DIR / name / "SOUL.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def llm_chat(endpoint: str, model: str, system: str, user: str,
             api_key: str = "", timeout: int = 600) -> str:
    """Aufruf eines OpenAI-kompatiblen /chat/completions-Endpoints."""
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def run_workflow(question: str, mandate_ctx: str, settings: dict,
                 mandate_dir: Path = None) -> dict:
    """Führt den 6-Phasen-Workflow aus. Liefert {phases: [{name, output}], final}.

    Nutzt Mandats-Memory (frühere Sitzungen) und den Mandats-Wissensgraph
    (aus Dokumenten extrahierte Normen/Daten/Beträge) als Kontext.
    """
    phases = []
    extra = ""
    if mandate_dir is not None:
        mem = fee_memory.context(mandate_dir)
        if mem:
            extra += "\n\n" + mem
        g = fee_graph.build(mandate_dir)
        gs = fee_graph.summary(g)
        if "Dokumente:" in gs:
            extra += "\n\n" + gs
    context = f"Mandat-Kontext:\n{mandate_ctx}{extra}\n\nNutzer-Anliegen:\n{question}"

    for name, instruction in PHASES:
        system = load_soul(name)
        user = f"{instruction}\n\n---\n\n{context}"
        try:
            out = llm_chat(settings["endpoint"], settings["model"], system, user,
                           settings.get("api_key", ""))
        except Exception as e:  # noqa: BLE001
            out = f"**Subagent '{name}' fehlgeschlagen:** {e}"
        phases.append({"name": name, "output": out})
        if mandate_dir is not None:
            try:
                fee_memory.distill(mandate_dir, name, out)
            except Exception:  # noqa: BLE001 – Memory darf Workflow nie brechen
                pass
        context = f"{context}\n\n--- Ergebnis Subagent {name}: ---\n{out}"

    final = phases[-1]["output"] if phases else ""
    if DISCLAIMER.split("**")[2][:20] not in final.replace("\n", " "):
        final = final.rstrip() + "\n\n" + DISCLAIMER
    return {"phases": phases, "final": final}


# ---------------------------------------------------------------- Mandate

def mandate_path(slug: str) -> Path:
    return MANDATE_DIR / slug


def list_mandates() -> list:
    out = []
    if MANDATE_DIR.exists():
        for p in sorted(MANDATE_DIR.iterdir()):
            if p.is_dir() and (p / "MANDAT.md").exists():
                fristen = []
                f = p / "fristen.md"
                if f.exists():
                    fristen = re.findall(r"^\|\s*([\d\-\.]{8,10})", f.read_text(
                        encoding="utf-8"), re.M)
                out.append({"slug": p.name, "naechste_frist": fristen[0] if fristen else "",
                            "status": "aktiv" if not (p / "ABGESCHLOSSEN").exists()
                            else "abgeschlossen"})
    return out


def create_mandate(slug: str, anzeigename: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_\-]", "-", slug)
    p = mandate_path(slug)
    for sub in ("eingang", "dokumente", "notizen"):
        (p / sub).mkdir(parents=True, exist_ok=True)
    (p / "MANDAT.md").write_text(
        f"# MANDAT: {slug}\n\nAnzeigename: {anzeigename}\n\n"
        "## Sachverhalt\n\n- \n\n## Offene Punkte\n\n- \n",
        encoding="utf-8")
    (p / "fristen.md").write_text(
        "| Frist | Grund | Norm | Aktion | Status |\n|---|---|---|---|---|\n"
        "\n⚠️ Orientierung, keine verbindliche Fristberechnung – anwaltlich prüfen lassen.\n",
        encoding="utf-8")
    return p
