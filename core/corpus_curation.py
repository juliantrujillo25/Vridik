"""
Vridik — core/corpus_curation.py
Roadmap Semana 7 ("Pipeline de ingesta del corpus"): "mini-herramienta de 3
pasos en una vista: carga con texto extraído siempre visible -> chunks
propuestos editables (unir/dividir/renombrar) -> metadatos con selects
preseleccionados por heurística. Borradores persistentes... Salida: ingesta
<10 min sin código." No existía ningún endpoint/UI para esto -- el corpus
solo se podía cargar por CSV + PDFs en disco vía rag/ingest_corpus.py
--commit (línea de comandos, sin curaduría interactiva).

Este módulo NO reinventa la lógica de chunking/dedup/embedding -- reusa
rag/ingest_corpus.py (chunkear_texto, insertar_chunk) y rag/context_builder.py
(embeber_texto) tal cual. Solo agrega el ciclo de vida de "borrador": crear a
partir de texto pegado o extraído de un PDF, editar chunks/metadata, publicar
(embeber + insertar en rag_chunks, mismo INSERT ... ON CONFLICT (hash_dedup)
DO NOTHING que la ingesta por CSV -- dedup por contenido, no por origen).

`rag_chunks` es corpus legal compartido de toda la plataforma (sin
despacho_id, ver rag/sql/rag_chunks_schema.sql) -- por eso esta herramienta,
igual que api/platform_endpoint.py, es exclusiva del admin de PLATAFORMA
(get_current_superadmin), nunca de un admin de despacho.
"""

from __future__ import annotations

import json
from io import BytesIO

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore

from rag.ingest_corpus import (
    TIPOS_VALIDOS,
    _ALIAS_PRIORIDAD,
    chunkear_texto,
    inferir_anio,
    insertar_chunk,
)
from rag.context_builder import embeber_texto

PRIORIDADES_VALIDAS = frozenset({"alta", "media", "baja"})
ESTADOS_VALIDOS = frozenset({"borrador", "publicado"})

_TRIBUNALES_CONOCIDOS = [
    "Consejo de Estado", "Corte Suprema de Justicia", "Corte Constitucional",
    "Tribunal Administrativo", "Tribunal Superior",
]


class TipoFuenteInvalidoError(ValueError):
    pass


class PrioridadInvalidaError(ValueError):
    pass


class BorradorNoEncontradoError(LookupError):
    pass


class BorradorNoEditableError(ValueError):
    """El borrador ya fue publicado -- no se edita ni se borra, queda como historial."""


class MetadataIncompletaError(ValueError):
    pass


class PdfSinTextoError(ValueError):
    pass


