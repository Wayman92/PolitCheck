"""
Bundestag API Client  +  ProtokollDatabase
Dokumentation: https://dip.bundestag.de/über-dip/hilfe/api

Klassen:
    BundestagAPI      – HTTP-Client für die DIP-REST-API
    ProtokollDatabase – SQLite-Speicher für rohe Plenarprotokoll-Metadaten
"""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://search.dip.bundestag.de/api/v1"
API_KEY  = "R2BZaee.DjdCyihKZMf8AOjtScubP2EVydegzjmBIQ"  

# ─────────────────────────────────────────────────────────────────────────────
# API-Client
# ─────────────────────────────────────────────────────────────────────────────

class BundestagAPI:
    def __init__(self, api_key: str = API_KEY):
        """
        API Key: Bundestag stellt einen öffentlichen Demo-Key bereit.
        Für produktiven Einsatz eigenen Key anfragen: https://dip.bundestag.de/
        """
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"ApiKey {api_key}",
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: dict = {}) -> dict:
        """Führt einen API-Request aus mit einfachem Rate-Limiting."""
        url = f"{BASE_URL}/{endpoint}"
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        time.sleep(0.3)  # Höfliches Rate-Limiting
        return response.json()

    # ── Einzelseiten-Abfragen ────────────────────────────────────────────────

    def get_reden(
        self,
        wahlperiode: int = 20,
        limit: int = 50,
        offset: int = 0,
        datum_von: Optional[str] = None,
        datum_bis: Optional[str] = None,
    ) -> dict:
        """
        Lädt eine Seite Plenarprotokolle (für schrittweise Verarbeitung).

        Args:
            wahlperiode: Wahlperiode (20 = aktuelle)
            limit:       Anzahl Ergebnisse (max 100)
            datum_von:   Format YYYY-MM-DD
            datum_bis:   Format YYYY-MM-DD
        """
        params: dict = {
            "wahlperiode": wahlperiode,
            "format": "json",
            "num": limit,
            "offset": offset,
        }
        if datum_von:
            params["datum.start"] = datum_von
        if datum_bis:
            params["datum.end"] = datum_bis
        return self._get("plenarprotokoll", params)

    def get_aktivitaeten(
        self,
        wahlperiode: int = 20,
        limit: int = 50,
        offset: int = 0,
        vorgangstyp: Optional[str] = None,
    ) -> dict:
        """
        Lädt parlamentarische Aktivitäten (Anfragen, Anträge, etc.)

        Args:
            vorgangstyp: z.B. "Große Anfrage", "Kleine Anfrage"
        """
        params: dict = {
            "wahlperiode": wahlperiode,
            "format": "json",
            "num": limit,
            "offset": offset,
        }
        if vorgangstyp:
            params["vorgangstyp"] = vorgangstyp
        return self._get("aktivitaet", params)

    def get_personen(
        self,
        wahlperiode: int = 20,
        limit: int = 100,
        fraktion: Optional[str] = None,
    ) -> dict:
        """
        Lädt MdB-Stammdaten.

        Args:
            fraktion: z.B. "SPD", "CDU/CSU", "AfD", "Grüne", "FDP", "Linke", "BSW"
        """
        params: dict = {
            "wahlperiode": wahlperiode,
            "format": "json",
            "num": limit,
        }
        if fraktion:
            params["fraktionMitgliedschaft.fraktion"] = fraktion
        return self._get("person", params)

    def get_drucksachen(
        self,
        wahlperiode: int = 20,
        limit: int = 50,
        drucksachentyp: Optional[str] = None,
        datum_von: Optional[str] = None,
    ) -> dict:
        """Lädt Drucksachen (Anträge, Anfragen, Gesetzentwürfe)."""
        params: dict = {
            "wahlperiode": wahlperiode,
            "format": "json",
            "num": limit,
        }
        if drucksachentyp:
            params["drucksachentyp"] = drucksachentyp
        if datum_von:
            params["datum.start"] = datum_von
        return self._get("drucksache", params)

    # ── Vollständiger Abruf via Cursor-Pagination ────────────────────────────

    def get_alle_protokolle(
        self,
        wahlperiode: int = 20,
        datum_von: Optional[str] = None,
        datum_bis: Optional[str] = None,
        batch_size: int = 100,
        max_results: Optional[int] = None,
        verbose: bool = True,
    ) -> list[dict]:
        """
        Lädt Plenarprotokolle via Cursor-Pagination.

        Die API liefert pro Request max. 100 Dokumente und einen `cursor`-Token
        für die nächste Seite. Diese Methode iteriert solange, bis kein Cursor
        mehr zurückkommt oder max_results erreicht ist.

        Args:
            wahlperiode: Wahlperiode (default: 20)
            datum_von:   Startdatum YYYY-MM-DD (optional)
            datum_bis:   Enddatum   YYYY-MM-DD (optional)
            batch_size:  Dokumente pro Request (max 100)
            max_results: Maximale Gesamtanzahl (optional, default: alle)
            verbose:     Fortschrittsausgabe auf stdout

        Returns:
            Liste der Protokoll-Dicts direkt aus der API
        """
        alle: list[dict] = []
        cursor: Optional[str] = None
        seite = 1

        while True:
            verbleibend = (max_results - len(alle)) if max_results else batch_size
            params: dict = {
                "wahlperiode": wahlperiode,
                "format": "json",
                "num": min(batch_size, verbleibend),
            }
            if datum_von:
                params["datum.start"] = datum_von
            if datum_bis:
                params["datum.end"] = datum_bis
            if cursor:
                params["cursor"] = cursor

            data = self._get("plenarprotokoll", params)
            batch = data.get("documents", [])
            alle.extend(batch)

            if verbose:
                print(f"  Seite {seite:>3} -> {len(batch):>3} Protokolle  (gesamt: {len(alle)})")

            cursor = data.get("cursor")
            if not batch or not cursor or (max_results and len(alle) >= max_results):
                break

            seite += 1

        return alle

    def fetch_und_speichere(
        self,
        db: "ProtokollDatabase",
        wahlperiode: int = 20,
        datum_von: Optional[str] = None,
        datum_bis: Optional[str] = None,
        verbose: bool = True,
    ) -> dict:
        """
        Kombiniert get_alle_protokolle() + ProtokollDatabase.speichere().
        Lädt alle Protokolle und persistiert sie direkt in der Datenbank.

        Args:
            db:          ProtokollDatabase-Instanz
            wahlperiode: Wahlperiode (default: 20)
            datum_von:   Startdatum YYYY-MM-DD (optional)
            datum_bis:   Enddatum   YYYY-MM-DD (optional)
            verbose:     Fortschrittsausgabe

        Returns:
            {"geladen": int, "neu": int, "duplikate": int}
        """
        if verbose:
            print(f"📥 Lade Plenarprotokolle (WP {wahlperiode}"
                  + (f", ab {datum_von}" if datum_von else "")
                  + (f" bis {datum_bis}" if datum_bis else "") + ") …\n")

        protokolle = self.get_alle_protokolle(
            wahlperiode=wahlperiode,
            datum_von=datum_von,
            datum_bis=datum_bis,
            verbose=verbose,
        )

        if verbose:
            print(f"\n💾 {len(protokolle)} Protokolle geladen — speichere in DB …")

        stats = db.speichere(protokolle)

        if verbose:
            print(f"   Neu gespeichert : {stats['neu']}")
            print(f"   Bereits in DB   : {stats['duplikate']}")

        return {"geladen": len(protokolle), **stats}


# ─────────────────────────────────────────────────────────────────────────────
# Datenbank-Schicht für Rohdaten
# ─────────────────────────────────────────────────────────────────────────────

class ProtokollDatabase:
    """
    SQLite-Speicher für rohe Plenarprotokoll-Metadaten.

    Trennt die Rohdaten (direkt von der API) von den
    KI-extrahierten Aussagen in der politcheck.db.

    Tabelle `protokolle`:
        id            – API-Primärschlüssel (TEXT)
        titel         – Sitzungstitel
        datum         – ISO-Datum der Sitzung
        wahlperiode   – Wahlperiode als Integer
        dokumentnummer– z.B. "21/81" oder "1065" (TEXT)
        pdf_url       – Direktlink zum PDF
        xml_url       – Direktlink zur XML-Version
        abstract      – Zusammenfassung falls vorhanden
        raw_json      – Vollständiges API-Dokument als JSON-String
        gespeichert_am– ISO-Timestamp des Imports
    """

    def __init__(self, db_path: str = "data/plenarprotokolle.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS protokolle (
                id              TEXT PRIMARY KEY,
                titel           TEXT,
                datum           TEXT,
                wahlperiode     INTEGER,
                dokumentnummer  TEXT,
                pdf_url         TEXT,
                xml_url         TEXT,
                abstract        TEXT,
                raw_json        TEXT,
                gespeichert_am  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_datum       ON protokolle(datum DESC);
            CREATE INDEX IF NOT EXISTS idx_wahlperiode ON protokolle(wahlperiode);
        """)
        self.conn.commit()

    def speichere(self, protokolle: list[dict]) -> dict:
        """
        Schreibt eine Liste von API-Dokumenten in die Datenbank.
        Bereits vorhandene IDs werden übersprungen (INSERT OR IGNORE).

        Returns:
            {"neu": int, "duplikate": int, "neue_dokumente": list[dict]}
            wobei neue_dokumente die tatsächlich neu eingefügten Dicts enthält.
        """
        neue_dokumente: list[dict] = []
        duplikate = 0
        jetzt = datetime.now().isoformat()

        for dok in protokolle:
            doc_id = str(dok.get("id", ""))
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO protokolle
                       (id, titel, datum, wahlperiode, dokumentnummer,
                        pdf_url, xml_url, abstract, raw_json, gespeichert_am)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        doc_id,
                        dok.get("titel"),
                        dok.get("datum"),
                        dok.get("wahlperiode"),
                        dok.get("dokumentnummer"),
                        dok.get("fundstelle", {}).get("pdf_url"),
                        dok.get("fundstelle", {}).get("xml_url"),
                        dok.get("abstract"),
                        json.dumps(dok, ensure_ascii=False),
                        jetzt,
                    ),
                )
                if self.conn.execute("SELECT changes()").fetchone()[0] > 0:
                    neue_dokumente.append(dok)
                else:
                    duplikate += 1
            except Exception as e:
                print(f"  ⚠️  Fehler bei id={doc_id}: {e}")

        self.conn.commit()
        return {"neu": len(neue_dokumente), "duplikate": duplikate, "neue_dokumente": neue_dokumente}

    def get_protokolle(
        self,
        limit: int = 50,
        wahlperiode: Optional[int] = None,
        datum_von: Optional[str] = None,
        datum_bis: Optional[str] = None,
    ) -> list[dict]:
        """Gibt gespeicherte Protokolle zurück, optional gefiltert."""
        query = "SELECT * FROM protokolle WHERE 1=1"
        params: list = []

        if wahlperiode is not None:
            query += " AND wahlperiode = ?"
            params.append(wahlperiode)
        if datum_von:
            query += " AND datum >= ?"
            params.append(datum_von)
        if datum_bis:
            query += " AND datum <= ?"
            params.append(datum_bis)

        query += " ORDER BY datum DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_statistiken(self) -> dict:
        """Gibt eine Übersicht über den Datenbankinhalt zurück."""
        total    = self.conn.execute("SELECT COUNT(*) FROM protokolle").fetchone()[0]
        aelteste = self.conn.execute("SELECT MIN(datum) FROM protokolle").fetchone()[0]
        neueste  = self.conn.execute("SELECT MAX(datum) FROM protokolle").fetchone()[0]
        wp_rows  = self.conn.execute("""
            SELECT wahlperiode, COUNT(*) AS n
            FROM protokolle
            GROUP BY wahlperiode
            ORDER BY wahlperiode DESC
        """).fetchall()
        return {
            "total":            total,
            "aeltestes_datum":  aelteste,
            "neuestes_datum":   neueste,
            "pro_wahlperiode":  [dict(r) for r in wp_rows],
        }

    def close(self) -> None:
        self.conn.close()
