"""Cliente asíncrono de Ollama: streaming de chat con salida estructurada, listado y descarga de modelos."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


class LLMError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def summarize_stats(obj: dict[str, Any]) -> dict[str, Any]:
    """Métricas del último fragmento de Ollama (duraciones en ns) -> segundos y tokens/s."""
    ns = 1e9
    pe, ev = obj.get("prompt_eval_count") or 0, obj.get("eval_count") or 0
    ped, evd = (obj.get("prompt_eval_duration") or 0) / ns, (obj.get("eval_duration") or 0) / ns
    return {
        "load_s": round((obj.get("load_duration") or 0) / ns, 2),
        "prompt_tokens": pe, "prefill_s": round(ped, 2), "prefill_tps": round(pe / ped, 1) if ped else None,
        "gen_tokens": ev, "gen_s": round(evd, 2), "gen_tps": round(ev / evd, 1) if evd else None,
        "total_s": round((obj.get("total_duration") or 0) / ns, 2),
    }


class OllamaClient:
    def __init__(self, base_url: str, keep_alive: str = "30m", num_ctx: int = 8192) -> None:
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx

    def _client(self, read_timeout: float = 600.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(read_timeout, connect=5.0))

    async def tags(self) -> list[str]:
        try:
            async with self._client(10) as c:
                r = await c.get("/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError("llm_unreachable", f"No se pudo consultar Ollama: {e}") from e

    async def has_model(self, name: str) -> bool:
        names = await self.tags()
        return name in names or (":" not in name and f"{name}:latest" in names)

    async def load(self, model: str) -> None:
        """Carga el modelo en memoria sin generar texto (evita el arranque en frío en la primera pregunta).

        Con el mismo num_ctx que los turnos: si difiere, Ollama recarga el modelo en la primera pregunta y la
        precarga no sirve de nada."""
        try:
            async with self._client(300) as c:
                await c.post("/api/generate", json={"model": model, "keep_alive": self.keep_alive,
                                                    "options": {"num_ctx": self.num_ctx}})
        except httpx.HTTPError:
            pass

    async def prime(self, model: str, messages: list[dict[str, str]], schema: dict[str, Any] | str) -> dict[str, Any]:
        """Precalentamiento: carga el modelo y deja en la caché de prefijo de Ollama el prompt de la próxima pregunta
        (genera un solo token). Si la pregunta real llega con el mismo prompt, se salta casi toda la lectura."""
        body = {"model": model, "messages": messages, "stream": False, "format": schema, "keep_alive": self.keep_alive,
                "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 1}}
        try:
            async with self._client() as c:
                r = await c.post("/api/chat", json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise LLMError("llm_unreachable", "No hay conexión con Ollama.") from e
        except httpx.ReadTimeout as e:
            raise LLMError("llm_timeout", "Ollama tardó demasiado en responder.") from e
        if r.status_code != 200:
            detail = r.text[:300]
            if r.status_code == 404 or "not found" in detail.lower():
                raise LLMError("model_missing", f"El modelo {model} no está descargado todavía.")
            raise LLMError(f"http_{r.status_code}", detail)
        return summarize_stats(r.json())

    async def pull(self, model: str) -> AsyncIterator[dict[str, Any]]:
        async with self._client(3600) as c:
            async with c.stream("POST", "/api/pull", json={"model": model, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if line.strip():
                        yield json.loads(line)

    async def chat_stream(
        self, model: str, messages: list[dict[str, str]], schema: dict[str, Any] | str,
        temperature: float = 0.7, num_predict: int = 450, stats: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Emite fragmentos de texto del contenido del asistente."""
        async def attempt(fmt: dict[str, Any] | str) -> AsyncIterator[str]:
            body = {
                "model": model, "messages": messages, "stream": True, "format": fmt,
                "keep_alive": self.keep_alive,
                "options": {"temperature": temperature, "top_p": 0.9, "num_ctx": self.num_ctx, "num_predict": num_predict},
            }
            try:
                async with self._client() as c:
                    async with c.stream("POST", "/api/chat", json=body) as r:
                        if r.status_code != 200:
                            detail = (await r.aread()).decode("utf-8", "ignore")
                            if r.status_code == 404 or "not found" in detail.lower():
                                raise LLMError("model_missing", f"El modelo {model} no está descargado todavía.")
                            raise LLMError(f"http_{r.status_code}", detail[:300])
                        async for line in r.aiter_lines():
                            if not line.strip():
                                continue
                            obj = json.loads(line)
                            if "error" in obj:
                                raise LLMError("llm_error", str(obj["error"])[:300])
                            piece = (obj.get("message") or {}).get("content", "")
                            if piece:
                                yield piece
                            if obj.get("done"):
                                if stats is not None:
                                    stats.update(summarize_stats(obj))
                                return
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                raise LLMError("llm_unreachable", "No hay conexión con Ollama.") from e
            except httpx.ReadTimeout as e:
                raise LLMError("llm_timeout", "Ollama tardó demasiado en responder.") from e

        try:
            async for piece in attempt(schema):
                yield piece
        except LLMError as e:
            # Ollama antiguo sin soporte de esquema JSON: reintenta con formato JSON simple.
            if e.code == "http_400" and isinstance(schema, dict):
                async for piece in attempt("json"):
                    yield piece
            else:
                raise
