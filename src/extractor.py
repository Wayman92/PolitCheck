"""
KI-Extraktions-Engine
Lädt Plenarprotokolle als PDF, extrahiert Text und analysiert per Claude API.

Kategorien:
  polarisierend         - Aussagen die spalten, vereinfachen oder emotionalisieren
  ehrlichkeit_rueckgrat - Ungewoehnlich ehrliche oder mutige Aussagen
  widerspruch           - Aussagen die der Parteilinie oder frueheren Positionen widersprechen
"""

import json
import os
import requests
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

PDF_CACHE_DIR = Path("data/pdfs")


@dataclass
class Aussage:
    politiker: str
    partei: str
    datum: str
    aussage: str
    kontext: str
    thema: str
    kategorie: str               # polarisierend | ehrlichkeit_rueckgrat | widerspruch
    polarisierungsgrad: int      # 1-10
    polarisierungsbegruendung: str
    sprachliche_extreme: list
    quelle_titel: str
    quelle_url: str

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# PDF-Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def lade_pdf(url: str, ziel_pfad: Path) -> bool:
    """Lädt PDF von url nach ziel_pfad. Ueberspringt Download wenn Datei bereits existiert."""
    if ziel_pfad.exists():
        return True
    try:
        ziel_pfad.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
        with open(ziel_pfad, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    PDF-Download fehlgeschlagen: {e}")
        return False


def extrahiere_text_aus_pdf(pdf_pfad: Path, max_zeichen: int = 40000) -> str:
    """Extrahiert eingebetteten Text aus einer PDF-Datei."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber nicht installiert. Bitte: pip install pdfplumber")

    text_parts = []
    gesamt = 0
    with pdfplumber.open(pdf_pfad) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            gesamt += len(page_text)
            if gesamt >= max_zeichen:
                break
    return "\n".join(text_parts)[:max_zeichen]


# ─────────────────────────────────────────────────────────────────────────────
# Extractor
# ─────────────────────────────────────────────────────────────────────────────

class AussagenExtractor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Kein Anthropic API Key gefunden. "
                "Setze die Umgebungsvariable ANTHROPIC_API_KEY."
            )

    def lade_protokoll_text(
        self,
        pdf_url: Optional[str],
        protokoll_id: str,
        fallback_text: str = "",
    ) -> tuple[str, str]:
        """
        Lädt PDF lokal und extrahiert Text.
        Returns: (text, quelle) wobei quelle "pdf" oder "fallback" ist.
        """
        if pdf_url:
            ziel = PDF_CACHE_DIR / f"{protokoll_id}.pdf"
            if lade_pdf(pdf_url, ziel):
                try:
                    text = extrahiere_text_aus_pdf(ziel)
                    if text and len(text.strip()) >= 200:
                        return text, "pdf"
                    print("    PDF geladen, aber zu wenig Text extrahiert -- nutze Fallback.")
                except Exception as e:
                    print(f"    Textextraktion fehlgeschlagen: {e}")
        return fallback_text, "fallback"

    def extrahiere_aussagen(
        self,
        text: str,
        quelle_titel: str = "",
        quelle_url: str = "",
        max_aussagen: int = 5,
    ) -> list["Aussage"]:
        """
        Extrahiert bemerkenswerte Aussagen aus einem Plenarprotokoll-Text.
        Drei Kategorien: polarisierend, ehrlichkeit_rueckgrat, widerspruch.
        """
        prompt = f"""Du analysierst ein deutsches Plenarprotokoll des Bundestages und extrahierst die {max_aussagen} bemerkenswertesten Aussagen.

KATEGORIEN (verwende exakt diese Bezeichner im Feld "kategorie"):
- "polarisierend": Aussagen die stark vereinfachen, emotionalisieren, spalten oder reisserisch formuliert sind
- "ehrlichkeit_rueckgrat": Ungewoehnlich ehrliche, selbstkritische oder mutige Aussagen - auch wenn sie gegen die Parteilinie gehen oder politisch riskant sind
- "widerspruch": Aussagen die bekannten Positionen der eigenen Partei oder frueheren Aussagen des Politikers direkt widersprechen

TEXT (Plenarprotokoll):
{text[:40000]}

Extrahiere die {max_aussagen} interessantesten Aussagen moeglichst verteilt ueber die Kategorien.
Ignoriere reine Verfahrensaussagen ("Ich beantrage...") und rein formelle Aussagen.

Antworte NUR mit einem JSON-Array, ohne Einleitung, ohne Markdown-Backticks:
[
  {{
    "politiker": "Vollstaendiger Name",
    "partei": "Parteiname oder leer wenn unbekannt",
    "datum": "YYYY-MM-DD oder leer wenn unbekannt",
    "aussage": "Die genaue Aussage",
    "kontext": "Kurze Beschreibung des Kontexts (1-2 Saetze)",
    "thema": "Eines von: Wirtschaft, Migration, Klimaschutz, Sicherheit, Soziales, Aussenpolitik, Gesundheit, Bildung, Sonstiges",
    "kategorie": "polarisierend",
    "polarisierungsgrad": 7,
    "polarisierungsbegruendung": "Warum ist diese Aussage bemerkenswert?",
    "sprachliche_extreme": ["auffaellige", "begriffe"],
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
                "max_tokens": 3000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        raw = data["content"][0]["text"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        parsed = json.loads(raw)

        aussagen = []
        for item in parsed:
            if "kategorie" not in item:
                item["kategorie"] = "polarisierend"
            try:
                aussagen.append(Aussage(**item))
            except Exception as e:
                print(f"    Konnte Aussage nicht parsen: {e}")

        return aussagen

    def bewerte_aussage(self, aussage: "Aussage") -> dict:
        """Bewertet eine einzelne Aussage detaillierter."""
        prompt = f"""Bewerte folgende politische Aussage objektiv:

Politiker: {aussage.politiker} ({aussage.partei})
Kategorie: {aussage.kategorie}
Aussage: {aussage.aussage}
Kontext: {aussage.kontext}

Antworte NUR mit JSON ohne Markdown:
{{
  "faktisch_pruefbar": true/false,
  "einschaetzung": "Kurze neutrale Einschaetzung der Aussage",
  "gegenpositionen": ["Welche Gegenargumente gibt es?"],
  "aehnliche_aussagen_suchbegriffe": ["Suchbegriffe um aehnliche Faktenchecks zu finden"]
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
