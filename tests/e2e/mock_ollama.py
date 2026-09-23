"""Ollama simulado (mismo protocolo NDJSON) para probar la cadena completa sin descargar modelos."""
import asyncio, json
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

app = FastAPI()
LOG = []

@app.get("/api/tags")
async def tags():
    return {"models": [{"name": "qwen2.5:3b-instruct"}, {"name": "qwen2.5:7b-instruct"}]}

@app.get("/_log")
async def log():
    return LOG

@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    LOG.append({"model": body["model"], "format": body.get("format"), "options": body.get("options"),
                "system": body["messages"][0]["content"][:80], "user": body["messages"][1]["content"]})
    schema = body["format"]
    follow = isinstance(schema, dict) and "reaccion" in schema["properties"]
    n = len(LOG)
    data = (
        {"reaccion": "Entiendo el punto, pero no me habla de supuestos.", "seguimiento": f"¿Qué supuesto sostiene el ROI y quién lo audita? ({n})", "lectura": "parcial", "vacios": ["Sin fuente del OTIF", "ROI sin sensibilidad"]}
        if follow else
        {"pregunta": f"Si excluyen E2, ¿cómo defienden los 3 contratos B2B que hoy cuestan $4.200M en riesgo? ({n})", "evalua": "Justificación de exclusiones", "senales": ["Cita riesgo si NO", "Propone mitigación"], "trampa": "Decir que el CRM es prescindible sin plan"}
    )
    txt = json.dumps(data, ensure_ascii=False)
    if not body.get("stream", True):
        return {"message": {"role": "assistant", "content": txt}, "done": True, "load_duration": 900000000, "prompt_eval_count": 2600 if n % 3 == 1 else 900,
                "prompt_eval_duration": 13000000000 if n % 3 == 1 else 4500000000, "eval_count": 110, "eval_duration": 8800000000, "total_duration": 23000000000}
    async def gen():
        for i in range(0, len(txt), 12):
            await asyncio.sleep(0.03)
            yield json.dumps({"message": {"role": "assistant", "content": txt[i:i+12]}, "done": False}) + "\n"
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "load_duration": 1200000000, "prompt_eval_count": 2100, "prompt_eval_duration": 14000000000, "eval_count": 120, "eval_duration": 9600000000, "total_duration": 24800000000}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")
