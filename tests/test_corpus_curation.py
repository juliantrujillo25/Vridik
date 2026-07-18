"""
Vridik — tests/test_corpus_curation.py
core/corpus_curation.py (roadmap S7: mini-herramienta de curaduría del
corpus legal). Dos capas:
  - Puras (sin BD): extracción de texto de PDF, heurística de año/tribunal.
  - Con Postgres real (fixture `db`, se salta sin TEST_DATABASE_URL): ciclo
    de vida completo del borrador (crear -> editar -> publicar/descartar).

`publicar_borrador` en producción real llama a rag/context_builder.py::
embeber_texto (carga sentence-transformers) e inserta en `rag_chunks`
(requiere pgvector) -- ninguna de las dos cosas está disponible en el
service container de Postgres del job `test` de CI (solo `validate-sql` la
tiene, ver ci.yml). Los tests de publicación acá mockean `insertar_chunk`
para probar la lógica de validación/transición de estado (que sí es
responsabilidad de este módulo) sin depender de esa infraestructura pesada
-- mismo criterio ya usado en el resto del repo para código que llama a
Anthropic/embeddings reales (ver tests/test_julix*.py).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from core.corpus_curation import (
    BorradorNoEditableError,
    BorradorNoEncontradoError,
    MetadataIncompletaError,
    PdfSinTextoError,
    PrioridadInvalidaError,
    TipoFuenteInvalidoError,
    _sugerir_anio_y_tribunal,
    actualizar_borrador,
    crear_borrador,
    descartar_borrador,
    ensure_corpus_drafts_table,
    extraer_texto_de_pdf_bytes,
    listar_borradores,
    obtener_borrador,
    publicar_borrador,
)


def _pdf_con_texto(texto: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf)
    for i, linea in enumerate(texto.split("\n")):
        c.drawString(72, 750 - i * 14, linea)
    c.save()
    return buf.getvalue()


# --- puras: extracción de PDF ---------------------------------------------

def test_extraer_texto_de_pdf_bytes_extrae_texto_real():
    pdf = _pdf_con_texto("Articulo 178 de la Ley 1607 de 2012.")
    texto = extraer_texto_de_pdf_bytes(pdf)
    assert "1607" in texto
    assert "178" in texto


def test_extraer_texto_de_pdf_bytes_pdf_vacio_de_texto_levanta_error():
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.save()  # página en blanco, sin texto
    pdf = buf.getvalue()
    with pytest.raises(PdfSinTextoError):
        extraer_texto_de_pdf_bytes(pdf)


# --- puras: heurística de año/tribunal ------------------------------------

def test_sugerir_anio_y_tribunal_desde_nombre_de_archivo():
    anio, tribunal = _sugerir_anio_y_tribunal(
        "SL17063-2017 Corte Suprema de Justicia.pdf", "texto irrelevante sin pistas",
    )
    assert anio == 2017
    assert tribunal == "Corte Suprema de Justicia"


def test_sugerir_anio_y_tribunal_cae_al_texto_si_no_hay_en_el_nombre():
    anio, tribunal = _sugerir_anio_y_tribunal(
        "documento.pdf", "Consejo de Estado, Sección Cuarta, sentencia de 2019",
    )
    assert anio == 2019
    assert tribunal == "Consejo de Estado"


def test_sugerir_anio_y_tribunal_sin_pistas_devuelve_none():
    anio, tribunal = _sugerir_anio_y_tribunal("documento.pdf", "texto sin fechas ni tribunales")
    assert anio is None
    assert tribunal is None


# --- con Postgres real: ciclo de vida del borrador ------------------------

@pytest.mark.asyncio
async def test_crear_borrador_propone_chunks_y_metadata_heuristica(db):
    await ensure_corpus_drafts_table(db)
    texto = "palabra " * 1000
    borrador = await crear_borrador(
        db, nombre_fuente="Sentencia SL17063-2017 Corte Suprema", texto=texto, creado_por=None,
    )
    assert borrador["estado"] == "borrador"
    assert len(borrador["chunks"]) > 1
    assert borrador["anio"] == 2017
    assert borrador["tribunal"] == "Corte Suprema de Justicia"
    assert borrador["norma"] is None  # metadata legal aún sin completar (paso 3)


@pytest.mark.asyncio
async def test_listar_y_obtener_borrador(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="contenido de prueba", creado_por=None)

    listado = await listar_borradores(db)
    assert any(b["id"] == creado["id"] for b in listado)

    obtenido = await obtener_borrador(db, creado["id"])
    assert obtenido["texto_extraido"] == "contenido de prueba"


@pytest.mark.asyncio
async def test_obtener_borrador_inexistente_levanta_error(db):
    await ensure_corpus_drafts_table(db)
    with pytest.raises(BorradorNoEncontradoError):
        await obtener_borrador(db, "00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_actualizar_borrador_edita_chunks_y_metadata(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto original", creado_por=None)

    actualizado = await actualizar_borrador(
        db, creado["id"],
        chunks=["chunk unido uno", "chunk unido dos"],
        norma="Ley 1607 de 2012", articulo="Art. 178", tipo_fuente="ley", prioridad="alta",
    )
    assert actualizado["chunks"] == ["chunk unido uno", "chunk unido dos"]
    assert actualizado["norma"] == "Ley 1607 de 2012"
    assert actualizado["tipo_fuente"] == "ley"
    assert actualizado["prioridad"] == "alta"


@pytest.mark.asyncio
async def test_actualizar_borrador_normaliza_alias_de_prioridad_en_ingles(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    actualizado = await actualizar_borrador(db, creado["id"], prioridad="high")
    assert actualizado["prioridad"] == "alta"


@pytest.mark.asyncio
async def test_actualizar_borrador_tipo_fuente_invalido_levanta_error(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    with pytest.raises(TipoFuenteInvalidoError):
        await actualizar_borrador(db, creado["id"], tipo_fuente="doctrina")


@pytest.mark.asyncio
async def test_actualizar_borrador_prioridad_invalida_levanta_error(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    with pytest.raises(PrioridadInvalidaError):
        await actualizar_borrador(db, creado["id"], prioridad="urgente")


@pytest.mark.asyncio
async def test_descartar_borrador(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    await descartar_borrador(db, creado["id"])
    with pytest.raises(BorradorNoEncontradoError):
        await obtener_borrador(db, creado["id"])


@pytest.mark.asyncio
async def test_publicar_sin_metadata_completa_levanta_error(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    with pytest.raises(MetadataIncompletaError):
        await publicar_borrador(db, creado["id"])


@pytest.mark.asyncio
async def test_publicar_con_chunks_vacios_levanta_error(db):
    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    await actualizar_borrador(
        db, creado["id"], chunks=[],
        norma="Ley X", articulo="Art. 1", tipo_fuente="ley", prioridad="alta",
    )
    with pytest.raises(MetadataIncompletaError):
        await publicar_borrador(db, creado["id"])


@pytest.mark.asyncio
async def test_publicar_borrador_completo_inserta_y_marca_publicado(db, monkeypatch):
    """Mockea insertar_chunk (embeddings + pgvector reales, no disponibles
    en este service container -- ver docstring del módulo) para probar la
    responsabilidad real de esta función: contar inserciones/duplicados y
    transicionar el estado."""
    import core.corpus_curation as cc

    llamadas = []

    async def _fake_insertar_chunk(conn, chunk):
        llamadas.append(chunk)
        return len(llamadas) <= 1  # el primer chunk se "inserta", el resto "duplicado"

    monkeypatch.setattr(cc, "insertar_chunk", _fake_insertar_chunk)

    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    await actualizar_borrador(
        db, creado["id"], chunks=["chunk uno", "chunk dos", "chunk tres"],
        norma="Ley 1607 de 2012", articulo="Art. 178", tipo_fuente="ley", prioridad="alta",
        anio=2012, tribunal=None,
    )

    publicado = await publicar_borrador(db, creado["id"])
    assert publicado["estado"] == "publicado"
    assert publicado["chunks_publicados"] == 1
    assert publicado["chunks_duplicados"] == 2
    assert len(llamadas) == 3
    assert all(c.norma == "Ley 1607 de 2012" for c in llamadas)


@pytest.mark.asyncio
async def test_publicar_borrador_ya_publicado_levanta_error(db, monkeypatch):
    import core.corpus_curation as cc
    monkeypatch.setattr(cc, "insertar_chunk", lambda conn, chunk: _async_true())

    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    await actualizar_borrador(
        db, creado["id"], chunks=["chunk uno"],
        norma="Ley X", articulo="Art. 1", tipo_fuente="ley", prioridad="alta",
    )
    await publicar_borrador(db, creado["id"])
    with pytest.raises(BorradorNoEditableError):
        await publicar_borrador(db, creado["id"])


@pytest.mark.asyncio
async def test_editar_borrador_ya_publicado_levanta_error(db, monkeypatch):
    import core.corpus_curation as cc
    monkeypatch.setattr(cc, "insertar_chunk", lambda conn, chunk: _async_true())

    await ensure_corpus_drafts_table(db)
    creado = await crear_borrador(db, nombre_fuente="fuente.pdf", texto="texto", creado_por=None)
    await actualizar_borrador(
        db, creado["id"], chunks=["chunk uno"],
        norma="Ley X", articulo="Art. 1", tipo_fuente="ley", prioridad="alta",
    )
    await publicar_borrador(db, creado["id"])

    with pytest.raises(BorradorNoEditableError):
        await actualizar_borrador(db, creado["id"], norma="Otra ley")
    with pytest.raises(BorradorNoEditableError):
        await descartar_borrador(db, creado["id"])


async def _async_true():
    return True
