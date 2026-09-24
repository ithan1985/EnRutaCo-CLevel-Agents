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

Verificación: `tests/e2e/mock_bucle.py` reproduce la sesión de este TODO con un modelo que ignora el prompt; las salvaguardas de código cortan el bucle. Pendiente: validar la calidad de las repreguntas con Ollama real (`make host`).
