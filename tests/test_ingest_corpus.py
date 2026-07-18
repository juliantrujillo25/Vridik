"""
Vridik — tests/test_ingest_corpus.py
rag/ingest_corpus.py (Sprint S7) nunca había tenido tests propios -- solo
rag/quality_gate.py (tests/test_rag_quality.py) estaba cubierto. Esto cubre
la lógica pura del pipeline (sin BD, sin embeddings, sin PDFs reales):
lectura/validación del manifiesto, filtrado por prioridad (incl. alias
en inglés), chunking con solape, dedup por hash, año/tribunal inferidos,
paginación de lotes, y la simulación de dry-run end-to-end.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from rag.ingest_corpus import (
    FilaManifiesto,
    chunkear_texto,
    filtrar_por_prioridad,
    inferir_anio,
    inferir_tribunal,
    leer_manifiesto,
    seleccionar_lote,
    simular_extraccion_y_chunking,
    _contar_tokens_aprox,
    _hash_dedup,
)


def _escribir_manifiesto(tmp_path: Path, filas: list[dict]) -> Path:
    path = tmp_path / "manifest.csv"
    columnas = ["fuente", "tipo", "norma", "articulos_clave", "prioridad"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(filas)
    return path


# --- leer_manifiesto ---------------------------------------------------

def test_leer_manifiesto_columnas_faltantes_levanta_error(tmp_path):
    path = tmp_path / "manifest.csv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("fuente,tipo,norma\ndata/x.pdf,ley,Ley 1 de 2020\n")
    with pytest.raises(ValueError, match="columnas requeridas"):
        leer_manifiesto(path)


def test_leer_manifiesto_omite_tipo_desconocido(tmp_path):
    path = _escribir_manifiesto(tmp_path, [
        {"fuente": "data/a.pdf", "tipo": "ley", "norma": "Ley 1 de 2020", "articulos_clave": "Art. 1", "prioridad": "alta"},
        {"fuente": "data/b.pdf", "tipo": "doctrina", "norma": "Concepto X", "articulos_clave": "N/A", "prioridad": "baja"},
    ])
    filas = leer_manifiesto(path)
    assert len(filas) == 1
    assert filas[0].norma == "Ley 1 de 2020"


def test_leer_manifiesto_normaliza_prioridad_en_ingles(tmp_path):
    path = _escribir_manifiesto(tmp_path, [
        {"fuente": "data/a.pdf", "tipo": "ley", "norma": "Ley 1 de 2020", "articulos_clave": "Art. 1", "prioridad": "HIGH"},
    ])
    filas = leer_manifiesto(path)
    assert filas[0].prioridad == "alta"


# --- filtrar_por_prioridad ----------------------------------------------

def _filas_de_prueba() -> list[FilaManifiesto]:
    return [
        FilaManifiesto("data/a.pdf", "ley", "Ley 1", "Art. 1", "alta"),
        FilaManifiesto("data/b.pdf", "decreto", "Decreto 2", "Art. 2", "media"),
        FilaManifiesto("data/c.pdf", "jurisprudencia", "Sentencia 3", "N/A", "baja"),
    ]


def test_filtrar_por_prioridad_alta():
    filas = _filas_de_prueba()
    assert [f.norma for f in filtrar_por_prioridad(filas, "alta")] == ["Ley 1"]


def test_filtrar_por_prioridad_alias_ingles():
    filas = _filas_de_prueba()
    assert [f.norma for f in filtrar_por_prioridad(filas, "high")] == ["Ley 1"]


def test_filtrar_por_prioridad_todas_no_filtra():
    filas = _filas_de_prueba()
    assert len(filtrar_por_prioridad(filas, "todas")) == 3


# --- chunkear_texto -------------------------------------------------------

def test_chunkear_texto_vacio_devuelve_lista_vacia():
    assert chunkear_texto("") == []
    assert chunkear_texto("   ") == []


def test_chunkear_texto_corto_es_un_solo_chunk():
    texto = "artículo primero de la norma de prueba " * 5
    chunks = chunkear_texto(texto)
    assert len(chunks) == 1
    assert chunks[0] == texto.strip()


def test_chunkear_texto_largo_produce_varios_chunks_con_solape():
    # 600 tokens/chunk a 0.75 palabras/token = 450 palabras por chunk,
    # solape de 120 tokens = 90 palabras -> paso de 360 palabras.
    palabras = [f"palabra{i}" for i in range(1000)]
    texto = " ".join(palabras)
    chunks = chunkear_texto(texto)

    assert len(chunks) > 1
    # El chunk 2 debe empezar en una palabra anterior al final del chunk 1
    # (el solape real, no chunks disjuntos).
    primer_chunk_palabras = chunks[0].split()
    segundo_chunk_palabras = chunks[1].split()
    assert segundo_chunk_palabras[0] in primer_chunk_palabras[-100:]
    # Ningún chunk debe superar el tamaño configurado (450 palabras).
    assert all(len(c.split()) <= 450 for c in chunks)
    # El texto original se reconstruye sin perder palabras al final.
    assert chunks[-1].split()[-1] == palabras[-1]


def test_chunkear_texto_progresa_siempre_incluso_con_solape_grande():
    # Regresión de guardia: si CHUNK_OVERLAP_TOKENS >= CHUNK_SIZE_TOKENS el
    # paso podría llegar a 0 y colgar en loop infinito -- `chunkear_texto`
    # ya protege con max(1, ...), esto solo confirma que termina.
    texto = " ".join(f"w{i}" for i in range(2000))
    chunks = chunkear_texto(texto)
    assert len(chunks) > 0


# --- hash dedup + conteo de tokens ---------------------------------------

def test_hash_dedup_es_determinista_y_sensible_al_contenido():
    a = _hash_dedup("mismo texto")
    b = _hash_dedup("mismo texto")
    c = _hash_dedup("texto distinto")
    assert a == b
    assert a != c


def test_contar_tokens_aprox_nunca_es_cero():
    assert _contar_tokens_aprox("") == 1
    assert _contar_tokens_aprox("una palabra") >= 1


# --- inferir_anio / inferir_tribunal --------------------------------------

def test_inferir_anio_toma_el_ultimo_anio_del_texto():
    assert inferir_anio("Ley 1607 de 2012") == 2012
    assert inferir_anio("Sentencia SU-213 de 2024, cita la Ley 1010 de 2006") == 2006
    assert inferir_anio("norma sin año") is None


def test_inferir_tribunal_solo_aplica_a_jurisprudencia():
    assert inferir_tribunal("ley", "Consejo de Estado, rad. 123") is None
    assert inferir_tribunal("jurisprudencia", "Consejo de Estado, Sección Cuarta") == "Consejo de Estado"
    assert inferir_tribunal("jurisprudencia", "Providencia sin tribunal identificado") == "Tribunal no identificado (revisar en curaduría)"


# --- seleccionar_lote -----------------------------------------------------

def test_seleccionar_lote_pagina_offset_y_limit():
    filas = _filas_de_prueba()
    assert [f.norma for f in seleccionar_lote(filas, offset=1, limit=1)] == ["Decreto 2"]
    assert [f.norma for f in seleccionar_lote(filas, offset=0, limit=None)] == ["Ley 1", "Decreto 2", "Sentencia 3"]


# --- simular_extraccion_y_chunking (dry-run real, sin BD/embeddings) -----

def test_simular_extraccion_reporta_archivos_no_encontrados_sin_inventar_chunks(tmp_path):
    lote = [FilaManifiesto(str(tmp_path / "no-existe.pdf"), "ley", "Ley X", "Art. 1", "alta")]
    resultado = simular_extraccion_y_chunking(lote)
    assert resultado["archivos_encontrados"] == 0
    assert resultado["archivos_no_encontrados"] == 1
    assert resultado["chunks_generados"] == 0
    assert resultado["detalle_no_encontrados"] == [str(tmp_path / "no-existe.pdf")]


def test_manifiesto_real_del_repo_se_lee_sin_error():
    """El manifiesto real (data/corpus_manifest.csv) usado en producción
    debe seguir siendo válido contra el parser real -- regresión de
    formato, no de contenido."""
    path = Path("data/corpus_manifest.csv")
    assert path.exists(), "data/corpus_manifest.csv debe existir en el repo"
    filas = leer_manifiesto(path)
    assert len(filas) > 0
    assert all(f.prioridad in ("alta", "media", "baja") for f in filas)
    assert all(f.tipo in ("ley", "decreto", "jurisprudencia") for f in filas)
