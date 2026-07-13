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
import re
import time
import xml.etree.ElementTree as ET
import requests
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

PDF_CACHE_DIR = Path("data/pdfs")
XML_CACHE_DIR = Path("data/xml")


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
# XML-Hilfsfunktionen (Bundestag Plenarprotokoll)
# ─────────────────────────────────────────────────────────────────────────────

def lade_xml(url: str, ziel_pfad: Path) -> Optional[bytes]:
    """Lädt XML von url nach ziel_pfad. Gibt Inhalt als bytes zurück, None bei Fehler."""
    if ziel_pfad.exists():
        return ziel_pfad.read_bytes()
    try:
        ziel_pfad.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        ziel_pfad.write_bytes(response.content)
        return response.content
    except Exception as e:
        print(f"    XML-Download fehlgeschlagen: {e}")
        return None


_ZWISCHENRUF_MUSTER = re.compile(r'^\(([^\[]+\[[^\]]+\]):\s*(.+?)\)$', re.DOTALL)


def _normalisiere_name(name: str) -> str:
    """Ersetzt geschuetzte Leerzeichen und normalisiert Whitespace."""
    return " ".join(name.replace("\xa0", " ").split())


def _parse_sprecher(sprecher_raw: str) -> tuple[str, str]:
    """Extrahiert (name, partei) aus 'Dr. Hans Muster [CDU/CSU]'."""
    bracket = sprecher_raw.rfind("[")
    if bracket == -1:
        return _normalisiere_name(sprecher_raw), ""
    name   = _normalisiere_name(sprecher_raw[:bracket])
    partei = sprecher_raw[bracket + 1:].rstrip("]").strip()
    return name, partei


