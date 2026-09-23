"""Motor Piper (ONNX, CPU en tiempo real). Voces desde Hugging Face: rhasspy/piper-voices.

La personalidad se expresa con parámetros por personaje: modelo de voz, tono (pitch), velocidad,
variación de timbre/ritmo y pausas entre frases. El tono se cambia sin costo: se sintetiza con
length_scale*pitch y se declara la tasa de muestreo como sr*pitch (duración final = length_scale).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .common import normalize_es, pcm_to_wav

log = logging.getLogger("tts.piper")
HF_REPO = "rhasspy/piper-voices"


def hf_files(voice_id: str) -> tuple[str, str]:
    """es_ES-davefx-medium -> (es/es_ES/davefx/medium/es_ES-davefx-medium.onnx, ...onnx.json)"""
    locale, name, quality = voice_id.split("-", 2)
    lang = locale.split("_")[0]
    base = f"{lang}/{locale}/{name}/{quality}/{voice_id}"
    return base + ".onnx", base + ".onnx.json"


def resolve_speaker(speaker_id_map: dict[str, int] | None, default_id: int, hint: Any) -> int | None:
    """Elige el id de hablante en modelos multi-voz a partir de una pista (F, M, número o nombre)."""
    m = speaker_id_map or {}
    if not m:
        return None
    if hint is None:
        return default_id
    if isinstance(hint, int):
        return hint
    h = str(hint).strip().lower()
    for name, i in m.items():
        if name.lower() == h:
            return i
    for name, i in m.items():
        if name.lower().startswith(h):
            return i
    for name, i in m.items():
        if h in name.lower():
            return i
    if h.isdigit():
        return int(h)
    log.warning("Pista de hablante %r no coincide con %s; usando el predeterminado", hint, list(m))
    return default_id


class PiperEngine:
    name = "piper"

    def __init__(self, personas: dict[str, dict[str, Any]], models_dir: Path) -> None:
        self.profiles = {cid: dict(p["voz"]["piper"]) for cid, p in personas.items() if p.get("voz", {}).get("piper")}
        self.cache_dir = Path(models_dir) / "hf"
        self._voices: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._errors: dict[str, str] = {}

    # ---- carga ----
    def _download(self, voice_id: str) -> tuple[str, str]:
        from huggingface_hub import hf_hub_download

        onnx, cfg = hf_files(voice_id)
        p1 = hf_hub_download(HF_REPO, onnx, cache_dir=str(self.cache_dir))
        p2 = hf_hub_download(HF_REPO, cfg, cache_dir=str(self.cache_dir))
        return p1, p2

    def _voice(self, voice_id: str) -> Any:
        with self._lock:
            if voice_id not in self._voices:
                from piper import PiperVoice

                onnx, cfg = self._download(voice_id)
                self._voices[voice_id] = PiperVoice.load(onnx, config_path=cfg)
                log.info("Voz cargada: %s", voice_id)
            return self._voices[voice_id]

    def prefetch(self) -> None:
        for voice_id in sorted({p["voice"] for p in self.profiles.values()}):
            try:
                self._voice(voice_id)
                self._errors.pop(voice_id, None)
            except Exception as e:  # noqa: BLE001 — se reporta en /api/health
                self._errors[voice_id] = str(e)[:200]
                log.error("No se pudo cargar %s: %s", voice_id, e)

    def status(self) -> dict[str, Any]:
        wanted = sorted({p["voice"] for p in self.profiles.values()})
        return {
            "engine": self.name,
            "ready": all(v in self._voices for v in wanted),
            "loaded": sorted(self._voices),
            "pending": [v for v in wanted if v not in self._voices],
            "errors": dict(self._errors),
        }

    def voices_info(self) -> dict[str, Any]:
        out = {}
        for vid, v in self._voices.items():
            out[vid] = {"sample_rate": v.config.sample_rate, "speakers": dict(v.config.speaker_id_map or {})}
        return out

    # ---- síntesis ----
    def synth(self, cid: str, text: str) -> bytes:
        from piper import SynthesisConfig

        prof = self.profiles[cid]
        voice = self._voice(prof["voice"])
        pitch = float(prof.get("pitch", 1.0))
        spk = resolve_speaker(voice.config.speaker_id_map, voice.config.default_speaker_id, prof.get("speaker"))
        cfg = SynthesisConfig(
            speaker_id=spk,
            length_scale=float(prof.get("length_scale", 1.0)) * pitch,
            noise_scale=float(prof.get("noise_scale", 0.667)),
            noise_w_scale=float(prof.get("noise_w", 0.8)),
            volume=float(prof.get("volume", 1.0)),
        )
        chunks = list(voice.synthesize(normalize_es(text), syn_config=cfg))
        if not chunks:
            raise RuntimeError("Piper no generó audio")
        sr = int(chunks[0].sample_rate)
        out_sr = int(round(sr * pitch))
        gap = b"\x00\x00" * int(out_sr * float(prof.get("pausa", 0.2)))
        pcm = gap.join(c.audio_int16_bytes for c in chunks)
        return pcm_to_wav(pcm, out_sr)
