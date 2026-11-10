# FEE-Agent – Master-Orchestrierung

Dieser Ordner definiert den **F.E.E. Master Agent** und seine Subagenten. Die Wissensbasis (Recherche-Abläufe, Instincts, Security-Regeln) kommt aus dem **F.E.E.-Repo** (`b3nb0x/F.E.E.`) – FEE-Agent orchestriert, F.E.E. liefert das juristische Handwerk.

## Aufbau

```
FEE-Agent/
├── SOUL.md               # Identität + Eisenregeln des Master Agents
├── WORKFLOW.md           # Der 6-Phasen-Orchestrierungs-Workflow
├── subagents/            # Ein Ordner je Subagent (SOUL + Auftrag)
│   ├── analyse/          # Sachverhaltsanalyse
│   ├── recherche/        # Normen- & Urteilsrecherche
│   ├── pruefung/         # Rechtliche Prüfung (Gutachtenstil)
│   ├── planung/          # Verfahrens-/Fristenplanung
│   ├── darstellung/      # Rechtliche Darstellung (Berichte, Schriftsätze)
│   ├── dokumente/        # Dokumenten-Aufnahme & OCR
│   └── mandant/          # Mandatsverwaltung & Registry
├── config/               # Hermes-Delegations-Konfiguration (Beispiele)
└── install.sh            # Installation (FEE-Agent + F.E.E.-Basis)
```

## Subagenten-Übersicht

| Subagent | Aufgabe | Nutzt F.E.E.-Skills |
|---|---|---|
| `analyse` | Sachverhalt strukturieren, Fakten/Lücken/Risiken identifizieren | 00, 16 |
| `recherche` | Normen + Urteile verifiziert recherchieren | 01, 02, 13 |
| `pruefung` | Anspruchsprüfung im Gutachtenstil, Vertrags-/Urteilsprüfung | 00, 05, 06 |
| `planung` | Rechtsweg, Zuständigkeit, Fristen, Strategie, Charts | 03, 07, 14 |
| `darstellung` | Berichte, Schriftsatz-Entwürfe, Gutachten-Texte | 00 |
| `dokumente` | Dokumente aufnehmen (OCR), indexieren | 08, 16 |
| `mandant` | Mandate anlegen/wechseln/mergen, Registry pflegen | 14 |

## Integration mit Hermes

Hermes unterstützt Subagenten nativ (`delegate_task`). Zwei Betriebsarten (siehe `config/`):

1. **Profil-Routen (empfohlen):** Jeder Subagent ist ein Hermes-Profil mit eigener SOUL.md (aus `subagents/<name>/SOUL.md`) – so erbt jeder Subagent seine Spezialisierung. Konfiguration: `config/hermes-profile-routes.yaml`.
2. **Einfach:** Master delegiert Aufgaben mit vollem Kontext und hängt die Subagenten-SOUL als Auftrag bei.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/b3nb0x/FEE-Agent/main/install.sh | sh
```

Der Installer installiert FEE-Agent **und** die F.E.E.-Basis (Skills, Memory, Security) in alle erkannten Agenten.
