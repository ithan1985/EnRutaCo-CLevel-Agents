"""Voz anticipada: el servidor envía el texto que se va a decir, ya saneado, en cuanto el modelo lo cierra."""
from app.main import field_value
from test_backend import FakeLLM, body, make_client, read_sse


def _eventos(llm, path, **kw):
    with make_client(llm).stream("POST", path, json=body(**kw)) as r:
        return read_sse(r)


def test_field_value_decodifica_como_json_y_espera_el_cierre():
    assert field_value('{"pregunta": "¿Dijo \\"sí\\" y \\\\ no?", "evalua": "x', "pregunta") == '¿Dijo "sí" y \\ no?'
    assert field_value('{"pregunta": "¿Todavía sin cerrar', "pregunta") is None
    assert field_value('{"reaccion":"Bien.\\nOk\\u00e1","lectura":"p"}', "reaccion") == "Bien.\nOká"
    assert field_value('{"otra": "x"}', "reaccion") is None


def test_pregunta_se_anuncia_saneada_antes_de_las_notas():
    llm = FakeLLM(payload={"pregunta": "¿Cómo podríamos garantizar el SLA del 98 %? Lo digo por el retailer.",
                           "evalua": "Plan concreto para el SLA con dueño y fecha", "senales": ["dueño", "fecha", "costo"],
                           "trampa": "Responder con buenas prácticas genéricas sin cifras"})
    ev = _eventos(llm, "/api/ask", cid="cs", mode="deep")
    tipos = [e["type"] for e in ev]
    i = tipos.index("speak")
    assert ev[i]["text"] == ev[-1]["data"]["pregunta"] == "¿Cómo podrían garantizar el SLA del 98 %?"
    assert "token" in tipos[i + 1:], "la voz debe salir antes de que terminen las notas del docente"


def test_reaccion_de_junta_se_anuncia_igual_al_texto_final():
    llm = FakeLLM(payload={"reaccion": "Registro el dueño del dato. Esto me ayuda a ver cómo garantizaré la trazabilidad. "
                                       "¿Y el costo?", "lectura": "parcial", "vacios": ["Falta el costo por ola"]})
    thread = [{"kind": "q", "cid": "ops", "text": "¿Quién es dueño del dato?"}, {"kind": "a", "text": "La Directora de Operaciones, con revisión semanal y meta del 80 %."}]
    ev = _eventos(llm, "/api/follow", cid="ops", thread=thread, junta=True)
    speak = [e for e in ev if e["type"] == "speak"]
    assert len(speak) == 1 and speak[0]["text"] == ev[-1]["data"]["reaccion"]
    assert "garantizarán" in speak[0]["text"] and "?" not in speak[0]["text"]


def test_reaccion_de_junta_con_tope_no_se_anticipa_y_queda_coherente():
    llm = FakeLLM(payload={"reaccion": "Convenció con datos concretos sobre el modelo B2B2C.", "lectura": "convence",
                           "vacios": []})
    thread = [{"kind": "q", "cid": "dn", "text": "¿Qué modelo se habilita?"},
              {"kind": "a", "text": "El modelo B2B2C con APIs y el Data Warehouse."}]
    ev = _eventos(llm, "/api/follow", cid="dn", thread=thread, junta=True)
    assert not [e for e in ev if e["type"] == "speak"]
    d = ev[-1]["data"]
    assert d["lectura"] == "no_convence" and "Convenció" not in d["reaccion"] and "no me convence" in d["reaccion"]


def test_repregunta_normal_no_se_anuncia():
    thread = [{"kind": "q", "cid": "cfo", "text": "¿Cuál es el ROI?"}, {"kind": "a", "text": "Del 18 % a 3 años."}]
    ev = _eventos(FakeLLM(), "/api/follow", cid="cfo", thread=thread)
    assert not [e for e in ev if e["type"] == "speak"]


def test_junta_respuesta_confusa_no_convence_y_no_inventa_cifras():
    llm = FakeLLM(payload={"reaccion": "La simulación del ROI muestra una inversión de $1.670M para el año 1.",
                           "lectura": "convence", "vacios": []})
    thread = [{"kind": "q", "cid": "cfo", "text": "¿Cuál es el ROI?"},
              {"kind": "a", "text": "John: no entiendo la pregunta, podría cambiarla; al menos 100% el año cero"}]
    ev = _eventos(llm, "/api/follow", cid="cfo", thread=thread, junta=True)
    assert not [e for e in ev if e["type"] == "speak"]
    d = ev[-1]["data"]
    assert d["lectura"] == "no_convence" and "1.670" not in d["reaccion"] and "no hay repreguntas" in d["reaccion"]
