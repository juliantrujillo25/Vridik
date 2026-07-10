"""
Vridik — api/casos_endpoint.py
`casos`: entidad propia del despacho legal (core/case.py), independiente
del marketplace (`orders`) -- ver core/case.py para el porqué.

POST /casos                genera un caso nuevo. El cliente lo crea sobre
                            sí mismo (cliente_id = usuario autenticado);
                            un admin puede crearlo para cualquier cliente
                            pasando `cliente_id` explícito.
GET  /casos                lista los casos del usuario autenticado (como
                            cliente o como abogado asignado); admin ve
                            todos.
GET  /casos/{id}           detalle de un caso -- mismo criterio de
                            ownership.
PATCH /casos/{id}/abogado  asigna/reasigna abogado -- solo admin.
PATCH /casos/{id}/estado   cambia el estado -- dueño (cliente/abogado) o
                            admin.

Ownership (mismo criterio que api/case_documents_endpoint.py): cliente_id
del caso, abogado_id asignado, o admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_admin, get_current_user
from api.auth_endpoint import _get_db
from core.case import (
    asignar_abogado,
    cambiar_estado,
    create_caso,
    ensure_casos_table,
    get_caso,
    list_casos_for_user,
)

router = APIRouter(prefix="/casos", tags=["casos"])

ESTADOS_VALIDOS = ("abierto", "en_progreso", "cerrado")


class CrearCasoRequest(BaseModel):
    titulo: str = Field(..., min_length=1)
    descripcion: str | None = None
    cliente_id: str | None = None  # solo admin puede pasarlo distinto al propio


class AsignarAbogadoRequest(BaseModel):
    abogado_id: str


class CambiarEstadoRequest(BaseModel):
    estado: str


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    if current["role"] == "admin":
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a este caso")


async def _caso_o_404(conn, caso_id: str) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return caso


@router.post("", status_code=201)
async def crear_caso(payload: CrearCasoRequest, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_casos_table(conn)

    if payload.cliente_id is not None and payload.cliente_id != str(current["id"]) and current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un admin puede crear un caso para otro cliente")

    cliente_id = payload.cliente_id or str(current["id"])
    return await create_caso(conn, cliente_id=cliente_id, titulo=payload.titulo, descripcion=payload.descripcion)


@router.get("")
async def listar_casos(request: Request, skip: int = 0, limit: int = 20, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    return await list_casos_for_user(
        conn, user_id=str(current["id"]), is_admin=current["role"] == "admin", skip=skip, limit=limit,
    )


@router.get("/{caso_id}")
async def detalle_caso(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)
    return caso


@router.patch("/{caso_id}/abogado")
async def asignar_abogado_endpoint(
    caso_id: str, payload: AsignarAbogadoRequest, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_casos_table(conn)
    await _caso_o_404(conn, caso_id)
    actualizado = await asignar_abogado(conn, caso_id=caso_id, abogado_id=payload.abogado_id)
    return actualizado


@router.patch("/{caso_id}/estado")
async def cambiar_estado_endpoint(
    caso_id: str, payload: CambiarEstadoRequest, request: Request, current: dict = Depends(get_current_user),
):
    if payload.estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Estado inválido (válidos: {ESTADOS_VALIDOS})")

    conn = _get_db(request)
    await ensure_casos_table(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_acceso_a_caso(caso, current)
    return await cambiar_estado(conn, caso_id=caso_id, estado=payload.estado)
