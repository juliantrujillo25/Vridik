"""
Vridik — api/mensajes_endpoint.py
Roadmap Semana 11, Fase A: mensajería real sobre un `caso` (core/case.py),
mismo criterio de ownership que api/case_documents_endpoint.py (cliente
del caso, abogado asignado, o admin) -- reemplaza al FakeMensajesService
de tests/support/fakes.py como capa de datos; el canal SSE (`message.new`)
llega en la Fase B, sin tocar estas rutas.

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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.case import ensure_casos_table, get_caso
from core.mensajes import (
    borrar_mensaje,
    crear_mensaje,
    ensure_mensajes_tables,
    get_or_create_conversacion,
    listar_mensajes,
    marcar_leido,
    no_leidos_para,
)

router = APIRouter(tags=["mensajes"])


class CrearMensajeRequest(BaseModel):
    texto: str = Field(..., min_length=1)
    adjunto_url: str | None = None


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    if current["role"] == "admin":
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
    await _caso_con_acceso(conn, caso_id, current)

    conversacion = await get_or_create_conversacion(conn, caso_id=caso_id)
    return await crear_mensaje(
        conn, conversacion_id=conversacion["id"], autor_id=str(current["id"]),
        texto=payload.texto, adjunto_url=payload.adjunto_url,
    )


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
