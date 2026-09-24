import json
import wave
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, Store
from app.llm import LLMError
from app.main import create_app
from app.prompts import (MAX_FOLLOWS, budget_info, budget_text, build_messages, build_system, catalog_text,
                         concern_attempts, fmt, is_confused, similar)
from app.tts.common import normalize_es, pcm_to_wav
from app.tts.piper_engine import hf_files, resolve_speaker, PiperEngine

ROOT = Path(__file__).resolve().parents[1]
STORE = Store(ROOT / "config")


class FakeLLM:
    """Simula Ollama: devuelve JSON en trozos y registra los mensajes recibidos."""
    def __init__(self, payload=None, fail=None):
        self.calls, self.payload, self.fail = [], payload, fail

    async def tags(self):
        return ["qwen2.5:3b-instruct", "qwen2.5:7b-instruct"]

    async def has_model(self, n):
        return True

    async def chat_stream(self, model, messages, schema, temperature, num_predict, stats=None):
        self.calls.append({"model": model, "messages": messages, "schema": schema})
        if self.fail:
            raise LLMError(self.fail, "falla simulada")
        if stats is not None:
            stats.update({"prompt_tokens": 100, "prefill_s": 1.0, "gen_tps": 12.5})
        follow = "reaccion" in schema["properties"]
        # payload: dict fijo, o lista de dicts consumida en orden (una por llamada al modelo).
        pay = self.payload.pop(0) if isinstance(self.payload, list) else self.payload
        data = pay or (
            {"reaccion": "Entiendo, pero falta el supuesto.", "seguimiento": "¿Quién audita el supuesto?", "lectura": "parcial", "vacios": ["sin fuente", "sin sensibilidad", "extra"]}
            if follow else
            {"pregunta": "¿Por qué excluyen E2 si hay 3 contratos en evaluación?", "evalua": "Justificación de exclusiones", "senales": ["cita riesgo si NO"], "trampa": "decir que es prescindible"}
        )
        txt = json.dumps(data, ensure_ascii=False)
        for i in range(0, len(txt), 25):
            yield txt[i:i + 25]


class FakeTTS:
    name = "fake"
    def __init__(self):
        self.profiles = {cid: {"voice": "x", "pitch": 1.0} for cid in STORE.personas}
        self.calls = 0
    def prefetch(self): pass
    def status(self): return {"engine": "fake", "ready": True}
    def voices_info(self): return {}
    def synth(self, cid, text):
        self.calls += 1
        return pcm_to_wav(b"\x00\x00" * 2205, 22050)


def make_client(llm=None, tts=None, web=False, tmp_path=None):
    env = {"CONFIG_DIR": str(ROOT / "config"), "WEB_DIR": str(ROOT / "web" if web else "/nonexistent")}
    app = create_app(Settings(env), llm=llm or FakeLLM(), tts=tts or FakeTTS(), start_background=False)
    return TestClient(app)


def read_sse(resp):
    return [json.loads(l[6:]) for l in resp.iter_lines() if l.startswith("data: ")]


def body(cid="cfo", **kw):
    b = {"cid": cid, "week": 8, "mode": "quick", "team": "Equipo Andes", "asked": [], "thread": []}
    b.update(kw)
    return b


# ───────────── Presupuesto y prompts ─────────────

def test_totales_del_catalogo():
    txt = catalog_text(STORE.caso)
    assert "obligatorios 2.150" in txt and "estratégicos 1.875" in txt and "habilitadores 475" in txt and "4.500" in txt


def test_seleccion_ejemplo_del_caso_no_supera_techo():
    # La «trampa pedagógica» del documento afirma 4.040; la suma real es 3.815.
    sel = ["O1", "O2", "O3", "O4", "O5", "H1", "H2", "E1", "E3", "E4", "E5", "E7"]
    assert budget_info(STORE.caso, sel)["total"] == 3815
    assert budget_info(STORE.caso, sel + ["H3", "H4"])["total"] == 4020


