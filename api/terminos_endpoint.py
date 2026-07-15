"""
Vridik — api/terminos_endpoint.py
Fase 2 (Copiloto Procesal): POST/GET /casos/{caso_id}/terminos --
términos procesales con vencimiento SIEMPRE calculado por
procesal/calendario_judicial.py (core/terminos.py::crear_termino), nunca
aceptado como fecha directa del cliente. Mismo criterio de ownership que
api/mensajes_endpoint.py/api/actuaciones_endpoint.py.

Roadmap: "Semáforo de vencimientos calculados (no manuales) en el
dashboard" -- este endpoint es la fuente de datos; el semáforo en sí
(verde/amarillo/rojo) lo pinta el frontend a partir de `dias_restantes`,
que este endpoint calcula al responder (nunca se persiste, ver
core/terminos.py para el porqué).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.case import ensure_casos_table, get_caso
from core.terminos import (
    ESTADOS_VALIDOS,
    crear_termino,
    dias_restantes,
    ensure_terminos_table,
    get_termino,
    list_terminos,
    marcar_estado_termino,
)

router = APIRouter(tags=["terminos"])


class CrearTerminoRequest(BaseModel):
    descripcion: str = Field(..., min_length=1)
    fecha_inicio: date
    dias_habiles: int = Field(..., gt=0)
    actuacion_id: str | None = None


class CambiarEstadoTerminoRequest(BaseModel):
    estado: str

    @field_validator("estado")
    @classmethod
    def _estado_valido(cls, v: str) -> str:
        if v not in ESTADOS_VALIDOS:
            raise ValueError(f"estado inválido (válidos: {ESTADOS_VALIDOS})")
        return v


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    # Fase 4: un admin ya no ve casos de otros despachos.
    if current["role"] == "admin" and str(caso["despacho_id"]) == str(current["despacho_id"]):
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a los términos de este caso")


async def _caso_con_acceso(conn, caso_id: str, current: dict) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    _exige_acceso_a_caso(caso, current)
    return caso


async def _preparar(conn) -> None:
    await ensure_casos_table(conn)
    await ensure_terminos_table(conn)


def _con_dias_restantes(termino: dict) -> dict:
    return {**termino, "dias_restantes": dias_restantes(termino["fecha_vencimiento"])}


@router.post("/casos/{caso_id}/terminos", status_code=201)
async def crear_termino_endpoint(
    caso_id: str, payload: CrearTerminoRequest, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    try:
        termino = await crear_termino(
            conn, caso_id=caso_id, created_by=str(current["id"]), descripcion=payload.descripcion,
            fecha_inicio=payload.fecha_inicio, dias_habiles=payload.dias_habiles,
            actuacion_id=payload.actuacion_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _con_dias_restantes(termino)


@router.get("/casos/{caso_id}/terminos")
async def listar_terminos_endpoint(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)
    terminos = await list_terminos(conn, caso_id=caso_id)
    return [_con_dias_restantes(t) for t in terminos]


@router.patch("/casos/{caso_id}/terminos/{termino_id}/estado")
async def cambiar_estado_termino_endpoint(
    caso_id: str, termino_id: str, payload: CambiarEstadoTerminoRequest, request: Request,
    current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    termino = await get_termino(conn, termino_id)
    if termino is None or str(termino["caso_id"]) != caso_id:
        raise HTTPException(status_code=404, detail="Término no encontrado")

    actualizado = await marcar_estado_termino(conn, termino_id=termino_id, estado=payload.estado)
    return _con_dias_restantes(actualizado)
