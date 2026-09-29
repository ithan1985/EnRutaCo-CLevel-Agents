"""Salvaguardas deterministas sobre la salida del modelo.

Pensadas para modelos pequeños (qwen2.5:3b en CPU) que no siempre obedecen el prompt. Todo aquí es código puro:
no llama al modelo, así que no añade carga de CPU ni latencia apreciable.

- sanitize(): corrige registro (primera persona plural, tuteo), prefijos de hablante, texto después de la pregunta,
  preguntas encadenadas, preguntas dentro de la reacción y 'vacios' copiados de la plantilla de formato.
- scaffold(): andamiaje con plantilla cuando el equipo dice que no entiende y el modelo solo repite su pregunta.
- team_figures(): cifras que el equipo ya dio en el hilo, para que el modelo no las ignore.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# ───────────── Registro ─────────────

# El personaje evalúa: no se incluye en el equipo consultor ni lo tutea. «nuestra operación» (la empresa) sí es válido.
_REGISTRO = {
    # 1.ª persona plural -> 3.ª plural (ustedes)
    "podríamos": "podrían", "podemos": "pueden", "necesitamos": "necesitan", "debemos": "deben",
    "tenemos": "tienen", "vamos": "van", "haremos": "harán", "garantizaremos": "garantizarán",
    "garantizaríamos": "garantizarían", "aseguraremos": "asegurarán", "aseguraríamos": "asegurarían",
    "mantendremos": "mantendrán", "definiremos": "definirán", "migraremos": "migrarán", "haríamos": "harían",
    "implementaremos": "implementarán", "mediremos": "medirán", "evitaremos": "evitarán", "lograremos": "lograrán",
    "definiríamos": "definirían", "implementaríamos": "implementarían", "mediríamos": "medirían",
    # 2.ª persona singular (tú) -> ustedes
    "garantizas": "garantizan", "presentarías": "presentarían", "harías": "harían", "podrías": "podrían",
    "tienes": "tienen", "puedes": "pueden", "propones": "proponen", "sugieres": "sugieren", "dirías": "dirían",
    "explicas": "explican", "aseguras": "aseguran", "defines": "definen", "planeas": "planean", "piensas": "piensan",
    "garantizarías": "garantizarían", "garantizaré": "garantizarán", "aseguraré": "asegurarán", "implementaré": "implementarán", "migraré": "migrarán", "mediré": "medirán", "garantizaría": "garantizarían", "asegurarías": "asegurarían", "definirías": "definirían", "tú": "ustedes",
    "migramos": "migran",
    # voz del equipo que el modelo adopta al evaluar (validación del 29-sep)
    "esperamos": "esperan", "establecemos": "establecen", "proponemos": "proponen", "buscamos": "buscan",
    "planeamos": "planean", "queremos": "quieren", "priorizamos": "priorizan", "reduciremos": "reducirán",
    "mejoraremos": "mejorarán", "reduciríamos": "reducirían", "contamos": "cuentan", "iniciaremos": "iniciarán",
    "lanzaremos": "lanzarán", "integraremos": "integrarán", "capacitaremos": "capacitarán",
    "garantizamos": "garantizan", "implementamos": "implementan", "aseguramos": "aseguran", "mantenemos": "mantienen",
    "evitamos": "evitan", "integramos": "integran", "medimos": "miden", "definimos": "definen", "logramos": "logran",
    "manejamos": "manejan", "gestionamos": "gestionan", "controlamos": "controlan", "cumplimos": "cumplen",
    "seguimos": "siguen", "continuamos": "continúan", "avanzamos": "avanzan", "operamos": "operan",
    "trabajamos": "trabajan", "hacemos": "hacen", "vemos": "ven",
}
_REG_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _REGISTRO), key=len, reverse=True)) + r")\b", re.I)

_SPEAKER = re.compile(r"^\s*[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)?\s*(?:\([^)]*\))?\s*:\s*")
_CHAIN = re.compile(
    r",?\s+y\s+(?=(?:(?:con|en|de|a|por|para|desde|hasta|bajo|sobre)\s+)?(?:c[oó]mo|qu[eé]|qui[eé]n(?:es)?|d[oó]nde|cu[aá]l(?:es)?|cu[aá]ndo|cu[aá]nt[oa]s?|por\s+qu[eé])\b)",
    re.I,
)
_TEMPLATE_VACIOS = ("qué faltó o estuvo débil", "máximo 2 elementos", "para el docente")


def _match_case(src: str, dst: str) -> str:
    return dst[0].upper() + dst[1:] if src[:1].isupper() else dst


# «nos permitirá», «nos garantiza»...: el evaluador no es beneficiario del plan del equipo. Solo estos verbos, para no
# tocar usos legítimos («nos preocupa», «nos dijeron»).
_NOS = re.compile(r"\b([Nn])os (permitir[áa]n?|permite|permiten|garantizar[áa]n?|garantiza|garantizan|dar[áa]n?|ayudar[áa]n?)\b")


def fix_register(text: str) -> str:
    t = _REG_RE.sub(lambda m: _match_case(m.group(0), _REGISTRO[m.group(0).lower()]), text or "")
    return _NOS.sub(lambda m: ("L" if m.group(1) == "N" else "l") + "es " + m.group(2), t)


def _fold(s: str) -> str:
    """minúsculas y sin tildes, para comparar términos sin depender de acentos."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def one_question(text: str, keep_chain_terms: Iterable[str] | None = None) -> str:
    """Deja una sola pregunta: quita el prefijo de hablante, lo que sigue al primer '?' y la segunda pregunta
    encadenada — salvo que 'keep_chain_terms' indique que la segunda parte conecta con un hilo previo (p. ej.
    una intervención cruzada que retoma lo dicho por otro personaje); en ese caso se conserva completa, con un
    tope de 45 palabras en vez del recorte habitual."""
    t = _SPEAKER.sub("", (text or "").strip())
    if "?" in t:
        t = t[: t.index("?") + 1]
    m = _CHAIN.search(t)
    if m and t.endswith("?") and len(t[: m.start()].split()) >= 4:  # la primera parte ya es una pregunta completa
        conecta = bool(keep_chain_terms) and any(term in _fold(t[m.end():]) for term in keep_chain_terms)
        if conecta:
            words = t.split()
            if len(words) > 45:
                t = " ".join(words[:45]).rstrip(" ,;") + "?"
        else:
            t = t[: m.start()].rstrip(" ,;") + "?"
    if t.endswith("?") and "¿" not in t:
        t = "¿" + t[0].lower() + t[1:]
    t = t.strip()
    if t.startswith("¿") and len(t) > 1:
        t = "¿" + t[1].upper() + t[2:]   # «¿cómo…» -> «¿Cómo…»
    return t


