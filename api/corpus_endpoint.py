"""
Vridik — api/corpus_endpoint.py
Roadmap Semana 7: mini-herramienta de curaduría del corpus legal en 3 pasos
(extraer texto -> editar chunks -> completar metadata -> publicar). Exclusiva
del admin de plataforma (get_current_superadmin) -- `rag_chunks` es corpus
compartido de toda la plataforma, sin despacho_id, mismo criterio que
api/platform_endpoint.py.

POST   /platform/corpus/extraer-pdf                  extrae texto de un PDF (nunca se persiste el archivo)
POST   /platform/corpus/borradores                    crea un borrador a partir de texto (pegado o ya extraído)
GET    /platform/corpus/borradores                    lista borradores (resumen)
GET    /platform/corpus/borradores/{id}                borrador completo
PATCH  /platform/corpus/borradores/{id}                edita chunks y/o metadata
POST   /platform/corpus/borradores/{id}/publicar       embebe + inserta en rag_chunks
DELETE /platform/corpus/borradores/{id}                descarta un borrador (solo si no está publicado)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_superadmin
from api.auth_endpoint import _get_db
from core.corpus_curation import (
    BorradorNoEditableError,
    BorradorNoEncontradoError,
    MetadataIncompletaError,
    PdfSinTextoError,
    PrioridadInvalidaError,
    TipoFuenteInvalidoError,
    actualizar_borrador,
    crear_borrador,
    descartar_borrador,
    ensure_corpus_drafts_table,
    extraer_texto_de_pdf_bytes,
    listar_borradores,
    obtener_borrador,
    publicar_borrador,
)

router = APIRouter(prefix="/platform/corpus", tags=["corpus"])

TAMANO_MAXIMO_PDF_BYTES = 20 * 1024 * 1024  # 20 MB -- sentencias/leyes largas caben de sobra


class CrearBorradorRequest(BaseModel):
    nombre_fuente: str = Field(..., min_length=1)
    texto: str = Field(..., min_length=1)


class ActualizarBorradorRequest(BaseModel):
    chunks: list[str] | None = None
    norma: str | None = None
    articulo: str | None = None
    tipo_fuente: str | None = None
    prioridad: str | None = None
    anio: int | None = None
    tribunal: str | None = None


async def _preparar(conn) -> None:
    await ensure_corpus_drafts_table(conn)


@router.post("/extraer-pdf")
async def extraer_pdf_endpoint(archivo: UploadFile, _: dict = Depends(get_current_superadmin)):
    if (archivo.filename or "").lower().rsplit(".", 1)[-1] != "pdf":
        raise HTTPException(status_code=422, detail="Solo se aceptan archivos .pdf")

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío")
    if len(contenido) > TAMANO_MAXIMO_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el máximo de {TAMANO_MAXIMO_PDF_BYTES // (1024 * 1024)} MB",
        )

    loop = asyncio.get_running_loop()
    try:
        texto = await loop.run_in_executor(None, extraer_texto_de_pdf_bytes, contenido)
    except PdfSinTextoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"texto": texto}


@router.post("/borradores", status_code=201)
async def crear_borrador_endpoint(
    payload: CrearBorradorRequest, request: Request, superadmin: dict = Depends(get_current_superadmin),
):
    conn = _get_db(request)
    await _preparar(conn)
    return await crear_borrador(
        conn, nombre_fuente=payload.nombre_fuente, texto=payload.texto, creado_por=str(superadmin["id"]),
    )


@router.get("/borradores")
async def listar_borradores_endpoint(request: Request, _: dict = Depends(get_current_superadmin)):
    conn = _get_db(request)
    await _preparar(conn)
    return await listar_borradores(conn)


@router.get("/borradores/{borrador_id}")
async def obtener_borrador_endpoint(borrador_id: str, request: Request, _: dict = Depends(get_current_superadmin)):
    conn = _get_db(request)
    await _preparar(conn)
    try:
        return await obtener_borrador(conn, borrador_id)
    except BorradorNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail="Borrador no encontrado") from exc


@router.patch("/borradores/{borrador_id}")
async def actualizar_borrador_endpoint(
    borrador_id: str, payload: ActualizarBorradorRequest, request: Request,
    _: dict = Depends(get_current_superadmin),
):
    conn = _get_db(request)
    await _preparar(conn)
    try:
        return await actualizar_borrador(
            conn, borrador_id,
            chunks=payload.chunks, norma=payload.norma, articulo=payload.articulo,
            tipo_fuente=payload.tipo_fuente, prioridad=payload.prioridad,
            anio=payload.anio, tribunal=payload.tribunal,
        )
    except BorradorNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail="Borrador no encontrado") from exc
    except BorradorNoEditableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (TipoFuenteInvalidoError, PrioridadInvalidaError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/borradores/{borrador_id}/publicar")
async def publicar_borrador_endpoint(borrador_id: str, request: Request, _: dict = Depends(get_current_superadmin)):
    conn = _get_db(request)
    await _preparar(conn)
    try:
        return await publicar_borrador(conn, borrador_id)
    except BorradorNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail="Borrador no encontrado") from exc
    except BorradorNoEditableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MetadataIncompletaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/borradores/{borrador_id}", status_code=204)
async def descartar_borrador_endpoint(borrador_id: str, request: Request, _: dict = Depends(get_current_superadmin)):
    conn = _get_db(request)
    await _preparar(conn)
    try:
        await descartar_borrador(conn, borrador_id)
    except BorradorNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail="Borrador no encontrado") from exc
    except BorradorNoEditableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