def test_obligatorios_siempre_incluidos_y_alertas():
    b = budget_info(STORE.caso, [])
    assert b["total"] == 2150 and b["nivel"] == "ok"
    assert any("mínimo es 2" in a for a in b["avisos"]) and any("H1 excluido" in a for a in b["avisos"])
    b2 = budget_info(STORE.caso, [c["c"] for c in STORE.caso["catalogo"]])
    assert b2["total"] == 4500 and b2["nivel"] == "warn"
    assert "300" in b2["estado"]


def test_gating_por_semana():
    p = STORE.personas["cfo"]
    s2 = build_system(STORE.caso, p, 2)
    assert "20 aplicaciones" in s2
    assert "4.200" not in s2 and "CATÁLOGO" not in s2 and "35% de las rutas" not in s2
    s5 = build_system(STORE.caso, p, 5)
    assert "CATÁLOGO DE INVERSIONES OFICIAL" in s5 and "18.700" in s5 and "22% trimestral" in s5
    assert "KMS formal: ninguno" not in s5          # semana 6
    s8 = build_system(STORE.caso, p, 8)
    assert "KMS formal: ninguno" in s8 and "Power BI" in s8


def test_gating_de_personaje_y_criterios():
    """Antes de su semana de debut, un personaje no conoce su ancla ni su tema; los criterios de rigor también se gatean."""
    cfo = STORE.personas["cfo"]
    for w in (1, 2, 3, 4):
        t = build_system(STORE.caso, cfo, w)
        assert "4.200" not in t and "catálogo" not in t.lower() and "Todavía no es tu tema" in t
    assert "4.200" in build_system(STORE.caso, cfo, 5)
    ops = STORE.personas["ops"]
    assert "onboarding" not in build_system(STORE.caso, ops, 5) and "onboarding" in build_system(STORE.caso, ops, 6)
    ceo = STORE.personas["ceo"]
    assert "5 KPIs críticos" not in build_system(STORE.caso, ceo, 6) and "5 KPIs críticos" in build_system(STORE.caso, ceo, 7)
    s1 = build_system(STORE.caso, ceo, 1)
    assert "91%" not in s1 and "insustituible" not in s1 and "OTIF de 87%" in s1
    assert "91%" in build_system(STORE.caso, ceo, 3)


def test_personalidad_y_rigor_en_prompt():
    s = build_system(STORE.caso, STORE.personas["cfo"], 8)
    assert "El guardián de los recursos" in s and "conservador" in s and "insustituible" in s
    assert "no se pueden asumir auditables" in s and "DINÁMICA DEL COMITÉ" in s


def test_prompt_open_con_presupuesto_y_contexto():
    req = SimpleNamespace(cid="cfo", week=8, team="X", context="Excluye E2", focus="exclusiones", budget=["H1"],
                          asked=[SimpleNamespace(cid="ceo", text="¿Qué decisión cambia el lunes?")], thread=[], cross_from=None)
    msgs, schema = build_messages("open", STORE, req)
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    u = msgs[1]["content"]
    assert "Excluye E2" in u and "Total de la selección: 2.270 M COP" in u and "exclusiones" in u
    assert "Carlos: ¿Qué decisión cambia el lunes?" in u
    assert list(schema["properties"])[0] == "pregunta"


def _q(text, cid="ti", follow=True, reaccion=""):
    return SimpleNamespace(kind="q", cid=cid, text=text, follow=follow, reaccion=reaccion)


def _a(text):
    return SimpleNamespace(kind="a", cid=None, text=text, follow=False, reaccion="")


def _req(thread, cid="ti", week=8):
    return SimpleNamespace(cid=cid, week=week, team="", context="", focus="", budget=None, asked=[], thread=thread,
                           cross_from=None)


LOOP_Q = "¿Cómo podríamos definir los planes de implementación sin afectar la eficiencia operacional actual?"


