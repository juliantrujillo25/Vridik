"""
Vridik / JuliX — julix/router.py
Sprint S6 (preparación de plugins, sin instalar aún): enrutador de área
temática. Decide a qué tarea de JuliX enviar una pregunta ANTES de construir
el contexto (RAG, ver rag/context_builder.py) y llamar al modelo — así cada
área usa su prompt calibrado correspondiente:

    'ugpp'    -> tarea 'ugpp_demanda'      (julix/prompts/v1_ugpp_demanda.md)
    'laboral' -> tarea 'laboral_consulta'  (julix/prompts/v2_laboral_consulta.md)
                 o 'laboral_colombia'      (julix/prompts/v3_laboral_colombia.md, litigio)
    'litigio' -> tarea 'litigio_colombia'  (julix/prompts/v3_litigio_colombia.md)

Estrategia: heurística de palabras clave en español — rápida, gratis y
determinística, sin llamar a Claude. Es deliberadamente simple para S6; un
clasificador por IA (Haiku, tarea 'clasificacion_documento') es la evolución
natural si la heurística demuestra ser insuficiente en el banco de S5/S6,
pero eso es una decisión con datos, no algo que se justifique agregar hoy
sin evidencia de que la heurística falla.

NO SE EJECUTA CONTRA ANTHROPIC EN ESTE MÓDULO — es puro Python, sin red.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AREA_UGPP = "ugpp"
AREA_LABORAL = "laboral"
AREA_LITIGIO = "litigio"

VALID_AREAS = (AREA_UGPP, AREA_LABORAL, AREA_LITIGIO)

# Señal fuerte e inequívoca: si aparece literalmente "ugpp", es UGPP.
_PALABRAS_UGPP = [
    "ugpp", "parafiscal", "parafiscales", "autoliquidaci", "aportes al sistema",
    "aporte patronal", "pila", "inexactitud en la autoliquidaci", "cotización al sistema",
    "ibc", "ingreso base de cotización", "sanción por omisión", "sanción por inexactitud",
]

# Señales procesales/de litigio: si aparecen, casi siempre dominan sobre el
# tema sustantivo (una "demanda laboral" es litigio, no laboral_consulta).
_PALABRAS_LITIGIO = [
    "demanda", "contestación de la demanda", "recurso de apelación", "recurso de reposición",
    "recurso de casación", "medio de control", "nulidad y restablecimiento", "reparación directa",
    "caducidad", "audiencia de conciliación", "audiencia de trámite", "audiencia de juzgamiento",
    "cpaca", "consejo de estado", "corte suprema de justicia", "juzgado laboral", "tribunal administrativo",
    "excepciones de mérito", "radicar", "proceso ordinario laboral", "instaurar el proceso",
]

# Señales laborales sustantivas (consulta, no litigio).
_PALABRAS_LABORAL = [
    "despido", "cst", "código sustantivo del trabajo", "horas extra", "prestaciones sociales",
    "cesantías", "indemnización", "contrato de trabajo", "acoso laboral", "estabilidad laboral",
    "vacaciones", "fuero de maternidad", "liquidación laboral", "prima de servicios",
    "terminación del contrato", "justa causa", "contrato a término fijo", "contrato a término indefinido",
]

_TIEBREAK_ORDEN = (AREA_UGPP, AREA_LITIGIO, AREA_LABORAL)
_AREA_POR_DEFECTO = AREA_LABORAL  # catch-all razonable: la mayoría de consultas del despacho son laborales/UGPP


@dataclass
class ResultadoRuteo:
    area: str
    scores: dict[str, int]
    motivo: str


def _normalizar(texto: str) -> str:
    return texto.lower().strip()


def _contar_coincidencias(texto_normalizado: str, palabras_clave: list[str]) -> int:
    return sum(1 for palabra in palabras_clave if palabra in texto_normalizado)


def clasificar(pregunta: str) -> ResultadoRuteo:
    """Devuelve el resultado completo del ruteo (área + scores + motivo),
    útil para logging/depuración. route_by_area() es el atajo que solo
    retorna el área."""
    texto = _normalizar(pregunta)

    # Señal literal "ugpp" es determinante de inmediato (evita que una
    # pregunta que mezcla "ugpp" y "despido" se vaya a laboral por conteo).
    if re.search(r"\bugpp\b", texto):
        return ResultadoRuteo(area=AREA_UGPP, scores={AREA_UGPP: 1}, motivo="mención literal de 'UGPP'")

    scores = {
        AREA_UGPP: _contar_coincidencias(texto, _PALABRAS_UGPP),
        AREA_LITIGIO: _contar_coincidencias(texto, _PALABRAS_LITIGIO),
        AREA_LABORAL: _contar_coincidencias(texto, _PALABRAS_LABORAL),
    }

    max_score = max(scores.values())
    if max_score == 0:
        return ResultadoRuteo(
            area=_AREA_POR_DEFECTO, scores=scores,
            motivo="sin señales claras de ninguna área; se usa el catch-all por defecto",
        )

    ganadores = [area for area in _TIEBREAK_ORDEN if scores[area] == max_score]
    area_elegida = ganadores[0]  # _TIEBREAK_ORDEN ya refleja la prioridad en empate
    return ResultadoRuteo(
        area=area_elegida, scores=scores,
        motivo=f"mayor conteo de palabras clave ({max_score}) para '{area_elegida}'"
        + (" (desempate por prioridad ugpp > litigio > laboral)" if len(ganadores) < len({a for a, s in scores.items() if s == max_score}) or len([a for a in scores if scores[a] == max_score]) > 1 else ""),
    )


def route_by_area(pregunta: str) -> str:
    """Punto de entrada usado por julix/service.py (o por api/julix_endpoint.py
    antes de llamar al service) para decidir la tarea/prompt correcto.
    Siempre retorna una de: 'ugpp' | 'laboral' | 'litigio'."""
    if not pregunta or not pregunta.strip():
        return _AREA_POR_DEFECTO
    return clasificar(pregunta).area


# Mapeo de área -> tarea de JuliX (prompt versionado). service.py puede usar
# esto directamente: tarea = TAREA_POR_AREA[route_by_area(pregunta)]
TAREA_POR_AREA: dict[str, str] = {
    AREA_UGPP: "ugpp_demanda",
    AREA_LABORAL: "laboral_consulta",
    AREA_LITIGIO: "litigio_colombia",
}
