"""Configuración por variables de entorno y carga de YAML del caso y los personajes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml


class Settings:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        e = env if env is not None else os.environ
        self.ollama_url = e.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        self.model_quick = e.get("LLM_MODEL_QUICK", "qwen2.5:3b-instruct")
        self.model_deep = e.get("LLM_MODEL_DEEP", "qwen2.5:7b-instruct")
        self.num_ctx = int(e.get("LLM_NUM_CTX", "8192"))
        self.temperature = float(e.get("LLM_TEMPERATURE", "0.7"))
        self.num_predict = int(e.get("LLM_NUM_PREDICT", "450"))
        self.notes_in_quick = e.get("LLM_NOTES_IN_QUICK", "0") == "1"
        self.keep_alive = e.get("LLM_KEEP_ALIVE", "30m")
        self.pull_on_start = e.get("PULL_ON_START", "1") == "1"
        self.tts_engine = e.get("TTS_ENGINE", "piper").strip().lower()  # piper | xtts | none
        self.models_dir = Path(e.get("MODELS_DIR", "/models"))
        self.config_dir = Path(e.get("CONFIG_DIR", "/app/config"))
        self.web_dir = Path(e.get("WEB_DIR", "/app/web"))

    def model_for(self, mode: str) -> str:
        return self.model_deep if mode == "deep" else self.model_quick


class Store:
    """Caso + personajes cargados desde YAML (recargables sin reiniciar)."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)
        self.caso: dict[str, Any] = {}
        self.personas: dict[str, dict[str, Any]] = {}
        self.orden: list[str] = []
        self.reload()

    def reload(self) -> None:
        with open(self.config_dir / "caso.yaml", encoding="utf-8") as f:
            caso = yaml.safe_load(f)
        with open(self.config_dir / "personas.yaml", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        personas = raw["personas"]
        orden = raw.get("orden") or list(personas)
        for cid in orden:
            if cid not in personas:
                raise ValueError(f"orden incluye un personaje inexistente: {cid}")
        for cid, p in personas.items():
            for r in p.get("rivales", []):
                if r not in personas:
                    raise ValueError(f"{cid}: rival inexistente {r}")
            personas[cid]["id"] = cid
            personas[cid].setdefault("desde", 1)
        self.caso, self.personas, self.orden = caso, personas, orden

    def week(self, n: int) -> dict[str, Any]:
        for w in self.caso["semanas"]:
            if w["n"] == n:
                return w
        raise KeyError(n)

    def public_config(self) -> dict[str, Any]:
        return {
            "orden": self.orden,
            "personas": {
                cid: {
                    k: p[k]
                    for k in ("id", "nombre", "corto", "cargo", "ini", "arquetipo", "ancla",
                              "frase_tipica", "conflicto", "rivales", "desde")
                } | {"voz_motivo": p.get("voz", {}).get("motivo", "")}
                for cid, p in self.personas.items()
            },
            "semanas": [{k: w[k] for k in ("n", "lead", "titulo", "entregable")} for w in self.caso["semanas"]],
            "catalogo": self.caso["catalogo"],
            "tipos": self.caso["tipos"],
            "presupuesto": self.caso["presupuesto"],
        }
