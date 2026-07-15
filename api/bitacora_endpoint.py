"""
Vridik — api/bitacora_endpoint.py
Fase 3: "Bitácora sellada de notificaciones con acuse" (core/auth_events.py
-- hash encadenado sobre `auth_events`).

GET  /bitacora/verificar               integridad de la cadena completa --
                                        solo admin (es una herramienta de
                                        auditoría/compliance, no algo que
                                        un cliente necesite ver).
GET  /bitacora/mis-notificaciones      notificaciones del usuario
                                        autenticado (actuaciones
                                        notificadas, etc.) con su estado
                                        de acuse -- Portal Cliente Vridik.
POST /bitacora/eventos/{evento_id}/acuse
                                        confirma recepción de una
                                        notificación propia -- el core ya
                                        exige que sea el destinatario real
                                        y que no esté confirmada todavía.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.admin_endpoint import get_current_admin, get_current_user
from api.auth_endpoint import _get_db
from core.auth_events import (
    AcuseInvalidoError,
    EventoNoEncontradoError,
    NoEsDestinatarioError,
    confirmar_acuse,
    ensure_bitacora_hash_chain,
    listar_notificaciones,
    verificar_cadena,
)

router = APIRouter(prefix="/bitacora", tags=["bitacora"])


@router.get("/verificar")
async def verificar_bitacora_endpoint(request: Request, current: dict = Depends(get_current_admin)):
    conn = _get_db(request)
    await ensure_bitacora_hash_chain(conn)
    return await verificar_cadena(conn)


@router.get("/mis-notificaciones")
async def mis_notificaciones_endpoint(request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_bitacora_hash_chain(conn)
    return await listar_notificaciones(conn, user_id=str(current["id"]))


@router.post("/eventos/{evento_id}/acuse")
async def confirmar_acuse_endpoint(evento_id: int, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_bitacora_hash_chain(conn)
    try:
        return await confirmar_acuse(conn, evento_id=evento_id, user_id=str(current["id"]))
    except EventoNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoEsDestinatarioError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AcuseInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
