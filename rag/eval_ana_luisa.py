#!/usr/bin/env python3
"""
Vridik / JuliX — rag/eval_ana_luisa.py
Sprint S11-extra: criterio adicional de evaluación "¿Suena como Ana Luisa?"
(0-2 puntos), complementario al banco de evaluación de eval/evaluador.py
(que califica precisión normativa y alucinación, S5) — este módulo evalúa
específicamente el ESTILO pedido para la socia UGPP:

    "Responde como a Ana Luisa, socia UGPP: primero 3 bullets accionables,
    luego explicación simple, evita tecnicismos DIAN a menos que los
    definas, usa ejemplo numérico siempre." (ver julix/prompt_v3.txt)

Dos formas de usar este criterio:
  1. Heurística pura (`evaluar_estilo_heuristico`) — sin LLM, sin BD, sin
     Anthropic. Corre en cualquier CI. Es la que implementa este archivo.
  2. `CRITERIO_JUEZ_SUENA_COMO_ANA_LUISA` — texto listo para pegar en el
     `JUEZ_SYSTEM_PROMPT` de eval/evaluador.py si se quiere que el "Claude
     juez" califique este criterio junto con precision_normativa/
     hallucination_flag en la misma corrida (integración futura, no se
     modifica eval/evaluador.py en este entregable para no tocar el gate de
     S5 sin que el usuario lo pida explícitamente).

Puntaje (0-2), igual para ambos mecanismos:
  2 = cumple los 4 sub-criterios (bullets al inicio, explicación simple
      después, sin tecnicismo DIAN sin definir, ejemplo numérico presente).
  1 = cumple al menos 2 de los 4.
  0 = cumple 0 o 1.

USO (heurística, sin infraestructura real):
    python rag/eval_ana_luisa.py --demo

NO SE EJECUTA CONTRA ANTHROPIC REAL NI CONTRA UNA BASE DE DATOS REAL EN ESTE
ENTREGABLE.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- Criterio para el "Claude juez" de eval/evaluador.py (integración futura) ---
CRITERIO_JUEZ_SUENA_COMO_ANA_LUISA = """
  - suena_como_ana_luisa (0-2): ¿la respuesta sigue el estilo pedido para
    Ana Luisa, socia UGPP? Otorga:
      2 si TODO lo siguiente se cumple: (a) empieza con 3 bullets
        accionables, (b) sigue una explicación en lenguaje simple, (c) no
        usa tecnicismos DIAN sin definirlos, (d) incluye al menos un
        ejemplo numérico.
      1 si cumple al menos 2 de los 4 puntos anteriores.
      0 si cumple 0 o 1.
