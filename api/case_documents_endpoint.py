"""
Vridik — api/case_documents_endpoint.py
Documentos de caso generados por JuliX.

Dos rutas de anclaje conviven (ver core/case_documents.py para el porqué):

POST/GET /casos/{caso_id}/documents        -- ruta nueva, sobre un `caso`
                                               propio (core/case.py),
                                               independiente del
                                               marketplace. Preferida para
                                               todo documento nuevo.
POST/GET /orders/{order_id}/documents       -- ruta original, sobre una
                                               orden del marketplace. Se
                                               mantiene por compatibilidad
                                               con lo que ya exista; no se
                                               quita hasta que el
                                               marketplace se desmantele
                                               de verdad.

Ambas comparten la generación real con JuliX (julix/service.py, con cache
y RAG reales — mismo motor que api/julix_endpoint.py y
workers/pdf_worker.py) vía `_generar_contenido_y_pdf()`. Opcionalmente
arman el PDF (julix/pdf_export.py) y lo suben con el backend configurado
(storage/object_storage.py).

Ownership:
  - /casos/{id}/...: cliente del caso, abogado asignado, o admin (ver
    api/casos_endpoint.py::_exige_acceso_a_caso, mismo criterio acá).
  - /orders/{id}/...: dueño de la orden (cliente), seller con al menos un
    producto en ella, o admin (core.order.order_has_seller_product).

NO SE PROBÓ CONTRA ANTHROPIC NI POSTGRESQL REALES EN ESTE ENTREGABLE — la
generación reutiliza julix.service.JuliXService tal cual (mismo mock del
SDK que el resto de la suite, ver tests/test_case_documents.py).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.case import ensure_casos_table, get_caso
from core.case_documents import (
    ensure_case_documents_table,
    get_case_document,
    insert_case_document,
    list_case_documents,
)
from core.order import ensure_order_tables, get_order, order_has_seller_product
from julix.client import JuliXClient
from julix.pdf_export import FuenteCitada, generar_pdf
from julix.router import TAREA_POR_AREA, route_by_area
from julix.service import JuliXService
from rag.context_builder import buscar_contexto as rag_buscar_contexto
from storage.object_storage import get_storage_backend

router = APIRouter(tags=["case-documents"])

ENVIRONMENT = os.environ.get("VRIDIK_ENVIRONMENT", "staging")
DIRECTORIO_SALIDA_PDF = Path(os.environ.get("PDF_WORKER_OUTPUT_DIR", "/tmp/vridik-pdf-jobs"))


class CrearCaseDocumentRequest(BaseModel):
    pregunta: str = Field(..., min_length=1)
    tarea: str | None = None
    generar_pdf: bool = False


async def _generar_contenido_y_pdf(
    conn, *, user_id: str, anclaje_id: str, payload: CrearCaseDocumentRequest,
) -> tuple[str, str, str | None]:
    """Genera el documento real con JuliX y, si se pidió, el PDF. Devuelve
    (contenido, tarea, pdf_url) -- `anclaje_id` es el order_id o caso_id,
    usado solo como `caso_id` de cara al ledger de JuliX (julix_calls) y
    para nombrar el PDF, nunca como FK real acá."""
    area = route_by_area(payload.pregunta)
    tarea = payload.tarea or TAREA_POR_AREA[area]

    client = JuliXClient(environment=ENVIRONMENT, db_connection=conn)
    service = JuliXService(client=client, db_connection=conn)

    contenido = ""
    async for fragmento in service.generar_documento(
        user_id=user_id, caso_id=anclaje_id, tarea=tarea,
        expediente_texto=payload.pregunta, pregunta=payload.pregunta,
    ):
        contenido += fragmento

    pdf_url = None
    if payload.generar_pdf:
        chunks_recuperados = await rag_buscar_contexto(conn, payload.pregunta)
        fuentes = [FuenteCitada.desde_chunk_recuperado(chunk) for chunk in chunks_recuperados]
        ruta_pdf = DIRECTORIO_SALIDA_PDF / f"case_{anclaje_id}_{area}.pdf".replace("/", "_")
        DIRECTORIO_SALIDA_PDF.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: generar_pdf(
                respuesta=contenido, fuentes=fuentes, ruta_salida=ruta_pdf, tarea=tarea, caso_id=anclaje_id,
            ),
        )
        storage = get_storage_backend()
        pdf_url = await storage.upload_pdf(ruta_pdf, key=ruta_pdf.name)

    return contenido, tarea, pdf_url


# ---------------------------------------------------------------------
# Ruta nueva: /casos/{caso_id}/documents (independiente del marketplace)
# ---------------------------------------------------------------------
def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    if current["role"] == "admin":
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a los documentos de este caso")


async def _caso_o_404(conn, caso_id: str) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return caso


@router.post("/casos/{caso_id}/documents", status_code=201)
async def crear_documento_de_caso(
    caso_id: str, payload: CrearCaseDocumentRequest, request: Request,
    current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    await ensure_case_documents_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)

    contenido, tarea, pdf_url = await _generar_contenido_y_pdf(
        conn, user_id=str(current["id"]), anclaje_id=caso_id, payload=payload,
    )
    return await insert_case_document(
        conn, caso_id=caso_id, created_by=str(current["id"]), tarea=tarea,
        pregunta=payload.pregunta, contenido=contenido, pdf_url=pdf_url,
    )


@router.get("/casos/{caso_id}/documents")
async def listar_documentos_de_caso(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    await ensure_case_documents_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)
    return await list_case_documents(conn, caso_id=caso_id)


@router.get("/casos/{caso_id}/documents/{document_id}")
async def detalle_documento_de_caso(
    caso_id: str, document_id: str, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    await ensure_case_documents_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)

    documento = await get_case_document(conn, document_id)
    if documento is None or documento.get("caso_id") is None or str(documento["caso_id"]) != caso_id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento


# ---------------------------------------------------------------------
# Ruta original: /orders/{order_id}/documents (compatibilidad, marketplace)
# ---------------------------------------------------------------------
async def _orden_o_404(conn, order_id: str) -> dict:
    orden = await get_order(conn, order_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return orden


async def _exige_acceso_a_orden(conn, orden: dict, current: dict) -> None:
    """Mismo criterio de ownership que GET /seller/orders/{id}: dueño de la
    orden (cliente), seller con al menos un producto en ella, o admin."""
    if current["role"] == "admin":
        return
    if str(orden["user_id"]) == str(current["id"]):
        return
    if await order_has_seller_product(conn, orden["id"], str(current["id"])):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a los documentos de esta orden")


@router.post("/orders/{order_id}/documents", status_code=201)
async def crear_case_document(
    order_id: str, payload: CrearCaseDocumentRequest, request: Request,
    current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await ensure_case_documents_table(conn)
    orden = await _orden_o_404(conn, order_id)
    await _exige_acceso_a_orden(conn, orden, current)

    contenido, tarea, pdf_url = await _generar_contenido_y_pdf(
        conn, user_id=str(current["id"]), anclaje_id=order_id, payload=payload,
    )
    return await insert_case_document(
        conn, order_id=order_id, created_by=str(current["id"]), tarea=tarea,
        pregunta=payload.pregunta, contenido=contenido, pdf_url=pdf_url,
    )


@router.get("/orders/{order_id}/documents")
async def listar_case_documents(order_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_case_documents_table(conn)
    orden = await _orden_o_404(conn, order_id)
    await _exige_acceso_a_orden(conn, orden, current)
    return await list_case_documents(conn, order_id=order_id)


@router.get("/orders/{order_id}/documents/{document_id}")
async def detalle_case_document(
    order_id: str, document_id: str, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await ensure_case_documents_table(conn)
    orden = await _orden_o_404(conn, order_id)
    await _exige_acceso_a_orden(conn, orden, current)

    documento = await get_case_document(conn, document_id)
    if documento is None or documento.get("order_id") is None or str(documento["order_id"]) != order_id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento
