# Junta del Comité Directivo: guía de operación

Sesión en línea: el docente comparte su pantalla y la app (con el backend en AWS) hace de Comité Directivo. Cada grupo expone y luego responde una pregunta de cada miembro del Comité, en las mismas condiciones para todos.

## 1. Formato por grupo (25 min)

| Bloque | Duración | En la app |
|---|---|---|
| Apertura del CEO | ~30 s | «Apertura del CEO» (texto fijo con voz, sin modelo) |
| Exposición del grupo | 15 min | «Presentación 15 min». Bloques: 1 Problema · 2 Propuesta · 3 BI · 4 Roadmap · 5 Caso financiero · 6 Decisión |
| Preguntas de la Junta | 10 min | «Preguntas 10 min». Una pregunta por miembro, orden fijo: TI → Servicio al Cliente → CFO → Negocio → Operaciones → CEO. Sin repreguntas |
| Cierre del CEO | ~20 s | «Cierre del CEO» (aparece cuando las 6 respuestas están evaluadas) |

Todos los integrantes deben intervenir: el selector «Responde:» registra quién contestó cada pregunta.

Sesión del 29 de septiembre de 2026:

| Grupo | Horario |
|---|---|
| Grupo 1 | 6:00 – 6:25 p.m. |
| Grupo 2 | 6:30 – 6:55 p.m. |
| Grupo 3 | 7:00 – 7:25 p.m. |
| Grupo 4 | 7:30 – 7:55 p.m. |

## 2. Preparación (60 minutos antes)

### 2.1 Encender y desplegar el backend en AWS

1. Consola de AWS → EC2 → Instancias → selecciona la instancia de la junta → «Estado de la instancia» → «Iniciar instancia».
2. Espera a que diga «En ejecución» y copia la «Dirección IPv4 pública». Cambia en cada encendido.
3. En una terminal de WSL, dentro de la carpeta del repositorio:
   ```bash
   bash scripts/desplegar_aws.sh <IP-pública>
   ```
   Tarda de 1 a 5 minutos. Al final muestra el estado de Ollama, los modelos y las voces, y el comando del túnel.
   Para programar el apagado automático como red de seguridad de costos, antepón `APAGAR_EN=<minutos>` y calcula que caiga después de la sesión. Ejemplo: a las 5:00 p.m., `APAGAR_EN=240` apaga a las 9:00 p.m.
4. Abre el túnel en otra terminal de WSL y déjala abierta toda la sesión. Es el comando que imprime el script:
   ```bash
   ssh -i ~/enrutaco.pem -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -N -L 8081:localhost:8080 ubuntu@<IP-pública>
   ```
5. Abre `http://localhost:8081` en el navegador.

### 2.2 Preparar la app

1. «Panel docente» → «Avanzado» → «Cargar grupos»: pega el JSON de los grupos (sección 6) y pulsa «Cargar grupos».
   Los grupos se guardan por dirección: si antes los cargaste en `localhost:8080`, cárgalos de nuevo en `localhost:8081`.
2. Marca «Modo junta».
3. Elige el modelo antes de empezar y no lo cambies durante la sesión: cambiarlo recarga el modelo (unos 20 s).
   - Rápido (3b): turnos más cortos.
   - Profundo (7b): evalúa mejor, tarda más.
4. «Avanzado» → «Sala de voces»: escucha a Carlos para confirmar el audio.
5. Pulsa «Ocultar notas del docente». Se ocultan:
   - la propuesta y «Dónde presionar»;
   - la lectura, la calificación y las observaciones;
   - la sección Avanzado.
   Se mantienen visibles el temporizador, el grupo y los botones.
6. Comparte la pestaña del navegador con audio:
   - Meet: «Una pestaña» y «Compartir también el audio de la pestaña».
   - Teams: activa «Incluir el audio del equipo».

## 3. Guion por grupo

| Minuto | Acción | Dónde |
|---|---|---|
| 0:00 | Elegir el grupo (el acta del grupo anterior se descarga sola) | Panel → Integrantes del equipo → Grupo |
| 0:00 | Iniciar el temporizador y dar la bienvenida | «Presentación 15 min» → «Apertura del CEO» |
| 0:30 – 15:00 | El grupo expone. Al terminar la apertura el modelo se precalienta solo | — |
| 15:00 | Iniciar las preguntas | «Preguntas 10 min» → «Dar la palabra a Andrés» |
| Cada pregunta | Escribir o dictar la respuesta, elegir quién respondió y enviar | «Responde:» → «Enviar respuesta» |
| Cada pregunta | Pasar al siguiente miembro | «Dar la palabra a …» |
| ~24:00 | Cerrar la junta | «Cierre del CEO» |
| 25:00 | Registrar la nota y guardar el acta | «Mostrar notas del docente» → «Usar la nota propuesta» o escribir la nota → «Guardar sesión (.md)» |