async def ensure_corpus_drafts_table(conn) -> None:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corpus_drafts (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre_fuente    TEXT NOT NULL,
            texto_extraido   TEXT NOT NULL,
            chunks           JSONB NOT NULL DEFAULT '[]'::jsonb,
            norma            TEXT,
            articulo         TEXT,
            tipo_fuente      TEXT,
            prioridad        TEXT,
            anio             SMALLINT,
            tribunal         TEXT,
            estado           TEXT NOT NULL DEFAULT 'borrador',
            chunks_publicados INTEGER,
            chunks_duplicados INTEGER,
            creado_por       UUID,
            creado_en        TIMESTAMPTZ NOT NULL DEFAULT now(),
            actualizado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def extraer_texto_de_pdf_bytes(contenido: bytes) -> str:
    """Extrae texto de un PDF ya leído en memoria -- nunca se persiste el
    PDF en disco (mismo criterio de almacenamiento efímero que el resto de
    la app: el PDF es un insumo derivado, no un artefacto que haya que
    guardar)."""
    if PdfReader is None:
        raise RuntimeError("Falta la dependencia 'pypdf' (pip install pypdf)")
    lector = PdfReader(BytesIO(contenido))
    texto = "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
    if not texto.strip():
        raise PdfSinTextoError(
            "No se pudo extraer texto del PDF (probablemente es un escaneo sin OCR)"
        )
    return texto


def _sugerir_anio_y_tribunal(nombre_fuente: str, texto: str) -> tuple[int | None, str | None]:
    """Heurística de preselección para el paso 3 (metadatos) -- el mismo
    principio que rag/ingest_corpus.py::inferir_anio/inferir_tribunal, pero
    sin depender de `tipo` (todavía no se eligió en el paso 1/2 de esta UI)
    ni de un manifiesto CSV: se busca en el nombre del archivo primero y,
    si no hay año ahí, en el arranque del texto extraído."""
    anio = inferir_anio(nombre_fuente) or inferir_anio(texto[:3000])
    tribunal = None
    fuente_busqueda = f"{nombre_fuente}\n{texto[:3000]}"
    for candidato in _TRIBUNALES_CONOCIDOS:
        if candidato.lower() in fuente_busqueda.lower():
            tribunal = candidato
            break
    return anio, tribunal


def _fila_a_dict(fila) -> dict:
    d = dict(fila)
    d["chunks"] = json.loads(d["chunks"]) if isinstance(d["chunks"], str) else d["chunks"]
    return d


async def crear_borrador(conn, *, nombre_fuente: str, texto: str, creado_por: str | None) -> dict:
    chunks = chunkear_texto(texto)
    anio, tribunal = _sugerir_anio_y_tribunal(nombre_fuente, texto)

    fila = await conn.fetchrow(
        """
        INSERT INTO corpus_drafts (nombre_fuente, texto_extraido, chunks, anio, tribunal, creado_por)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6)
        RETURNING *
        """,
        nombre_fuente, texto, json.dumps(chunks), anio, tribunal, creado_por,
    )
    return _fila_a_dict(fila)


async def listar_borradores(conn) -> list[dict]:
    filas = await conn.fetch(
        """
        SELECT id, nombre_fuente, estado, norma, tipo_fuente, prioridad,
               jsonb_array_length(chunks) AS cantidad_chunks,
               chunks_publicados, chunks_duplicados, creado_en, actualizado_en
        FROM corpus_drafts
        ORDER BY creado_en DESC
        """
    )
    return [dict(f) for f in filas]


async def obtener_borrador(conn, borrador_id: str) -> dict:
    fila = await conn.fetchrow("SELECT * FROM corpus_drafts WHERE id = $1", borrador_id)
    if fila is None:
        raise BorradorNoEncontradoError(borrador_id)
    return _fila_a_dict(fila)


async def actualizar_borrador(
    conn, borrador_id: str, *,
    chunks: list[str] | None = None,
    norma: str | None = None,
    articulo: str | None = None,
    tipo_fuente: str | None = None,
    prioridad: str | None = None,
    anio: int | None = None,
    tribunal: str | None = None,
) -> dict:
    actual = await obtener_borrador(conn, borrador_id)
    if actual["estado"] != "borrador":
        raise BorradorNoEditableError("Este borrador ya fue publicado -- no se puede editar")

    if tipo_fuente is not None and tipo_fuente not in TIPOS_VALIDOS:
        raise TipoFuenteInvalidoError(f"tipo_fuente debe ser uno de {sorted(TIPOS_VALIDOS)}")
    if prioridad is not None:
        prioridad = _ALIAS_PRIORIDAD.get(prioridad.strip().lower(), prioridad.strip().lower())
        if prioridad not in PRIORIDADES_VALIDAS:
            raise PrioridadInvalidaError(f"prioridad debe ser una de {sorted(PRIORIDADES_VALIDAS)}")
    if chunks is not None:
        chunks = [c.strip() for c in chunks if c.strip()]

    campos: dict = {
        "chunks": json.dumps(chunks) if chunks is not None else None,
        "norma": norma,
        "articulo": articulo,
        "tipo_fuente": tipo_fuente,
        "prioridad": prioridad,
        "anio": anio,
        "tribunal": tribunal,
    }
    sets = []
    valores = []
    for columna, valor in campos.items():
        if valor is None:
            continue
        sufijo = "::jsonb" if columna == "chunks" else ""
        valores.append(valor)
        sets.append(f"{columna} = ${len(valores)}{sufijo}")
    if not sets:
        return actual

    sets.append("actualizado_en = now()")
    query = f"UPDATE corpus_drafts SET {', '.join(sets)} WHERE id = ${len(valores) + 1} RETURNING *"
    valores.append(borrador_id)
    fila = await conn.fetchrow(query, *valores)
    return _fila_a_dict(fila)


async def descartar_borrador(conn, borrador_id: str) -> None:
    actual = await obtener_borrador(conn, borrador_id)
    if actual["estado"] != "borrador":
        raise BorradorNoEditableError("Este borrador ya fue publicado -- no se puede borrar (queda como historial)")
    await conn.execute("DELETE FROM corpus_drafts WHERE id = $1", borrador_id)


async def publicar_borrador(conn, borrador_id: str) -> dict:
    """Corre exactamente el mismo camino que rag/ingest_corpus.py --commit
    (embeber_texto + insertar_chunk, mismo INSERT ... ON CONFLICT (hash_dedup)
    DO NOTHING) para cada chunk final del borrador.

    `insertar_chunk` llama a `embeber_texto` (síncrono/bloqueante, carga
    sentence-transformers) sin executor -- mismo patrón ya existente en
    `rag/context_builder.py::buscar_contexto`, que hace lo mismo en el
    camino caliente de generación real. No se envuelve acá tampoco: la
    conexión de asyncpg no es segura para usar desde otro hilo, así que
    "arreglarlo" bien requeriría separar embeber_texto (executor) de la
    escritura en BD (event loop principal) -- fuera de alcance de esta
    pasada, ya que esta acción es de admin, baja frecuencia, y el modelo
    queda cacheado (`lru_cache`) después de la primera llamada."""
    borrador = await obtener_borrador(conn, borrador_id)
    if borrador["estado"] != "borrador":
        raise BorradorNoEditableError("Este borrador ya fue publicado")

    faltantes = [
        campo for campo in ("norma", "tipo_fuente", "articulo", "prioridad")
        if not borrador.get(campo)
    ]
    if faltantes:
        raise MetadataIncompletaError(f"Faltan campos de metadata antes de publicar: {', '.join(faltantes)}")
    if not borrador["chunks"]:
        raise MetadataIncompletaError("El borrador no tiene chunks -- no hay nada que publicar")

    from rag.ingest_corpus import ChunkParaIngestar, _contar_tokens_aprox, _hash_dedup

    insertados = 0
    duplicados = 0
    for idx, texto_chunk in enumerate(borrador["chunks"]):
        chunk = ChunkParaIngestar(
            norma=borrador["norma"],
            articulo=borrador["articulo"],
            parrafo=None,
            texto=texto_chunk,
            tokens=_contar_tokens_aprox(texto_chunk),
            fuente_pdf=borrador["nombre_fuente"],
            chunk_index=idx,
            hash_dedup=_hash_dedup(texto_chunk),
            anio=borrador["anio"],
            tribunal=borrador["tribunal"],
            tipo_fuente=borrador["tipo_fuente"],
            prioridad=borrador["prioridad"],
        )
        if await insertar_chunk(conn, chunk):
            insertados += 1
        else:
            duplicados += 1

    fila = await conn.fetchrow(
        """
        UPDATE corpus_drafts
        SET estado = 'publicado', chunks_publicados = $1, chunks_duplicados = $2, actualizado_en = now()
        WHERE id = $3
        RETURNING *
        """,
        insertados, duplicados, borrador_id,
    )
    return _fila_a_dict(fila)
