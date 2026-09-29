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


def test_api_junta_deja_nota_de_plazos_contradictorios():
    # En modo junta tampoco hay repregunta: la contradicción de plazos queda anotada para el docente.
    llm = FakeLLM(payload={"reaccion": "Registro el plan de migración.", "lectura": "parcial", "vacios": []})
    thread = [{"kind": "q", "cid": "ti", "text": "¿En cuánto tiempo migran el AS/400?"},
              {"kind": "a", "text": "Migramos 120.000 registros en 3 fases de 2 meses; la limpieza se hace en un fin de semana."}]
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ti", thread=thread, junta=True)) as r:
        d = read_sse(r)[-1]["data"]
    assert d["seguimiento"] == "" and any("contradicción de plazos" in v for v in d["vacios"])


def test_tope_de_lectura_para_respuestas_genericas():
    from app.guard import lectura_por_respuesta, fix_register
    john = ("John Chávez: al haber una adopción progresiva se va a mejorar los indicadores como el churn y los ANS, "
            "mejor calidad de entrega y por ende más velocidad, mejor servicio, clientes felices, logramos objetivos")
    assert lectura_por_respuesta(john, "convence")[0] == "no_convence"
    buena = "Ana: la Directora de Operaciones es la dueña; revisión semanal en el tablero de BI; OTIF de 96 % al año 3."
    assert lectura_por_respuesta(buena, "convence") == ("convence", "")
    assert fix_register("Esperamos reducirlo y establecemos compuertas.") == "Esperan reducirlo y establecen compuertas."


def test_api_junta_pregunta_repetida_de_otro_miembro_se_reintenta():
    q = "¿Cómo afectará la implementación progresiva de ERP, CRM y KMS a las alertas y trazabilidad del paquete?"
    llm = FakeLLM(payload=[{"pregunta": q}, {"pregunta": "¿Cuál es el payback de la ola 1 con sus supuestos de ahorro?"}])
    asked = [{"cid": "cs", "text": q}]
    with make_client(llm).stream("POST", "/api/ask", json=body(cid="cfo", junta=True, asked=asked, focus="ROI")) as r:
        ev = read_sse(r)
    assert any(e["type"] == "retry" for e in ev) and "payback" in ev[-1]["data"]["pregunta"]
    assert "CORRECCIÓN OBLIGATORIA" in llm.calls[1]["messages"][-1]["content"]


def test_tope_ignora_cifras_debiles():
    from app.guard import lectura_por_respuesta
    r = ("John Chávez: haciéndole seguimiento y control permanente de los sistemas verificando las integraciones y "
         "siguiendo el plan de trabajo y la inversión en los próximos 4 años eso garantizará los acuerdos de servicio")
    assert lectura_por_respuesta(r, "convence")[0] == "no_convence"
