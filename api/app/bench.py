"""Mide la velocidad real de tu equipo con los modelos y prompts del proyecto.

Uso:  docker compose exec api python -m app.bench
Reporta carga del modelo, prefill (lectura del prompt), generación y el beneficio de la caché de prefijo.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import httpx

from .config import Settings, Store
from .llm import summarize_stats
from .prompts import build_messages


def call(base: str, model: str, messages: list, schema: dict, st: Settings) -> dict:
    body = {"model": model, "messages": messages, "stream": False, "format": schema, "keep_alive": st.keep_alive,
            "options": {"temperature": st.temperature, "num_ctx": st.num_ctx, "num_predict": st.num_predict}}
    r = httpx.post(f"{base}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return r.json()


def main() -> None:
    st = Settings()
    store = Store(st.config_dir)
    sel = ["O1", "O2", "O3", "O4", "O5", "H1", "H2", "E1", "E3", "E4"]
    def req(cid: str) -> NS:
        return NS(cid=cid, week=8, team="Equipo bench", context="Fase 1: fundamentos. Excluye E2 y E6. Pide exceder el techo con ROI.",
                  focus="", budget=sel, asked=[], thread=[], cross_from=None)

    print(f"Ollama: {st.ollama_url}  ·  num_ctx={st.num_ctx}  ·  num_predict={st.num_predict}\n")
    for model, notes in dict.fromkeys([(st.model_quick, st.notes_in_quick), (st.model_deep, True)]):
        print(f"== {model}  (notas del docente: {'sí' if notes else 'no'})")
        print(f"{'llamada':<34}{'carga':>7}{'prefill':>18}{'generación':>20}{'total':>8}")
        for label, cid in (("1. frío: CFO, semana 8", "cfo"), ("2. mismo personaje (caché)", "cfo"), ("3. otro personaje (prefijo común)", "ops")):
            msgs, schema = build_messages("open", store, req(cid), notes=notes)
            try:
                s = summarize_stats(call(st.ollama_url, model, msgs, schema, st))
            except httpx.HTTPError as e:
                print(f"  error: {e}  (¿modelo descargado? ¿Ollama activo?)")
                break
            pre = f"{s['prompt_tokens']} tok · {s['prefill_s']} s"
            gen = f"{s['gen_tokens']} tok · {s['gen_tps']} t/s"
            print(f"{label:<34}{s['load_s']:>6}s{pre:>18}{gen:>20}{s['total_s']:>7}s")
        print()
    print("Lectura: la pregunta aparece cuando termina el prefill y se han generado ~40 tokens. "
          "Si la llamada 3 sigue lenta, baja la semana, reduce el resumen del docente o usa el modo Rápido.")


if __name__ == "__main__":
    main()
