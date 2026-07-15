"""
Vridik — api/mensajes_endpoint.py
Roadmap Semana 11, Fase A: mensajería real sobre un `caso` (core/case.py),
mismo criterio de ownership que api/case_documents_endpoint.py (cliente
del caso, abogado asignado, o admin) -- reemplaza al FakeMensajesService
de tests/support/fakes.py como capa de datos.

Fase B: crear_mensaje_endpoint notifica `message.new` (core/events.py) al
otro participante del caso -- el cliente si escribió el abogado, el
abogado asignado si escribió el cliente (nunca al propio autor). Quién
notificar se decide acá, no en core/mensajes.py (que no conoce roles) ni
en core/events.py (que no conoce casos) -- este archivo es el único que
tiene ambos datos a mano.

POST   /casos/{caso_id}/mensajes                crea un mensaje (autor =
                                                  usuario autenticado)
GET    /casos/{caso_id}/mensajes                 lista mensajes (más
                                                  reciente primero)
GET    /casos/{caso_id}/mensajes/no-leidos       cuenta no leídos del
                                                  usuario autenticado
POST   /casos/{caso_id}/mensajes/{id}/leido      marca leído hasta ese
                                                  mensaje (avanza el
                                                  cursor, nunca lo
                                                  retrocede)
DELETE /casos/{caso_id}/mensajes/{id}            soft delete -- solo el
                                                  autor puede borrar su
                                                  propio mensaje
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.case import ensure_casos_table, get_caso
from core.events import notificar_evento
from core.mensajes import (
    borrar_mensaje,
    crear_mensaje,
    ensure_mensajes_tables,
    get_mensaje,
    get_or_create_conversacion,
    listar_mensajes,
    marcar_leido,
    no_leidos_para,
)

router = APIRouter(tags=["mensajes"])

# Adjuntos de mensajes (roadmap S11: "Chat interno con adjuntos") -- mismo
# almacenamiento efímero que storage/object_storage.py backend "local"
# (se pierde en cada redeploy del contenedor; no se reusa esa clase porque
# está nombrada/pensada específicamente para PDFs de JuliX -- acá el
# archivo lo sube el usuario directo, sin pasar por generación de JuliX).
DIRECTORIO_ADJUNTOS = Path(os.environ.get("MENSAJES_ADJUNTOS_DIR", "/tmp/vridik-mensajes-adjuntos"))
TAMANO_MAXIMO_ADJUNTO_BYTES = 10 * 1024 * 1024  # 10 MB
EXTENSIONES_PERMITIDAS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt",
})


class CrearMensajeRequest(BaseModel):
    texto: str = Field(..., min_length=1)
    adjunto_url: str | None = None
    adjunto_nombre: str | None = None


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    # Fase 4: un admin ya no ve casos de otros despachos.
    if current["role"] == "admin" and str(caso["despacho_id"]) == str(current["despacho_id"]):
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a los mensajes de este caso")


async def _caso_con_acceso(conn, caso_id: str, current: dict) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    _exige_acceso_a_caso(caso, current)
    return caso


async def _preparar(conn) -> None:
    await ensure_casos_table(conn)
    await ensure_mensajes_tables(conn)


@router.post("/casos/{caso_id}/mensajes", status_code=201)
async def crear_mensaje_endpoint(
    caso_id: str, payload: CrearMensajeRequest, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    caso = await _caso_con_acceso(conn, caso_id, current)

    conversacion = await get_or_create_conversacion(conn, caso_id=caso_id)
    mensaje = await crear_mensaje(
        conn, conversacion_id=conversacion["id"], autor_id=str(current["id"]),
        texto=payload.texto, adjunto_url=payload.adjunto_url, adjunto_nombre=payload.adjunto_nombre,
    )

    autor_id = str(current["id"])
    destinatarios = {str(caso["cliente_id"]), str(caso["abogado_id"])} if caso["abogado_id"] else {str(caso["cliente_id"])}
    destinatarios.discard(autor_id)
    for user_id in destinatarios:
        await notificar_evento(
            conn, user_id=user_id, tipo="message.new",
            payload={"caso_id": caso_id, "conversacion_id": conversacion["id"], "mensaje_id": mensaje["id"]},
        )

    return mensaje


@router.get("/casos/{caso_id}/mensajes")
async def listar_mensajes_endpoint(
    caso_id: str, request: Request, skip: int = 0, limit: int = 50, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    conversacion = await get_or_create_conversacion(conn, caso_id=caso_id)
    return await listar_mensajes(conn, conversacion_id=conversacion["id"], skip=skip, limit=limit)


@router.get("/casos/{caso_id}/mensajes/no-leidos")
async def no_leidos_endpoint(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    conversacion = await get_or_create_conversacion(conn, caso_id=caso_id)
    conteo = await no_leidos_para(conn, user_id=str(current["id"]), conversacion_id=conversacion["id"])
    return {"no_leidos": conteo}


@router.post("/casos/{caso_id}/mensajes/{mensaje_id}/leido")
async def marcar_leido_endpoint(
    caso_id: str, mensaje_id: str, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    marcado = await marcar_leido(conn, mensaje_id=mensaje_id, user_id=str(current["id"]))
    if not marcado:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    return {"ok": True}


@router.delete("/casos/{caso_id}/mensajes/{mensaje_id}", status_code=204)
async def borrar_mensaje_endpoint(
    caso_id: str, mensaje_id: str, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    borrado = await borrar_mensaje(conn, mensaje_id=mensaje_id, actor_id=str(current["id"]))
    if not borrado:
        raise HTTPException(status_code=403, detail="Solo el autor puede borrar su propio mensaje")
    return None


@router.post("/casos/{caso_id}/mensajes/adjuntos", status_code=201)
async def subir_adjunto_endpoint(
    caso_id: str, request: Request, archivo: UploadFile, current: dict = Depends(get_current_user),
):
    """Sube el archivo a disco local y devuelve {adjunto_url, adjunto_nombre}
    para pasarlos tal cual a POST /mensajes -- separado de crear_mensaje_
    endpoint porque el archivo se sube ANTES de que el usuario termine de
    escribir el texto del mensaje (mismo flujo que cualquier chat con
    adjuntos: elegís el archivo, después mandás).

    `adjunto_url` nunca es un link público -- ver descargar_adjunto_
    endpoint más abajo, mismo criterio que api/case_documents_endpoint.py::
    descargar_pdf_de_documento (bug real de producción encontrado hoy con
    los PDF de JuliX: una ruta de filesystem del contenedor nunca es una
    URL que el navegador pueda abrir sola, y exponerla sin auth sería
    servir archivos de un caso legal a quien tuviera el link)."""
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    nombre_original = archivo.filename or "adjunto"
    extension = Path(nombre_original).suffix.lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo de archivo no permitido ({extension or 'sin extensión'}). "
            f"Permitidos: {', '.join(sorted(EXTENSIONES_PERMITIDAS))}",
        )

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_ADJUNTO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el máximo de {TAMANO_MAXIMO_ADJUNTO_BYTES // (1024 * 1024)} MB",
        )
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío")

    # Nombre de archivo en disco SIEMPRE generado acá (UUID + extensión ya
    # validada) -- nunca se usa `nombre_original` para construir la ruta,
    # para no depender de que el cliente no mande algo como "../../etc/passwd".
    DIRECTORIO_ADJUNTOS.mkdir(parents=True, exist_ok=True)
    nombre_en_disco = f"{uuid.uuid4()}{extension}"
    ruta = DIRECTORIO_ADJUNTOS / nombre_en_disco
    ruta.write_bytes(contenido)

    return {"adjunto_url": str(ruta), "adjunto_nombre": nombre_original}


@router.get("/casos/{caso_id}/mensajes/{mensaje_id}/adjunto")
async def descargar_adjunto_endpoint(
    caso_id: str, mensaje_id: str, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    conversacion = await get_or_create_conversacion(conn, caso_id=caso_id)
    mensaje = await get_mensaje(conn, mensaje_id)
    if (
        mensaje is None
        or str(mensaje["conversacion_id"]) != str(conversacion["id"])
        or not mensaje["adjunto_url"]
    ):
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    ruta = Path(mensaje["adjunto_url"])
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail="El adjunto ya no está disponible (almacenamiento efímero)")
    return FileResponse(ruta, filename=mensaje["adjunto_nombre"] or ruta.name)