Recomendaciones:

- Resume cada respuesta en 1 a 3 frases con las cifras que dio el grupo: el Comité evalúa lo que escribes.
- Si una pregunta sale confusa y el grupo todavía no respondió, usa «Cambiar la pregunta de …». La pregunta descartada no va al acta.
- «Detener» corta la generación en curso. Para callar una voz que ya está sonando, apaga «Voz» (arriba) y vuelve a encenderla.
- La propuesta de nota se muestra solo en el Panel docente, no en el escenario compartido. Revísala después de dejar de compartir o con las notas ocultas.

## 4. Propuesta de nota

| Lectura del Comité | Puntos |
|---|---|
| Convence | 5,0 |
| Convence a medias | 3,5 |
| No convence | 2,0 |

- Ajuste de −0,5 cuando hubo que activar la guía automática («no entiendo»).
- Ajuste de −0,5 cuando algún integrante no respondió ninguna pregunta.
- La nota es el promedio de las 6 evaluaciones con los ajustes, redondeado a una décima.
- La nota final la decide el docente: queda en el acta como «Nota final del docente».

## 5. Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «Sin conexión con la API local» o errores al dar la palabra | Se cayó el túnel | Repite el comando del túnel y recarga la página. La sesión, los grupos y el temporizador se conservan |
| `ssh` se queda esperando y termina en *timeout* | Cambió la IP pública de tu casa | EC2 → Grupos de seguridad → «Editar reglas de entrada» → regla SSH → origen «Mi IP» → Guardar |
| `ssh` avisa `REMOTE HOST IDENTIFICATION HAS CHANGED` | AWS reutilizó la IP | `ssh-keygen -R <IP-pública>` y repite |
| Los estudiantes no oyen al Comité | No se compartió el audio de la pestaña | Deja de compartir y comparte de nuevo con audio |
| «Voz no disponible» o «sin voz» en la apertura | Falló la síntesis de voz | El texto queda en pantalla: léelo tú. La junta sigue |
| La pregunta tarda más de 30 s | El modelo se está cargando (cambio de modo o primera carga) | Espera. Si pasa de 60 s: «Detener» y «Dar la palabra» otra vez |
| La reacción no corresponde a la respuesta | Limitación del modelo | Anótalo en «Observación de la respuesta actual» y ajusta la nota final |
| Se recargó la página | — | Se conserva todo: sesión, grupos, nota final y temporizador |

## 6. JSON de grupos

```json
{"grupos": [{
  "id": "g1",
  "nombre": "Grupo 1",
  "integrantes": ["Nombre Apellido", "Nombre Apellido"],
  "propuesta": "1. PROBLEMA: ...\n2. PROPUESTA: ...\n3. BI: ...\n4. ROADMAP: ...\n5. FINANCIERO: ...\n6. DECISIÓN: ...",
  "seleccion": ["E2", "E4", "H1", "H2"],
  "focos": {},
  "presionar": ["Punto débil para el docente"]
}]}
```

| Campo | Uso |
|---|---|
| `nombre` | Nombre corto: lo dice el CEO y va al acta |
| `integrantes` | Opciones de «Responde:» y control de participación |
| `propuesta` | Resumen por bloques. Es el contexto de los agentes (máximo 4.000 caracteres) |
| `seleccion` | Códigos del catálogo §6.2 además de O1–O5, que siempre van incluidos |
| `focos` | Opcional: foco por miembro (`ti`, `cs`, `cfo`, `dn`, `ops`, `ceo`). Si falta, se usa el foco estándar de la junta |
| `presionar` | Notas solo para el docente («Dónde presionar») |

El JSON con nombres de estudiantes vive solo en el navegador del docente. No lo subas al repositorio: `.gitignore` excluye `grupos*.json`, las actas (`acta-*.md`) y las llaves (`*.pem`).

## 7. Después de la sesión

1. Guarda el acta del último grupo.
2. Cierra el túnel (Ctrl+C en su terminal).
3. Detén la instancia: EC2 → Instancias → «Estado de la instancia» → «Detener instancia». Detenida no cobra cómputo; el disco sí, y es mínimo.
4. Revisa el consumo en «Billing» → «Créditos» al día siguiente.

## 8. Tiempos de referencia

| Entorno | Modelo | Primera pregunta en frío | Turno típico |
|---|---|---|---|
| AWS c7a.8xlarge (CPU, 32 núcleos) | Rápido (3b) | ~12 s | ~6 s |
| AWS c7a.8xlarge | Profundo (7b) | ~20 s | 6 – 15 s |
| PC del docente (CPU) | Rápido (3b) | 90 – 120 s | 30 – 42 s |

El precalentamiento al terminar la apertura busca que la primera pregunta de cada grupo tarde como un turno típico. Aún no se ha medido con el modelo real. La voz añade el tiempo de lectura: unos 10 a 20 s por intervención.
