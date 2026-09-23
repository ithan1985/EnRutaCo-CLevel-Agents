# Comité Directivo EnRutaCo — agentes locales

Seis agentes (CEO, TI, Servicio al Cliente, CFO, Desarrollo de Negocio, Operaciones) que preguntan, repreguntan e intervienen entre sí ante el equipo consultor. Todo corre en tu máquina: LLM en Ollama, voces de Hugging Face y una interfaz web para proyectar.

## Arquitectura

```
Navegador (web/index.html)  ──SSE──►  API FastAPI (api/app)  ──►  Ollama (LLM local)
        ▲                                   │
        └──────── audio WAV ◄───────────────┴──►  TTS: Piper (rhasspy/piper-voices) o XTTS-v2 (coqui/XTTS-v2)
```

| Pieza | Dónde | Función |
|---|---|---|
| Personajes | `config/personas.yaml` | Personalidad (documento del docente), lectura del caso, voz. Fuente única. |
| Caso | `config/caso.yaml` | Hechos por semana, catálogo §6.2, reglas y criterios de rigor. |
| Prompts | `api/app/prompts.py` | El servidor arma los prompts; el navegador solo envía estado. |
| LLM | `api/app/llm.py` | Streaming NDJSON de Ollama con salida JSON estructurada. |
| Voz | `api/app/tts/` | Piper (CPU, tiempo real) o XTTS-v2 (calidad, GPU). |
| Interfaz | `web/index.html` | Escena, panel docente, sala de voces, exportación. |

## Arranque (WSL2 Ubuntu + Docker)

Trabaja dentro del sistema de archivos de WSL (`~/enrutaco-agentes-local`), no en `/mnt/c`.

```bash
cp .env.example .env
docker compose up -d --build        # con GPU NVIDIA: make gpu
docker compose logs -f api          # muestra la descarga de modelos y voces
```

Abre `http://localhost:8080`. La primera vez la página muestra una barra mientras Ollama descarga los modelos y la API descarga las voces desde Hugging Face; después funciona sin internet.

Si ya tienes Ollama instalado en Windows, usa `make host` (`docker-compose.host-ollama.yml`).

## Modelos de lenguaje

| Modo (selector «Modelo») | Variable | Por defecto | Uso |
|---|---|---|---|
| Rápido | `LLM_MODEL_QUICK` | `qwen2.5:3b-instruct` | Clase en vivo en CPU |
| Profundo | `LLM_MODEL_DEEP` | `qwen2.5:7b-instruct` | Mejor razonamiento; más lento en CPU |

La pregunta se ve mientras el modelo la escribe (la clave `pregunta` va primero en el JSON) y la voz empieza cuando la pregunta termina, sin esperar las notas del docente. Cambia los modelos en `.env` y reinicia el contenedor `api`.

## Rendimiento en tu equipo (Ryzen 5 5600 · 32 GB · sin GPU confirmada)

El Ryzen 5 5600 no tiene gráficos integrados, así que hay una tarjeta dedicada que el resumen del sistema no muestra. Confírmala en PowerShell: `Get-CimInstance Win32_VideoController | Select-Object Name` (y `nvidia-smi` si es NVIDIA).

| Tarjeta | Qué hacer |
|---|---|
| NVIDIA | `make gpu`. Con 8 GB o más, el modo Profundo (7b) responde en pocos segundos y XTTS es viable. |
| AMD Radeon (tu caso: RX 5500 XT) | Ollama instalado en Windows, no en Docker; ver la sección siguiente. |
| Ninguna útil | CPU: modo Rápido (3b) para clase en vivo. |

### AMD Radeon RX 5500 XT en Windows

La RX 5500 XT (RDNA 1, gfx1012) no figura en la lista oficial de ROCm de Ollama para Windows. La documentación de Ollama indica que el respaldo adicional para GPU en Windows llega por **Vulkan**, activo por defecto y sin pasos extra; no consta específicamente para tu modelo, así que se comprueba en dos minutos. Docker sobre WSL2 no expone GPU AMD, por eso Ollama va en Windows y la API en Docker.

