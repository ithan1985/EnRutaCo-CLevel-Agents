"""Utilidades comunes de TTS: normalización de texto en español, WAV y caché LRU."""
from __future__ import annotations

import io
import re
import wave
from collections import OrderedDict
from typing import Optional

_ACRONIMOS = {
    "TMS": "T M S", "ERP": "E R P", "CRM": "C R M", "CDP": "C D P", "SLA": "S L A", "API": "api", "APIs": "apis",
    "OTIF": "O T I F", "KPI": "K P I", "KPIs": "K P I s", "ROI": "R O I", "BI": "B I", "KMS": "K M S", "RAG": "R A G",
    "SCM": "S C M", "BPM": "B P M", "GPS": "G P S", "IoT": "I o T", "TI": "T I", "CFO": "C F O", "CEO": "C E O",
    "IA": "I A", "DW": "D W", "ETL": "E T L", "TPS": "T P S", "MIS": "M I S", "DSS": "D S S", "COP": "pesos",
    "B2B2C": "bi tu bi tu ci", "B2B": "bi tu bi", "B2C": "bi tu ci", "B2G": "bi tu yi",
    "AS/400": "A S cuatrocientos", "CRC": "C R C", "UMNG": "U M N G", "PMO": "P M O", "RPA": "R P A",
}
_DIGITOS = {"0": "cero", "1": "uno", "2": "dos", "3": "tres", "4": "cuatro", "5": "cinco", "6": "seis", "7": "siete"}

# Palabras/frases en inglés reescritas fonéticamente para que espeak-ng (voz es) se acerque
# a la pronunciación original en inglés, en vez de leerlas con reglas de lectura del español.
# Verificado comparando fonemas IPA (piper.phonemize_espeak) contra la voz en-us de espeak-ng.
_ANGLICISMOS = {
    "gateway": "gueitwei", "dashboard": "dasbord", "roadmap": "rodmap", "marketplace": "marketpleis",
    "copilot": "cópailot", "churn": "chern", "retailer": "ríteiler", "cutover": "cátover",
    "e-commerce": "icómers", "mulesoft": "múlsoft", "power bi": "páuer B I", "looker": "lúker",
    "single source of truth": "sínguel sors of truz",
}


def normalize_es(text: str) -> str:
    """Prepara texto de negocio para que el sintetizador lo lea de forma natural."""
    t = text.strip()
    n = r"(\d+(?:\.\d{3})*)"
    t = re.sub(rf"\$\s?{n}\s?M\b(\s*COP)?", lambda m: f"{m.group(1)} millones de pesos", t)
    t = re.sub(rf"\$\s?{n}(\s*COP)?", lambda m: f"{m.group(1)} pesos", t)
    t = re.sub(r"(\d)\s?M\s?COP", r"\1 millones de pesos", t)
    t = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", t)              # 4.200 -> 4200
    t = re.sub(r"(\d+)\s?%", r"\1 por ciento", t)
    t = re.sub(r"\+(\d)", r"más \1", t)
    t = re.sub(r"\b([OEH])([1-7])\b", lambda m: f"{m.group(1)} {_DIGITOS[m.group(2)]}", t)
    for k in sorted(_ANGLICISMOS, key=len, reverse=True):  # antes de acrónimos: puede contener siglas (p.ej. "power bi")
        t = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", _ANGLICISMOS[k], t, flags=re.IGNORECASE)
    for k in sorted(_ACRONIMOS, key=len, reverse=True):
        t = re.sub(rf"(?<![\w/]){re.escape(k)}(?![\w/])", _ACRONIMOS[k], t)
    t = t.replace("&", " y ").replace("/", " o ")
    t = re.sub(r"[«»“”\"]", "", t)
    return re.sub(r"\s+", " ", t)


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm)
    return buf.getvalue()


class LRU:
    def __init__(self, size: int = 128) -> None:
        self.size, self._d = size, OrderedDict()

    def get(self, key: str) -> Optional[bytes]:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key: str, val: bytes) -> None:
        self._d[key] = val
        self._d.move_to_end(key)
        while len(self._d) > self.size:
            self._d.popitem(last=False)
