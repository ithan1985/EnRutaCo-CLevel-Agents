# TODO

## Evaluación de los agentes: la pregunta es pertinente en tema, pero falla en la dinámica

La transcripción está en orden inverso (lo más reciente arriba). Reconstruida en orden cronológico, el tema de las preguntas es correcto, pero el agente Andrés entra en un bucle: no procesa las respuestas del equipo, no maneja el "no entiendo" y no tiene condición de cierre.

### Análisis turno a turno (orden cronológico)

| # | Agente | Pregunta / feedback | Respuesta del equipo | Evaluación del agente |
|---|--------|----------------------|------------------------|--------------------------|
| 1 | Juliana | Integración de E7 con O1/O2, riesgos de compatibilidad | API Gateway como mediador | Bien. Pregunta específica que usa los códigos del caso. Falla: dice "Concordo" (portugués) |
| 2 | Andrés | ¿El API Gateway asegura escalabilidad a corto y largo plazo? | "En cloud se asegura con políticas horizontales y verticales" | Bien. Construye sobre la respuesta anterior y profundiza |
| 3 | Andrés | ¿Cuáles políticas específicamente, en capacidad y costos? | Números concretos: 2 cores, 85%, 6 nodos, USD 300–750 | Aceptable. Buena pregunta, pero su feedback solo repite la afirmación del equipo como si fuera un hecho validado |
| 4 | Andrés | ¿Cómo garantizas la aplicación continua? | "En las políticas cloud native" | Falla. Ignora por completo los números del turno 3. Debió cuestionar el umbral del 85% o el costo, no volver a lo genérico |
| 5 | Andrés | ¿Cómo definir los planes de implementación? | "No entiendo, ¿qué sugieres?" | Falla crítica. El equipo pidió ayuda y el agente repitió la pregunta casi igual. No reformula ni da un ejemplo de lo que espera |
| 6 | Andrés | Misma pregunta | "Con control plane sobre AWS" | Falla. No reconoce el nuevo dato ni pide que lo expliquen |
| 7 | Andrés | Misma pregunta | 85% memoria, 86% CPU, 1M peticiones/min | Falla. No detecta la contradicción entre 1M peticiones/min y un tope de USD 750 |
| 8 | Andrés | Misma pregunta (sin respuesta) | — | Bucle confirmado: 5 turnos con la misma frase "sin afectar la eficiencia operacional actual" |

### Defectos del agente Andrés

| Defecto | Evidencia | Consecuencia |
|---------|-----------|---------------|
| No usa la respuesta anterior | Nunca cita un número ni un término dado por el equipo | El estudiante percibe que no lo escucha |
| No maneja la confusión | Responde a "no entiendo" repitiendo la misma pregunta | Bloquea el aprendizaje en lugar de guiarlo |
| No tiene criterio de "concreto" | Pide concreción sin decir qué le falta (métrica, herramienta, dueño, cadencia) | El equipo adivina qué se espera de él |
| No detecta inconsistencias | Deja pasar 1M/min vs USD 750, y umbrales del 85% | Pierde su rol de evaluador crítico |
| No tiene salida | Sin límite de repeticiones ni escalamiento | Conversación infinita |
| Registro inconsistente | Alterna "garantiza", "garantizarás" y "¿cómo podríamos…?" | La persona se desdibuja: a veces evalúa, a veces se incluye en el equipo |
| Feedback vacío | "La solución responde a parte de mi preocupación" se repite en 4 turnos | No aporta información nueva |

### Lo que Andrés debió preguntar

| Turno | Pregunta esperada |
|-------|--------------------|
| 4 | "Proponen escalar al 85% de uso. ¿Cuánto tarda un nodo nuevo en estar operativo y qué pasa con los usuarios durante ese tiempo?" |
| 5 (ante "no entiendo") | "Me refiero a tres cosas: qué herramienta ejecuta la política, quién la revisa y con qué frecuencia, y cómo la prueban antes de llevarla a producción. Empecemos por la herramienta." |
| 7 | "Hablan de 1M de peticiones por minuto con un tope de USD 750 al mes. ¿Ese volumen es pico o sostenido? ¿Cómo cuadra con el costo por petición del API Gateway?" |

### Ajustes recomendados al prompt del agente

