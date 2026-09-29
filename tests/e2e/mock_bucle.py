"""Ollama simulado que reproduce el bucle del agente Andrés documentado en TODO.md.

Simula un modelo "terco": a partir de la tercera repregunta repite siempre la misma frase, ignore o no las reglas del
prompt. Solo cede cuando el servidor le reenvía la corrección explícita de repetición (CORRECCIÓN OBLIGATORIA), como
haría un modelo que sí obedece una instrucción directa. Sirve para verificar las salvaguardas deterministas del
backend (anti-bucle, andamiaje y cierre), no la calidad del modelo real.

Uso: uvicorn tests.e2e.mock_bucle:app --port 11555
"""
import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
LOG: list[dict] = []

OPEN = "¿El API Gateway asegura la escalabilidad de la integración de E7 con O1 y O2 a corto y largo plazo?"
FOLLOWS = [
    "¿Cuáles políticas específicamente, en capacidad y en costos, sostienen esa escalabilidad?",
    "¿Cómo garantizas la aplicación continua de esas políticas en la operación?",
]
LOOP = ("¿Cómo podríamos definir los planes de implementación de esas políticas sin afectar la eficiencia "
        "operacional actual?")
LOOP_REACCION = "La solución responde a parte de mi preocupación."

# Respuestas de un modelo que sí atiende la corrección (las preguntas esperadas del TODO).
CORREGIDAS = {
    "confusion": ("Me refiero a tres cosas: qué herramienta ejecuta la política, quién la revisa y con qué frecuencia, "
                  "y cómo la prueban antes de producción.",
                  "Empecemos por la primera: ¿qué herramienta ejecuta concretamente la política de escalamiento?"),
    "cifras": ("Registro el dato del control plane, pero ahora me hablan de un millón de peticiones por minuto con un "
               "tope de USD 750 al mes.",
               "¿Ese millón por minuto es pico o sostenido, y cómo cuadra con el costo por petición del API Gateway?"),
    "anclaje": ("Registro el control plane sobre AWS, pero aún no me dicen quién lo opera ni cada cuánto se revisan "
                "las políticas.",
                "¿Quién es el dueño de ese control plane y con qué cadencia revisa los umbrales de escalamiento?"),
}


# «Grupo Lento»: respuestas que el servidor debe sanear (registro, pregunta encadenada, pregunta en la reacción),
# generadas despacio y con notas largas. Sirve para ver en el navegador que pantalla y voz usan el texto saneado del
# evento «speak» mientras el modelo sigue escribiendo.
LENTO = "Grupo Lento"
SLOW_OPEN = {"pregunta": "¿Cómo podríamos garantizar el SLA del 98 % sin frenar la operación? Lo digo por el retailer.",
             "evalua": "Plan concreto para el SLA: dueño, fecha, costo y el indicador con el que se reportará al Comité.",
             "senales": ["Nombra un dueño con cargo", "Da fecha y costo", "Cita el indicador SLA con umbral"],
             "trampa": "Responder con buenas prácticas genéricas y sin cifras verificables."}
SLOW_JUNTA = {"reaccion": "Registro el dueño del dato. Esto me ayuda a ver cómo garantizaré la trazabilidad. ¿Y el costo?",
              "lectura": "parcial",
              "vacios": ["Falta el costo por ola y quién lo aprueba", "Falta la fecha de corte del piloto con su indicador"]}


@app.get("/api/tags")
async def tags():
    return {"models": [{"name": "qwen2.5:3b-instruct"}, {"name": "qwen2.5:7b-instruct"}]}


@app.get("/_log")
async def log():
    return LOG


def respond(body: dict) -> dict:
    schema = body["format"]
    user = body["messages"][1]["content"]
    extra = " ".join(m["content"] for m in body["messages"][2:])
    if LENTO in user:
        return SLOW_JUNTA if isinstance(schema, dict) and "reaccion" in schema["properties"] else SLOW_OPEN
    if not (isinstance(schema, dict) and "reaccion" in schema["properties"]):
        return {"pregunta": OPEN, "evalua": "Escalabilidad de la integración", "senales": ["Cita capacidad"], "trampa": "Genérico"}
    n = user.count("(repregunta)")
    if "CORRECCIÓN OBLIGATORIA" in extra:
        last = [l for l in user.splitlines() if l.startswith("Equipo:")][-1]
        key = "confusion" if "no entiende" in extra else ("cifras" if "1M" in last else "anclaje")
        r, s = CORREGIDAS[key]
        return {"reaccion": r, "seguimiento": s, "lectura": "parcial", "vacios": ["Respuesta sin herramienta ni dueño"]}
    if n < len(FOLLOWS):
        return {"reaccion": "Entiendo el planteamiento.", "seguimiento": FOLLOWS[n], "lectura": "parcial",
                "vacios": ["Falta concreción"]}
    return {"reaccion": LOOP_REACCION, "seguimiento": LOOP, "lectura": "no_convence", "vacios": ["Falta concreción"]}


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    LOG.append({"messages": body["messages"], "format": body.get("format")})
    txt = json.dumps(respond(body), ensure_ascii=False)
    if not body.get("stream", True):
        return {"message": {"role": "assistant", "content": txt}, "done": True}

    pausa = 0.12 if LENTO in body["messages"][1]["content"] else 0.01

    async def gen():
        for i in range(0, len(txt), 24):
            await asyncio.sleep(pausa)
            yield json.dumps({"message": {"role": "assistant", "content": txt[i:i + 24]}, "done": False}) + "\n"
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": 2000,
                          "prompt_eval_duration": 2_000_000_000, "eval_count": 100, "eval_duration": 2_000_000_000,
                          "total_duration": 4_000_000_000}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")
