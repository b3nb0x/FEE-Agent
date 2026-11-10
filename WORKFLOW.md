# Der F.E.E. Master-Workflow (6 Phasen)

Jedes Mandat durchläuft der Master Agent in sechs Phasen. Delegation ist Pflicht, Selbst-Arbeit die Ausnahme (nur bei Trivialitäten).

## Phase 1 – Aufnahme (Master selbst)

- Nutzeranfrage + Dokumente entgegennehmen
- Mandat klären (bestehend? neu? → Subagent `mandant`)
- Unklarheiten ausräumen: gezielte Nachfragen (WER/WAS/FRISTEN/VERFAHREN/RECHTSGEBIET)

## Phase 2 – Analyse (→ Subagent `analyse`)

**Auftrag an analyse:** „Strukturiere folgenden Sachverhalt: [Kontext]. Liefere: chronologische Fakten, Beteiligte mit Rollen, offene Lücken (was fehlt für eine Prüfung?), erste Risikokennzeichnung. Keine rechtliche Bewertung."

**Prüfung des Ergebnisses:** Vollständig? Lücken explizit benannt? Keine Bewertungen vorgetäuscht?

## Phase 3 – Planung (→ Subagent `planung`)

**Auftrag an planung:** „Erstelle Prüf-/Verfahrensplan zu: [Analyse-Ergebnis]. Liefere: zu prüfende Ansprüche/Normen (Prüfreihenfolge), relevante Fristen (⚠️ mit Warnhinweis), zuständiger Rechtsweg, Arbeitspakete für die Subagenten, Dringlichkeitsreihenfolge."

**Prüfung:** Fristen korrekt zugeordnet? Prüfreihenfolge logisch (Anspruchsgrundlage vor Anspruchsvoraussetzung)?

## Phase 4 – Recherche & Prüfung (parallel: → `recherche`, `pruefung`)

**Auftrag an recherche:** „Verifiziere: [Normen/Urteile aus dem Plan]. Liefere je Fundstelle: exaktes Zitat, Stand/Fassung, bei Urteilen Gericht+Az.+Datum+Leitsatz, Konfidenz."

**Auftrag an pruefung:** „Prüfe im Gutachtenstil: [Anspruch/Frage]. Nutze: [Recherche-Ergebnisse]. Liefere: Obersatz, Definition, Subsumtion, Ergebnis je Prüfpunkt; Gegenansichten bei Streit."

**Prüfung:** Jede Aussage mit Fundstelle? Aktenzeichen verifiziert (nicht erfunden)? Streitfragen mit Mindermeinung dargestellt?

## Phase 5 – Darstellung (→ Subagent `darstellung`)

**Auftrag an darstellung:** „Erstelle [Bericht/Schriftsatz-Entwurf/Gutachten] aus: [geprüfte Ergebnisse]. Struktur: Zusammenfassung → Sachverhalt → rechtliche Würdigung → Handlungsempfehlungen (nach Dringlichkeit) → offene Fragen → Haftungshinweis (wörtlich)."

**Prüfung:** Pflicht-Haftungshinweis als letzte Zeile? Fristen rot/warnend? Sprache verständlich?

## Phase 6 – Abschluss (Master selbst)

- Ergebnisse ins Mandats-Memory schreiben (→ Subagent `mandant` für Registry/Fristen)
- Nutzer-Ausgabe: Statuszeile (welche Subagenten liefen), Gesamtprodukt, nächste Schritte
- Offene Punkte dokumentieren

## Delegations-Disziplin (immer)

1. **Auftrag = Kontext + Ziel + Format + Grenze** („nicht über den Auftrag hinaus entscheiden")
2. **Ergebnis prüfen, bevor es übernommen wird** – bei Mängeln: einmal nachbessern lassen mit konkreter Kritik
3. **Mandatstrennung:** Subagenten bekommen nur den Sachverhalt ihres Mandats
4. **Dokumente** laufen immer über Subagent `dokumente` (Original in `eingang/`, Volltext in `dokumente/`)
5. **Keine Frist berechnet der Master selbst** – Fristen kommen von `planung` mit Warnhinweis, verbindlich nur anwaltlich

## Trivialfälle (Ausnahme von der Delegierung)

Bei einfachen Einzelfragen („Was sagt § 536 BGB?") arbeitet der Master direkt mit den F.E.E.-Skills – Delegation wäre Overkill. Kriterium: eine Phase reicht für die Antwort.
