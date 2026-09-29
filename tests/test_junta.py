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


def test_api_junta_respuesta_evasiva_reaccion_determinista():
    llm = FakeLLM(payload={"reaccion": "John respaldó que garantizarían un SLA continuo con el KMS.", "lectura": "convence", "vacios": []})
    thread = [{"kind": "q", "cid": "ceo", "text": "¿Qué decisión piden aprobar?"}, {"kind": "a", "text": "John Chávez: no se dime tu"}]
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="ceo", thread=thread, junta=True)) as r:
        d = read_sse(r)[-1]["data"]
    assert d["lectura"] == "no_convence" and "No recibí una respuesta" in d["reaccion"] and "KMS" not in d["reaccion"]


def test_api_junta_quita_exceso_de_techo_falso():
    llm = FakeLLM(payload={"reaccion": "El ROI al año 3 es −7,8 %. Falta justificar el exceso del techo base.", "lectura": "parcial", "vacios": ["Faltan supuestos para justificar el exceso del techo base."]})
    thread = [{"kind": "q", "cid": "cfo", "text": "¿Cuál es el ROI?"}, {"kind": "a", "text": "Ana: ROI −7,8 % al año 3 y payback en el año 4 con 3 % de ahorro."}]
    with make_client(llm).stream("POST", "/api/follow", json=body(cid="cfo", thread=thread, junta=True, budget=["E2"])) as r:
        d = read_sse(r)[-1]["data"]
    assert "exceso" not in d["reaccion"] and "−7,8 %" in d["reaccion"] and not any("exceso del techo" in v for v in d["vacios"])


def test_similar_junta_detecta_marco_copiado_y_respeta_preguntas_distintas():
    from app.prompts import similar_junta
    a = ("¿Cómo garantizan que la adopción progresiva de ERP, CRM y CDP en los años 1 y 2 del roadmap no afecte el ROI "
         "y el payback, manteniendo el techo presupuestal y la escalabilidad del TMS y la app móvil?")
    b = ("¿Cómo garantizan que la adopción progresiva de ERP, CRM y CDP en los años 1 y 2 del roadmap no altere la "
         "estructura de datos críticos como OTIF, SLA, manteniendo la escalabilidad del TMS y la app móvil?")
    assert similar_junta(a, b)
    assert not similar_junta("¿Cuál es el modelo de ROI para el año 3?",
                             "¿Qué modelo de negocio B2B2C se habilita en 12 a 18 meses?")


def test_asked_block_en_junta_no_muestra_textos_previos():
    from types import SimpleNamespace as NS
    from app.prompts import asked_block
    personas = {"ti": {"corto": "Andrés", "cargo": "Director de TI"}}
    req = NS(junta=True, asked=[NS(cid="ti", text="¿Cómo garantizan la adopción progresiva de ERP?")])
    out = asked_block(req, personas)
    assert "Andrés (Director de TI)" in out and "adopción progresiva" not in out


def test_reaccion_coherente_quita_elogio_cuando_el_tope_baja_la_lectura():
    from app.guard import reaccion_coherente
    r = reaccion_coherente("Convenció con datos concretos sobre el modelo B2B2C y su implementación progresiva, "
                           "mencionando el uso de APIs y el Data Warehouse como herramientas clave.", "no_convence")
    assert "Convenció" not in r and r.endswith("así no me convence.")
    r2 = reaccion_coherente("Ustedes proponen APIs para aliados. Sin embargo, no dan plazos.", "parcial")
    assert r2.startswith("Ustedes proponen APIs") and "Sin embargo" in r2 and r2.endswith("solo a medias.")