def parse_reden_aus_xml(
    xml_bytes: bytes,
    protokoll_id: str,
    datum: Optional[str] = None,
    wahlperiode: Optional[int] = None,
    min_woerter: int = 50,
) -> list[dict]:
    """
    Parst ein Bundestag-Plenarprotokoll-XML.

    Extrahiert:
    - Reden (typ='rede'): vollstaendige Beitraege, gefiltert auf min_woerter
    - Zwischenrufe (typ='zwischenruf'): kurze Einwuerfe aus <kommentar>-Elementen,
      werden an bestehende Reden desselben Politikers angehaengt oder als
      eigener Eintrag gespeichert (kein Wortlimit).

    Returns: Liste von dicts mit:
        xml_rede_id, protokoll_id, datum, wahlperiode,
        politiker, partei, seite, typ, redetext, wortanzahl
    """
    root = ET.fromstring(xml_bytes)

    # Seiten-Mapping: xml-rede-id -> Seitennummer (aus Inhaltsverzeichnis)
    rede_zu_seite: dict[str, int] = {}
    for xref in root.findall(".//xref"):
        rid = xref.get("rid")
        pnr = xref.get("pnr")
        if rid and pnr:
            try:
                rede_zu_seite[rid] = int(pnr)
            except ValueError:
                pass

    # Phase 1: Vollstaendige Reden parsen
    reden_by_id: dict[str, dict] = {}
    reden_by_politiker: dict[str, dict] = {}

    for rede_elem in root.findall(".//rede"):
        xml_rede_id = rede_elem.get("id", "")
        seite = rede_zu_seite.get(xml_rede_id)

        vorname = nachname = partei = ""
        for p in rede_elem.findall("p"):
            if p.get("klasse") == "redner":
                redner_elem = p.find("redner")
                if redner_elem is not None:
                    vorname  = redner_elem.findtext("name/vorname") or ""
                    nachname = redner_elem.findtext("name/nachname") or ""
                    partei   = redner_elem.findtext("name/fraktion") or ""
                break

        if not nachname:
            continue

        politiker = _normalisiere_name(f"{vorname} {nachname}")

        textteile = []
        for child in rede_elem:
            if child.tag == "p" and child.get("klasse") != "redner":
                text = "".join(child.itertext()).strip()
                if text:
                    textteile.append(text)

        redetext   = "\n".join(textteile)
        wortanzahl = len(redetext.split())

        if wortanzahl < min_woerter:
            continue

        eintrag = {
            "xml_rede_id":  xml_rede_id,
            "protokoll_id": protokoll_id,
            "datum":        datum,
            "wahlperiode":  wahlperiode,
            "politiker":    politiker,
            "partei":       partei,
            "seite":        seite,
            "typ":          "rede",
            "redetext":     redetext,
            "wortanzahl":   wortanzahl,
        }
        reden_by_id[xml_rede_id] = eintrag
        reden_by_politiker[politiker] = eintrag

    # Phase 2: Zwischenrufe aus <kommentar>-Elementen sammeln
    zwischenrufe_by_politiker: dict[str, dict] = {}

    for kommentar in root.findall(".//kommentar"):
        text = "".join(kommentar.itertext()).strip()
        m = _ZWISCHENRUF_MUSTER.match(text)
        if not m:
            continue
        name, partei = _parse_sprecher(m.group(1))
        inhalt = m.group(2).strip()

        # Triviale Einwuerfe (< 3 Woerter) ueberspringen
        if len(inhalt.split()) < 3:
            continue

        if name not in zwischenrufe_by_politiker:
            zwischenrufe_by_politiker[name] = {"partei": partei, "texte": []}
        zwischenrufe_by_politiker[name]["texte"].append(inhalt)

    # Phase 3: Zwischenrufe an bestehende Reden anhaengen oder eigenen Eintrag anlegen
    for name, zw in zwischenrufe_by_politiker.items():
        zw_block = "\n\nZwischenrufe:\n" + "\n".join(f"- {t}" for t in zw["texte"])

        if name in reden_by_politiker:
            # An bestehende Rede anhaengen
            r = reden_by_politiker[name]
            r["redetext"]   += zw_block
            r["wortanzahl"]  = len(r["redetext"].split())
        else:
            # Eigener Eintrag ohne Wortlimit
            redetext = zw_block.strip()
            reden_by_id[f"zw_{protokoll_id}_{name}"] = {
                "xml_rede_id":  f"zw_{protokoll_id}_{name.replace(' ', '_')}",
                "protokoll_id": protokoll_id,
                "datum":        datum,
                "wahlperiode":  wahlperiode,
                "politiker":    name,
                "partei":       zw["partei"],
                "seite":        None,
                "typ":          "zwischenruf",
                "redetext":     redetext,
                "wortanzahl":   sum(len(t.split()) for t in zw["texte"]),
            }

    return list(reden_by_id.values())


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
# JSON-Hilfsfunktion
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_robust(raw: str) -> list | dict:
    """
    Versucht JSON zu parsen. Bereinigt zuerst Markdown-Blöcke,
    dann probiert es direkte JSON-Parse. Bei Fehler sucht es per Regex
    nach dem ersten vollständigen Array/Objekt.
    """
    text = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Versuche erstes JSON-Array oder -Objekt zu extrahieren
    for pattern in (r'(\[[\s\S]*\])', r'(\{[\s\S]*\})'):
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Extractor
# ─────────────────────────────────────────────────────────────────────────────

