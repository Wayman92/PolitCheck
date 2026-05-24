"""
Bundestag API Client
Dokumentation: https://dip.bundestag.de/über-dip/hilfe/api
"""

import requests
import time
from typing import Optional
from datetime import datetime

BASE_URL = "https://search.dip.bundestag.de/api/v1"


class BundestagAPI:
    def __init__(self, api_key: str = "I9FKdCn.hbfefNWCY336dL6x690GCU5PsGbDzlq0"):
        """
        API Key: Bundestag stellt einen öffentlichen Demo-Key bereit.
        Für produktiven Einsatz eigenen Key anfragen: https://dip.bundestag.de/
        """
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"ApiKey {api_key}",
            "Accept": "application/json"
        })

    def _get(self, endpoint: str, params: dict = {}) -> dict:
        """Führt einen API-Request aus mit einfachem Rate-Limiting."""
        url = f"{BASE_URL}/{endpoint}"
        response = self.session.get(url, params=params, timeout=15)
        response.raise_for_status()
        time.sleep(0.3)  # Höfliches Rate-Limiting
        return response.json()

    def get_reden(
        self,
        wahlperiode: int = 20,
        limit: int = 50,
        offset: int = 0,
        datum_von: Optional[str] = None,
        datum_bis: Optional[str] = None,
    ) -> dict:
        """
        Lädt Plenarprotokolle / Reden aus dem Bundestag.

        Args:
            wahlperiode: Wahlperiode (20 = aktuelle)
            limit: Anzahl Ergebnisse (max 100)
            datum_von: Format YYYY-MM-DD
            datum_bis: Format YYYY-MM-DD
        """
        params = {
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
        params = {
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
        params = {
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
        """
        Lädt Drucksachen (Anträge, Anfragen, Gesetzentwürfe).
        """
        params = {
            "wahlperiode": wahlperiode,
            "format": "json",
            "num": limit,
        }
        if drucksachentyp:
            params["drucksachentyp"] = drucksachentyp
        if datum_von:
            params["datum.start"] = datum_von

        return self._get("drucksache", params)
