"""Modo junta: evaluación sin repregunta, rúbrica por contenido y coherencia entre reacción y lectura."""
from types import SimpleNamespace

from app.guard import coherencia_lectura
from app.prompts import SCHEMA_JUNTA, build_messages
from test_backend import STORE, FakeLLM, body, make_client, read_sse

REAL = ("El grupo mencionó gobierno de datos con dueño de los datos en cada sistema. Esto me ayuda a entender mejor "
        "cómo garantizaré la visión centralizada sin incrementar complejidad operacional.")


def _req(junta=True):
    thread = [SimpleNamespace(kind="q", cid="ops", text="¿Quién es dueño del dato?", follow=False, reaccion=""),
              SimpleNamespace(kind="a", cid=None, text="Cada sistema tendrá un dueño de datos con gobierno de datos.",
                              follow=False, reaccion="")]
    return SimpleNamespace(cid="ops", week=8, team="", context="", focus="", budget=None, asked=[], thread=thread,
                           cross_from=None, junta=junta)


def test_prompt_junta_usa_rubrica_y_esquema_sin_repregunta():
    msgs, schema = build_messages("follow", STORE, _req())
    u = msgs[1]["content"]
    assert schema is SCHEMA_JUNTA and "seguimiento" not in schema["properties"]
    assert "JUNTA" in u and "SOLO por el contenido" in u and "no te incluyas en su plan" in u
    assert "REGLAS DE LA REPREGUNTA" not in u


def test_prompt_sin_junta_sigue_igual():
    _, schema = build_messages("follow", STORE, _req(junta=False))
    assert "seguimiento" in schema["properties"]


def test_coherencia_caso_real_y_casos_limite():
    assert coherencia_lectura(REAL, "no_convence") == "parcial"
    assert coherencia_lectura("No responden quién es el dueño; falta el plazo.", "convence") == "parcial"
    assert coherencia_lectura("No responden quién es el dueño.", "no_convence") == "no_convence"
    assert coherencia_lectura("Queda claro: dueño, plazo y costo concretos.", "convence") == "convence"


def test_api_junta_corrige_lectura_y_no_repregunta():
    llm = FakeLLM(payload={"reaccion": REAL, "seguimiento": "¿Algo más?", "lectura": "no_convence", "vacios": []})
    thread = [{"kind": "q", "cid": "ops", "text": "¿Quién es dueño del dato?"},
              {"kind": "a", "text": "Cada sistema tendrá un dueño de datos."}]
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ops", thread=thread, junta=True)) as r:
        d = read_sse(r)[-1]["data"]
    assert d["seguimiento"] == "" and d["lectura"] == "parcial" and d["estado"] == "parcial"
    assert "garantizarán" in d["reaccion"] or "garantizaré" not in d["reaccion"]
    assert llm.calls[0]["schema"] is SCHEMA_JUNTA