class AussagenExtractor:
    _API_URL     = "https://api.anthropic.com/v1/messages"
    _MODEL       = "claude-sonnet-4-6"
    _HAIKU_MODEL = "claude-haiku-4-5-20251001"
    _SCREEN_BATCH = 8    # Reden pro Haiku-Screening-Call
    _SCREEN_CHARS = 800  # Zeichen pro Rede beim Screening
    _ANALYSE_CHARS = 3000  # Zeichen pro Rede bei Sonnet-Analyse

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Kein Anthropic API Key gefunden. "
                "Setze die Umgebungsvariable ANTHROPIC_API_KEY."
            )

    def _api_call(self, prompt: str, max_tokens: int = 2000, model: str = "") -> str:
        """
        Sendet Prompt an Claude API. Wartet kurz vor jedem Call,
        wiederholt bei Rate-Limit-Fehlern (429 / 529) mit Backoff.
        """
        headers = {
            "x-api-key":         self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        }
        payload = {
            "model":      model or self._MODEL,
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        }
        time.sleep(0.4)  # Basis-Pause zwischen Calls
        for attempt in range(4):
            resp = requests.post(self._API_URL, headers=headers, json=payload, timeout=90)
            if resp.status_code in (429, 529):
                wait = 2 ** attempt * 5  # 5s, 10s, 20s, 40s
                print(f"    Rate-limit ({resp.status_code}), warte {wait}s ...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["content"][0]["text"].strip()
        resp.raise_for_status()  # letzter Versuch schlägt durch
        return ""

    def screen_reden_batch(self, reden_batch: list[dict]) -> list[int]:
        """
        Haiku bewertet bis zu _SCREEN_BATCH Reden auf Bemerkungswürdigkeit.
        Gibt Liste von Scores 1-5 in gleicher Reihenfolge zurück.
        Score >= 4 → Sonnet-Analyse, Score <= 3 → überspringen.
        Kostet ~20x weniger als Sonnet.
        """
        eintraege = []
        for i, r in enumerate(reden_batch, 1):
            text = r["redetext"][:self._SCREEN_CHARS].replace("\n", " ")
            eintraege.append(f"[{i}] {r['politiker']} ({r.get('partei', '')}): {text}")

        prompt = (
            f"Bewerte diese {len(reden_batch)} Bundestagsreden auf politische "
            f"Bemerkungswürdigkeit (1=routinemaessig, 5=sehr bemerkenswert: "
            f"polarisierend/mutig/widersprüchlich).\n\n"
            + "\n\n".join(eintraege)
            + "\n\nAntworte NUR mit JSON-Array der Scores in gleicher Reihenfolge, "
            "z.B.: [2, 5, 1, 4, 3, 2, 5, 1]"
        )
        try:
            raw    = self._api_call(prompt, max_tokens=80, model=self._HAIKU_MODEL)
            scores = _parse_json_robust(raw)
            if isinstance(scores, list) and len(scores) == len(reden_batch):
                return [int(s) if isinstance(s, (int, float)) else 3 for s in scores]
        except Exception:
            pass
        return [3] * len(reden_batch)  # Fallback: alle mit 3 (Grenzfall, Sonnet entscheidet)

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

        raw    = self._api_call(prompt, max_tokens=3000)
        parsed = _parse_json_robust(raw)

        aussagen = []
        for item in parsed:
            if "kategorie" not in item:
                item["kategorie"] = "polarisierend"
            try:
                aussagen.append(Aussage(**item))
            except Exception as e:
                print(f"    Konnte Aussage nicht parsen: {e}")

        return aussagen

    def extrahiere_aussagen_aus_rede(
        self,
        rede: dict,
        max_aussagen: int = 3,
        quelle_url: str = "",
    ) -> list["Aussage"]:
        """
        Analysiert eine einzelne Rede eines bekannten Politikers.
        Politiker, Partei und Datum sind bereits aus dem XML bekannt.
        """
        politiker = rede["politiker"]
        partei    = rede["partei"] or "unbekannt"
        datum     = rede["datum"] or ""
        redetext  = rede["redetext"]
        quelle_titel = f"Plenarprotokoll {datum}"

        prompt = f"""Analysiere diese Rede von {politiker} ({partei}) im Deutschen Bundestag vom {datum}.

REDETEXT:
{redetext[:self._ANALYSE_CHARS]}

Extrahiere bis zu {max_aussagen} bemerkenswerte Aussagen aus diesen Kategorien:
- "polarisierend": Stark vereinfachend, emotionalisierend, spaltend oder reisserisch formuliert
- "ehrlichkeit_rueckgrat": Ungewoehnlich ehrlich, selbstkritisch oder mutig – auch gegen Parteilinie
- "widerspruch": Widerspricht bekannten Positionen dieser Partei oder frueheren Aussagen des Politikers

Falls keine bemerkenswerten Aussagen vorhanden sind, gib ein leeres Array zurueck: []

Antworte NUR mit JSON-Array, ohne Einleitung, ohne Markdown-Backticks:
[
  {{
    "politiker": "{politiker}",
    "partei": "{partei}",
    "datum": "{datum}",
    "aussage": "Die genaue Aussage",
    "kontext": "Kurze Beschreibung des Kontexts (1-2 Saetze)",
    "thema": "Wirtschaft|Migration|Klimaschutz|Sicherheit|Soziales|Aussenpolitik|Gesundheit|Bildung|Sonstiges",
    "kategorie": "polarisierend",
    "polarisierungsgrad": 7,
    "polarisierungsbegruendung": "Warum ist diese Aussage bemerkenswert?",
    "sprachliche_extreme": ["auffaellige", "begriffe"],
    "quelle_titel": "{quelle_titel}",
    "quelle_url": "{quelle_url}"
  }}
]"""

        raw = self._api_call(prompt, max_tokens=800)
        aussagen = []
        for item in _parse_json_robust(raw):
            if "kategorie" not in item:
                item["kategorie"] = "polarisierend"
            try:
                aussagen.append(Aussage(**item))
            except Exception as e:
                print(f"    Konnte Aussage nicht parsen: {e}")
        return aussagen

    def erstelle_politikerprofil(
        self,
        politiker: str,
        partei: str,
        reden: list[dict],
        aussagen: list[dict],
    ) -> dict:
        """
        Erstellt ein politisches Profil basierend auf allen Reden und Aussagen
        eines Politikers. Identifiziert Kernthemen, Kernpositionen, Widersprueche
        und rhetorische Muster.
        """
        # Aussagen chronologisch aufbereiten (max 60 fuer Kontextfenster)
        aussagen_text = ""
        for a in aussagen[-60:]:
            datum    = a.get("datum") or "?"
            kategorie = a.get("kategorie") or "?"
            thema    = a.get("thema") or "?"
            aussage  = a.get("aussage") or ""
            aussagen_text += f"[{datum} | {kategorie} | {thema}]\n{aussage}\n\n"

        # Redehistorie kompakt (max 30 Eintraege)
        reden_zeilen = []
        for r in reden[-30:]:
            datum = r.get("datum") or "?"
            wort  = r.get("wortanzahl") or 0
            typ   = r.get("typ") or "rede"
            reden_zeilen.append(f"  {datum} | {typ} | {wort} Woerter")
        reden_uebersicht = "\n".join(reden_zeilen)

        zeitraum_von = reden[0].get("datum")  if reden else None
        zeitraum_bis = reden[-1].get("datum") if reden else None

        prompt = f"""Erstelle ein politisches Profil von {politiker} ({partei}).

REDEHISTORIE ({len(reden)} Eintraege, {zeitraum_von} bis {zeitraum_bis}):
{reden_uebersicht}

BEKANNTE AUSSAGEN ({len(aussagen)} gesamt, chronologisch):
{aussagen_text[:12000]}

Analysiere und antworte NUR mit JSON, ohne Einleitung, ohne Markdown-Backticks:
{{
  "kernthemen": ["Thema1", "Thema2"],
  "kernpositionen": [
    {{
      "thema": "Migration",
      "position": "Kurze praegnante Beschreibung der Position",
      "begruendung": "Belegt durch welche Aussagen?"
    }}
  ],
  "widersprueche": [
    {{
      "aussage1": "Erste Aussage",
      "datum1": "YYYY-MM-DD",
      "aussage2": "Spaetere Aussage die widerspricht",
      "datum2": "YYYY-MM-DD",
      "erklaerung": "Worin besteht der Widerspruch?"
    }}
  ],
  "rhetorische_muster": [
    "Beschreibung eines wiederkehrenden Musters (z.B. Feindbildkonstruktion, Zahlenrhetorik)"
  ],
  "zusammenfassung": "Kurzes politisches Portrait in 3-5 Saetzen."
}}

Wichtig:
- Nur belegte Widersprueche aufnehmen, keine Spekulationen
- Leere Arrays wenn keine Daten vorhanden
- Kernthemen nach Haeufigkeit sortieren"""

        raw   = self._api_call(prompt, max_tokens=3000)
        profil = _parse_json_robust(raw)
        if not isinstance(profil, dict):
            profil = {}

        profil["politiker"]       = politiker
        profil["partei"]          = partei
        profil["anzahl_reden"]    = len(reden)
        profil["anzahl_aussagen"] = len(aussagen)
        profil["zeitraum_von"]    = zeitraum_von
        profil["zeitraum_bis"]    = zeitraum_bis
        return profil

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

        raw = self._api_call(prompt, max_tokens=800)
        return _parse_json_robust(raw)