def test_prompt_follow_reglas_de_anclaje_concrecion_y_rol_critico():
    thread = [_q("P1", cid="cfo", follow=False), _a("R1"), _q("P2", cid="cfo", reaccion="ok"), _a("R2"),
              _q("P3", cid="cfo", reaccion="mm"), _a("R3")]
    msgs, schema = build_messages("follow", STORE, _req(thread, cid="cfo", week=5))
    u = msgs[1]["content"]
    assert "Equipo: R3" in u and "Ricardo (repregunta): mm P3" in u
    assert "Anclaje obligatorio" in u and "métrica, umbral, herramienta, dueño, cadencia e indicador" in u
    assert "Si dos cifras no cuadran" in u and "responde a parte de mi preocupación" in u  # prohibida explícitamente
    assert "ANDAMIAJE" not in u and "CIERRE OBLIGATORIO:" not in u
    assert list(schema["properties"])[:2] == ["reaccion", "seguimiento"]


def test_sistema_fija_registro_y_rol_evaluador():
    s = build_system(STORE.caso, STORE.personas["ti"], 8)
    assert "nunca en portugués" in s and "«ustedes»" in s and "no te incluyas en el equipo consultor" in s


def test_detecta_confusion_y_similitud():
    assert is_confused("No entiendo, ¿qué sugieres?") and is_confused("¿Podría reformular la pregunta?")
    assert not is_confused("Con un control plane sobre AWS.")
    assert similar(LOOP_Q, "¿Cómo podríamos definir los planes de implementación sin afectar la eficiencia operacional?")
    assert not similar(LOOP_Q, "¿Cuáles políticas específicamente, en capacidad y en costos, sostienen esa escalabilidad?")


def test_prompt_andamiaje_ante_no_entiendo():
    thread = [_q("P1", follow=False), _a("R1"), _q(LOOP_Q), _a("No entiendo, ¿qué sugieres?")]
    u = build_messages("follow", STORE, _req(thread))[0][1]["content"]
    assert "ANDAMIAJE" in u and "NO la repitas" in u


def test_prompt_reformula_tras_dos_intentos_y_cierra_tras_tres():
    t2 = [_q("P1", follow=False), _a("R1"), _q(LOOP_Q), _a("R2"), _q(LOOP_Q), _a("R3")]
    assert concern_attempts(_req(t2)) == 2
    u2 = build_messages("follow", STORE, _req(t2))[0][1]["content"]
    assert "REFORMULACIÓN" in u2 and "CIERRE OBLIGATORIO:" not in u2
    t3 = t2 + [_q(LOOP_Q), _a("R4")]
    u3 = build_messages("follow", STORE, _req(t3))[0][1]["content"]
    assert concern_attempts(_req(t3)) == 3 and "CIERRE OBLIGATORIO:" in u3


def test_prompt_cierra_al_tope_de_repreguntas():
    thread = [_q("P0", follow=False), _a("R0")]
    for i in range(MAX_FOLLOWS):
        thread += [_q(f"Pregunta distinta número {i} sobre tema {i * 7}"), _a(f"R{i}")]
    u = build_messages("follow", STORE, _req(thread))[0][1]["content"]
    assert "CIERRE OBLIGATORIO:" in u


def test_intervencion_cruzada_usa_conflicto_natural():
    thread = [SimpleNamespace(kind="q", cid="ceo", text="P", follow=False, reaccion=""),
              SimpleNamespace(kind="a", cid=None, text="R", follow=False, reaccion="")]
    req = SimpleNamespace(cid="ti", week=8, team="", context="", focus="", budget=None, asked=[], thread=thread, cross_from="ceo")
    u = build_messages("open", STORE, req)[0][1]["content"]
    assert "tensión natural con Carlos" in u and "sí, pero" in u


def test_rivales_validos_y_voces_completas():
    for cid, p in STORE.personas.items():
        assert p["rivales"] and cid not in p["rivales"]
        assert p["voz"]["piper"]["voice"] and p["voz"]["xtts"]["speaker"]
    assert set(STORE.orden) == set(STORE.personas)


# ───────────── API ─────────────

