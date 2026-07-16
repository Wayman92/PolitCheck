"""
PolitCheck – drei unabhängige Workflows

  fetch    – Workflow 1: Bundestag API -> Rohdaten-DB (plenarprotokolle.db)
  extract  – Workflow 2: Rohdaten-DB -> LLM -> Analyse-DB (politcheck.db)
  report   – Workflow 3: Analyse-DB -> HTML-Report

  analyse  – Konsolenausgabe der Analyseergebnisse (Bonus)

Verwendung:
  python main.py fetch   --from-date 2024-01-01
  python main.py fetch   --from-date 2024-01-01 --to-date 2024-06-30 --limit 50
  python main.py extract
  python main.py extract --limit 20 --max-aussagen 5
  python main.py report
  python main.py report  --open
  python main.py analyse --partei AfD --thema Migration
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from src.bundestag_api import BundestagAPI, ProtokollDatabase
from src.extractor import AussagenExtractor, lade_xml, parse_reden_aus_xml, XML_CACHE_DIR
from src.database import Database
from src.reporter import generiere_html_report


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 1 – FETCH
# Bundestag API -> Rohdaten-DB
# ─────────────────────────────────────────────────────────────────────────────

def cmd_fetch(args):
    """
    Fragt die Bundestag API ab und speichert die Rohdaten der Plenarprotokolle
    in der Rohdaten-Datenbank (data/plenarprotokolle.db).
    Keine LLM-Verarbeitung, keine Extraktion.
    """
    print(f"\n[Workflow 1] Bundestag API -> Rohdaten-DB")
    print(f"  Wahlperiode : {args.wahlperiode}")
    print(f"  Von Datum   : {args.from_date}")
    if args.to_date:
        print(f"  Bis Datum   : {args.to_date}")
    if args.limit:
        print(f"  Limit       : {args.limit} Protokolle")
    print()

    api = BundestagAPI()
    db  = ProtokollDatabase()

    print("Lade Plenarprotokolle von der Bundestag API ...")
    try:
        protokolle = api.get_alle_protokolle(
            wahlperiode=args.wahlperiode,
            datum_von=args.from_date,
            datum_bis=args.to_date,
            max_results=args.limit,
            verbose=True,
        )
    except Exception as e:
        print(f"  API-Fehler: {e}")
        db.close()
        sys.exit(1)

    if not protokolle:
        print("  Keine Protokolle fuer den angegebenen Zeitraum gefunden.")
        db.close()
        return

    stats = db.speichere(protokolle)
    db.close()

    print(f"\nErgebnis:")
    print(f"  Abgerufen       : {len(protokolle)} Protokolle")
    print(f"  Neu gespeichert : {stats['neu']}")
    print(f"  Bereits bekannt : {stats['duplikate']}")
    print(f"\nWeiter mit: python main.py extract")


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 2 – EXTRACT
# Rohdaten-DB -> LLM -> Analyse-DB
# ─────────────────────────────────────────────────────────────────────────────

def cmd_extract(args):
    """
    Liest unverarbeitete Protokolle aus der Rohdaten-DB, extrahiert per LLM
    die polarisierendsten Aussagen und speichert sie in der Analyse-DB
    (data/politcheck.db).
    Verarbeitet nur Protokolle, die noch nicht extrahiert wurden.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  Kein ANTHROPIC_API_KEY gesetzt.")
        print("  Setze ihn mit: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    print(f"\n[Workflow 2] Rohdaten-DB -> LLM -> Analyse-DB")
    print(f"  Max. Aussagen/Protokoll : {args.max_aussagen}")
    if args.limit:
        print(f"  Batch-Limit             : {args.limit} Protokolle")
    if args.from_date:
        print(f"  Von Datum               : {args.from_date}")
    if args.to_date:
        print(f"  Bis Datum               : {args.to_date}")
    print()

    protokoll_db = ProtokollDatabase()
    aussagen_db  = Database()
    extractor    = AussagenExtractor()

    # Alle gespeicherten Rohdaten laden
    alle = protokoll_db.get_protokolle(limit=999_999)
    protokoll_db.close()

    # Nur die noch nicht extrahierten filtern
    nicht_extrahiert = [
        p for p in alle
        if not aussagen_db.quelle_bereits_verarbeitet(p["id"])
    ]

    # Optional: Datum-Filter
    if args.from_date:
        nicht_extrahiert = [p for p in nicht_extrahiert if (p["datum"] or "") >= args.from_date]
    if args.to_date:
        nicht_extrahiert = [p for p in nicht_extrahiert if (p["datum"] or "") <= args.to_date]

    if not nicht_extrahiert:
        aussagen_db.close()
        print("  Alle Protokolle wurden bereits extrahiert.")
        print("  Fuehre zuerst 'python main.py fetch' aus um neue Daten zu laden.")
        return

    # Neueste Protokolle zuerst verarbeiten
    nicht_extrahiert.sort(key=lambda p: p.get("datum") or "", reverse=True)

    # Optional: Batch begrenzen
    zu_verarbeiten = nicht_extrahiert[:args.limit] if args.limit else nicht_extrahiert

    print(f"  Protokolle in Rohdaten-DB : {len(alle)}")
    print(f"  Davon noch nicht extrahiert: {len(nicht_extrahiert)}")
    print(f"  In diesem Lauf verarbeiten : {len(zu_verarbeiten)}\n")

    gesamt_aussagen = 0
    gesamt_reden    = 0
    verarbeitet     = 0
    gesamt_kosten   = 0.0
    budget_stop     = False

    for i, p in enumerate(zu_verarbeiten, 1):
        dok_id      = p["id"]
        titel       = p["titel"] or "Unbekannt"
        xml_url     = p["xml_url"]
        pdf_url     = p["pdf_url"]
        datum       = p["datum"]
        wahlperiode = p["wahlperiode"]

        print(f"  [{i}/{len(zu_verarbeiten)}] {titel[:70]}")

        # Schritt 1: XML laden und Reden parsen
        if not xml_url:
            print(f"    Kein XML verfuegbar, ueberspringe")
            aussagen_db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            continue

        xml_bytes = lade_xml(xml_url, XML_CACHE_DIR / f"{dok_id}.xml")
        if not xml_bytes:
            aussagen_db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            continue

        try:
            reden, ordnungsrufe = parse_reden_aus_xml(xml_bytes, dok_id, datum, wahlperiode)
        except Exception as e:
            print(f"    XML-Parse-Fehler: {e}")
            aussagen_db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
            continue

        neu_reden = aussagen_db.speichere_reden(reden)
        if ordnungsrufe:
            aussagen_db.speichere_ordnungsrufe(ordnungsrufe)
            print(f"    Ordnungsrufe: {len(ordnungsrufe)} gespeichert")
        print(f"    XML: {len(reden)} Reden, {neu_reden} neu gespeichert")

        # Schritt 2: Noch nicht analysierte Reden per LLM verarbeiten
        nicht_analysiert = aussagen_db.get_reden_fuer_protokoll(
            dok_id, nur_nicht_analysiert=True
        )
        protokoll_aussagen = 0
        quelle_url = pdf_url or f"https://dip.bundestag.de/vorgang/{dok_id}"

        # Zwischenrufe sofort überspringen, echte Reden sammeln
        reden_zu_screenen = []
        for rede in nicht_analysiert:
            if rede.get("typ") == "zwischenruf":
                aussagen_db.markiere_rede_analysiert(rede["id"])
            else:
                reden_zu_screenen.append(rede)

        # Haiku-Vorfilter: Reden in Batches bewerten (Score 1-5)
        BATCH = extractor._SCREEN_BATCH
        reden_fuer_sonnet = []
        for i in range(0, len(reden_zu_screenen), BATCH):
            batch = reden_zu_screenen[i:i + BATCH]
            scores = extractor.screen_reden_batch(batch)
            for rede, score in zip(batch, scores):
                name_safe = rede["politiker"].encode("ascii", errors="replace").decode("ascii")
                if score >= 4:
                    reden_fuer_sonnet.append(rede)
                else:
                    aussagen_db.markiere_rede_analysiert(rede["id"])
                    print(f"    Haiku skip ({score}/5): {name_safe}")

        print(f"    Haiku: {len(reden_zu_screenen)} Reden -> {len(reden_fuer_sonnet)} fuer Sonnet")

        # Sonnet-Analyse nur für Reden mit Score >= 4
        for rede in reden_fuer_sonnet:
            name_safe = rede["politiker"].encode("ascii", errors="replace").decode("ascii")
            try:
                aussagen = extractor.extrahiere_aussagen_aus_rede(
                    rede=rede,
                    max_aussagen=args.max_aussagen,
                    quelle_url=quelle_url,
                )
                for aussage in aussagen:
                    aussagen_db.speichere_aussage(aussage, rede_id=rede["id"])
                    gesamt_aussagen  += 1
                    protokoll_aussagen += 1
                aussagen_db.markiere_rede_analysiert(rede["id"])
            except Exception as e:
                print(f"    Fehler bei {name_safe}: {e}")
                continue

        aussagen_db.markiere_quelle_verarbeitet(dok_id, "plenarprotokoll")
        gesamt_reden += len(nicht_analysiert)
        verarbeitet  += 1
        print(f"    LLM: {len(nicht_analysiert)} Reden -> {protokoll_aussagen} Aussagen")

        # Geschätzte Kosten: Haiku-Batches + Sonnet-Calls
        kosten_haiku  = (len(reden_zu_screenen) / 8) * 0.006
        kosten_sonnet = len(reden_fuer_sonnet) * 0.0077
        gesamt_kosten += kosten_haiku + kosten_sonnet
        print(f"    Kosten geschätzt: ${gesamt_kosten:.2f}")

        if args.budget and gesamt_kosten >= args.budget:
            print(f"\n  Budget von ${args.budget:.2f} erreicht – stoppe Extract.")
            print(f"  Weiter mit: py main.py profile")
            budget_stop = True
            break

    db_stats = aussagen_db.get_statistiken()
    aussagen_db.close()

    verbleibend = len(nicht_extrahiert) - len(zu_verarbeiten)
    print(f"\nErgebnis:")
    print(f"  Verarbeitet     : {verarbeitet} Protokolle")
    print(f"  Reden analysiert: {gesamt_reden}")
    print(f"  Neue Aussagen   : {gesamt_aussagen}")
    print(f"  Gesamt in DB    : {db_stats['total_aussagen']} Aussagen")
    if verbleibend:
        print(f"  Noch ausstehend : {verbleibend} (naechster Lauf: python main.py extract)")
    elif not budget_stop:
        print(f"\nWeiter mit: python main.py profile")


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 3 – REPORT
# Analyse-DB -> HTML-Report
# ─────────────────────────────────────────────────────────────────────────────

def cmd_report(args):
    """
    Liest die Analyseergebnisse aus der Analyse-DB und generiert den HTML-Report.
    """
    db    = Database()
    stats = db.get_statistiken()

    if stats["total_aussagen"] == 0:
        print("\n  Keine Analyseergebnisse in der Datenbank.")
        print("  Fuehre zuerst 'python main.py extract' aus.")
        db.close()
        return

    print(f"\n[Workflow 3] Analyse-DB -> HTML-Report")
    print(f"  Lese {stats['total_aussagen']} Aussagen aus der Datenbank ...")

    report_path = generiere_html_report(db, args.output)
    db.close()

    abs_path = Path(report_path).resolve()
    print(f"  Report gespeichert: {abs_path}")

    if args.open:
        webbrowser.open(abs_path.as_uri())
        print("  Report im Browser geoeffnet.")
    else:
        print(f"  Oeffne mit --open oder direkt im Browser.")


# ─────────────────────────────────────────────────────────────────────────────
# Workflow 4 – PROFILE
# Analyse-DB -> Politikerprofile
# ─────────────────────────────────────────────────────────────────────────────

def cmd_profile(args):
    """
    Erstellt oder aktualisiert Politikerprofile aus den gesammelten Reden
    und Aussagen. Pro Politiker: Kernthemen, Kernpositionen, Widersprueche,
    rhetorische Muster und eine Zusammenfassung.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  Kein ANTHROPIC_API_KEY gesetzt.")
        print("  Setze ihn mit: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    db        = Database()
    extractor = AussagenExtractor()

    alle_politiker = db.get_alle_politiker(min_reden=args.min_reden)

    if args.politiker:
        suchbegriff    = args.politiker.lower()
        alle_politiker = [p for p in alle_politiker if suchbegriff in p["politiker"].lower()]

    if not alle_politiker:
        print("\n  Keine Politiker gefunden (noch zu wenig Reden extrahiert?).")
        print("  Fuehre zuerst 'python main.py extract' aus.")
        db.close()
        return

    print(f"\n[Workflow 4] Politikerprofile erstellen")
    print(f"  Politiker gefunden : {len(alle_politiker)}")
    if args.politiker:
        print(f"  Filter             : {args.politiker}")
    print(f"  Mindest-Reden      : {args.min_reden}")
    print()

    erstellt = 0
    for i, p_info in enumerate(alle_politiker, 1):
        name   = p_info["politiker"]
        partei = p_info["partei"] or "?"

        print(f"  [{i}/{len(alle_politiker)}] {name} ({partei})"
              f" | {p_info['anzahl_reden']} Reden"
              f" | {p_info['zeitraum_von']} bis {p_info['zeitraum_bis']}")

        reden   = db.get_reden_fuer_politiker(name)
        aussagen = db.get_aussagen_fuer_politiker(name)

        if not aussagen and not args.auch_ohne_aussagen:
            print(f"    Keine Aussagen extrahiert, ueberspringe (--auch-ohne-aussagen zum Erzwingen)")
            continue

        try:
            profil = extractor.erstelle_politikerprofil(
                politiker=name,
                partei=partei,
                reden=reden,
                aussagen=aussagen,
            )
            db.speichere_profil(profil)
            erstellt += 1

            themen = ", ".join(profil.get("kernthemen", [])[:3])
            wsp    = len(profil.get("widersprueche", []))
            print(f"    Kernthemen: {themen or '-'} | Widersprueche: {wsp}")
        except Exception as e:
            print(f"    Fehler: {e}")
            continue

    db.close()
    print(f"\nErgebnis: {erstellt} Profile erstellt/aktualisiert")
    print(f"Weiter mit: python main.py report")


# ─────────────────────────────────────────────────────────────────────────────
# Bonus – ANALYSE (Konsolenausgabe)
# ─────────────────────────────────────────────────────────────────────────────

def cmd_analyse(args):
    """Zeigt Statistiken und Top-Aussagen aus der Analyse-DB in der Konsole."""

    db    = Database()
    stats = db.get_statistiken()

    if stats["total_aussagen"] == 0:
        print("\n  Keine Daten. Fuehre zuerst 'python main.py extract' aus.")
        db.close()
        return

    print(f"\nPolitCheck – Analyse")
    print("=" * 50)
    print(f"  Aussagen gesamt       : {stats['total_aussagen']}")
    print(f"  Verarbeitete Quellen  : {stats['verarbeitete_quellen']}")

    print(f"\nThemenverteilung:")
    for t in stats["themen"]:
        bar = "#" * t["n"]
        print(f"  {t['thema']:<20} {bar}  ({t['n']})")

    politiker_stats = db.get_politiker_stats()
    if politiker_stats:
        print(f"\nTop-Politiker nach Polarisierung:")
        print(f"  {'Name':<28} {'Partei':<12} {'Aussagen':>8}  {'Pol.':>6}  {'Max':>4}")
        print("  " + "-" * 65)
        for p in politiker_stats[:10]:
            avg = p["avg_polarisierung"] or 0
            mx  = p["max_polarisierung"] or 0
            print(
                f"  {p['politiker']:<28} {(p['partei'] or '-'):<12}"
                f" {p['anzahl_aussagen']:>8}  {avg:>6.1f}  {mx:>4}"
            )

    filter_info = []
    if args.partei:
        filter_info.append(f"Partei={args.partei}")
    if args.thema:
        filter_info.append(f"Thema={args.thema}")
    label = f" [{', '.join(filter_info)}]" if filter_info else ""

    print(f"\nTop-{args.top} Aussagen{label}:")
    print("=" * 50)

    top_aussagen = db.get_top_aussagen(
        limit=args.top,
        partei=args.partei or None,
        thema=args.thema or None,
    )

    if not top_aussagen:
        print("  Keine Aussagen gefunden (Filter zu eng?).")
    else:
        for i, a in enumerate(top_aussagen, 1):
            grad    = a["polarisierungsgrad"] or 0
            extreme = ", ".join(a["sprachliche_extreme"] or [])
            print(f"\n  [{i}] {a['politiker']} ({a['partei'] or '?'})  –  {a['datum'] or 'kein Datum'}")
            print(f"       Thema      : {a['thema'] or 'Sonstiges'}")
            print(f"       Polarisier.: {'#' * grad}{'.' * (10 - grad)}  {grad}/10")
            print(f"       Aussage    : {a['aussage'][:120]}{'...' if len(a['aussage']) > 120 else ''}")
            if extreme:
                print(f"       Extreme    : {extreme}")

    db.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="politcheck",
        description="PolitCheck – Bundestag Aussagen-Analyse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflows (in dieser Reihenfolge ausfuehren):
  1. fetch    Bundestag API abrufen -> Rohdaten-DB
  2. extract  Rohdaten-DB -> LLM-Extraktion -> Analyse-DB (Reden + Aussagen)
  3. profile  Analyse-DB -> Politikerprofile (Kernthemen, Widersprueche, Rhetorik)
  4. report   Analyse-DB -> HTML-Report

Beispiele:
  python main.py fetch   --from-date 2024-01-01
  python main.py extract --from-date 2026-01-01 --limit 5
  python main.py profile
  python main.py profile --politiker "Alice Weidel"
  python main.py report  --open
        """,
    )
    sub = parser.add_subparsers(dest="mode", metavar="WORKFLOW")
    sub.required = True

    # ── fetch ──────────────────────────────────────────────────────────────
    p_fetch = sub.add_parser(
        "fetch",
        help="[1] Bundestag API -> Rohdaten-DB",
        description="Fragt die Bundestag API ab und speichert Rohdaten. Keine LLM-Verarbeitung.",
    )
    p_fetch.add_argument("--from-date", required=True, metavar="YYYY-MM-DD",
                         help="Startdatum (erforderlich)")
    p_fetch.add_argument("--to-date", default=None, metavar="YYYY-MM-DD",
                         help="Enddatum (optional, default: heute)")
    p_fetch.add_argument("--limit", type=int, default=None, metavar="N",
                         help="Max. Anzahl Protokolle gesamt (default: alle)")
    p_fetch.add_argument("--wahlperiode", type=int, default=20,
                         help="Wahlperiode (default: 20)")
    p_fetch.set_defaults(func=cmd_fetch)

    # ── extract ────────────────────────────────────────────────────────────
    p_extract = sub.add_parser(
        "extract",
        help="[2] Rohdaten-DB -> LLM -> Analyse-DB",
        description="Extrahiert Aussagen aus noch nicht verarbeiteten Protokollen per LLM.",
    )
    p_extract.add_argument("--limit", type=int, default=None, metavar="N",
                           help="Max. Protokolle in diesem Lauf (default: alle ausstehenden)")
    p_extract.add_argument("--max-aussagen", type=int, default=3, metavar="N",
                           help="Max. Aussagen pro Protokoll (default: 3)")
    p_extract.add_argument("--from-date", default=None, metavar="YYYY-MM-DD",
                           help="Nur Protokolle ab diesem Datum verarbeiten")
    p_extract.add_argument("--to-date", default=None, metavar="YYYY-MM-DD",
                           help="Nur Protokolle bis zu diesem Datum verarbeiten")
    p_extract.add_argument("--budget", type=float, default=None, metavar="USD",
                           help="Geschaetztes API-Kostenlimit in USD (default: unbegrenzt)")
    p_extract.set_defaults(func=cmd_extract)

    # ── profile ────────────────────────────────────────────────────────────
    p_profile = sub.add_parser(
        "profile",
        help="[3] Reden + Aussagen -> Politikerprofile",
        description="Erstellt politische Profile mit Kernthemen, Widerspruechen und rhetorischen Mustern.",
    )
    p_profile.add_argument("--politiker", default=None, metavar="NAME",
                           help="Nur diesen Politiker profilieren (Teilstring reicht)")
    p_profile.add_argument("--min-reden", type=int, default=2, metavar="N",
                           help="Mindestanzahl Reden fuer ein Profil (default: 2)")
    p_profile.add_argument("--auch-ohne-aussagen", action="store_true",
                           help="Profil auch erstellen wenn keine Aussagen extrahiert wurden")
    p_profile.set_defaults(func=cmd_profile)

    # ── report ─────────────────────────────────────────────────────────────
    p_report = sub.add_parser(
        "report",
        help="[3] Analyse-DB -> HTML-Report",
        description="Generiert den HTML-Report aus den Analyseergebnissen.",
    )
    p_report.add_argument("--output", default="output/report.html", metavar="PFAD",
                          help="Ausgabepfad (default: output/report.html)")
    p_report.add_argument("--open", action="store_true",
                          help="Report direkt im Browser oeffnen")
    p_report.set_defaults(func=cmd_report)

    # ── analyse ────────────────────────────────────────────────────────────
    p_analyse = sub.add_parser(
        "analyse",
        help="Statistiken in der Konsole anzeigen",
        description="Zeigt Auswertungen der Analyse-DB direkt in der Konsole.",
    )
    p_analyse.add_argument("--partei", default=None,
                           help="Nur Aussagen dieser Partei (z.B. SPD, AfD)")
    p_analyse.add_argument("--thema", default=None,
                           help="Nur Aussagen zu diesem Thema (z.B. Migration)")
    p_analyse.add_argument("--top", type=int, default=10, metavar="N",
                           help="Anzahl Top-Aussagen (default: 10)")
    p_analyse.set_defaults(func=cmd_analyse)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
