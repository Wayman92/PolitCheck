"""
Exportiert echte Daten aus politcheck.db nach output/data.json
für das PolitCheck-Frontend.

Verwendung:
  py generate_data.py
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH  = Path("data/politcheck.db")
OUT_PATH = Path("output/data.json")


def load_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def export_zitate(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    """Top-Aussagen nach Polarisierungsgrad für die fliegenden Zitate."""
    rows = conn.execute("""
        SELECT
            a.politiker, a.partei, a.aussage, a.datum,
            a.polarisierungsgrad, a.kategorie, a.thema,
            a.quelle_url, a.quelle_titel
        FROM aussagen a
        WHERE a.aussage IS NOT NULL AND LENGTH(a.aussage) > 20
        ORDER BY a.polarisierungsgrad DESC
        LIMIT ?
    """, (limit,)).fetchall()

    return [
        {
            "politiker":  r["politiker"],
            "partei":     r["partei"] or "",
            "text":       r["aussage"],
            "datum":      r["datum"] or "",
            "grad":       r["polarisierungsgrad"] or 5,
            "kategorie":  r["kategorie"] or "polarisierend",
            "thema":      r["thema"] or "",
            "quelle_url": r["quelle_url"] or "",
            "quelle_titel": r["quelle_titel"] or "",
        }
        for r in rows
    ]


def export_widersprueche(conn: sqlite3.Connection, limit: int = 6) -> list[dict]:
    """Widersprüche aus den Politikerprofilen."""
    rows = conn.execute("""
        SELECT politiker, partei, widersprueche
        FROM politikerprofile
        WHERE widersprueche IS NOT NULL AND widersprueche != '[]'
        ORDER BY anzahl_reden DESC
        LIMIT ?
    """, (limit,)).fetchall()

    result = []
    for r in rows:
        wsp_list = json.loads(r["widersprueche"] or "[]")
        for w in wsp_list[:2]:  # max 2 Widersprüche pro Politiker
            if w.get("aussage1") and w.get("aussage2"):
                result.append({
                    "politiker":  r["politiker"],
                    "partei":     r["partei"] or "",
                    "aussage1":   {"text": w["aussage1"], "datum": w.get("datum1", "")},
                    "aussage2":   {"text": w["aussage2"], "datum": w.get("datum2", "")},
                    "erklaerung": w.get("erklaerung", ""),
                })
    return result


def export_partei_stats(conn: sqlite3.Connection) -> list[dict]:
    """Reden, Zwischenrufe und Beleidigungen pro Partei."""
    rows = conn.execute("""
        SELECT
            partei,
            SUM(CASE WHEN typ != 'zwischenruf' THEN 1 ELSE 0 END) AS reden,
            SUM(CASE WHEN typ  = 'zwischenruf' THEN 1 ELSE 0 END) AS zwischenrufe
        FROM reden
        WHERE partei IS NOT NULL AND partei != ''
        GROUP BY partei
        ORDER BY reden DESC
    """).fetchall()

    result = {
        r["partei"]: {
            "partei":        r["partei"],
            "reden":         r["reden"],
            "zwischenrufe":  r["zwischenrufe"],
            "ordnungsrufe":  0,
        }
        for r in rows
    }

    # Ordnungsrufe: Partei per Nachschlage in reden-Tabelle ergänzen
    ord_rows = conn.execute("""
        SELECT
            COALESCE(r.partei, o.partei, '') AS partei,
            COUNT(*) AS n
        FROM ordnungsrufe o
        LEFT JOIN (
            SELECT politiker, MAX(partei) AS partei
            FROM reden
            WHERE partei IS NOT NULL AND partei != ''
            GROUP BY politiker
        ) r ON r.politiker = o.politiker
        WHERE COALESCE(r.partei, o.partei, '') != ''
        GROUP BY COALESCE(r.partei, o.partei)
    """).fetchall()
    for o in ord_rows:
        if o["partei"] in result:
            result[o["partei"]]["ordnungsrufe"] = o["n"]
        else:
            result[o["partei"]] = {
                "partei": o["partei"], "reden": 0,
                "zwischenrufe": 0, "ordnungsrufe": o["n"],
            }

    return list(result.values())


def export_profile(conn: sqlite3.Connection) -> list[dict]:
    """Alle Politikerprofile für die Suchansicht."""
    rows = conn.execute("""
        SELECT *
        FROM politikerprofile
        ORDER BY anzahl_reden DESC
    """).fetchall()

    result = []
    for r in rows:
        kernthemen      = json.loads(r["kernthemen"]         or "[]")
        kernpositionen  = json.loads(r["kernpositionen"]     or "[]")
        widersprueche   = json.loads(r["widersprueche"]      or "[]")
        rhet_muster     = json.loads(r["rhetorische_muster"] or "[]")

        # Top-3-Aussagen direkt aus aussagen-Tabelle laden
        top_aussagen = conn.execute("""
            SELECT aussage, datum, polarisierungsgrad, kategorie, quelle_url, thema
            FROM aussagen
            WHERE politiker = ?
            ORDER BY polarisierungsgrad DESC
            LIMIT 3
        """, (r["politiker"],)).fetchall()

        result.append({
            "name":             r["politiker"],
            "partei":           r["partei"] or "",
            "kernthemen":       kernthemen,
            "kernpositionen":   kernpositionen,
            "widersprueche":    widersprueche,
            "rhetorische_muster": rhet_muster,
            "zusammenfassung":  r["zusammenfassung"] or "",
            "anzahl_reden":     r["anzahl_reden"] or 0,
            "anzahl_aussagen":  r["anzahl_aussagen"] or 0,
            "zeitraum_von":     r["zeitraum_von"] or "",
            "zeitraum_bis":     r["zeitraum_bis"] or "",
            "top_aussagen": [
                {
                    "text":      a["aussage"],
                    "datum":     a["datum"] or "",
                    "grad":      a["polarisierungsgrad"] or 0,
                    "kategorie": a["kategorie"] or "",
                    "quelle_url": a["quelle_url"] or "",
                    "thema":     a["thema"] or "",
                }
                for a in top_aussagen
            ],
        })
    return result


def main():
    if not DB_PATH.exists():
        print(f"Datenbank nicht gefunden: {DB_PATH}")
        print("Fuehre zuerst 'py main.py extract' aus.")
        return

    conn = load_db(DB_PATH)

    zitate        = export_zitate(conn)
    widersprueche = export_widersprueche(conn)
    profile       = export_profile(conn)
    partei_stats  = export_partei_stats(conn)
    conn.close()

    OUT_PATH.parent.mkdir(exist_ok=True)
    data = {
        "generiert_am":  datetime.now().isoformat(),
        "zitate":        zitate,
        "widersprueche": widersprueche,
        "profile":       profile,
        "partei_stats":  partei_stats,
    }
    # JSON fuer HTTP-Fetch
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # JS-Fallback fuer file://-Protokoll (kein CORS-Problem)
    js_path = OUT_PATH.parent / "data.js"
    js_content = "window.POLITCHECK_DATA = " + json.dumps(data, ensure_ascii=False) + ";"
    js_path.write_text(js_content, encoding="utf-8")

    print(f"Exportiert nach {OUT_PATH} + data.js:")
    print(f"  {len(zitate)} Zitate")
    print(f"  {len(widersprueche)} Widersprueche")
    print(f"  {len(profile)} Profile")
    print(f"  {len(partei_stats)} Parteien (Statistiken)")


if __name__ == "__main__":
    main()
