"""Precalentamiento del modelo: mismo prompt que /api/ask y mismo num_ctx que los turnos (si no, Ollama recarga)."""
import asyncio
import json

import httpx

from app.llm import LLMError, OllamaClient
from test_backend import FakeLLM, body, make_client, read_sse


class PrimingLLM(FakeLLM):
    def __init__(self, fail=None, **kw):
        super().__init__(**kw)
        self.primed, self.prime_fail = [], fail

    async def prime(self, model, messages, schema):
        if self.prime_fail:
            raise LLMError(self.prime_fail, "falla simulada")
        self.primed.append({"model": model, "messages": messages, "schema": schema})
        return {"load_s": 3.2, "prompt_tokens": 2100, "prefill_s": 4.0}


def test_warmup_usa_exactamente_el_prompt_de_la_primera_pregunta():
    llm = PrimingLLM()
    c = make_client(llm)
    req = body(cid="ti", junta=True, context="1. PROBLEMA: prueba", focus="arquitectura To-Be", budget=["O1", "E2"])
    r = c.post("/api/warmup", json=req)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["stats"]["prompt_tokens"] == 2100
    with c.stream("POST", "/api/ask", json=req) as s:
        read_sse(s)
    # Mismo modelo, mismos mensajes y mismo esquema: la pregunta real reutiliza la caché de prefijo completa.
    assert llm.primed[0]["messages"] == llm.calls[0]["messages"]
    assert llm.primed[0]["schema"] == llm.calls[0]["schema"] and llm.primed[0]["model"] == llm.calls[0]["model"]


def test_warmup_modo_profundo_carga_el_modelo_profundo():
    llm = PrimingLLM()
    r = make_client(llm).post("/api/warmup", json=body(cid="ti", mode="deep"))
    assert r.json()["model"] == "qwen2.5:7b-instruct" == llm.primed[0]["model"]


def test_warmup_errores_y_cliente_sin_precalentamiento():
    assert make_client(PrimingLLM()).post("/api/warmup", json=body(cid="nadie")).status_code == 404
    r = make_client(PrimingLLM(fail="llm_unreachable")).post("/api/warmup", json=body(cid="ti"))
    assert r.status_code == 503 and "falla simulada" in r.json()["detail"]
    assert make_client(FakeLLM()).post("/api/warmup", json=body(cid="ti")).json()["status"] == "skipped"


def _ollama(handler):
    """OllamaClient con transporte simulado: registra el cuerpo de cada petición."""
    cli = OllamaClient("http://ollama:11434", keep_alive="30m", num_ctx=8192)
    cli._client = lambda read_timeout=600.0: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url=cli.base_url, transport=httpx.MockTransport(handler))
    return cli


def test_load_y_prime_envian_el_mismo_num_ctx_que_los_turnos():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "{"}, "done": True, "load_duration": 3_000_000_000,
                                             "prompt_eval_count": 2000, "prompt_eval_duration": 2_000_000_000,
                                             "eval_count": 1, "eval_duration": 50_000_000, "total_duration": 5_100_000_000})
        return httpx.Response(200, json={"done": True})

    cli = _ollama(handler)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    asyncio.run(cli.load("qwen2.5:3b-instruct"))
    stats = asyncio.run(cli.prime("qwen2.5:3b-instruct", msgs, {"type": "object"}))
    (p1, b1), (p2, b2) = sent
    assert p1 == "/api/generate" and b1["options"]["num_ctx"] == 8192 and b1["keep_alive"] == "30m"
    assert p2 == "/api/chat" and b2["stream"] is False and b2["messages"] == msgs and b2["format"] == {"type": "object"}
    assert b2["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 1} and b2["keep_alive"] == "30m"
    assert stats["load_s"] == 3.0 and stats["prompt_tokens"] == 2000 and stats["prefill_s"] == 2.0


def test_prime_modelo_faltante():
    cli = _ollama(lambda request: httpx.Response(404, text='{"error":"model not found"}'))
    try:
        asyncio.run(cli.prime("x", [], {}))
    except LLMError as e:
        assert e.code == "model_missing"
    else:
        raise AssertionError("debía fallar")