| Regla | Instrucción sugerida |
|-------|------------------------|
| Anclaje obligatorio | "Cada pregunta debe citar un elemento específico de la última respuesta del equipo." |
| Límite anti-bucle | "Si la misma preocupación sigue sin resolverse tras 2 intentos, reformula con un ejemplo concreto de lo esperado. Tras 3 intentos, cierra la preocupación con una calificación y pasa al siguiente tema." |
| Andamiaje | "Si el equipo dice que no entiende o pide sugerencias, descompón la pregunta en sub-preguntas y pide solo una a la vez." |
| Checklist de concreción | "Una respuesta es concreta si incluye métrica, umbral, herramienta, dueño, cadencia e indicador. Pregunta solo por el elemento que falta." |
| Rol crítico | "Verifica la coherencia entre las cifras (capacidad, volumen, costo) y cuestiona cualquier contradicción." |
| Estado por preocupación | "Registra cada preocupación como abierta, parcial o resuelta, e informa el estado en tu feedback." |
| Persona y registro | "Habla siempre en español, trata al equipo de usted y actúa como evaluador, nunca como parte del equipo." |

### Estado: implementado

| Regla | Implementación | Tipo |
|-------|----------------|------|
| Anclaje obligatorio | `follow_task` exige citar un elemento de la última respuesta | Prompt |
| Límite anti-bucle | `concern_attempts`: 2 intentos → REFORMULACIÓN; 3 → CIERRE OBLIGATORIO. Tope duro `MAX_FOLLOWS = 6` | Prompt + código |
| Repregunta repetida | `similar()` la detecta; 1 reintento con `correction_message`; si persiste, `force_close("repeticion")` | Código (determinista) |
| Andamiaje | `is_confused()` detecta "no entiendo / ¿qué sugieres?" y activa ANDAMIAJE | Prompt + código |
| Checklist de concreción | Métrica, umbral, herramienta, dueño, cadencia e indicador; preguntar solo por lo que falte | Prompt |
| Rol crítico | Coherencia de cifras en todo el hilo | Prompt |
| Estado por preocupación | Campo `estado` (abierta, parcial, resuelta) y `cierre` (limite, repeticion) en la respuesta y la UI | Código |
| Persona y registro | Regla 9 del sistema: solo español, «ustedes», evaluador y nunca parte del equipo | Prompt |

Verificación: `tests/e2e/mock_bucle.py` reproduce la sesión de este TODO con un modelo que ignora el prompt; las salvaguardas de código cortan el bucle.

### Fase 2: validación con qwen2.5:3b real

Sesión real por API (`POST /api/ask` y `/api/follow`, SSE), `cid="ti"` (Andrés, Director de TI), `week=8`, `mode="quick"`, contra el contenedor con `OLLAMA_MAX_LOADED_MODELS=1`. El equipo respondió en este orden: genérico sin datos → cifras concretas → genérico → "no entiendo" → herramienta vaga → cifras contradictorias con el paso 2. Se envió siempre el hilo completo, como hace `web/index.html` (`threadList`).

| # | Paso | Equipo dice | Reacción / repregunta de Andrés | lectura | estado | cierre | guía | vacíos | tiempo (s) |
|---|------|-------------|----------------------------------|---------|--------|--------|------|--------|------------|
| 1 | pregunta inicial | — | «¿Cuáles son las dependencias críticas que requerirán soluciones tecnológicas antes de comenzar la migración al ERP?» | — | — | — | — | — | 92.4 |
| 2 | genérico sin datos | "Con buenas prácticas generales vamos a asegurar que todo funcione bien." | "Los equipos sugirieron buenas prácticas generales pero aún falta definir qué datos se migrarán…" → «¿qué datos se migrarán?» | no_convence | abierta | — | — | [] | 30.3 |
| 3 | cifras concretas | "Migramos 120.000 registros en 3 fases de 2 meses, con 2 personas y $180M." | "Migramos un volumen estimado de registros sin definir quién será el dueño…" → «¿qué datos no se incluirán en la primera fase?» | no_convence | abierta | — | — | [dueño del dato maestro] | 32.8 |
| 4 | genérico | "Con buenas prácticas de gobierno de datos." | Reacción **idéntica, palabra por palabra**, a la del paso 3 → «¿Cuál es el criterio…?» | no_convence | abierta | — | — | [] | 35.4 |
| 5 | "No entiendo, ¿qué sugieres?" | — | Andamiaje determinista: "para darlo por concreto necesito herramienta, dueño, cadencia, métrica con umbral e indicador… empecemos por herramienta." → «¿Qué herramienta o sistema concreto ejecutará lo que proponen?» | no_convence | abierta | — | **andamiaje** | [nota automática] | 37.3 |
| 6 | herramienta vaga ("Con un MDM sobre AWS") | — | 1 intento repitió una repregunta anterior (reintento automático); reacción final cita "MDM sobre AWS" → «¿Qué métrica utilizará…?» | no_convence | abierta | — | — | [] | 20.7 (wall 60.5, 2 llamadas) |
| 7 | cifras contradictorias ("Limpiamos los 120.000 registros en **un fin de semana**… sin detener la facturación") | — | 1 reintento por repregunta repetida; reacción final **no menciona la contradicción** con "3 fases de 2 meses" del paso 3 → «¿Quién será el dueño del dato maestro…?» | no_convence | abierta | — | — | [dueño de los datos] | 12.2 (wall 52.1, 2 llamadas) |

