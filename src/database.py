"""
Datenbank-Schicht (SQLite)
Speichert extrahierte Aussagen persistent.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from src.extractor import Aussage


class Database:
    def __init__(self, db_path: str = "data/politcheck.db"):
        Path(db_path).parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS aussagen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                politiker TEXT NOT NULL,
                partei TEXT,
                datum TEXT,
                aussage TEXT NOT NULL,
                kontext TEXT,
                thema TEXT,
                kategorie TEXT DEFAULT 'polarisierend',
                polarisierungsgrad INTEGER,
                polarisierungsbegruendung TEXT,
                sprachliche_extreme TEXT,
                quelle_titel TEXT,
                quelle_url TEXT,
                erstellt_am TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verarbeitete_quellen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quelle_id TEXT UNIQUE,
                quelle_typ TEXT,
                verarbeitet_am TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_politiker ON aussagen(politiker);
            CREATE INDEX IF NOT EXISTS idx_partei ON aussagen(partei);
            CREATE INDEX IF NOT EXISTS idx_thema ON aussagen(thema);
            CREATE INDEX IF NOT EXISTS idx_polarisierung ON aussagen(polarisierungsgrad DESC);
        """)
        self.conn.commit()
        # Migration: kategorie-Spalte zu bestehenden DBs hinzufuegen
        try:
            self.conn.execute("ALTER TABLE aussagen ADD COLUMN kategorie TEXT DEFAULT 'polarisierend'")
            self.conn.commit()
        except Exception:
            pass  # Spalte existiert bereits

    def speichere_aussage(self, aussage: Aussage) -> int:
        cursor = self.conn.execute(
            """INSERT INTO aussagen
               (politiker, partei, datum, aussage, kontext, thema,
                kategorie, polarisierungsgrad, polarisierungsbegruendung,
                sprachliche_extreme, quelle_titel, quelle_url, erstellt_am)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                aussage.politiker,
                aussage.partei,
                aussage.datum,
                aussage.aussage,
                aussage.kontext,
                aussage.thema,
                getattr(aussage, "kategorie", "polarisierend"),
                aussage.polarisierungsgrad,
                aussage.polarisierungsbegruendung,
                json.dumps(aussage.sprachliche_extreme, ensure_ascii=False),
                aussage.quelle_titel,
                aussage.quelle_url,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def quelle_bereits_verarbeitet(self, quelle_id: str) -> bool:
        row = self.conn.execute(
            "SELECT id FROM verarbeitete_quellen WHERE quelle_id = ?", (quelle_id,)
        ).fetchone()
        return row is not None

    def markiere_quelle_verarbeitet(self, quelle_id: str, quelle_typ: str):
        self.conn.execute(
            """INSERT OR IGNORE INTO verarbeitete_quellen
               (quelle_id, quelle_typ, verarbeitet_am) VALUES (?,?,?)""",
            (quelle_id, quelle_typ, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_top_aussagen(
        self,
        limit: int = 20,
        partei: Optional[str] = None,
        thema: Optional[str] = None,
        min_polarisierung: int = 1,
    ) -> list[dict]:
        query = """
            SELECT * FROM aussagen
            WHERE polarisierungsgrad >= ?
        """
        params = [min_polarisierung]

        if partei:
            query += " AND partei = ?"
            params.append(partei)
        if thema:
            query += " AND thema = ?"
            params.append(thema)

        query += " ORDER BY polarisierungsgrad DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["sprachliche_extreme"] = json.loads(d["sprachliche_extreme"] or "[]")
            result.append(d)
        return result

    def get_politiker_stats(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT
                politiker,
                partei,
                COUNT(*) as anzahl_aussagen,
                ROUND(AVG(polarisierungsgrad), 1) as avg_polarisierung,
                MAX(polarisierungsgrad) as max_polarisierung
            FROM aussagen
            GROUP BY politiker, partei
            ORDER BY avg_polarisierung DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_statistiken(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM aussagen").fetchone()[0]
        quellen = self.conn.execute("SELECT COUNT(*) FROM verarbeitete_quellen").fetchone()[0]
        themen = self.conn.execute("""
            SELECT thema, COUNT(*) as n FROM aussagen GROUP BY thema ORDER BY n DESC
        """).fetchall()
        return {
            "total_aussagen": total,
            "verarbeitete_quellen": quellen,
            "themen": [dict(t) for t in themen],
        }

    def close(self):
        self.conn.close()