"""

# --- Heurística pura (sin LLM) -------------------------------------------
_RE_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+\S", re.MULTILINE)

# Términos técnicos de la DIAN/UGPP que se consideran "tecnicismo" si
# aparecen SIN una definición cercana (paréntesis, "es decir", "que
# significa", "esto es"). Lista deliberadamente acotada a los términos más
# opacos para un no-contador; UGPP/CST no cuentan como tecnicismo DIAN
# porque son el propio dominio del despacho, no jerga tributaria interna.
_TERMINOS_DIAN = [
    "ibc", "pila", "rut sancionatorio", "renta presuntiva", "iva descontable",
    "retefuente", "autorretención", "mecanismo de pago", "formulario 490",
    "sanción por inexactitud", "firmeza de la declaración",
]
_RE_DEFINICION_CERCANA = re.compile(
    r"(\(.{3,80}\)|es decir|que significa|esto es[,:])", re.IGNORECASE
)

# Ejemplo numérico: un número (con o sin separador de miles/decimales)
# acompañado de una unidad/monetaria/porcentual, o explícitamente marcado
# como "ejemplo".
_RE_EJEMPLO_NUMERICO = re.compile(
    r"(ejemplo[^.\n]{0,120}\d|"
    r"\$\s?[\d.,]+|"
    r"\d+[.,]?\d*\s?%|"
    r"\d+[.,]?\d*\s?(?:smlv|salarios? m[ií]nimos?|pesos|cop))",
    re.IGNORECASE,
)


@dataclass
class ResultadoEstiloAnaLuisa:
    puntos: int  # 0-2
    cumple_bullets_iniciales: bool
    cumple_explicacion_simple: bool
    evita_tecnicismos_no_definidos: bool
    tiene_ejemplo_numerico: bool
    detalle: list[str] = field(default_factory=list)


def _bullets_al_inicio(respuesta: str, *, max_lineas_iniciales: int = 15) -> bool:
    """Al menos 3 líneas-bullet dentro de las primeras `max_lineas_iniciales`
    líneas no vacías del texto — 'primero 3 bullets accionables'."""
    lineas = [l for l in respuesta.splitlines() if l.strip()][:max_lineas_iniciales]
    bloque_inicial = "\n".join(lineas)
    return len(_RE_BULLET.findall(bloque_inicial)) >= 3


def _explicacion_simple_despues(respuesta: str) -> bool:
    """Heurística mínima: después del bloque de bullets debe seguir un
    párrafo de prosa (no otra lista) de al menos 40 caracteres — 'luego
    explicación simple'."""
    lineas = [l for l in respuesta.splitlines() if l.strip()]
    idx_ultimo_bullet = -1
    for i, linea in enumerate(lineas):
        if _RE_BULLET.match(linea):
            idx_ultimo_bullet = i
    if idx_ultimo_bullet == -1:
        return False
    resto = "\n".join(lineas[idx_ultimo_bullet + 1 :]).strip()
    return len(resto) >= 40 and not _RE_BULLET.match(resto)


def _tecnicismos_no_definidos(respuesta: str) -> list[str]:
    """Retorna la lista de términos DIAN encontrados SIN definición cercana
    (mismo párrafo). Lista vacía = 'evita tecnicismos DIAN a menos que los
    definas' se cumple."""
    texto_lower = respuesta.lower()
    encontrados = []
    for termino in _TERMINOS_DIAN:
        idx = texto_lower.find(termino)
        if idx == -1:
            continue
        ventana = respuesta[max(0, idx - 80) : idx + len(termino) + 80]
        if not _RE_DEFINICION_CERCANA.search(ventana):
            encontrados.append(termino)
    return encontrados


def evaluar_estilo_heuristico(respuesta: str) -> ResultadoEstiloAnaLuisa:
    """Punto de entrada principal: evalúa el texto de una respuesta de
    JuliX contra el estilo pedido para Ana Luisa. Pura (sin I/O, sin red),
    apta para tests unitarios y para CI sin infraestructura real."""
    cumple_bullets = _bullets_al_inicio(respuesta)
    cumple_explicacion = _explicacion_simple_despues(respuesta)
    tecnicismos = _tecnicismos_no_definidos(respuesta)
    evita_tecnicismos = len(tecnicismos) == 0
    tiene_ejemplo = bool(_RE_EJEMPLO_NUMERICO.search(respuesta))

    sub_criterios_cumplidos = sum(
        [cumple_bullets, cumple_explicacion, evita_tecnicismos, tiene_ejemplo]
    )
    if sub_criterios_cumplidos == 4:
        puntos = 2
    elif sub_criterios_cumplidos >= 2:
        puntos = 1
    else:
        puntos = 0

    detalle = []
    if not cumple_bullets:
        detalle.append("No empieza con al menos 3 bullets accionables")
    if not cumple_explicacion:
        detalle.append("No hay explicación en prosa después de los bullets")
    if not evita_tecnicismos:
        detalle.append(f"Tecnicismos DIAN sin definir: {', '.join(tecnicismos)}")
    if not tiene_ejemplo:
        detalle.append("No incluye un ejemplo numérico")

    return ResultadoEstiloAnaLuisa(
        puntos=puntos,
        cumple_bullets_iniciales=cumple_bullets,
        cumple_explicacion_simple=cumple_explicacion,
        evita_tecnicismos_no_definidos=evita_tecnicismos,
        tiene_ejemplo_numerico=tiene_ejemplo,
        detalle=detalle,
    )


