"""
KI-Extraktions-Engine
Nutzt Claude API um aus Rohtexten politische Aussagen zu extrahieren und zu bewerten.
"""

import json
import os
import requests
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class Aussage:
    politiker: str
    partei: str
    datum: str
    aussage: str
    kontext: str
    thema: str
    polarisierungsgrad: int      # 1-10
    polarisierungsbegruendung: str
    sprachliche_extreme: list    # z.B. ["alle", "nie", "immer"]
    quelle_titel: str
    quelle_url: str

    def to_dict(self) -> dict:
        return asdict(self)


class AussagenExtractor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Kein Anthropic API Key gefunden. "
                "Setze die Umgebungsvariable ANTHROPIC_API_KEY."
            )

    def extrahiere_aussagen(
        self,
        text: str,
        quelle_titel: str = "",
        quelle_url: str = "",
        max_aussagen: int = 5,
    ) -> list[Aussage]:
        """
        Extrahiert politische Aussagen aus einem Text und bewertet sie.

        Args:
            text: Rohtext (Rede, Protokoll, etc.)
            quelle_titel: Titel der Quelle
            quelle_url: URL der Quelle
            max_aussagen: Maximale Anzahl zu extrahierender Aussagen

        Returns:
            Liste von Aussage-Objekten
        """

        prompt = f"""Du analysierst einen deutschen politischen Text und extrahierst die {max_aussagen} polarisierendsten oder kontroversesten Aussagen.

TEXT:
{text[:4000]}

AUFGABE:
Extrahiere die {max_aussagen} Aussagen, die am ehesten polarisieren, kontrovers sind oder faktisch überprüfbar sind.
Ignoriere reine Verfahrensaussagen ("Ich beantrage...") oder rein formelle Aussagen.

Antworte NUR mit einem JSON-Array, ohne Einleitung, ohne Markdown-Backticks. Format:
[
  {{
    "politiker": "Vollständiger Name",
    "partei": "Parteiname oder leer wenn unbekannt",
    "datum": "YYYY-MM-DD oder leer wenn unbekannt",
    "aussage": "Die genaue Aussage in Anführungszeichen",
    "kontext": "Kurze Beschreibung des Kontexts (1-2 Sätze)",
    "thema": "Eines von: Wirtschaft, Migration, Klimaschutz, Sicherheit, Soziales, Außenpolitik, Gesundheit, Bildung, Sonstiges",
    "polarisierungsgrad": 7,
    "polarisierungsbegruendung": "Warum ist diese Aussage polarisierend?",
    "sprachliche_extreme": ["Liste", "von", "Absolutbegriffen", "falls", "vorhanden"],
    "quelle_titel": "{quelle_titel}",
    "quelle_url": "{quelle_url}"
  }}
]"""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        raw = data["content"][0]["text"].strip()
        # JSON-Fences entfernen falls vorhanden
        raw = raw.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(raw)

        aussagen = []
        for item in parsed:
            try:
                aussagen.append(Aussage(**item))
            except Exception as e:
                print(f"  ⚠️  Konnte Aussage nicht parsen: {e}")

        return aussagen

    def bewerte_aussage(self, aussage: Aussage) -> dict:
        """
        Bewertet eine einzelne Aussage detaillierter.
        Nützlich für eine Detailansicht.
        """
        prompt = f"""Bewerte folgende politische Aussage objektiv:

Politiker: {aussage.politiker} ({aussage.partei})
Aussage: {aussage.aussage}
Kontext: {aussage.kontext}

Antworte NUR mit JSON ohne Markdown:
{{
  "faktisch_pruefbar": true/false,
  "einschaetzung": "Kurze neutrale Einschätzung der Aussage",
  "gegenpositionen": ["Welche Gegenargumente gibt es?"],
  "aehnliche_aussagen_suchbegriffe": ["Suchbegriffe um ähnliche Faktenchecks zu finden"]
}}"""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        raw = data["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
