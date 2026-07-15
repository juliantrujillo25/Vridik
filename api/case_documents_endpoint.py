"""
Vridik — api/case_documents_endpoint.py
Documentos de caso generados por JuliX, sobre un `caso` propio
(core/case.py) — POST/GET /casos/{caso_id}/documents.

Comparte la generación real con JuliX (julix/service.py, con cache y RAG
reales — mismo motor que api/julix_endpoint.py y workers/pdf_worker.py)
vía `_generar_contenido_y_pdf()`. Opcionalmente arma el PDF
(julix/pdf_export.py) y lo sube con el backend configurado
(storage/object_storage.py).

Ownership: cliente del caso, abogado asignado, o admin (ver
api/casos_endpoint.py::_exige_acceso_a_caso, mismo criterio acá).

Desmantelamiento del marketplace (fase 4, ver Instrucciones - CLAUDE.md,
"Consolidación de producto"): la ruta legacy POST/GET /orders/{id}/documents
se quitó entera -- la tabla case_documents nunca llegó a crearse en
producción (nadie la había llamado todavía), así que no había ningún
documento real anclado a una orden que preservar.

NO SE PROBÓ CONTRA ANTHROPIC NI POSTGRESQL REALES EN ESTE ENTREGABLE -- la
generación reutiliza julix.service.JuliXService tal cual (mismo mock del
SDK que el resto de la suite, ver tests/test_case_documents.py).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
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
    conn, *, user_id: str, caso_id: str, payload: CrearCaseDocumentRequest,
) -> tuple[str, str, str | None]:
    """Genera el documento real con JuliX y, si se pidió, el PDF. Devuelve
    (contenido, tarea, pdf_url)."""
    area = route_by_area(payload.pregunta)
    tarea = payload.tarea or TAREA_POR_AREA[area]

    client = JuliXClient(environment=ENVIRONMENT, db_connection=conn)
    service = JuliXService(client=client, db_connection=conn)

    contenido = ""
    async for fragmento in service.generar_documento(
        user_id=user_id, caso_id=caso_id, tarea=tarea,
        expediente_texto=payload.pregunta, pregunta=payload.pregunta,
    ):
        contenido += fragmento

    pdf_url = None
    if payload.generar_pdf:
        chunks_recuperados = await rag_buscar_contexto(conn, payload.pregunta)
        fuentes = [FuenteCitada.desde_chunk_recuperado(chunk) for chunk in chunks_recuperados]
        ruta_pdf = DIRECTORIO_SALIDA_PDF / f"case_{caso_id}_{area}.pdf".replace("/", "_")
        DIRECTORIO_SALIDA_PDF.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: generar_pdf(
                respuesta=contenido, fuentes=fuentes, ruta_salida=ruta_pdf, tarea=tarea, caso_id=caso_id,
            ),
        )
        storage = get_storage_backend()
        pdf_url = await storage.upload_pdf(ruta_pdf, key=ruta_pdf.name)

    return contenido, tarea, pdf_url


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    # Fase 4: un admin ya no ve casos de otros despachos.
    if current["role"] == "admin" and str(caso["despacho_id"]) == str(current["despacho_id"]):
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
        conn, user_id=str(current["id"]), caso_id=caso_id, payload=payload,
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
    if documento is None or str(documento["caso_id"]) != caso_id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return documento


@router.get("/casos/{caso_id}/documents/{document_id}/pdf")
async def descargar_pdf_de_documento(
    caso_id: str, document_id: str, request: Request, current: dict = Depends(get_current_user),
):
    """Bug real de producción (15-jul-2026): con OBJECT_STORAGE_BACKEND=local
    (default), `pdf_url` es una ruta de filesystem del CONTENEDOR, no una URL
    que el navegador pueda abrir directo -- el intento original de arreglarlo
    exponiendo esa carpeta por un mount público sin auth se descartó (sería
    servir documentos legales potencialmente confidenciales a quien tuviera
    la URL, sin el mismo control de acceso que protege el resto de
    case_documents). Esta ruta exige el mismo ownership que el resto del
    router y sirve el archivo desde acá -- el frontend la pide con
    fetch+Authorization (api.descargarPdf), nunca como link público directo.

    Con el backend S3 (no activado hoy en producción, ver storage/
    object_storage.py), `pdf_url` YA es una URL http(s) real (firmada o
    pública) -- ahí alcanza con redirigir."""
    conn = _get_db(request)
    await ensure_casos_table(conn)
    await ensure_case_documents_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)

    documento = await get_case_document(conn, document_id)
    if documento is None or str(documento["caso_id"]) != caso_id or not documento["pdf_url"]:
        raise HTTPException(status_code=404, detail="PDF no encontrado")

    pdf_url = documento["pdf_url"]
    if pdf_url.startswith("http://") or pdf_url.startswith("https://"):
        return RedirectResponse(pdf_url)

    ruta = Path(pdf_url)
    if not ruta.is_file():
        # Almacenamiento efímero del backend local (ver storage/object_storage.py)
        # -- el archivo se pierde en cada redeploy del contenedor.
        raise HTTPException(status_code=404, detail="El PDF ya no está disponible (almacenamiento efímero)")
    return FileResponse(ruta, media_type="application/pdf", filename=f"{documento['tarea']}.pdf")