def generar_reporte_estilo(respuestas: dict[str, str]) -> dict:
    """Agrega evaluar_estilo_heuristico() sobre un lote {caso_id: respuesta}
    — mismo espíritu que rag/quality_gate.py: reporte agregado + motivos de
    los casos que no llegan a puntaje 2."""
    resultados = {caso_id: evaluar_estilo_heuristico(texto) for caso_id, texto in respuestas.items()}
    total = len(resultados)
    promedio = round(sum(r.puntos for r in resultados.values()) / total, 2) if total else 0.0
    return {
        "total_casos": total,
        "promedio_suena_como_ana_luisa": promedio,
        "casos_puntaje_2": [cid for cid, r in resultados.items() if r.puntos == 2],
        "casos_puntaje_1": [cid for cid, r in resultados.items() if r.puntos == 1],
        "casos_puntaje_0": [cid for cid, r in resultados.items() if r.puntos == 0],
        "detalle_por_caso": {
            cid: {"puntos": r.puntos, "motivos": r.detalle} for cid, r in resultados.items()
        },
    }


# --- Casos de demostración (sin datos reales de clientes) ----------------
_RESPUESTA_DEMO_BUENA = """- Ya tiene los soportes de pago completos para los 3 periodos objetados.
- El plazo para responder el requerimiento vence en 15 días hábiles.
- Recomendamos radicar la respuesta con las planillas antes del viernes.

En términos simples: la UGPP le está pidiendo que demuestre que sí pagó los
aportes de seguridad social de esos meses. Como ya tiene los recibos, solo
hay que anexarlos con un escrito breve.

Por ejemplo, si el aporte mensual promedio fue de $450.000 y hay 3 meses en
discusión, el valor total objetado es de $1.350.000 — el mismo monto que
ya está soportado en las planillas adjuntas.
"""

_RESPUESTA_DEMO_MALA_SIN_BULLETS = """La UGPP notificó un requerimiento de información dentro del proceso de
fiscalización. Es necesario revisar el IBC declarado y verificar la
autorretención aplicada en cada periodo, sin perjuicio de lo que
determine la firmeza de la declaración correspondiente.
"""


def _demo() -> int:
    print("=== Vridik/JuliX — rag/eval_ana_luisa.py (demo heurístico, sin LLM) ===\n")
    reporte = generar_reporte_estilo(
        {
            "demo-buena": _RESPUESTA_DEMO_BUENA,
            "demo-mala-sin-bullets-ni-ejemplo": _RESPUESTA_DEMO_MALA_SIN_BULLETS,
        }
    )
    print(json.dumps(reporte, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vridik/JuliX — criterio '¿Suena como Ana Luisa?' (0-2, heurístico, sin LLM)"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Corre el criterio contra 2 respuestas de ejemplo (una que cumple, una que no) y muestra el reporte JSON",
    )
    parser.add_argument(
        "--reporte", default=None,
        help="Si se pasa junto con --demo, además escribe el reporte JSON en esta ruta",
    )
    args = parser.parse_args()

    if not args.demo:
        print("Nada que ejecutar sin --demo (este módulo es una librería + demo, no un CLI de producción).")
        print("Uso: python rag/eval_ana_luisa.py --demo")
        return 0

    reporte = generar_reporte_estilo(
        {
            "demo-buena": _RESPUESTA_DEMO_BUENA,
            "demo-mala-sin-bullets-ni-ejemplo": _RESPUESTA_DEMO_MALA_SIN_BULLETS,
        }
    )
    print(json.dumps(reporte, ensure_ascii=False, indent=2))
    if args.reporte:
        Path(args.reporte).write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nReporte escrito en {args.reporte}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
