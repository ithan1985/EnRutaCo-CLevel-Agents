from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def build_engine(name: str, personas: dict[str, dict[str, Any]], models_dir: Path) -> Optional[Any]:
    if name in ("none", "off", ""):
        return None
    if name == "piper":
        from .piper_engine import PiperEngine
        return PiperEngine(personas, models_dir)
    if name == "xtts":
        from .xtts_engine import XTTSEngine
        return XTTSEngine(personas, models_dir)
    raise ValueError(f"TTS_ENGINE desconocido: {name} (usa piper, xtts o none)")
