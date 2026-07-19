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
            CREATE TABLE IF NOT EXISTS reden (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                xml_rede_id   TEXT UNIQUE,
                protokoll_id  TEXT NOT NULL,
                datum         TEXT,
                wahlperiode   INTEGER,
                politiker     TEXT NOT NULL,
                partei        TEXT,
                seite         INTEGER,
                typ           TEXT DEFAULT 'rede',
                redetext      TEXT NOT NULL,
                wortanzahl    INTEGER,
                analysiert    INTEGER DEFAULT 0,
                erstellt_am   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reden_politiker  ON reden(politiker);
            CREATE INDEX IF NOT EXISTS idx_reden_protokoll  ON reden(protokoll_id);
            CREATE INDEX IF NOT EXISTS idx_reden_datum      ON reden(datum);

            CREATE TABLE IF NOT EXISTS aussagen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rede_id INTEGER REFERENCES reden(id),
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

            CREATE INDEX IF NOT EXISTS idx_politiker    ON aussagen(politiker);
            CREATE INDEX IF NOT EXISTS idx_partei       ON aussagen(partei);
            CREATE INDEX IF NOT EXISTS idx_thema        ON aussagen(thema);
            CREATE INDEX IF NOT EXISTS idx_polarisierung ON aussagen(polarisierungsgrad DESC);

            CREATE TABLE IF NOT EXISTS ordnungsrufe (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                protokoll_id TEXT NOT NULL,
                datum        TEXT,
                politiker    TEXT,
                partei       TEXT,
                erstellt_am  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ordnungsrufe_partei ON ordnungsrufe(partei);

            CREATE TABLE IF NOT EXISTS politikerprofile (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                politiker           TEXT NOT NULL UNIQUE,
                partei              TEXT,
                kernthemen          TEXT,   -- JSON-Array
                kernpositionen      TEXT,   -- JSON-Array [{thema, position, begruendung}]
                widersprueche       TEXT,   -- JSON-Array [{aussage1, datum1, aussage2, datum2, erklaerung}]
                rhetorische_muster  TEXT,   -- JSON-Array
                zusammenfassung     TEXT,
                anzahl_reden        INTEGER,
                anzahl_aussagen     INTEGER,
                zeitraum_von        TEXT,
                zeitraum_bis        TEXT,
                aktualisiert_am     TEXT NOT NULL
            );
        """)
        self.conn.commit()
        # Migrationen fuer bestehende DBs
        for migration in [
            "ALTER TABLE aussagen ADD COLUMN kategorie TEXT DEFAULT 'polarisierend'",
            "ALTER TABLE aussagen ADD COLUMN rede_id INTEGER",
            "ALTER TABLE reden ADD COLUMN typ TEXT DEFAULT 'rede'",
            "ALTER TABLE aussagen ADD COLUMN geloescht INTEGER DEFAULT 0",
        ]:
            try:
                self.conn.execute(migration)
                self.conn.commit()
            except Exception:
                pass

    def speichere_reden(self, reden: list[dict]) -> int:
        """Speichert Reden aus XML-Parsing. Gibt Anzahl neu eingefügter zurück."""
        neu = 0
        jetzt = datetime.now().isoformat()
        for r in reden:
            self.conn.execute(
                """INSERT OR IGNORE INTO reden
                   (xml_rede_id, protokoll_id, datum, wahlperiode, politiker,
                    partei, seite, typ, redetext, wortanzahl, erstellt_am)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["xml_rede_id"], r["protokoll_id"], r["datum"], r["wahlperiode"],
                    r["politiker"], r["partei"], r["seite"], r.get("typ", "rede"),
                    r["redetext"], r["wortanzahl"], jetzt,
                ),
            )
            if self.conn.execute("SELECT changes()").fetchone()[0] > 0:
                neu += 1
        self.conn.commit()
        return neu

    def get_reden_fuer_protokoll(
        self, protokoll_id: str, nur_nicht_analysiert: bool = False
    ) -> list[dict]:
        sql = "SELECT * FROM reden WHERE protokoll_id = ?"
        if nur_nicht_analysiert:
            sql += " AND analysiert = 0"
        sql += " ORDER BY seite ASC"
        rows = self.conn.execute(sql, (protokoll_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_reden_fuer_politiker(self, politiker: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM reden WHERE politiker = ? ORDER BY datum ASC",
            (politiker,),
        ).fetchall()
        return [dict(r) for r in rows]

    def speichere_ordnungsrufe(self, ordnungsrufe: list[dict]) -> int:
        """Speichert Ordnungsrufe aus XML-Parsing. Gibt Anzahl gespeicherter zurück."""
        jetzt = datetime.now().isoformat()
        for o in ordnungsrufe:
            self.conn.execute(
                """INSERT INTO ordnungsrufe (protokoll_id, datum, politiker, partei, erstellt_am)
                   VALUES (?, ?, ?, ?, ?)""",
                (o["protokoll_id"], o.get("datum", ""), o["politiker"], o.get("partei", ""), jetzt),
            )
        if ordnungsrufe:
            self.conn.commit()
        return len(ordnungsrufe)

    def markiere_rede_analysiert(self, rede_id: int):
        self.conn.execute("UPDATE reden SET analysiert = 1 WHERE id = ?", (rede_id,))
        self.conn.commit()

    def speichere_aussage(self, aussage: Aussage, rede_id: Optional[int] = None) -> int:
        cursor = self.conn.execute(
            """INSERT INTO aussagen
               (rede_id, politiker, partei, datum, aussage, kontext, thema,
                kategorie, polarisierungsgrad, polarisierungsbegruendung,
                sprachliche_extreme, quelle_titel, quelle_url, erstellt_am)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rede_id,
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

    def get_alle_politiker(self, min_reden: int = 1) -> list[dict]:
        """Gibt alle Politiker zurück die mindestens min_reden Reden haben."""
        rows = self.conn.execute("""
            SELECT
                politiker,
                partei,
                COUNT(*)   AS anzahl_reden,
                MIN(datum) AS zeitraum_von,
                MAX(datum) AS zeitraum_bis
            FROM reden
            GROUP BY politiker
            HAVING anzahl_reden >= ?
            ORDER BY anzahl_reden DESC
        """, (min_reden,)).fetchall()
        return [dict(r) for r in rows]

    def get_aussagen_fuer_politiker(self, politiker: str) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM aussagen
            WHERE politiker = ?
            ORDER BY datum ASC
        """, (politiker,)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["sprachliche_extreme"] = json.loads(d["sprachliche_extreme"] or "[]")
            result.append(d)
        return result

    def speichere_profil(self, profil: dict) -> None:
        self.conn.execute("""
            INSERT INTO politikerprofile
                (politiker, partei, kernthemen, kernpositionen, widersprueche,
                 rhetorische_muster, zusammenfassung, anzahl_reden, anzahl_aussagen,
                 zeitraum_von, zeitraum_bis, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(politiker) DO UPDATE SET
                partei             = excluded.partei,
                kernthemen         = excluded.kernthemen,
                kernpositionen     = excluded.kernpositionen,
                widersprueche      = excluded.widersprueche,
                rhetorische_muster = excluded.rhetorische_muster,
                zusammenfassung    = excluded.zusammenfassung,
                anzahl_reden       = excluded.anzahl_reden,
                anzahl_aussagen    = excluded.anzahl_aussagen,
                zeitraum_von       = excluded.zeitraum_von,
                zeitraum_bis       = excluded.zeitraum_bis,
                aktualisiert_am    = excluded.aktualisiert_am
        """, (
            profil["politiker"],
            profil.get("partei"),
            json.dumps(profil.get("kernthemen", []),         ensure_ascii=False),
            json.dumps(profil.get("kernpositionen", []),     ensure_ascii=False),
            json.dumps(profil.get("widersprueche", []),      ensure_ascii=False),
            json.dumps(profil.get("rhetorische_muster", []), ensure_ascii=False),
            profil.get("zusammenfassung"),
            profil.get("anzahl_reden", 0),
            profil.get("anzahl_aussagen", 0),
            profil.get("zeitraum_von"),
            profil.get("zeitraum_bis"),
            datetime.now().isoformat(),
        ))
        self.conn.commit()

    def get_profil(self, politiker: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM politikerprofile WHERE politiker = ?", (politiker,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("kernthemen", "kernpositionen", "widersprueche", "rhetorische_muster"):
            d[key] = json.loads(d[key] or "[]")
        return d

    def get_alle_profile(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM politikerprofile ORDER BY anzahl_reden DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for key in ("kernthemen", "kernpositionen", "widersprueche", "rhetorische_muster"):
                d[key] = json.loads(d[key] or "[]")
            result.append(d)
        return result

    def close(self):
        self.conn.close()
