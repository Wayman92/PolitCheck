# 🏛️ PolitCheck

Automatische Analyse polarisierender Aussagen aus dem Deutschen Bundestag.

## Was macht PolitCheck?

1. **Lädt** Plenarprotokolle über die offizielle Bundestag Open Data API
2. **Extrahiert** mit Claude AI die polarisierendsten / kontroversesten Aussagen
3. **Speichert** sie in einer lokalen SQLite-Datenbank
4. **Generiert** einen übersichtlichen HTML-Report

## Setup

```powershell
# Dependencies installieren
pip install -r requirements.txt

# Anthropic API Key setzen
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Verwendung

```powershell
# Standard: 10 neueste Plenarprotokolle analysieren
python main.py

# Mehr Protokolle
python main.py --limit 20

# Nur HTML-Report aus vorhandenen Daten neu generieren
python main.py --report-only

# Statistiken anzeigen
python main.py --stats
```

## Projektstruktur

```
PolitCheck/
├── main.py                 # Einstiegspunkt / Orchestrierung
├── requirements.txt
├── src/
│   ├── bundestag_api.py    # Bundestag DIP API Client
│   ├── extractor.py        # KI-Extraktion via Claude API
│   ├── database.py         # SQLite-Datenbankschicht
│   └── reporter.py         # HTML-Report Generator
├── data/
│   └── politcheck.db       # SQLite-Datenbank (auto-erstellt)
└── output/
    └── report.html         # Generierter Report
```

## Datenmodell: Aussage

| Feld | Beschreibung |
|------|-------------|
| `politiker` | Vollständiger Name |
| `partei` | Partei des Politikers |
| `datum` | Datum der Aussage |
| `aussage` | Die Aussage im Wortlaut |
| `kontext` | Kurze Kontextbeschreibung |
| `thema` | Wirtschaft / Migration / Klimaschutz / … |
| `polarisierungsgrad` | 1–10 (KI-bewertet) |
| `polarisierungsbegruendung` | Warum ist es polarisierend? |
| `sprachliche_extreme` | Absolutbegriffe wie "immer", "alle", "nie" |
| `quelle_url` | Link zum Original-Protokoll |

## Hinweis

Der Polarisierungsgrad ist eine automatische KI-Einschätzung, keine redaktionelle Bewertung. 
Alle Aussagen sind mit dem Originalprotokoll verlinkt und überprüfbar.

---
Datenquelle: [Bundestag Open Data API](https://dip.bundestag.de/über-dip/hilfe/api) · KI: Anthropic Claude
