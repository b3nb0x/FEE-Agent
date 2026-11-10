# FEE-Agent – Der eigenständige juristische Master-Agent

<p align="center"><b>F.E.E. Agent</b> – Master-Agent mit Subagenten, eigenständig lauffähig, mit Web-GUI.</p>

**FEE-Agent** ist ein eigenständiges Programm (kein Hermes, kein Claude Code nötig): Ein Master-Agent orchestriert spezialisierte Subagenten für die juristische Fallbearbeitung – **Analyse, Planung, Recherche, Prüfung, rechtliche Darstellung** – und die Web-GUI verwaltet Mandate, Dokumente und Fristen. Die Wissensbasis (Recherche-Abläufe, Instincts, Security-Regeln) kommt aus dem [F.E.E.-Repo](https://github.com/b3nb0x/F.E.E.).

## Architektur

```
Nutzer ⇄ Web-GUI (localhost:8765)
              │
        FastAPI-Server (feeagent/server.py)
              │
        Master-Agent (feeagent/agent.py)  ── 6-Phasen-Workflow
              │ delegiert an Subagenten (subagents/*/SOUL.md)
   ┌──────────┼──────────┬──────────┬──────────┬──────────┐
 analyse   recherche   planung   pruefung  darstellung  dokumente/mandant
              │
        LLM-Endpoint (OpenAI-kompatibel, konfigurierbar)
        z. B. lokaler llama.cpp-Server: http://localhost:8080/v1
```

**Der 6-Phasen-Workflow** (siehe `WORKFLOW.md`):

1. **Aufnahme** (Master) – Anliegen + Mandat klären
2. **Analyse** (Subagent `analyse`) – Sachverhalt strukturieren, Lücken finden
3. **Planung** (Subagent `planung`) – Prüfreihenfolge, Fristen ⚠️, Rechtsweg
4. **Recherche + Prüfung** (Subagents `recherche` + `pruefung`) – Fundstellen verifizieren, Gutachtenstil
5. **Darstellung** (Subagent `darstellung`) – Bericht mit Handlungsempfehlungen
6. **Abschluss** (Master) – Ergebnis mit Pflicht-Haftungshinweis

Jede Ausarbeitung endet wörtlich mit dem Haftungshinweis (keine Rechtsberatung im Sinne des RDG).

## Installation & Start

```bash
git clone https://github.com/b3nb0x/FEE-Agent.git
cd FEE-Agent
./run.sh
```

Dann im Browser öffnen: **http://localhost:8765**

`run.sh` legt beim ersten Start eine virtuelle Python-Umgebung an und installiert FastAPI/uvicorn.

**Modell einbinden** (Tab „Einstellungen"):

| Szenario | Endpoint | Modell |
|---|---|---|
| **LM Studio** (lokal, GPU) | `http://localhost:1234/v1` | leer lassen oder Name des geladenen Modells |
| llama.cpp (lokal) | `http://localhost:8080/v1` | Name des geladenen Modells |
| Cloud (OpenRouter, Mistral, …) | `https://openrouter.ai/api/v1` | z. B. `mistralai/mistral-large` + API-Key |

**LM Studio** (empfohlen für den lokalen Betrieb):
1. Modell laden (Register „Chat"): bei 6 GB VRAM ein 7–8B-Modell in **Q4_K_M** (z. B. `Meta-Llama-3.1-8B-Instruct` oder `Mistral-7B-Instruct`)
2. Register **„Developer"** → **„Start Server"** (Standard-Port 1234)
3. In der FEE-Agent-GUI (Tab „Einstellungen"): Endpoint `http://localhost:1234/v1` eintragen

llama.cpp alternativ:
```bash
./llama-server -m <modell>.gguf --port 8080
```

## OCR-/Dokumenten-Werkzeuge (optional, für Dokument-Aufnahme)

```bash
# Debian/Ubuntu/Mint:
sudo apt-get install tesseract-ocr tesseract-ocr-deu poppler-utils libreoffice
# Fedora/Nobara:
sudo dnf install tesseract tesseract-langpack-deu poppler-utils libreoffice
```

Unterstützte Typen: PDF (Text-Layer + Scan-OCR), Bilder (JPG/PNG/TIFF), Word (doc/docx/odt/rtf), Excel (xls/xlsx/ods → csv).

## Web-GUI

- **Tab „Mandate":** Mandate anlegen (Ordnerkonvention `JJJJ-MM-TT_<Slug>_<Name>/` mit `eingang/`, `dokumente/`, `notizen/`, `MANDAT.md`, `fristen.md`), Liste mit Status und nächster Frist
- **Tab „Fallbearbeitung":** Mandat wählen → Dokumente hochladen (automatische OCR-Aufnahme) → Anliegen eingeben → der Master-Workflow läuft mit Live-Status je Subagent → Ergebnis
- **Tab „Einstellungen":** LLM-Endpoint, Modell, API-Key

## Mandate-Speicherort

Standard: `~/FEE-Mandate` – überschreibbar mit `FEE_MANDATE_DIR=/pfad ./run.sh`.

## Subagenten

| Subagent | Aufgabe |
|---|---|
| `analyse` | Sachverhalt strukturieren, Fakten/Lücken/Risiken |
| `recherche` | Normen + Urteile verifiziert (Fundstellen-Pflicht) |
| `pruefung` | Gutachtenstil-Prüfung mit Gegenansichten |
| `planung` | Fristen ⚠️, Rechtsweg, Arbeitspakete |
| `darstellung` | Berichte/Schriftsatz-Entwürfe (nie versandfertig ohne Freigabe) |
| `dokumente` | OCR-Aufnahme, Original-Schutz |
| `mandant` | Registry, Mandatstrennung, Merge nur nach Bestätigung |

Jeder Subagent hat eine eigene `SOUL.md` (Mission + Regeln) in `subagents/<name>/`.

## Eingebaute Fähigkeits-Module (nach den Hermes-Plugins headroom, graphify, memory)

| Modul | Vorbild | Was es für Master + Subagenten tut |
|---|---|---|
| `feeagent/headroom.py` | headroom | Schwere Jobs (OCR, LibreOffice) laufen nur bei genug freiem RAM, eine nach der anderen, mit Queue und sauberer Fehlermeldung statt Absturz. Status: `GET /api/headroom` |
| `feeagent/graph.py` | graphify | Mandats-Wissensgraph: extrahiert Normen, Daten, Beträge, Aktenzeichen aus allen Dokumenten-Volltexten – Subagenten erhalten die Graph-Zusammenfassung statt ganzer Dokumente (Token-Ersparnis). `GET /api/mandates/{slug}/graph`, gespeichert als `graph.json` |
| `feeagent/memory.py` | memory | Sitzungsübergreifendes Mandats-Gedächtnis: Fakten/Fristen als `memory.jsonl`; der Workflow destilliert Subagenten-Ergebnisse automatisch in Memory-Einträge und lädt das Memory beim nächsten Lauf als Kontext. `GET/POST /api/mandates/{slug}/memory` |

## Beziehung zu F.E.E.

FEE-Agent ist die Orchestrierungsschicht; F.E.E. (`b3nb0x/F.E.E.`) liefert das juristische Handwerk (Skills, Instincts, Security, Mandatskonvention). Beide Repos können unabhängig genutzt werden: F.E.E. in Hermes/Claude Code, FEE-Agent als eigenständiges Programm.

## Lizenz

MIT
