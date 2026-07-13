"""Entfernt 'verarbeitet'-Einträge für Protokolle ohne Aussagen, damit sie erneut verarbeitet werden."""
import sqlite3

conn = sqlite3.connect("data/politcheck.db")

# Finde alle verarbeiteten Protokoll-IDs die keine Aussagen haben
rows = conn.execute("""
    SELECT v.quelle_id
    FROM verarbeitete_quellen v
    WHERE v.quelle_typ = 'plenarprotokoll'
    AND NOT EXISTS (
        SELECT 1 FROM reden r
        JOIN aussagen a ON a.rede_id = r.id
        WHERE r.protokoll_id = v.quelle_id
    )
""").fetchall()

ids = [r[0] for r in rows]
print(f"Protokolle ohne Aussagen die zurueckgesetzt werden: {len(ids)}")

if ids:
    conn.execute(
        f"DELETE FROM verarbeitete_quellen WHERE quelle_id IN ({','.join('?' * len(ids))})",
        ids
    )
    # Auch analysiert-Flag zuruecksetzen
    conn.execute(
        f"UPDATE reden SET analysiert = 0 WHERE protokoll_id IN ({','.join('?' * len(ids))})",
        ids
    )
    conn.commit()
    print("Zurueckgesetzt. Naechster 'extract'-Lauf wird diese erneut verarbeiten.")
else:
    print("Nichts zurueckzusetzen.")

conn.close()