1. Confirma tu VRAM: Administrador de tareas → Rendimiento → GPU → *Memoria de GPU dedicada* (4 u 8 GB).
2. Actualiza el controlador Adrenalin e instala Ollama para Windows.
3. Variables de usuario (PowerShell) y reinicio de Ollama desde la bandeja:
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","1","User")
   [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE","30m","User")
   [Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")   # 4 GB; usa 2 con 8 GB
   ```
4. Prueba: `ollama run qwen2.5:3b-instruct "hola" --verbose`. En otra terminal, `ollama ps` debe mostrar **100% GPU** y `eval rate` sube frente a CPU. Si muestra CPU, la tarjeta no se usa: continúa con el modo CPU (`make up`).
5. En WSL: `docker compose down && make host`, luego `make bench`.

| VRAM | Rápido | Profundo |
|---|---|---|
| 4 GB | `qwen2.5:3b-instruct` cabe entero en GPU | `qwen2.5:7b-instruct` (4,7 GB) solo se carga en parte; mejora poco frente a CPU |
| 8 GB | `qwen2.5:3b-instruct` | `qwen2.5:7b-instruct` cabe entero |

Si la GPU funciona, el mayor beneficio es la lectura del prompt (los ~3.000 tokens de la semana 8), que pasa de decenas de segundos a unos pocos. Si Vulkan da errores o cierres, desactívalo con `OLLAMA_VULKAN=0` y vuelve a CPU. Las voces (Piper) siguen en CPU y no compiten con el modelo.

En CPU la velocidad la limita el ancho de banda de la RAM y la lectura del prompt. Estimaciones, no mediciones: 3b ≈ 10–15 tokens/s y 7b ≈ 4–7 tokens/s; el primer turno en semana 8 lee ~3.000 tokens de sistema y puede tardar decenas de segundos. Lo que ya está optimizado:

- El prompt pone primero lo que comparten todos los personajes (~80 %), así que Ollama reutiliza esa parte al cambiar de personaje.
- El modo Rápido omite las notas del docente (`LLM_NOTES_IN_QUICK=0`) y responde en la mitad de tiempo.
- El modelo rápido se precarga al arrancar; `OLLAMA_NUM_PARALLEL=1` y `OLLAMA_MAX_LOADED_MODELS=2` dejan ambos modelos en memoria.
- Semanas 1–4 usan un prompt de ~1.400 tokens.

Mide tu equipo real antes de clase: `make bench` (carga, lectura del prompt, generación y beneficio de la caché). El panel docente muestra las mismas métricas de cada turno.

Si Windows bloquea el instalador de Docker Desktop u Ollama, revisa la política de control de aplicaciones que reporta tu sistema (probablemente Smart App Control): dentro de WSL2 no aplica. WSL2 usa por defecto la mitad de la RAM (16 GB), suficiente para este proyecto; para más, `memory=20GB` en `%UserProfile%\.wslconfig`.

## Voces: personalidad → parámetros

La voz de cada personaje sale de su personalidad. En Piper se combinan modelo de voz, tono, velocidad, variación de timbre, variación de ritmo y pausas entre frases.

| Personaje | Personalidad (resumen) | Piper (modelo · pitch · velocidad · pausa) | XTTS-v2 |
|---|---|---|---|
| Carlos Restrepo · CEO | Decisivo, exigente | `es_ES-davefx-medium` · 0,94 · 0,98 · 0,25 s | Damien Black |
| Andrés Mendoza · TI | Técnico, estructurado | `es_ES-sharvard-medium` (voz M) · 1,00 · 1,04 · 0,30 s | Luis Moray |
| Martha Ligia Gómez · Servicio | Empática, diplomática | `es_MX-claude-high` · 1,00 · 1,08 · 0,30 s | Alma María |
| Ricardo Valencia · CFO | Conservador, escéptico | `es_MX-ald-medium` · 0,90 · 1,10 · 0,40 s | Gilberto Mathias |
| Claudia Dávila · Negocio | Persuasiva, dinámica | `es_ES-sharvard-medium` (voz F) · 1,05 · 0,88 · 0,12 s | Ana Florence |
| Juliana Pérez · Operaciones | Directa, práctica | `es_MX-claude-high` · 0,92 · 0,90 · 0,15 s | Claribel Dervla |

Las asignaciones son un punto de partida: no fueron auditadas de oído. Abre el panel docente, entra en **Sala de voces**, escucha cada una y ajusta `config/personas.yaml`; aplica con **Recargar** (no reinicia nada).

Notas de ajuste:

- `es_ES-sharvard-medium` tiene dos voces. La API elige por la pista `F` o `M` del YAML leyendo el mapa de hablantes del modelo. Si suena al revés, consulta `GET /api/voices` y usa el número o nombre exacto en `speaker`.
- Martha y Juliana comparten modelo (`claude-high`) y se distinguen por tono, ritmo y pausas. Piper solo tiene dos voces femeninas en español; para seis voces distintas usa XTTS.
- XTTS: `WITH_XTTS=1`, `TTS_ENGINE=xtts`, `COQUI_TOS_AGREED=1` (licencia CPML de Coqui, uso no comercial) y `docker compose build api`. En CPU es lento; GPU recomendada. Si un hablante no existe en tu versión, la API usa el primero disponible y lo registra en el log.
- El texto se normaliza antes de sintetizar (`$4.200M COP` → «4200 millones de pesos», `TMS` → «T M S», `H1` → «H uno»). Ajusta `api/app/tts/common.py` si una sigla se lee mal.

## Cómo se usa en clase

1. Elige la semana. Cada agente solo conoce los hechos de esa semana y las anteriores; antes de su semana de debut actúa solo desde su personalidad.
2. En el panel docente pega el resumen de la propuesta y marca la selección presupuestal: el servidor calcula el total contra $4.200M y $4.830M con el catálogo oficial.
3. **Dar la palabra** → el agente pregunta con su voz. El equipo responde (escrito o dictado) → **Enviar respuesta** → reacción, lectura en personaje y repregunta o cierre.
4. **Intervención cruzada** hace que un rival natural del que acaba de hablar intervenga desde su conflicto (CFO contra CEO y TI, TI contra Negocio, Operaciones contra TI…). Definido en `rivales` y `conflicto`.
5. Tus observaciones y notas quedan en el panel; **Guardar sesión** exporta un `.md`. La sesión se conserva al recargar la página.

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/config` | Personajes, semanas y catálogo (sin prompts) |
| GET | `/api/health` | Ollama, descarga de modelos y voces |
| POST | `/api/ask` · `/api/follow` | Pregunta / reacción (SSE: `token`, `done`, `error`) |
| POST | `/api/tts` | `{cid, text}` → `audio/wav` |
| GET | `/api/tts/sample/{cid}` | Muestra de voz con la frase ancla |
| GET | `/api/voices` | Perfiles y hablantes por modelo |
| POST | `/api/reload` | Recarga `personas.yaml` y `caso.yaml` |

## Pruebas

```bash
make test
```

Cubren totales del catálogo, gating por semana (incluidos personajes y criterios de rigor), prompts, streaming SSE con un LLM simulado, errores, caché de audio, normalizador de texto y la lógica de tono y pausas de Piper con una voz simulada. `tests/e2e/` levanta la API contra un Ollama simulado para probarla con un navegador. Sin verificar en el entorno de desarrollo (sin acceso a Ollama ni a Hugging Face): la descarga real de modelos y voces, la calidad de las respuestas del LLM y de las voces, y el motor XTTS. La API de Piper sí se comprobó contra `piper-tts` 1.8.0 instalado.

## Corrección al caso

La sección 6.3 del caso afirma que O1–O5 + H1 + H2 + E1 + E3 + E4 + E5 + E7 suman $4.040M y que con H3 o H4 se supera el techo. La suma real es $3.815M (con H3, $3.910M; con H4, $3.925M; con ambos, $4.020M). `caso.yaml` no guarda totales: se calculan en código.

## Licencias

`piper-tts` es GPL-3.0-or-later; las voces de `rhasspy/piper-voices` heredan la licencia de su conjunto de datos; XTTS-v2 usa CPML (no comercial). Revisa también la licencia de cada modelo de Ollama antes de un uso distinto al docente.