def test_config_no_expone_prompts():
    c = make_client().get("/api/config").json()
    assert c["personas"]["cfo"]["arquetipo"] == "El guardián de los recursos"
    assert "angulos" not in c["personas"]["cfo"] and "trampas" not in c["personas"]["cfo"]
    assert len(c["catalogo"]) == 16 and c["tts"]["engine"] == "fake"


def test_ask_stream_y_done():
    llm = FakeLLM()
    cl = make_client(llm)
    with cl.stream("POST", "/api/ask", json=body(context="x")) as r:
        ev = read_sse(r)
    assert ev[0]["type"] == "token" and ev[-1]["type"] == "done"
    assert "".join(e["t"] for e in ev if e["type"] == "token").startswith('{"pregunta"')
    assert ev[-1]["data"]["pregunta"].startswith("¿Por qué excluyen E2")
    assert llm.calls[0]["model"] == "qwen2.5:3b-instruct"


def test_modo_profundo_usa_modelo_grande():
    llm = FakeLLM()
    with make_client(llm).stream("POST", "/api/ask", json=body(mode="deep")) as r:
        read_sse(r)
    assert llm.calls[0]["model"] == "qwen2.5:7b-instruct"


def test_follow_normaliza_y_limita_vacios():
    thread = [{"kind": "q", "cid": "cfo", "text": "P"}, {"kind": "a", "text": "R"}]
    with make_client().stream("POST", "/api/follow", json=body(thread=thread)) as r:
        ev = read_sse(r)
    d = ev[-1]["data"]
    assert d["lectura"] == "parcial" and len(d["vacios"]) == 2 and d["seguimiento"].startswith("¿Quién")


def _thread_json(n_loops=1, last="No entiendo, ¿qué sugieres?"):
    t = [{"kind": "q", "cid": "ti", "text": "P inicial"}, {"kind": "a", "text": "R inicial"}]
    for i in range(n_loops):
        t += [{"kind": "q", "cid": "ti", "text": LOOP_Q, "follow": True}, {"kind": "a", "text": last if i == n_loops - 1 else "R"}]
    return t


def test_follow_repetido_reintenta_con_correccion_y_acepta_la_nueva():
    rep = {"reaccion": "Responde a parte de mi preocupación.", "seguimiento": LOOP_Q, "lectura": "no_convence", "vacios": []}
    ok = {"reaccion": "Me refiero a herramienta, dueño y cadencia.", "seguimiento": "¿Qué herramienta ejecuta la política?",
          "lectura": "parcial", "vacios": []}
    llm = FakeLLM(payload=[rep, ok])
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ti", thread=_thread_json())) as r:
        ev = read_sse(r)
    assert [e["type"] for e in ev].count("retry") == 1 and len(llm.calls) == 2
    corr = llm.calls[1]["messages"][-1]["content"]
    assert corr.startswith("CORRECCIÓN OBLIGATORIA") and "no entiende" in corr
    d = ev[-1]["data"]
    assert d["seguimiento"] == "¿Qué herramienta ejecuta la política?" and d["cierre"] == "" and d["estado"] == "parcial"


def test_follow_repetido_dos_veces_se_cierra_sin_bucle():
    rep = {"reaccion": "Responde a parte de mi preocupación.", "seguimiento": LOOP_Q, "lectura": "no_convence", "vacios": []}
    llm = FakeLLM(payload=[dict(rep), dict(rep)])
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ti", thread=_thread_json(last="Con control plane."))) as r:
        d = read_sse(r)[-1]["data"]
    assert d["seguimiento"] == "" and d["cierre"] == "repeticion" and d["estado"] == "abierta"
    assert "acta" in d["reaccion"] and len(llm.calls) == 2


def test_follow_tras_tres_intentos_cierre_forzado_aunque_el_modelo_desobedezca():
    nueva = {"reaccion": "Sigo sin verlo.", "seguimiento": "¿Quién aprueba el cambio de umbral en producción?",
             "lectura": "no_convence", "vacios": []}
    llm = FakeLLM(payload=[nueva])
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ti", thread=_thread_json(n_loops=3, last="R"))) as r:
        d = read_sse(r)[-1]["data"]
    assert d["seguimiento"] == "" and d["cierre"] == "limite" and len(llm.calls) == 1


