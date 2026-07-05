"""
Vridik — tests/test_cache.py (Sprint S11-extra)
3 tests puros (sin Anthropic, sin Postgres) sobre rag/cache.py y la
integración en julix/context_builder.py:
  1. Hit: una entrada recién guardada se recupera dentro de su TTL.
  2. Miss: una pregunta nunca cacheada dispara `generar_respuesta` y guarda
     el resultado.
  3. Expiración: una entrada con `created_at` viejo (más allá del TTL) ya
     no se retorna — se trata como miss.

Usa un archivo SQLite temporal por test (fixture `tmp_path` de pytest) para
no tocar data/rag_cache.db real ni depender de estado entre tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from rag.cache import RAGCache, hash_query, normalizar_query, ttl_horas_para_query
from julix.context_builder import METRICAS, obtener_respuesta_con_cache


def _cache_en(tmp_path):
    return RAGCache(db_path=tmp_path / "rag_cache_test.db")


def _forzar_created_at_antiguo(cache: RAGCache, query_hash: str, *, horas_atras: float) -> None:
    """Sobreescribe created_at directamente en SQLite para simular una
    entrada vieja, sin depender de mockear datetime.now()."""
    viejo = (datetime.now(timezone.utc) - timedelta(hours=horas_atras)).isoformat()
    cache._conn.execute(
        "UPDATE rag_cache SET created_at = ? WHERE query_hash = ?", (viejo, query_hash)
    )
    cache._conn.commit()


def test_hit_devuelve_respuesta_cacheada_sin_llamar_generar_respuesta(tmp_path):
    cache = _cache_en(tmp_path)
    query = "¿Cuál es el plazo para responder un requerimiento de la UGPP?"
    query_hash = RAGCache.hash_query(query)
    cache.set(query_hash, "Respuesta cacheada", ["Ley 1607 de 2012, Art. 178"], 250)

    METRICAS["cache_hits"] = 0
    METRICAS["cache_misses"] = 0
    llamadas = {"n": 0}

    def generar_respuesta():
        llamadas["n"] += 1
        return "NUNCA debería llamarse", [], 0

    respuesta, fuentes, tokens, from_cache = obtener_respuesta_con_cache(
        query=query, generar_respuesta=generar_respuesta, cache=cache
    )

    assert from_cache is True
    assert respuesta == "Respuesta cacheada"
    assert fuentes == ["Ley 1607 de 2012, Art. 178"]
    assert tokens == 250
    assert llamadas["n"] == 0  # nunca se llamó a generar_respuesta
    assert METRICAS["cache_hits"] == 1
    assert METRICAS["cache_misses"] == 0


def test_miss_llama_generar_respuesta_y_guarda_en_cache(tmp_path):
    cache = _cache_en(tmp_path)
    query = "¿Qué recursos proceden contra una liquidación oficial de la UGPP?"

    METRICAS["cache_hits"] = 0
    METRICAS["cache_misses"] = 0
    llamadas = {"n": 0}

    def generar_respuesta():
        llamadas["n"] += 1
        return "Respuesta generada por JuliX", ["CPACA, Art. 74"], 480

    respuesta, fuentes, tokens, from_cache = obtener_respuesta_con_cache(
        query=query, generar_respuesta=generar_respuesta, cache=cache
    )

    assert from_cache is False
    assert respuesta == "Respuesta generada por JuliX"
    assert llamadas["n"] == 1
    assert METRICAS["cache_misses"] == 1
    assert METRICAS["cache_hits"] == 0

    # La segunda vez con la misma pregunta ya debe ser hit (se guardó en set()).
    respuesta2, _, _, from_cache2 = obtener_respuesta_con_cache(
        query=query, generar_respuesta=generar_respuesta, cache=cache
    )
    assert from_cache2 is True
    assert respuesta2 == "Respuesta generada por JuliX"
    assert llamadas["n"] == 1  # sigue en 1: la segunda vez fue hit, no volvió a generar


def test_entrada_expirada_se_trata_como_miss(tmp_path):
    cache = _cache_en(tmp_path)
    query = "¿Cuál es el estado del expediente radicado 2024-01239?"
    query_hash = RAGCache.hash_query(query)

    cache.set(query_hash, "Respuesta vieja", [], 100)
    # Pregunta normal (no-definición) -> TTL de 24h; la forzamos a 30h de antigüedad.
    assert ttl_horas_para_query(query) == 24
    _forzar_created_at_antiguo(cache, query_hash, horas_atras=30)

    METRICAS["cache_hits"] = 0
    METRICAS["cache_misses"] = 0
    llamadas = {"n": 0}

    def generar_respuesta():
        llamadas["n"] += 1
        return "Respuesta nueva tras expiración", ["Auto ADC-2024-01239"], 300

    respuesta, fuentes, tokens, from_cache = obtener_respuesta_con_cache(
        query=query, generar_respuesta=generar_respuesta, cache=cache
    )

    assert from_cache is False  # expiró -> se trata como miss
    assert respuesta == "Respuesta nueva tras expiración"
    assert llamadas["n"] == 1
    assert METRICAS["cache_misses"] == 1
    assert METRICAS["cache_hits"] == 0


def test_ttl_definicion_es_7_dias_y_normal_es_24_horas():
    assert ttl_horas_para_query("¿Qué es el IBC?") == 24 * 7
    assert ttl_horas_para_query("definición de mora presunta") == 24 * 7
    assert ttl_horas_para_query("¿Cuál es el plazo para responder la UGPP?") == 24


def test_normalizar_query_ignora_mayusculas_acentos_y_espacios():
    a = normalizar_query("¿Qué   es el IBC?")
    b = normalizar_query("¿que es el ibc?")
    assert a == b
    assert hash_query("¿Qué   es el IBC?") == hash_query("¿que es el ibc?")
