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
    "garantizarías": "garantizarían", "asegurarías": "asegurarían", "definirías": "definirían", "tú": "ustedes",
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


def fix_register(text: str) -> str:
    return _REG_RE.sub(lambda m: _match_case(m.group(0), _REGISTRO[m.group(0).lower()]), text or "")


def one_question(text: str) -> str:
    """Deja una sola pregunta: quita el prefijo de hablante, lo que sigue al primer '?' y la segunda pregunta encadenada."""
    t = _SPEAKER.sub("", (text or "").strip())
    if "?" in t:
        t = t[: t.index("?") + 1]
    m = _CHAIN.search(t)
    if m and t.endswith("?") and len(t[: m.start()].split()) >= 4:  # la primera parte ya es una pregunta completa
        t = t[: m.start()].rstrip(" ,;") + "?"
    if t.endswith("?") and "¿" not in t:
        t = "¿" + t[0].lower() + t[1:]
    return t.strip()


def strip_questions(text: str) -> str:
    """Quita de la reacción cualquier oración interrogativa (la pregunta va en 'seguimiento')."""
    t = _SPEAKER.sub("", (text or "").strip())
    t = re.sub(r"¿[^?]*\?", "", t)
    t = re.sub(r"[^.!¡¿?]*\?", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,;")


def clean_vacios(items: Iterable[str]) -> list[str]:
    return [v for v in items if v.strip() and not any(p in v.lower() for p in _TEMPLATE_VACIOS)]


def sanitize(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Aplica todas las correcciones deterministas. Registra en data['ajustes'] qué se corrigió (para el docente)."""
    ajustes: list[str] = []

    def fix(key: str, fn) -> None:
        before = data.get(key, "")
        after = fn(before)
        if after != before:
            data[key] = after
            ajustes.append(key)

    if kind == "open":
        fix("pregunta", lambda s: one_question(fix_register(s)))
    else:
        fix("reaccion", lambda s: strip_questions(fix_register(s)) or s)
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


def scaffold(prev_question: str, answers: Iterable[str]) -> dict[str, Any]:
    """Reacción y repregunta guiadas cuando el equipo no entiende y el modelo solo repite su pregunta."""
    text = " ".join(answers)
    tiene = [n for n, pat, _ in _CHECKLIST
             if re.search(pat, text, re.I) or (n == "herramienta" and re.search(r"\b[A-Z]{2,}\b", text))]
    falta = [(n, q) for n, _, q in _CHECKLIST if n not in tiene]
    nombre, pregunta = falta[0] if falta else ("detalle", "¿Qué dato concreto sustenta su propuesta?")
    base = f"Les aclaro a qué me refería con «{prev_question.strip(' ¿?')}»: para darlo por concreto necesito " \
           "herramienta, dueño, cadencia, métrica con umbral e indicador."
    base += f" De eso ya tengo {', '.join(tiene)}; " if tiene else " "
    base += f"empecemos por {nombre}."
    return {"reaccion": base, "seguimiento": pregunta}