def test_follow_sin_respuesta_es_error():
    with make_client().stream("POST", "/api/follow", json=body(thread=[{"kind": "q", "cid": "cfo", "text": "P"}])) as r:
        ev = read_sse(r)
    assert ev[-1] == {"type": "error", "code": "bad_request", "message": "No hay respuesta del equipo a la que reaccionar."}


def test_errores_del_llm_llegan_como_evento():
    with make_client(FakeLLM(fail="llm_unreachable")).stream("POST", "/api/ask", json=body()) as r:
        ev = read_sse(r)
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "llm_unreachable"


def test_json_invalido_del_modelo():
    with make_client(FakeLLM(payload={"otra": "cosa"})).stream("POST", "/api/ask", json=body()) as r:
        ev = read_sse(r)
    assert ev[-1]["code"] == "invalid_json"


def test_personaje_desconocido_y_semana_invalida():
    cl = make_client()
    with cl.stream("POST", "/api/ask", json=body(cid="zzz")) as r:
        assert read_sse(r)[-1]["code"] == "bad_request"
    assert cl.post("/api/ask", json=body(week=9)).status_code == 422


def test_health():
    h = make_client().get("/api/health").json()
    assert h["llm"]["reachable"] and h["llm"]["models"]["deep"]["ready"] and h["tts"]["ready"]


def test_tts_cache_y_errores():
    tts = FakeTTS()
    cl = make_client(tts=tts)
    r1 = cl.post("/api/tts", json={"cid": "ceo", "text": "Hola"})
    r2 = cl.post("/api/tts", json={"cid": "ceo", "text": "Hola"})
    assert r1.status_code == 200 and r1.headers["content-type"] == "audio/wav" and r1.content[:4] == b"RIFF"
    assert tts.calls == 1 and r1.content == r2.content
    assert cl.post("/api/tts", json={"cid": "nadie", "text": "Hola"}).status_code == 404
    assert cl.get("/api/tts/sample/cfo").status_code == 200


def test_tts_desactivado():
    app = create_app(Settings({"CONFIG_DIR": str(ROOT / "config"), "WEB_DIR": "/nonexistent"}), llm=FakeLLM(), tts=None, start_background=False)
    assert TestClient(app).post("/api/tts", json={"cid": "ceo", "text": "Hola"}).status_code == 503


def test_reload():
    assert make_client().post("/api/reload").json() == {"status": "ok"}


def test_estaticos_no_tapan_api():
    cl = make_client(web=True)
    assert cl.get("/api/config").status_code == 200
    assert cl.get("/").status_code == 200


# ───────────── TTS ─────────────

def test_normalizador_es():
    assert normalize_es("El presupuesto es $4.200M COP.") == "El presupuesto es 4200 millones de pesos."
    assert "18700 pesos" in normalize_es("Cuesta $18.700 COP por envío.")
    assert "980 millones de pesos" in normalize_es("O1 (980 M COP)")
    assert normalize_es("Churn de 8% y +40%") == "chern de 8 por ciento y más 40 por ciento"
    assert normalize_es("El TMS y el ERP") == "El T M S y el E R P"
    assert "bi tu bi" in normalize_es("modelo B2B") and "O uno" in normalize_es("incluye O1")
    assert "1200 empleados" in normalize_es("1.200 empleados")
    assert normalize_es("La API y el API Gateway") == "La api y el api gueitwei"


def test_hf_files():
    assert hf_files("es_ES-davefx-medium") == ("es/es_ES/davefx/medium/es_ES-davefx-medium.onnx", "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json")
    assert hf_files("es_ES-carlfm-x_low")[0] == "es/es_ES/carlfm/x_low/es_ES-carlfm-x_low.onnx"
    assert hf_files("es_MX-claude-high")[0] == "es/es_MX/claude/high/es_MX-claude-high.onnx"


