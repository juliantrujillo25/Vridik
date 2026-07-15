"""
Vridik — api/cobro_endpoint.py
Fase 3 (Cobro Inteligente): valor en disputa + esquema de honorarios por
caso, con liquidación automática (core/cobro.py -- honorarios_liquidados
SIEMPRE calculado, nunca aceptado como input).

PUT  /casos/{caso_id}/cobro            configura valor en disputa y
                                        esquema de honorarios -- SOLO
                                        abogado asignado o admin (nunca el
                                        cliente: es la negociación interna
                                        del despacho sobre lo que va a
                                        cobrar).
GET  /casos/{caso_id}/cobro            lee el estado de cobro del caso --
                                        cliente, abogado o admin (mismo
                                        criterio de siempre; es el dato
                                        base del futuro panel "ahorro
                                        generado" del roadmap, el cliente
                                        tiene que poder verlo).
POST /casos/{caso_id}/cobro/liquidar   liquida honorarios a partir de
                                        valor_recuperado -- solo abogado o
                                        admin, solo una vez.

Factura vía proveedor DIAN autorizado ("integrar, no construir", roadmap
Fase 3) sigue bloqueada en la misma decisión de negocio que la ingesta de
actuaciones de Fase 2 -- no se construye acá.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.case import ensure_casos_table, get_caso
from core.cobro import ensure_cobro_table, get_cobro, liquidar_honorarios, set_cobro

router = APIRouter(tags=["cobro"])


class SetCobroRequest(BaseModel):
    valor_en_disputa: Decimal | None = Field(None, ge=0)
    esquema_honorarios: str | None = None
    monto_fijo: Decimal | None = Field(None, ge=0)
    porcentaje_cuota_litis: Decimal | None = Field(None, ge=0, le=100)


class LiquidarRequest(BaseModel):
    valor_recuperado: Decimal = Field(..., ge=0)


def _exige_lectura(caso: dict, current: dict) -> None:
    if current["role"] == "admin":
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso al cobro de este caso")


def _exige_escritura(caso: dict, current: dict) -> None:
    """Nunca el cliente -- ver docstring del módulo."""
    if current["role"] == "admin":
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="Solo el abogado asignado o un admin puede configurar el cobro")


async def _caso_o_404(conn, caso_id: str) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return caso


async def _preparar(conn) -> None:
    await ensure_casos_table(conn)
    await ensure_cobro_table(conn)


@router.put("/casos/{caso_id}/cobro")
async def set_cobro_endpoint(
    caso_id: str, payload: SetCobroRequest, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_escritura(caso, current)

    try:
        return await set_cobro(
            conn, caso_id=caso_id, valor_en_disputa=payload.valor_en_disputa,
            esquema_honorarios=payload.esquema_honorarios, monto_fijo=payload.monto_fijo,
            porcentaje_cuota_litis=payload.porcentaje_cuota_litis,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/casos/{caso_id}/cobro")
async def get_cobro_endpoint(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await _preparar(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_lectura(caso, current)

    cobro = await get_cobro(conn, caso_id)
    if cobro is None:
        # Todavía sin configurar -- 200 con nulls, no 404 (el caso existe,
        # simplemente nadie cargó todavía el valor en disputa/esquema).
        return {
            "caso_id": caso_id, "valor_en_disputa": None, "esquema_honorarios": None,
            "monto_fijo": None, "porcentaje_cuota_litis": None, "valor_recuperado": None,
            "honorarios_liquidados": None, "liquidado_en": None,
        }
    return cobro


@router.post("/casos/{caso_id}/cobro/liquidar")
async def liquidar_cobro_endpoint(
    caso_id: str, payload: LiquidarRequest, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    caso = await _caso_o_404(conn, caso_id)
    _exige_escritura(caso, current)

    try:
        return await liquidar_honorarios(conn, caso_id=caso_id, valor_recuperado=payload.valor_recuperado)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
