"""
Report Generator
Erstellt einen HTML-Report aus den gesammelten Aussagen.
"""

from datetime import datetime
from src.database import Database


def generiere_html_report(db: Database, output_path: str = "output/report.html"):
    aussagen = db.get_top_aussagen(limit=50)
    politiker_stats = db.get_politiker_stats()
    stats = db.get_statistiken()

    # Farben pro Partei
    partei_farben = {
        "SPD": "#E3000F",
        "CDU": "#000000",
        "CSU": "#0570C9",
        "CDU/CSU": "#000000",
        "Grüne": "#46962B",
        "FDP": "#FFED00",
        "AfD": "#009EE0",
        "Linke": "#BE3075",
        "BSW": "#6B1A52",
    }

    def partei_farbe(partei: str) -> str:
        for key, color in partei_farben.items():
            if key.lower() in partei.lower():
                return color
        return "#888888"

    def polarisierungs_farbe(grad: int) -> str:
        if grad >= 8:
            return "#dc2626"
        elif grad >= 6:
            return "#f97316"
        elif grad >= 4:
            return "#eab308"
        return "#22c55e"

    aussagen_html = ""
    for a in aussagen:
        extreme_badges = "".join(
            f'<span class="badge extreme">{e}</span>'
            for e in (a["sprachliche_extreme"] or [])
        )
        p_farbe = polarisierungs_farbe(a["polarisierungsgrad"] or 0)
        partei_color = partei_farbe(a["partei"] or "")

        aussagen_html += f"""
        <div class="aussage-card">
            <div class="card-header">
                <div class="politiker-info">
                    <span class="partei-badge" style="background:{partei_color}">{a['partei'] or 'unbekannt'}</span>
                    <strong>{a['politiker']}</strong>
                    <span class="datum">{a['datum'] or ''}</span>
                </div>
                <div class="polarisierung" style="color:{p_farbe}">
                    {'●' * (a['polarisierungsgrad'] or 0)}{'○' * (10 - (a['polarisierungsgrad'] or 0))}
                    <span>{a['polarisierungsgrad']}/10</span>
                </div>
            </div>
            <blockquote class="aussage-text">"{a['aussage']}"</blockquote>
            <div class="meta">
                <span class="thema-badge">{a['thema'] or 'Sonstiges'}</span>
                {extreme_badges}
            </div>
            <p class="begruendung">📊 {a['polarisierungsbegruendung']}</p>
            <p class="kontext">🔍 <em>{a['kontext']}</em></p>
            {"<a href='" + a['quelle_url'] + "' target='_blank' class='quelle-link'>→ Quelle: " + a['quelle_titel'] + "</a>" if a['quelle_url'] else ""}
        </div>"""

    politiker_html = ""
    for p in politiker_stats[:15]:
        farbe = partei_farbe(p["partei"] or "")
        politiker_html += f"""
        <tr>
            <td><span class="partei-dot" style="background:{farbe}"></span>{p['politiker']}</td>
            <td>{p['partei'] or '-'}</td>
            <td>{p['anzahl_aussagen']}</td>
            <td style="color:{polarisierungs_farbe(int(p['avg_polarisierung'] or 0))}">{p['avg_polarisierung']}</td>
            <td style="color:{polarisierungs_farbe(p['max_polarisierung'] or 0)}">{p['max_polarisierung']}</td>
        </tr>"""

    themen_html = ""
    for t in stats["themen"]:
        themen_html += f"<li><strong>{t['thema']}</strong>: {t['n']} Aussagen</li>"

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PolitCheck – Bundestag Aussagen-Analyse</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f4f5f7; color: #1a1a2e; }}

        header {{ background: #1a1a2e; color: white; padding: 2rem; }}
        header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.7; }}

        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}

        .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 2rem; }}
        .stat-card {{ background: white; border-radius: 12px; padding: 1.5rem; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .stat-card .number {{ font-size: 2.5rem; font-weight: bold; color: #1a1a2e; }}
        .stat-card .label {{ color: #666; font-size: 0.9rem; margin-top: 0.3rem; }}

        .section-title {{ font-size: 1.3rem; font-weight: bold; margin: 2rem 0 1rem; border-left: 4px solid #1a1a2e; padding-left: 1rem; }}

        .aussage-card {{ background: white; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-left: 4px solid #e5e7eb; transition: transform 0.2s; }}
        .aussage-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.1); }}

        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem; }}
        .politiker-info {{ display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }}
        .partei-badge {{ color: white; padding: 2px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; }}
        .datum {{ color: #888; font-size: 0.85rem; }}
        .polarisierung {{ font-family: monospace; font-size: 0.85rem; display: flex; align-items: center; gap: 0.5rem; }}

        blockquote.aussage-text {{ font-size: 1.05rem; line-height: 1.6; color: #333; border-left: 3px solid #ddd; padding-left: 1rem; margin: 1rem 0; font-style: italic; }}

        .meta {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.5rem 0; }}
        .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
        .thema-badge {{ background: #e0f2fe; color: #0369a1; }}
        .badge.extreme {{ background: #fef3c7; color: #92400e; }}

        .begruendung {{ font-size: 0.9rem; color: #555; margin: 0.5rem 0; }}
        .kontext {{ font-size: 0.85rem; color: #777; margin: 0.3rem 0; }}
        .quelle-link {{ font-size: 0.85rem; color: #2563eb; text-decoration: none; }}
        .quelle-link:hover {{ text-decoration: underline; }}

        table {{ width: 100%; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); border-collapse: collapse; overflow: hidden; }}
        th {{ background: #1a1a2e; color: white; padding: 1rem; text-align: left; font-size: 0.9rem; }}
        td {{ padding: 0.8rem 1rem; border-bottom: 1px solid #f0f0f0; font-size: 0.9rem; }}
        tr:last-child td {{ border-bottom: none; }}
        .partei-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }}

        .themen-liste {{ background: white; border-radius: 12px; padding: 1.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .themen-liste ul {{ list-style: none; display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }}
        .themen-liste li {{ padding: 0.5rem; border-radius: 6px; background: #f9fafb; }}

        .disclaimer {{ background: #fef9c3; border: 1px solid #fde68a; border-radius: 8px; padding: 1rem; margin: 2rem 0; font-size: 0.9rem; color: #713f12; }}

        footer {{ text-align: center; padding: 2rem; color: #888; font-size: 0.85rem; }}

        @media (max-width: 600px) {{
            .stats-grid {{ grid-template-columns: 1fr; }}
            .themen-liste ul {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>🏛️ PolitCheck</h1>
            <p>Automatische Analyse polarisierender Aussagen aus dem Deutschen Bundestag</p>
            <p style="margin-top:0.5rem; opacity:0.5; font-size:0.85rem">Generiert am {datetime.now().strftime('%d.%m.%Y %H:%M')} · Datenquelle: Bundestag Open Data API</p>
        </div>
    </header>

    <div class="container">

        <div class="disclaimer">
            ⚠️ <strong>Hinweis:</strong> Der Polarisierungsgrad wird automatisch durch KI berechnet und stellt keine redaktionelle Bewertung dar.
            Alle Aussagen sind verlinkt und im Originalkontext überprüfbar. Das Tool ersetzt keine journalistische Einordnung.
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="number">{stats['total_aussagen']}</div>
                <div class="label">Analysierte Aussagen</div>
            </div>
            <div class="stat-card">
                <div class="number">{stats['verarbeitete_quellen']}</div>
                <div class="label">Verarbeitete Quellen</div>
            </div>
            <div class="stat-card">
                <div class="number">{len(politiker_stats)}</div>
                <div class="label">Erfasste Politiker</div>
            </div>
        </div>

        <div class="section-title">📊 Politiker nach Polarisierungsgrad</div>
        <table>
            <thead>
                <tr>
                    <th>Politiker</th><th>Partei</th><th>Aussagen</th>
                    <th>⌀ Polarisierung</th><th>Max. Polarisierung</th>
                </tr>
            </thead>
            <tbody>{politiker_html}</tbody>
        </table>

        <div class="section-title">🔥 Top Aussagen nach Polarisierungsgrad</div>
        {aussagen_html if aussagen_html else '<p style="color:#888; padding:1rem">Noch keine Aussagen in der Datenbank. Führe zunächst main.py aus.</p>'}

        <div class="section-title">📁 Themenverteilung</div>
        <div class="themen-liste">
            <ul>{themen_html if themen_html else '<li>Noch keine Daten</li>'}</ul>
        </div>

    </div>

    <footer>
        PolitCheck · Daten: <a href="https://dip.bundestag.de" target="_blank">Bundestag Open Data</a> ·
        KI-Analyse: Anthropic Claude · Kein kommerzielles Projekt
    </footer>
</body>
</html>"""

    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] Report gespeichert: {output_path}")
    return output_path