def test_resolve_speaker():
    assert resolve_speaker({}, 0, "F") is None
    m = {"F_1": 0, "M_1": 1}
    assert resolve_speaker(m, 0, "F") == 0 and resolve_speaker(m, 0, "M") == 1
    assert resolve_speaker(m, 0, 1) == 1 and resolve_speaker(m, 0, None) == 0
    assert resolve_speaker({"mujer": 3, "hombre": 5}, 0, "hombre") == 5


def test_piper_pitch_y_pausas(monkeypatch):
    """Sin descargar modelos: simula PiperVoice y verifica tasa de muestreo (tono) y pausas."""
    import numpy as np

    class Chunk:
        sample_rate = 22050
        def __init__(self, n): self.audio_int16_bytes = (np.ones(n, dtype=np.int16) * 1000).tobytes()

    class FakeVoice:
        config = SimpleNamespace(sample_rate=22050, speaker_id_map={"F_1": 0, "M_1": 1}, default_speaker_id=0)
        def __init__(self): self.last = None
        def synthesize(self, text, syn_config=None):
            self.last = (text, syn_config)
            return [Chunk(22050), Chunk(11025)]

    eng = PiperEngine({"dn": {"voz": {"piper": {"voice": "es_ES-sharvard-medium", "speaker": "M", "pitch": 1.1, "length_scale": 0.9,
                                                   "noise_scale": 0.8, "noise_w": 0.9, "pausa": 0.5}}}}, Path("/tmp"))
    fv = FakeVoice()
    eng._voices["es_ES-sharvard-medium"] = fv
    wav = eng.synth("dn", "El TMS cuesta $420M COP")
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == round(22050 * 1.1)
        frames = w.getnframes()
    assert frames == 22050 + 11025 + int(round(22050 * 1.1) * 0.5)
    text, cfg = fv.last
    assert text == "El T M S cuesta 420 millones de pesos"
    assert cfg.speaker_id == 1 and abs(cfg.length_scale - 0.99) < 1e-9 and cfg.noise_w_scale == 0.9
    assert eng.status()["ready"] is False or eng.status()["loaded"] == ["es_ES-sharvard-medium"]


# ───────────── Rendimiento en CPU ─────────────

def test_prefijo_compartido_entre_personajes():
    """Para la caché de prefijo de Ollama: la mayor parte del prompt de sistema es idéntica entre personajes."""
    import os
    a = build_system(STORE.caso, STORE.personas["cfo"], 8)
    b = build_system(STORE.caso, STORE.personas["ops"], 8)
    assert len(os.path.commonprefix([a, b])) / len(a) > 0.75


def test_notas_solo_en_modo_profundo_por_defecto():
    llm = FakeLLM()
    cl = make_client(llm)
    with cl.stream("POST", "/api/ask", json=body(mode="quick")) as r:
        ev = read_sse(r)
    assert list(llm.calls[0]["schema"]["properties"]) == ["pregunta"] and ev[-1]["notes"] is False
    with cl.stream("POST", "/api/ask", json=body(mode="deep")) as r:
        ev = read_sse(r)
    assert "trampa" in llm.calls[1]["schema"]["properties"] and ev[-1]["notes"] is True
    assert ev[-1]["stats"]["gen_tps"] == 12.5


def test_resumen_de_presupuesto_es_compacto():
    sel = ["O1", "H1", "E1"]
    txt = budget_text(STORE.caso, sel)
    assert "ERP Cloud" not in txt            # el nombre completo ya está en el catálogo del sistema
    assert "E2 (290 M; riesgo si NO: Medio: pérdida B2B)" in txt and len(txt) < 1400


def test_summarize_stats():
    from app.llm import summarize_stats
    s = summarize_stats({"prompt_eval_count": 2000, "prompt_eval_duration": 10_000_000_000, "eval_count": 100,
                         "eval_duration": 8_000_000_000, "load_duration": 2_000_000_000, "total_duration": 21_000_000_000})
    assert s["prefill_tps"] == 200.0 and s["gen_tps"] == 12.5 and s["load_s"] == 2.0 and s["total_s"] == 21.0