def strip_questions(text: str) -> str:
    """Quita de la reacción cualquier oración interrogativa (la pregunta va en 'seguimiento')."""
    t = _SPEAKER.sub("", (text or "").strip())
    t = re.sub(r"¿[^?]*\?", "", t)
    t = re.sub(r"[^.!¡¿?]*\?", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,;")


def clean_vacios(items: Iterable[str]) -> list[str]:
    return [v for v in items if v.strip() and not any(p in v.lower() for p in _TEMPLATE_VACIOS)]


# Negación seguida (en la misma oración) de un patrón del _CHECKLIST: candidato a "reclamo de vacío falso".
_NEGACION = re.compile(r"\b(no\s|sin\s|falta[n]?\s|nadie\s|ning[uú]n\w*\s)", re.I)


def strip_false_gaps(reaccion: str, dados: Iterable[tuple[str, str]] | None) -> str:
    """Quita de 'reaccion' oraciones que reclaman como faltante un elemento que el equipo ya dio en el hilo
    (ver datos_ya_dados). No se aplica a 'métrica y umbral': su patrón es solo un dígito y es demasiado débil
    para borrar texto del modelo con esa sola señal."""
    if not dados or not reaccion:
        return reaccion
    nombres = {n for n, _ in dados if n != "métrica y umbral"}
    if not nombres:
        return reaccion
    patrones = [pat for n, pat, _ in _CHECKLIST if n in nombres]
    frases = re.split(r"(?<=[.!?])\s+", reaccion.strip())
    out = [f for f in frases if not (_NEGACION.search(f) and any(re.search(p, f, re.I) for p in patrones))]
    return " ".join(out).strip()


def trim_reaccion(text: str, max_frases: int = 2) -> str:
    """Recorta 'reaccion' a máximo 2 oraciones, priorizando las que citan cifras o señalan una contradicción
    (para no perder lo más útil al acortar reacciones largas de ~3 frases)."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if f.strip()]
    if len(frases) <= max_frases:
        return " ".join(frases)
    prioridad = [f for f in frases if _NUM.search(f) or re.search(r"contradic|no cuadra|no coincide", f, re.I)]
    elegidas = set((prioridad + [f for f in frases if f not in prioridad])[:max_frases])
    return " ".join(f for f in frases if f in elegidas)


def fix_reaccion(s: str, dados: Iterable[tuple[str, str]] | None = None) -> str:
    t = strip_questions(fix_register(s))
    t = strip_false_gaps(t, dados) or t
    t = trim_reaccion(t) or t
    return t or s


def sanitize(kind: str, data: dict[str, Any], keep_chain_terms: Iterable[str] | None = None,
             dados: Iterable[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Aplica todas las correcciones deterministas. Registra en data['ajustes'] qué se corrigió (para el docente)."""
    ajustes: list[str] = []

    def fix(key: str, fn) -> None:
        before = data.get(key, "")
        after = fn(before)
        if after != before:
            data[key] = after
            ajustes.append(key)

    if kind == "open":
        fix("pregunta", lambda s: one_question(fix_register(s), keep_chain_terms))
    else:
        fix("reaccion", lambda s: fix_reaccion(s, dados))
        if data.get("seguimiento"):
            fix("seguimiento", lambda s: one_question(fix_register(s)))
        before = list(data.get("vacios", []))
        data["vacios"] = clean_vacios(before)
        if data["vacios"] != before:
            ajustes.append("vacios")
    data["ajustes"] = ajustes
    return data


# ───────────── Cifras del equipo ─────────────

_NUM = re.compile(r"\d")


def team_figures(answers: Iterable[str], limit: int = 8) -> list[str]:
    """Fragmentos de las respuestas del equipo que contienen cifras, en orden y sin duplicados."""
    out: list[str] = []
    for a in answers:
        for frag in re.split(r"(?<=[.;])\s+|,\s+(?=[a-záéíóúñ])", a or ""):
            frag = frag.strip(" .;")
            if _NUM.search(frag) and frag not in out:
                out.append(frag)
    return out[-limit:]


# ───────────── Andamiaje determinista ─────────────

_CHECKLIST = [
    # (elemento, patrón que indica que el equipo ya lo dio, pregunta si falta)
    ("herramienta", r"\b(herramienta|sistema|plataforma|software|erp|mdm|tms|crm|api|aws|azure|gcp|excel|power ?bi|"
                    r"tablero|dashboard|script|orquestador|control plane)\b",
     "¿Qué herramienta o sistema concreto ejecutará lo que proponen?"),
    ("dueño", r"\b(due[ñn]o|responsable|l[ií]der|gerente|director[a]?|jefe|coordinador[a]?|rol|[aá]rea de|equipo de)\b",
     "¿Qué cargo concreto será el dueño de eso?"),
    ("cadencia", r"\b(diari|semanal|mensual|trimestral|quincenal|cada\s+\d|frecuencia|cadencia|por (d[ií]a|semana|mes))",
     "¿Con qué frecuencia se revisará?"),
    ("métrica y umbral", r"\d",
     "¿Qué métrica y qué umbral usarán para saber que funciona?"),
    ("indicador", r"\b(indicador|kpi|sla|otif|tasa|porcentaje|%)",
     "¿Con qué indicador le reportarán el avance al Comité?"),
]


def datos_ya_dados(answers: Iterable[str]) -> list[tuple[str, str]]:
    """(elemento, fragmento) de los elementos del _CHECKLIST que el equipo ya dio en el hilo, en el orden en que
    aparecen. Para que el modelo (y el respaldo determinista de strip_false_gaps) no reclame como faltante algo
    que ya está en el hilo — p. ej. "el responsable será el líder de TI" para el elemento 'dueño'."""
    found: dict[str, str] = {}
    for a in answers:
        for frag in re.split(r"(?<=[.;])\s+|,\s+(?=[a-záéíóúñ])", a or ""):
            frag = frag.strip(" .;")
            if not frag:
                continue
            for nombre, pat, _ in _CHECKLIST:
                if nombre in found:
                    continue
                if re.search(pat, frag, re.I) or (nombre == "herramienta" and re.search(r"\b[A-Z]{2,}\b", frag)):
                    found[nombre] = frag
    return list(found.items())


_TOPIC_TAIL = re.compile(r"\b(en|durante|sobre|para|con)\s+(.+)$", re.I)


def _topic(prev_question: str) -> str:
    """Frase final de 'prev_question' (el objeto de la preocupación), para que la plantilla de andamiaje no
    pierda el tema al reformular (p. ej. "la fase de convivencia"). Solo si hay un conector claro (en/durante/
    sobre/para/con): sin eso, es mejor no tocar la pregunta que adivinar un tema con las últimas palabras."""
    q = prev_question.strip(" ¿?")
    m = None
    for mm in _TOPIC_TAIL.finditer(q):
        m = mm  # la última coincidencia: la más cercana al final de la pregunta
    if m and 1 <= len(m.group(2).split()) <= 8:
        return m.group(2).strip(" ,.")
    return ""


def scaffold(prev_question: str, answers: Iterable[str]) -> dict[str, Any]:
    """Reacción y repregunta guiadas cuando el equipo no entiende y el modelo solo repite su pregunta."""
    text = " ".join(answers)
    tiene = [n for n, pat, _ in _CHECKLIST
             if re.search(pat, text, re.I) or (n == "herramienta" and re.search(r"\b[A-Z]{2,}\b", text))]
    falta = [(n, q) for n, _, q in _CHECKLIST if n not in tiene]
    nombre, pregunta = falta[0] if falta else ("detalle", "¿Qué dato concreto sustenta su propuesta?")
    tema = _topic(prev_question)
    if tema and _fold(tema) not in _fold(pregunta):
        pregunta = pregunta.rstrip("?") + f" {tema}?"
    base = f"Les aclaro a qué me refería con «{prev_question.strip(' ¿?')}»: para darlo por concreto necesito " \
           "herramienta, dueño, cadencia, métrica con umbral e indicador."
    base += f" De eso ya tengo {', '.join(tiene)}; " if tiene else " "
    base += f"empecemos por {nombre}."
    return {"reaccion": base, "seguimiento": pregunta}


# ───────────── Contradicciones de plazos ─────────────

# Frases de plazo sin cifra (equivalente aproximado en días) + menciones numéricas ("2 meses", "3 semanas"...).
_DURATION_WORDS = {
    "un día": 1.0, "un dia": 1.0, "unos días": 3.0, "unos dias": 3.0,
    "una semana": 7.0, "un par de semanas": 14.0, "unas semanas": 14.0,
    "un fin de semana": 2.0, "el fin de semana": 2.0,
    "un mes": 30.0, "un par de meses": 60.0,
}
_DURATION_NUM_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(d[ií]as?|semanas?|meses?)\b", re.I)
_UNIT_DAYS = {"dia": 1.0, "dias": 1.0, "día": 1.0, "días": 1.0,
              "semana": 7.0, "semanas": 7.0, "mes": 30.0, "meses": 30.0}


def team_durations(answers: Iterable[str]) -> list[tuple[float, str]]:
    """(días aproximados, fragmento textual) de cada plazo mencionado en las respuestas del equipo."""
    out: list[tuple[float, str]] = []
    for a in answers:
        low = (a or "").lower()
        for phrase, days in _DURATION_WORDS.items():
            if phrase in low:
                out.append((days, phrase))
        for m in _DURATION_NUM_RE.finditer(a or ""):
            n = float(m.group(1).replace(",", "."))
            out.append((n * _UNIT_DAYS[m.group(2).lower()], m.group(0)))
    return out


def duration_contradiction(answers: Iterable[str]) -> str:
    """Si el equipo dio plazos muy distintos entre sí en el hilo, describe la contradicción; si no, ''.

    Verificación simple (no semántica): compara el plazo más corto contra el más largo mencionados en
    cualquier respuesta del equipo. Pensada para el caso real de la validación con qwen2.5:3b: el equipo dijo
    "3 fases de 2 meses" y luego "un fin de semana" para la misma migración, y el modelo no lo cuestionó.
    """
    durs = team_durations(answers)
    if len(durs) < 2:
        return ""
    lo = min(durs, key=lambda d: d[0])
    hi = max(durs, key=lambda d: d[0])
    if hi[0] >= lo[0] * 4 and hi[0] - lo[0] >= 5:
        return f'mencionaron «{lo[1]}» y también «{hi[1]}»: los plazos no cuadran'
    return ""


# ───────────── Respuestas vagas ─────────────

_VAGUE_PHRASES = re.compile(
    r"\bbuenas pr[aá]cticas\b|\bseg[uú]n el est[aá]ndar\b|\bseg[uú]n los est[aá]ndares\b|"
    r"\blo definiremos despu[eé]s\b|\blo veremos despu[eé]s\b|\bm[aá]s adelante lo (definimos|vemos)\b",
    re.I,
)


def is_vague(answer: str) -> bool:
    """True si la respuesta no aporta nada nuevo: una frase genérica típica ("buenas prácticas", "según el
    estándar"...), o bien corta (≤12 palabras), sin cifras y sin ningún elemento del _CHECKLIST."""
    a = (answer or "").strip()
    if not a:
        return True
    if _VAGUE_PHRASES.search(a):
        return True
    if len(a.split()) > 12:
        return False
    sin_cifras = not _NUM.search(a)
    sin_concrecion = not any(re.search(pat, a, re.I) for nombre, pat, _ in _CHECKLIST if nombre != "métrica y umbral")
    return sin_cifras and sin_concrecion


# ───────────── Coherencia reacción / lectura (modo junta) ─────────────

_NEGATIVO = re.compile(r"\b(no (responde|responden|explica|explican|detalla|detallan|precisa|precisan|especifica|especifican|"
                       r"mencion|queda|convence|resuelve|aclara|dijeron)|falta|faltan|faltó|sin (datos|cifras|dueño|responsable|"
                       r"plazo|evidencia)|insuficiente|genéric|vag[oa]|contradic|no cuadra|pendiente|preocupa|dud)", re.I)
_POSITIVO = re.compile(r"\b(convence|resuelve|resuelto|resuelta|claro|clara|concret|me ayuda|ayuda a entender|responde|"
                       r"bien planteado|sólid|coherente|satisfac|queda cubierto|cubre)", re.I)


def coherencia_lectura(reaccion: str, lectura: str) -> str:
    """Evita lecturas que contradicen la reacción (p. ej. reacción positiva calificada como no_convence)."""
    txt = reaccion or ""
    sin_negadas = re.sub(r"\bno\s+\w+(\s+\w+)?", " ", txt, flags=re.I)   # «no responden», «no queda claro»
    neg, pos = bool(_NEGATIVO.search(txt)), bool(_POSITIVO.search(sin_negadas))
    if lectura == "no_convence" and pos and not neg:
        return "parcial"
    if lectura == "convence" and neg and not pos:
        return "parcial"
    return lectura


def lectura_por_respuesta(respuesta: str, lectura: str) -> tuple[str, str]:
    """Tope determinista a la lectura según la concreción de la respuesta del equipo (modo junta).

    El modelo pequeño califica «convence» respuestas genéricas y les atribuye datos del resumen de la propuesta que
    el equipo no dijo. Regla: sin cifras y con a lo sumo un elemento concreto (herramienta, dueño, cadencia,
    indicador) -> no_convence; sin cifras y con dos -> máximo parcial. Devuelve (lectura, nota para el docente)."""
    txt = re.sub(r"^[^:]{2,40}:\s*", "", (respuesta or "").strip())   # quita el «Nombre:» de quien respondió
    orden = {"no_convence": 0, "parcial": 1, "convence": 2}
    # Solo cuentan cifras fuertes (%, $, decimales o números de 2+ dígitos): «los próximos 4 años» no es un dato.
    if re.search(r"\d+\s*%|\$\s*\d|\d+[.,]\d+|\d{2,}", txt):
        return lectura, ""
    hits = sum(1 for n, pat, _ in _CHECKLIST if n != "métrica y umbral" and re.search(pat, txt, re.I))
    tope = "no_convence" if hits <= 1 else "parcial" if hits == 2 else "convence"
    if orden[lectura] <= orden[tope]:
        return lectura, ""
    return tope, f"Lectura ajustada a «{tope}»: la respuesta no trae cifras y casi no tiene elementos concretos."
