"""
PolitCheck – Hauptskript
Orchestriert API-Abruf, KI-Analyse und HTML-Report in drei Modi.

Verwendung:
    python main.py fetch   --from-date 2024-01-01          # Daten ab Datum laden & in DB speichern
    python main.py fetch   --from-date 2024-01-01 --to-date 2024-06-30 --limit 50
    python main.py analyse                                  # Gespeicherte Daten analysieren & anzeigen
    python main.py analyse --partei SPD --thema Migration
    python main.py report                                   # HTML-Report generieren
    python main.py report  --output output/report.html --open
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from src.bundestag_api import BundestagAPI
from src.extractor import AussagenExtractor
from src.database import Database
from src.reporter import generiere_html_report


# ─────────────────────────────────────────────────────────────────────────────
# Mode 1 – FETCH
# ─────────────────────────────────────────────────────────────────────────────

def cmd_fetch(args):
    """Ruft Plenarprotokolle ab einem Startdatum ab und speichert Aussagen in der DB."""

#    if not os.environ.get("ANTHROPIC_API_KEY"):
#        print("❌ Kein ANTHROPIC_API_KEY gesetzt!")
#        print("   Setze ihn mit: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
#        sys.exit(1)

    print(f"\n🏛️  PolitCheck – Fetch-Modus")
    print(f"   Wahlperiode : {args.wahlperiode}")
    print(f"   Von Datum   : {args.from_date}")
    if args.to_date:
        print(f"   Bis Datum   : {args.to_date}")
    print(f"   Limit       : {args.limit} Protokolle\n")

    db = Database()
    api = BundestagAPI()
    extractor = AussagenExtractor()

    # Protokolle laden
    print("📥 Lade Plenarprotokolle von der Bundestag API...")
    try:
        result = api.get_reden(
            wahlperiode=args.wahlperiode,
            limit=args.limit,
            datum_von=args.from_date,
            datum_bis=args.to_date,
        )
    except Exception as e:
        print(f"❌ API-Fehler: {e}")
        db.close()
        sys.exit(1)

    dokumente = result.get("documents", [])
    if not dokumente:
        print("⚠️  Keine Protokolle für den angegebenen Zeitraum gefunden.")
        db.close()
        return

    print(f"   {len(dokumente)} Protokoll(e) gefunden\n")

    neu = 0
    gesamt_aussagen = 0
    uebersprungen = 0

    for i, dok in enumerate(dokumente, 1):
        dok_id   = str(dok.get("id", ""))
        titel    = dok.get("titel", "Unbekannt")
        datum    = dok.get("datum", "")
        url      = (
            dok.get("fundstelle", {}).get("pdf_url", "")
            or f"https://dip.bundestag.de/vorgang/{dok_id}"
        )

        prefix = f"  [{i}/{len(dokumente)}]"

        # Bereits verarbeitet?
        if db.quelle_bereits_verarbeitet(dok_id):
            print(f"{prefix} ⏭️  Bereits verarbeitet: {titel[:60]}")
            uebersprungen += 1
            continue

        print(f"{prefix} 🔍 Analysiere: {titel[:60]}")

        # Text zusammensetzen
        text_parts = [titel]
        if dok.get("abstract"):
            text_parts.append(dok["abstract"])
        text = "\n\n".join(text_parts)

        if len(text.strip()) < 50:
            print("           ⚠️  Zu wenig Text, überspringe")
            db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            uebersprungen += 1
            continue

        try:
            aussagen = extractor.extrahiere_aussagen(
                text=text,
                quelle_titel=titel,
                quelle_url=url,
                max_aussagen=args.max_aussagen,
            )

            for aussage in aussagen:
                db.speichere_aussage(aussage)
                gesamt_aussagen += 1

            db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            neu += 1
            print(f"           ✅ {len(aussagen)} Aussage(n) extrahiert")

        except Exception as e:
            print(f"           ❌ Fehler bei KI-Extraktion: {e}")
            continue

    stats = db.get_statistiken()
    db.close()

    print(f"\n📊 Zusammenfassung:")
    print(f"   Neu verarbeitet : {neu} Quellen")
    print(f"   Übersprungen    : {uebersprungen} Quellen")
    print(f"   Neue Aussagen   : {gesamt_aussagen}")
    print(f"   Gesamt in DB    : {stats['total_aussagen']} Aussagen")
    print(f"\n💡 Tipp: Führe 'python main.py analyse' oder 'python main.py report' aus.")


# ─────────────────────────────────────────────────────────────────────────────
# Mode 2 – ANALYSE
# ─────────────────────────────────────────────────────────────────────────────

def cmd_analyse(args):
    """Analysiert und zeigt die gespeicherten Daten in der Konsole."""

    db = Database()
    stats = db.get_statistiken()

    if stats["total_aussagen"] == 0:
        print("\n⚠️  Keine Daten in der Datenbank.")
        print("   Führe zuerst 'python main.py fetch --from-date YYYY-MM-DD' aus.")
        db.close()
        return

    print(f"\n📊 PolitCheck – Analyse")
    print("=" * 50)
    print(f"   Aussagen gesamt      : {stats['total_aussagen']}")
    print(f"   Verarbeitete Quellen : {stats['verarbeitete_quellen']}")

    # Themenverteilung
    print(f"\n📁 Themenverteilung:")
    for t in stats["themen"]:
        bar = "█" * t["n"]
        print(f"   {t['thema']:<20} {bar}  ({t['n']})")

    # Politiker-Ranking
    politiker_stats = db.get_politiker_stats()
    if politiker_stats:
        print(f"\n🏆 Top-Politiker nach Ø Polarisierung:")
        print(f"   {'Name':<28} {'Partei':<12} {'Aussagen':>8}  {'Ø Pol.':>7}  {'Max':>4}")
        print("   " + "-" * 65)
        for p in politiker_stats[:10]:
            avg = p["avg_polarisierung"] or 0
            mx  = p["max_polarisierung"] or 0
            print(
                f"   {p['politiker']:<28} {(p['partei'] or '-'):<12}"
                f" {p['anzahl_aussagen']:>8}  {avg:>7.1f}  {mx:>4}"
            )

    # Top-Aussagen (optional gefiltert)
    filter_info = []
    if args.partei:
        filter_info.append(f"Partei={args.partei}")
    if args.thema:
        filter_info.append(f"Thema={args.thema}")

    filter_label = f" [{', '.join(filter_info)}]" if filter_info else ""
    print(f"\n🔥 Top-{args.top} Aussagen nach Polarisierung{filter_label}:")
    print("=" * 50)

    top_aussagen = db.get_top_aussagen(
        limit=args.top,
        partei=args.partei or None,
        thema=args.thema or None,
    )

    if not top_aussagen:
        print("   Keine Aussagen gefunden (Filter zu eng?).")
    else:
        for i, a in enumerate(top_aussagen, 1):
            grad    = a["polarisierungsgrad"] or 0
            filled  = "●" * grad
            empty   = "○" * (10 - grad)
            extreme = ", ".join(a["sprachliche_extreme"] or [])

            print(f"\n  [{i}] {a['politiker']} ({a['partei'] or '?'})  –  {a['datum'] or 'kein Datum'}")
            print(f"      Thema      : {a['thema'] or 'Sonstiges'}")
            print(f"      Polarisier.: {filled}{empty}  {grad}/10")
            print(f"      Aussage    : {a['aussage'][:120]}{'…' if len(a['aussage']) > 120 else ''}")
            print(f"      Begründung : {a['polarisierungsbegruendung'][:100]}")
            if extreme:
                print(f"      Extreme    : {extreme}")

    db.close()
    print(f"\n💡 Tipp: Führe 'python main.py report' aus um einen HTML-Report zu erstellen.")


# ─────────────────────────────────────────────────────────────────────────────
# Mode 3 – REPORT
# ─────────────────────────────────────────────────────────────────────────────

def cmd_report(args):
    """Generiert den HTML-Report und öffnet ihn optional im Browser."""

    db = Database()
    stats = db.get_statistiken()

    if stats["total_aussagen"] == 0:
        print("\n⚠️  Keine Daten in der Datenbank.")
        print("   Führe zuerst 'python main.py fetch --from-date YYYY-MM-DD' aus.")
        db.close()
        return

    print(f"\n📄 PolitCheck – Report-Modus")
    print(f"   Generiere Report aus {stats['total_aussagen']} Aussagen...")

    report_path = generiere_html_report(db, args.output)
    db.close()

    abs_path = Path(report_path).resolve()
    print(f"✅ Report gespeichert: {abs_path}")

    if args.open:
        webbrowser.open(abs_path.as_uri())
        print("🌐 Report im Browser geöffnet.")
    else:
        print(f"💡 Tipp: Öffne die Datei im Browser oder nutze --open.")


# ─────────────────────────────────────────────────────────────────────────────
# CLI-Definitionen
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="politcheck",
        description="PolitCheck – Bundestag Aussagen-Analyse in drei Modi",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modi:
  fetch    Lädt Plenarprotokolle ab einem Datum und speichert Aussagen in der DB
  analyse  Zeigt statistische Auswertung der gespeicherten Daten
  report   Generiert einen HTML-Report aus den gespeicherten Daten

Beispiele:
  python main.py fetch   --from-date 2024-01-01
  python main.py fetch   --from-date 2024-01-01 --to-date 2024-03-31 --limit 30
  python main.py analyse
  python main.py analyse --partei AfD --thema Migration --top 5
  python main.py report
  python main.py report  --open
        """,
    )

    subparsers = parser.add_subparsers(dest="mode", metavar="MODE")
    subparsers.required = True

    # ── fetch ──────────────────────────────────────────────────────────────
    fetch_p = subparsers.add_parser(
        "fetch",
        help="API abrufen und Daten in DB speichern",
        description="Lädt Plenarprotokolle ab einem Startdatum und extrahiert Aussagen per KI.",
    )
    fetch_p.add_argument(
        "--from-date", required=True, metavar="YYYY-MM-DD",
        help="Startdatum für den API-Abruf (erforderlich)"
    )
    fetch_p.add_argument(
        "--to-date", default=None, metavar="YYYY-MM-DD",
        help="Enddatum für den API-Abruf (optional, default: heute)"
    )
    fetch_p.add_argument(
        "--limit", type=int, default=10, metavar="N",
        help="Max. Anzahl Protokolle (default: 10)"
    )
    fetch_p.add_argument(
        "--wahlperiode", type=int, default=20,
        help="Wahlperiode (default: 20)"
    )
    fetch_p.add_argument(
        "--max-aussagen", type=int, default=3, metavar="N",
        help="Max. Aussagen pro Protokoll (default: 3)"
    )
    fetch_p.set_defaults(func=cmd_fetch)

    # ── analyse ────────────────────────────────────────────────────────────
    analyse_p = subparsers.add_parser(
        "analyse",
        help="Gespeicherte Daten analysieren und anzeigen",
        description="Wertet die Daten in der Datenbank aus und zeigt Statistiken in der Konsole.",
    )
    analyse_p.add_argument(
        "--partei", default=None,
        help="Nur Aussagen dieser Partei anzeigen (z.B. SPD, AfD)"
    )
    analyse_p.add_argument(
        "--thema", default=None,
        help="Nur Aussagen zu diesem Thema (z.B. Migration, Wirtschaft)"
    )
    analyse_p.add_argument(
        "--top", type=int, default=10, metavar="N",
        help="Anzahl Top-Aussagen (default: 10)"
    )
    analyse_p.set_defaults(func=cmd_analyse)

    # ── report ─────────────────────────────────────────────────────────────
    report_p = subparsers.add_parser(
        "report",
        help="HTML-Report generieren",
        description="Erstellt einen HTML-Report aus den gespeicherten Daten.",
    )
    report_p.add_argument(
        "--output", default="output/report.html", metavar="PFAD",
        help="Ausgabepfad des Reports (default: output/report.html)"
    )
    report_p.add_argument(
        "--open", action="store_true",
        help="Report nach Erstellung im Browser öffnen"
    )
    report_p.set_defaults(func=cmd_report)

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Einstiegspunkt
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
