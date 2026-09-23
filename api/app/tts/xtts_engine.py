"""Motor XTTS-v2 (Hugging Face: coqui/XTTS-v2). Mayor calidad y voces distintas por personaje; GPU recomendada.

Requiere `pip install -r requirements-xtts.txt` y aceptar la licencia CPML de Coqui (COQUI_TOS_AGREED=1).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .common import normalize_es, pcm_to_wav

log = logging.getLogger("tts.xtts")
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


class XTTSEngine:
    name = "xtts"

    def __init__(self, personas: dict[str, dict[str, Any]], models_dir: Path) -> None:
        self.profiles = {cid: dict(p["voz"]["xtts"]) for cid, p in personas.items() if p.get("voz", {}).get("xtts")}
        self._tts: Any = None
        self._lock = threading.Lock()
        self._error = ""

    def _load(self) -> Any:
        with self._lock:
            if self._tts is None:
                import torch
                from TTS.api import TTS

                dev = "cuda" if torch.cuda.is_available() else "cpu"
                log.info("Cargando XTTS-v2 en %s", dev)
                self._tts = TTS(MODEL).to(dev)
            return self._tts

    def prefetch(self) -> None:
        try:
            self._load()
        except Exception as e:  # noqa: BLE001
            self._error = str(e)[:300]
            log.error("No se pudo cargar XTTS: %s", e)

    def status(self) -> dict[str, Any]:
        return {"engine": self.name, "ready": self._tts is not None, "errors": {"xtts": self._error} if self._error else {}}

    def voices_info(self) -> dict[str, Any]:
        if self._tts is None:
            return {}
        return {"speakers": list(getattr(self._tts, "speakers", []) or [])}

    def synth(self, cid: str, text: str) -> bytes:
        import numpy as np

        prof = self.profiles[cid]
        tts = self._load()
        speakers = list(getattr(tts, "speakers", []) or [])
        speaker = prof["speaker"]
        if speakers and speaker not in speakers:
            log.warning("Hablante XTTS %r no existe; usando %r", speaker, speakers[0])
            speaker = speakers[0]
        with self._lock:
            wav = tts.tts(text=normalize_es(text), speaker=speaker, language="es", speed=float(prof.get("speed", 1.0)))
        arr = np.clip(np.asarray(wav, dtype="float32"), -1.0, 1.0)
        sr = int(tts.synthesizer.output_sample_rate)
        return pcm_to_wav((arr * 32767).astype("int16").tobytes(), sr)
