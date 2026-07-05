"""
JuliX — context_builder.py
Arma el contexto que se envía a Claude respetando un presupuesto de tokens
por parte del documento, priorizando por jerarquía kelseniana y vigencia
normativa (ver corpus_documents/corpus_chunks, Sprint S7).

Sprint S11-extra (personalización): boost condicional por usuario. Cuando
`construir_contexto(..., user_id="ana_luisa")`, los chunks etiquetados
"explicación_simple" (ver `RankedChunk.etiquetas`) se priorizan en el orden
final — antes del truncado por presupuesto — para que Ana Luisa (socia a
cargo de UGPP) reciba con más frecuencia el material redactado en términos
simples en vez de la fuente técnica cruda, cuando ambas están disponibles
para el mismo punto. Para cualquier otro usuario (o user_id=None) el orden
no cambia: sigue siendo puramente jerarquía kelseniana + vigencia (S7).

Sprint S11-extra (cache): `obtener_respuesta_con_cache()` es el punto de
entrada que revisa rag/cache.py (SQLite, data/rag_cache.db) ANTES de que el
caller invoque a Anthropic. Recibe la generación real como un callback
(`generar_respuesta`) en vez de importar julix/client.py directamente —
evita acoplar este módulo (que hoy no depende de red) a una llamada real, y
hace trivial testear hit/miss/expiración con un callback falso. Si hay hit
vigente, no se llama `generar_respuesta` y se suma 1 a
`METRICAS["cache_hits"]`; si hay miss (o la entrada expiró según el TTL de
la pregunta — 24h UGPP / 7 días definiciones, ver
`rag.cache.ttl_horas_para_query`), se llama `generar_respuesta()` una vez y
el resultado se guarda en cache antes de retornarlo.

NO SE EJECUTA EN ESTE ENTREGABLE — esqueleto de referencia para Sprint S4.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Repo layout: julix/ y rag/ son hermanos en la raíz (mismo patrón de
# sys.path que eval/evaluador.py usa para importar julix.* desde eval/).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rag.cache import RAGCache, ttl_horas_para_query  # noqa: E402

# --- S11-extra: personalización por usuario -----------------------------
USER_ID_ANA_LUISA = "ana_luisa"
ETIQUETA_EXPLICACION_SIMPLE = "explicación_simple"

# --- S11-extra: métricas de cache (contador en memoria del proceso) ------
METRICAS: dict[str, int] = {"cache_hits": 0, "cache_misses": 0}


@dataclass
class ContextBudget:
    """Presupuesto de tokens por parte del documento final. Los valores son
    de partida; se recalibran con datos reales del banco de evaluación (S5)."""

    total_tokens: int = 100_000
    instrucciones_tokens: int = 1_500       # instrucciones del sistema / rol de JuliX
    expediente_tokens: int = 20_000         # hechos del caso, cliente, historial
    corpus_tokens: int = 60_000             # chunks del RAG (S7-S9)
    patron_oro_tokens: int = 10_000         # ejemplos del banco cuando aplique (S6)
    margen_respuesta_tokens: int = 8_500    # reservado para la salida del modelo


@dataclass
class RankedChunk:
    referencia: str          # p.ej. "Art. 33 CST"
    jerarquia: int             # menor = mayor jerarquía (Constitución=1, Ley=2, Decreto=3, ...)
    vigente: bool
    tokens: int
    contenido: str
    # S11-extra: etiquetas de contenido (p.ej. "explicación_simple") usadas
    # por el boost de personalización de aplicar_boost_personalizacion().
    # Opcional y con default vacío — no rompe construcciones existentes.
    etiquetas: list[str] = field(default_factory=list)


def ordenar_por_prioridad_normativa(chunks: list[RankedChunk]) -> list[RankedChunk]:
    """Ordena chunks priorizando jerarquía kelseniana y vigencia. Lo derogado
    nunca se descarta del corpus (relevancia retroactiva), pero se posterga
    en el orden salvo que el caso pida explícitamente norma histórica."""
    return sorted(chunks, key=lambda c: (not c.vigente, c.jerarquia))


def aplicar_boost_personalizacion(
    chunks: list[RankedChunk], *, user_id: str | None
) -> list[RankedChunk]:
    """S11-extra: si `user_id` es Ana Luisa, sube al frente los chunks
    etiquetados 'explicación_simple' — usa un sort estable, así que dentro de
    cada grupo (etiquetado / no etiquetado) se conserva el orden que ya trajo
    `ordenar_por_prioridad_normativa` (jerarquía + vigencia). Para cualquier
    otro usuario retorna la lista sin tocar; nunca cambia el orden para
    usuarios distintos a Ana Luisa."""
    if user_id != USER_ID_ANA_LUISA:
        return chunks
    return sorted(chunks, key=lambda c: ETIQUETA_EXPLICACION_SIMPLE not in c.etiquetas)


def truncar_con_criterio(chunks: list[RankedChunk], presupuesto_tokens: int) -> list[RankedChunk]:
    """Trunca por relevancia jurídica, no por corte ciego de caracteres:
    se van incluyendo chunks ya ordenados hasta agotar el presupuesto;
    un chunk que no cabe completo se descarta entero (nunca se corta a la mitad
    un artículo o una sección de sentencia)."""
    seleccionados: list[RankedChunk] = []
    tokens_usados = 0
    for chunk in chunks:
        if tokens_usados + chunk.tokens > presupuesto_tokens:
            continue
        seleccionados.append(chunk)
        tokens_usados += chunk.tokens
    return seleccionados


@dataclass
class BuiltContext:
    system_prompt: str
    user_content: str
    chunks_incluidos: list[str] = field(default_factory=list)  # referencias citables, para el validador de citas
    tokens_estimados: int = 0


def construir_contexto(
    *,
    instrucciones: str,
    expediente_texto: str,
    chunks_candidatos: list[RankedChunk],
    presupuesto: ContextBudget = ContextBudget(),
    user_id: str | None = None,
) -> BuiltContext:
    """Punto de entrada único usado por service.py. El resultado alimenta
    directamente a client.stream_completion(). Las referencias en
    `chunks_incluidos` son las que el validador de citas post-generación
    (S7) usa para verificar que toda cita del borrador corresponde a una
    referencia realmente presente en el contexto enviado.

    `user_id` (S11-extra, opcional): si es "ana_luisa", aplica el boost de
    aplicar_boost_personalizacion() antes de truncar por presupuesto — para
    cualquier otro valor (incluido None, el caso normal) el comportamiento
    es idéntico al de antes de S11-extra."""
    chunks_ordenados = ordenar_por_prioridad_normativa(chunks_candidatos)
    chunks_ordenados = aplicar_boost_personalizacion(chunks_ordenados, user_id=user_id)
    chunks_finales = truncar_con_criterio(chunks_ordenados, presupuesto.corpus_tokens)

    corpus_texto = "\n\n".join(f"[{c.referencia}]\n{c.contenido}" for c in chunks_finales)
    user_content = (
        f"## Expediente\n{expediente_texto}\n\n"
        f"## Fuentes normativas y jurisprudenciales disponibles\n{corpus_texto}"
    )

    return BuiltContext(
        system_prompt=instrucciones,
        user_content=user_content,
        chunks_incluidos=[c.referencia for c in chunks_finales],
        tokens_estimados=presupuesto.instrucciones_tokens + presupuesto.expediente_tokens
        + sum(c.tokens for c in chunks_finales),
    )


def obtener_respuesta_con_cache(
    *,
    query: str,
    generar_respuesta: Callable[[], tuple[str, list, int]],
    cache: RAGCache | None = None,
) -> tuple[str, list, int, bool]:
    """S11-extra: punto de entrada que el caller (julix/service.py) usa
    ANTES de invocar a Anthropic. `generar_respuesta` es un callback sin
    argumentos que, al ejecutarse, hace la llamada real (vía
    julix/client.py) y retorna (respuesta, fuentes, tokens) — se ejecuta
    como máximo una vez, solo en caso de miss.

    Retorna (respuesta, fuentes, tokens, from_cache):
      - Hit vigente: NO se llama `generar_respuesta`; se suma 1 a
        METRICAS["cache_hits"]; from_cache=True.
      - Miss (o entrada expirada): se llama `generar_respuesta()`, se
        guarda en cache con `rag.cache.RAGCache.set()`, se suma 1 a
        METRICAS["cache_misses"]; from_cache=False.

    El TTL aplicado (24h o 7 días) se decide con
    `rag.cache.ttl_horas_para_query(query)` y se usa tanto para el chequeo
    de vigencia en `get()` como, implícitamente, para la próxima lectura de
    esta misma pregunta — la tabla no guarda el TTL por fila (ver
    rag/cache.py), así que ambas puntas deben clasificar la misma query."""
    cache = cache or RAGCache()
    query_hash = RAGCache.hash_query(query)
    ttl_horas = ttl_horas_para_query(query)

    resultado_cacheado = cache.get(query_hash, ttl_horas=ttl_horas)
    if resultado_cacheado is not None:
        METRICAS["cache_hits"] += 1
        respuesta, fuentes, tokens = resultado_cacheado
        return respuesta, fuentes, tokens, True

    METRICAS["cache_misses"] += 1
    respuesta, fuentes, tokens = generar_respuesta()
    cache.set(query_hash, respuesta, fuentes, tokens)
    return respuesta, fuentes, tokens, False
