"""API local de los agentes del Comité Directivo de EnRutaCo.

Endpoints:
  GET  /api/config            personajes, semanas y catálogo (sin prompts)
  GET  /api/health            estado de Ollama, descarga de modelos y voces
  POST /api/ask               pregunta de un personaje (SSE)
  POST /api/follow            reacción y repregunta tras la respuesta del equipo (SSE)
  POST /api/warmup            carga el modelo y precalienta el prompt de la próxima pregunta (sin generar texto)
  POST /api/tts               texto -> audio WAV con la voz del personaje
  GET  /api/tts/sample/{cid}  muestra de voz (frase ancla del personaje)
  GET  /api/voices            hablantes disponibles por modelo (para ajustar personas.yaml)
  POST /api/reload            recarga caso.yaml y personas.yaml
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, Store
from .guard import coherencia_lectura, datos_ya_dados, duration_contradiction, sanitize, scaffold
from .llm import LLMError, OllamaClient
from .prompts import (MAX_ATTEMPTS, MAX_FOLLOWS, build_messages, concern_attempts, correction_message, estado_de,
                      follow_count, is_confused, last_answer, prior_questions, similar, thread_terms)
from .tts import build_engine
from .tts.common import LRU

log = logging.getLogger("api")


# ───────────── Modelos de petición ─────────────

class Asked(BaseModel):
    cid: str = ""
    text: str = Field("", max_length=1500)


class Turn(BaseModel):
    kind: Literal["q", "a"]
    cid: Optional[str] = None
    text: str = Field("", max_length=4000)
    follow: bool = False
    reaccion: str = Field("", max_length=1500)


class TurnReq(BaseModel):
    cid: str
    week: int = Field(8, ge=1, le=8)
    mode: Literal["quick", "deep"] = "quick"
    team: str = Field("", max_length=80)
    context: str = Field("", max_length=6000)
    focus: str = Field("", max_length=200)
    budget: Optional[list[str]] = None
    asked: list[Asked] = []
    thread: list[Turn] = []
    cross_from: Optional[str] = None
    junta: bool = False


class TTSReq(BaseModel):
    cid: str
    text: str = Field(min_length=1, max_length=1500)


# ───────────── Utilidades ─────────────

def sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def extract_json(text: str) -> Any:
    t = text.strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i : j + 1])
        except ValueError:
            return None
    return None


def field_value(text: str, key: str) -> Optional[str]:
    """Valor completo de la clave de texto `key` dentro de un JSON que todavía se está generando; None si aún no
    cerró. Decodifica los escapes igual que json.loads, para que coincida con el valor del JSON final."""
    m = re.search(r'"%s"\s*:\s*"' % re.escape(key), text)
    if not m:
        return None
    esc = False
    for j in range(m.end(), len(text)):
        ch = text[j]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            try:
                return json.loads(text[m.end() - 1 : j + 1])
            except ValueError:
                return None
    return None


def validate(kind: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise LLMError("invalid_json", "La respuesta del modelo no es un objeto JSON.")
    strs = lambda v: [str(x) for x in v if str(x).strip()] if isinstance(v, list) else []  # noqa: E731
    if kind == "open":
        q = str(data.get("pregunta", "")).strip()
        if not q:
            raise LLMError("invalid_json", "El modelo no produjo una pregunta.")
        return {"pregunta": q, "evalua": str(data.get("evalua", "")), "senales": strs(data.get("senales")),
                "trampa": str(data.get("trampa", ""))}
    r = str(data.get("reaccion", "")).strip()
    if not r:
        raise LLMError("invalid_json", "El modelo no produjo una reacción.")
    lect = data.get("lectura")
    lect = lect if lect in ("convence", "parcial", "no_convence") else "parcial"
    return {"reaccion": r, "seguimiento": str(data.get("seguimiento", "")).strip(), "lectura": lect,
            "estado": estado_de(lect), "cierre": "", "guia": "", "vacios": strs(data.get("vacios"))[:2]}


CIERRES = {
    "limite": "Cierro este punto por ahora y lo dejo en el acta como {estado}.",
    "repeticion": "No quiero dar más vueltas sobre lo mismo: dejo este punto en el acta como {estado} y paso al siguiente tema.",
}


def repeated(data: dict[str, Any], req: "TurnReq") -> Optional[tuple[str, Optional[str]]]:
    """Devuelve (pregunta_previa, cid_de_otro_personaje_o_None) que la repregunta repite, o None. Compara con el
    hilo actual y también con req.asked (toda la sesión, cualquier personaje) para detectar el contagio entre
    personajes que puede darse en una intervención cruzada."""
    seg = data.get("seguimiento", "")
    if not seg:
        return None
    prev = next((q for q in prior_questions(req) if similar(seg, q)), None)
    if prev:
        return (prev, None)
    other = next((a for a in req.asked if a.text and a.cid and a.cid != req.cid and similar(seg, a.text)), None)
    if other:
        return (other.text, other.cid)
    return None


def apply_scaffold(data: dict[str, Any], prev: str, req: "TurnReq") -> dict[str, Any]:
    guia = scaffold(prev, (t.text for t in req.thread if t.kind == "a"))
    data.update(guia, lectura="no_convence", guia="andamiaje")
    data["estado"] = estado_de(data["lectura"])
    data["vacios"] = (data["vacios"] + ["Andamiaje automático: el modelo repitió la pregunta ante la confusión del equipo."])[-3:]
    return data


def force_close(data: dict[str, Any], motivo: str) -> dict[str, Any]:
    """Cierre determinista: el hilo termina aunque el modelo no obedezca."""
    if data["lectura"] == "convence":
        data["lectura"] = "parcial"
    data["estado"] = estado_de(data["lectura"])
    data["seguimiento"], data["cierre"] = "", motivo
    data["reaccion"] = f"{data['reaccion'].rstrip()} {CIERRES[motivo].format(estado=data['estado'])}".strip()
    nota = ("Cierre automático: límite de intentos sobre la misma preocupación." if motivo == "limite"
            else "Cierre automático: el agente repitió una repregunta anterior.")
    data["vacios"] = (data["vacios"] + [nota])[-3:]
    return data


# ───────────── App ─────────────

def create_app(settings: Settings | None = None, llm: Any = None, tts: Any = "auto",
               start_background: bool = True) -> FastAPI:
    st = settings or Settings()
    store = Store(st.config_dir)
    client = llm or OllamaClient(st.ollama_url, st.keep_alive, st.num_ctx)
    engine = build_engine(st.tts_engine, store.personas, st.models_dir) if tts == "auto" else tts
    audio_cache = LRU(128)
    pull_state: dict[str, Any] = {}

    async def bootstrap() -> None:
        """Espera a Ollama, descarga los modelos que falten y precarga las voces."""
        if engine is not None:
            asyncio.get_running_loop().run_in_executor(None, engine.prefetch)
        if not st.pull_on_start:
            return
        for _ in range(150):
            try:
                await client.tags()
                break
            except LLMError:
                await asyncio.sleep(2)
        else:
            return
        for m in dict.fromkeys([st.model_quick, st.model_deep]):
            try:
                if await client.has_model(m):
                    continue
                async for ev in client.pull(m):
                    pull_state.update(model=m, status=ev.get("status", ""), completed=ev.get("completed"), total=ev.get("total"))
                pull_state.clear()
            except Exception as e:  # noqa: BLE001
                pull_state.update(model=m, status="error", error=str(e)[:200])
                log.error("Fallo al descargar %s: %s", m, e)
        if hasattr(client, "load"):
            await client.load(st.model_quick)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(bootstrap()) if start_background else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Comité Directivo EnRutaCo — agentes locales", lifespan=lifespan)
    app.state.store, app.state.engine, app.state.client = store, engine, client

    # ---- config y salud ----
    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        return store.public_config() | {
            "llm": {"quick": st.model_quick, "deep": st.model_deep},
            "tts": {"engine": engine.name if engine else "none"},
        }

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        llm_state: dict[str, Any] = {"reachable": False, "models": {}, "pull": dict(pull_state) or None}
        try:
            names = await client.tags()
            llm_state["reachable"] = True
            for k, m in (("quick", st.model_quick), ("deep", st.model_deep)):
                llm_state["models"][k] = {"name": m, "ready": m in names or (":" not in m and f"{m}:latest" in names)}
        except LLMError as e:
            llm_state["error"] = e.message
        return {"llm": llm_state, "tts": engine.status() if engine else {"engine": "none", "ready": False}}

    @app.post("/api/reload")
    async def reload() -> dict[str, str]:
        store.reload()
        if engine is not None and hasattr(engine, "profiles"):
            fresh = build_engine(st.tts_engine, store.personas, st.models_dir)
            engine.profiles = fresh.profiles  # type: ignore[union-attr]
        audio_cache._d.clear()
        return {"status": "ok"}

    # ---- turnos del LLM (SSE) ----
    async def turn_stream(kind: str, req: TurnReq) -> AsyncIterator[str]:
        try:
            if req.cid not in store.personas:
                raise LLMError("bad_request", f"Personaje desconocido: {req.cid}")
            if kind == "follow" and not any(t.kind == "a" for t in req.thread):
                raise LLMError("bad_request", "No hay respuesta del equipo a la que reaccionar.")
            notes = req.mode == "deep" or st.notes_in_quick
            messages, schema = build_messages(kind, store, req, notes=notes)
            model = st.model_for(req.mode)
            out: dict[str, Any] = {}
            keep_terms = thread_terms(req, store.personas) if (kind == "open" and req.cross_from and req.thread) else None
            dados = datos_ya_dados(t.text for t in req.thread if t.kind == "a") if kind == "follow" else None
            # Voz anticipada: en cuanto el modelo cierra el texto que se va a decir (la pregunta, o la reacción en modo
            # junta), se envía ya saneado con las mismas reglas del resultado final. La voz arranca antes de que
            # terminen las notas del docente o los vacíos, y no se corrige en voz alta. Una repregunta normal no se
            # anticipa: el servidor todavía puede reintentarla o cerrarla.
            speak_key = "pregunta" if kind == "open" else ("reaccion" if req.junta else None)

            async def generate(msgs: list[dict[str, str]]) -> AsyncIterator[str]:
                acc, stats, spoken = "", {}, speak_key is None
                async for piece in client.chat_stream(model, msgs, schema, st.temperature, st.num_predict, stats):
                    acc += piece
                    yield sse({"type": "token", "t": piece})
                    if not spoken:
                        raw = field_value(acc, speak_key)
                        if raw is not None:
                            spoken = True
                            if raw.strip():
                                early = sanitize(kind, {speak_key: raw.strip(), "vacios": []}, keep_terms, dados)[speak_key]
                                yield sse({"type": "speak", "text": early})
                if stats:
                    log.info("LLM %s %s: prefill %s tok en %ss (%s t/s) · gen %s tok (%s t/s)", model, kind,
                             stats.get("prompt_tokens"), stats.get("prefill_s"), stats.get("prefill_tps"),
                             stats.get("gen_tokens"), stats.get("gen_tps"))
                out.update(acc=acc, stats=stats,
                           data=sanitize(kind, validate(kind, extract_json(acc)), keep_terms, dados))

            async for ev in generate(messages):
                yield ev
            data = out["data"]
            if kind == "follow" and req.junta:
                # Modo junta: evaluación sin repregunta; la lectura se alinea con la reacción.
                data["seguimiento"] = ""
                data["lectura"] = coherencia_lectura(data["reaccion"], data["lectura"])
                data["estado"] = estado_de(data["lectura"])
            elif kind == "follow":
                prev = repeated(data, req)
                if prev and is_confused(last_answer(req)):
                    # El equipo no entiende y el modelo solo repite: andamiaje con plantilla, sin gastar otra llamada.
                    log.info("Andamiaje determinista para %s (confusión + repetición).", req.cid)
                    data = apply_scaffold(data, prev[0], req)
                elif prev:
                    # Un reintento con la corrección explícita; el cliente descarta lo que ya mostró.
                    log.info("Repregunta repetida de %s; se reintenta con corrección.", req.cid)
                    yield sse({"type": "retry", "reason": "repeticion"})
                    retry = [*messages, {"role": "assistant", "content": out["acc"]},
                             {"role": "user", "content": correction_message(req, data["seguimiento"], prev[1], store.personas)}]
                    async for ev in generate(retry):
                        yield ev
                    data = out["data"]
                    if repeated(data, req):
                        data = force_close(data, "repeticion")
                if data["seguimiento"] and (follow_count(req) >= MAX_FOLLOWS or concern_attempts(req) >= MAX_ATTEMPTS):
                    data = force_close(data, "limite")
            if kind == "follow":
                dur = duration_contradiction(t.text for t in req.thread if t.kind == "a")
                ya_senalada = "contradic" in data["reaccion"].lower() or any(
                    "contradic" in v.lower() for v in data["vacios"])
                if dur and not ya_senalada:
                    # El modelo obedece poco el aviso del prompt; se deja constancia igual para el docente.
                    data["vacios"] = (data["vacios"] + [f"Posible contradicción de plazos: {dur}."])[-3:]
            yield sse({"type": "done", "data": data, "model": model, "stats": out["stats"], "notes": notes})
        except LLMError as e:
            yield sse({"type": "error", "code": e.code, "message": e.message})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Error inesperado en el turno")
            yield sse({"type": "error", "code": "server_error", "message": str(e)[:200]})

    def sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
        return StreamingResponse(gen, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/ask")
    async def ask(req: TurnReq) -> StreamingResponse:
        return sse_response(turn_stream("open", req))

    @app.post("/api/follow")
    async def follow(req: TurnReq) -> StreamingResponse:
        return sse_response(turn_stream("follow", req))

    @app.post("/api/warmup")
    async def warmup(req: TurnReq) -> dict[str, Any]:
        """Carga el modelo del modo pedido y deja en la caché de prefijo el prompt exacto de la próxima pregunta.

        La interfaz lo llama al abrir la junta: mientras el equipo expone (15 min) el modelo queda listo y la primera
        pregunta no paga el arranque en frío. Mismo prompt que /api/ask con la misma petición."""
        if req.cid not in store.personas:
            raise HTTPException(404, "Personaje desconocido.")
        notes = req.mode == "deep" or st.notes_in_quick
        messages, schema = build_messages("open", store, req, notes=notes)
        model = st.model_for(req.mode)
        if not hasattr(client, "prime"):
            return {"status": "skipped", "model": model}
        try:
            stats = await client.prime(model, messages, schema)
        except LLMError as e:
            raise HTTPException(503, e.message) from e
        log.info("Precalentamiento %s para %s: carga %ss · prefill %s tok en %ss", model, req.cid,
                 stats.get("load_s"), stats.get("prompt_tokens"), stats.get("prefill_s"))
        return {"status": "ok", "model": model, "stats": stats}

    # ---- voz ----
    async def synth(cid: str, text: str) -> bytes:
        if engine is None:
            raise HTTPException(503, "TTS desactivado (TTS_ENGINE=none).")
        if cid not in store.personas or cid not in getattr(engine, "profiles", {}):
            raise HTTPException(404, f"Sin perfil de voz para {cid}.")
        key = hashlib.sha1(f"{engine.name}|{cid}|{json.dumps(engine.profiles[cid], sort_keys=True)}|{text}".encode()).hexdigest()
        hit = audio_cache.get(key)
        if hit is not None:
            return hit
        try:
            wav = await asyncio.get_running_loop().run_in_executor(None, engine.synth, cid, text)
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo de TTS")
            raise HTTPException(503, f"No se pudo sintetizar la voz: {str(e)[:200]}") from e
        audio_cache.put(key, wav)
        return wav

    @app.post("/api/tts")
    async def tts_endpoint(req: TTSReq) -> Response:
        return Response(await synth(req.cid, req.text), media_type="audio/wav")

    @app.get("/api/tts/sample/{cid}")
    async def tts_sample(cid: str) -> Response:
        if cid not in store.personas:
            raise HTTPException(404, "Personaje desconocido.")
        return Response(await synth(cid, store.personas[cid]["ancla"]), media_type="audio/wav")

    @app.get("/api/voices")
    async def voices() -> dict[str, Any]:
        return {"engine": engine.name if engine else "none",
                "profiles": {cid: (engine.profiles.get(cid) if engine else None) for cid in store.personas},
                "models": engine.voices_info() if engine else {}}

    # ---- interfaz web (al final para no tapar /api) ----
    if st.web_dir.exists():
        app.mount("/", StaticFiles(directory=st.web_dir, html=True), name="web")
    return app