**Qué quedó resuelto (validado con llamadas reales, no solo lectura de código):**
- El andamiaje determinista ante "no entiendo" funciona: descompone en partes y no repite la pregunta (paso 5).
- El anti-bucle de repregunta repetida funciona: dos veces (pasos 6 y 7) el modelo repitió una repregunta anterior, el servidor reintentó con `correction_message` y obtuvo una repregunta distinta sin exponer el bucle al usuario.
- Bug nuevo encontrado y corregido: el modelo repite literalmente el "nosotros" de la respuesta del equipo ("Migramos 120.000 registros…") violando la regla 9 (nunca incluirse en el equipo). Se agregó `"migramos": "migran"` a `_REGISTRO` en `guard.py`; confirmado corregido en una llamada real posterior ("Migran 120.000 registros…").
- Bug nuevo encontrado y corregido (motivo de esta fase): el modelo **no detectó** la contradicción de plazos del paso 7 ("3 fases de 2 meses" vs. "un fin de semana") a pesar de que el prompt ya listaba las cifras y pedía verificar coherencia. Se agregó `guard.duration_contradiction()` (compara el plazo más corto contra el más largo mencionado por el equipo en el hilo, con frases sin cifra como "un fin de semana" traducidas a días aproximados) y se inyecta en el prompt como regla explícita `POSIBLE CONTRADICCIÓN`. Como el aviso en el prompt tampoco bastó para que el modelo lo verbalizara en una prueba dirigida posterior, se agregó además un respaldo determinista en `main.py`: si `duration_contradiction()` detecta algo y ni la reacción ni los vacíos ya lo mencionan, el servidor añade "Posible contradicción de plazos: …" a `vacios`. Confirmado con una llamada real: `vacios=['Posible contradicción de plazos: mencionaron «un fin de semana» y también «2 meses»: los plazos no cuadran.']`.

**Límites conocidos:**
- Corte heurístico de preguntas encadenadas (`_CHAIN` en `guard.py`): sigue siendo una lista de patrones, no un parser real; frases inusuales pueden colarse.
- Dependencia del modelo para cuestionar cifras: incluso con la regla `POSIBLE CONTRADICCIÓN` explícita en el prompt, qwen2.5:3b normalmente no lo verbaliza en su propia repregunta (solo lo repite como dato, sin señalar la incoherencia); el respaldo determinista en `vacios` garantiza que quede en el acta, pero no que Andrés "la pregunte".
- `duration_contradiction()` es una heurística simple (plazo mínimo vs. máximo en todo el hilo, sin verificar que hablen del mismo tema); puede dar falsos positivos si el equipo menciona plazos de dos actividades distintas y no relacionadas.
- El diccionario `_REGISTRO` es una lista fija: en las pruebas de esta fase aparecieron otras conjugaciones en primera persona no cubiertas (p. ej. "sugeriremos", "asegurarás") que se colaron sin corregir. Ampliar caso por caso, como con "migramos", en vez de intentar cubrir todas las formas verbales.
- Feedback repetido palabra por palabra entre turnos consecutivos (paso 3→4 en la tabla): la regla de prompt "prohibidas las fórmulas vacías" no es suficiente por sí sola; no se implementó salvaguarda determinista para esto en esta fase (no era el objetivo original) — candidato para una próxima iteración, análogo al anti-bucle de repregunta repetida pero aplicado a `reaccion`.
- Se observó una cifra inventada por el modelo en una corrida (dijo "doce personas" cuando el equipo dijo "2 personas"): riesgo de fabricación de cifras no verificado por ninguna salvaguarda actual.

**Pendientes:**
- Evaluación de qwen2.5:7b, solo en GPU (no se debe cargar junto al 3b sin GPU: satura el equipo).
- Publicación del proyecto con enlace público (más allá del repo en GitHub).
- Considerar una salvaguarda determinista para la reacción repetida palabra por palabra entre turnos.
- Considerar una verificación (aunque sea heurística) de cifras que el modelo menciona sin que estén en el hilo ni en el caso.
