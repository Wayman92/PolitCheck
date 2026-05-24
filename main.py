"""
PolitCheck – Hauptskript
Orchestriert: API-Abruf → KI-Extraktion → Datenbank → HTML-Report

Verwendung:
    python main.py                    # Standard: 10 neueste Protokolle
    python main.py --limit 20         # 20 Protokolle
    python main.py --report-only      # Nur Report aus vorhandenen Daten
    python main.py --stats            # Statistiken anzeigen
"""

import argparse
import os
import sys
from src.bundestag_api import BundestagAPI
from src.extractor import AussagenExtractor
from src.database import Database
from src.reporter import generiere_html_report


def main():
    parser = argparse.ArgumentParser(description="PolitCheck – Bundestag Aussagen-Analyse")
    parser.add_argument("--limit", type=int, default=10, help="Anzahl Protokolle (default: 10)")
    parser.add_argument("--wahlperiode", type=int, default=20, help="Wahlperiode (default: 20)")
    parser.add_argument("--report-only", action="store_true", help="Nur Report generieren")
    parser.add_argument("--stats", action="store_true", help="Statistiken anzeigen")
    parser.add_argument("--output", default="output/report.html", help="Report-Pfad")
    args = parser.parse_args()

    # API Key prüfen
    if not args.report_only and not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ Kein ANTHROPIC_API_KEY gesetzt!")
        print("   Setze ihn mit: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    db = Database()

    # Nur Statistiken anzeigen
    if args.stats:
        stats = db.get_statistiken()
        print(f"\n📊 PolitCheck Statistiken")
        print(f"   Aussagen gesamt:       {stats['total_aussagen']}")
        print(f"   Verarbeitete Quellen:  {stats['verarbeitete_quellen']}")
        print(f"\n   Themenverteilung:")
        for t in stats["themen"]:
            print(f"   • {t['thema']:<20} {t['n']} Aussagen")
        db.close()
        return

    # Nur Report generieren
    if args.report_only:
        print("📄 Generiere Report aus vorhandenen Daten...")
        generiere_html_report(db, args.output)
        db.close()
        return

    # Vollständiger Durchlauf
    print(f"\n🏛️  PolitCheck startet")
    print(f"   Wahlperiode: {args.wahlperiode} | Limit: {args.limit} Protokolle\n")

    api = BundestagAPI()
    extractor = AussagenExtractor()

    # Protokolle laden
    print("📥 Lade Plenarprotokolle von der Bundestag API...")
    try:
        result = api.get_reden(wahlperiode=args.wahlperiode, limit=args.limit)
    except Exception as e:
        print(f"❌ API-Fehler: {e}")
        sys.exit(1)

    dokumente = result.get("documents", [])
    print(f"   {len(dokumente)} Protokolle gefunden\n")

    neu = 0
    gesamt_aussagen = 0

    for i, dok in enumerate(dokumente, 1):
        dok_id = str(dok.get("id", ""))
        titel = dok.get("titel", "Unbekannt")
        datum = dok.get("datum", "")
        url = dok.get("fundstelle", {}).get("pdf_url", "") or \
              f"https://dip.bundestag.de/vorgang/{dok_id}"

        # Bereits verarbeitet?
        if db.quelle_bereits_verarbeitet(dok_id):
            print(f"  [{i}/{len(dokumente)}] ⏭️  Bereits verarbeitet: {titel[:60]}")
            continue

        print(f"  [{i}/{len(dokumente)}] 🔍 Analysiere: {titel[:60]}")

        # Text zusammensetzen
        text_parts = [titel]
        if dok.get("abstract"):
            text_parts.append(dok["abstract"])
        text = "\n\n".join(text_parts)

        if len(text.strip()) < 50:
            print("      ⚠️  Zu wenig Text, überspringe")
            db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            continue

        try:
            aussagen = extractor.extrahiere_aussagen(
                text=text,
                quelle_titel=titel,
                quelle_url=url,
                max_aussagen=3,
            )

            for aussage in aussagen:
                db.speichere_aussage(aussage)
                gesamt_aussagen += 1

            db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            neu += 1
            print(f"      ✅ {len(aussagen)} Aussagen extrahiert")

        except Exception as e:
            print(f"      ❌ Fehler bei KI-Extraktion: {e}")
            continue

    print(f"\n📊 Zusammenfassung:")
    print(f"   Neu verarbeitet:    {neu} Quellen")
    print(f"   Neue Aussagen:      {gesamt_aussagen}")

    stats = db.get_statistiken()
    print(f"   Gesamt in DB:       {stats['total_aussagen']} Aussagen")

    print(f"\n📄 Generiere HTML-Report...")
    generiere_html_report(db, args.output)

    print(f"\n✅ Fertig! Öffne {args.output} im Browser.")
    db.close()


if __name__ == "__main__":
    main()
