"""
Vridik — api/clientes_endpoint.py
Fase 4 (SAGRILAFT lite): vista de "cliente" independiente del caso
(core/clientes.py) + matriz de riesgo por cliente (core/cumplimiento.py).

GET  /clientes                     lista del despacho -- abogado o admin
                                    (nunca cliente: es una vista interna del
                                    despacho, no algo que un cliente vea de
                                    sí mismo agrupado con otros).
GET  /clientes/{cliente_id}        perfil + casos asociados -- abogado/admin
                                    del despacho, o el propio cliente (ve
                                    su propio perfil).
GET  /clientes/{cliente_id}/riesgo mismo criterio de acceso que el perfil.
POST /clientes/{cliente_id}/riesgo crea/actualiza la matriz -- exclusivo de
                                    abogado o admin (nunca el cliente evalúa
                                    su propio riesgo, mismo principio que
                                    "el cliente nunca configura su propio
                                    cobro" en core/cobro.py).
GET  /clientes/riesgo/reporte      resumen + detalle de la matriz de riesgo
                                    del despacho (insumo del informe del
                                    oficial de cumplimiento) -- abogado/admin.
                                    `?formato=csv` descarga el detalle como
                                    archivo. Ruta de DOS segmentos a propósito
                                    (/riesgo/reporte, no /reporte-riesgo) para
                                    no colisionar con /{cliente_id}.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.clientes import listar_casos_de_cliente, listar_clientes, obtener_cliente
from core.cumplimiento import (
    ClienteDeOtroDespachoError,
    FactorInvalidoError,
    ensure_matriz_riesgo_table,
    generar_reporte_riesgo,
    obtener_matriz_riesgo,
    set_matriz_riesgo,
)

router = APIRouter(prefix="/clientes", tags=["clientes"])


class SetMatrizRiesgoRequest(BaseModel):
    tipo_persona: str
    actividad_economica_riesgo: str
    jurisdiccion_riesgo: str
    canal: str
    es_pep: bool = False


def _exige_abogado_o_admin(current: dict) -> None:
    if current["role"] not in ("abogado", "admin"):
        raise HTTPException(status_code=403, detail="Solo un abogado o admin del despacho puede acceder a esta sección")


async def _preparar(conn) -> None:
    await ensure_matriz_riesgo_table(conn)


@router.get("")
async def get_clientes_endpoint(request: Request, current: dict = Depends(get_current_user)):
    _exige_abogado_o_admin(current)
    conn = _get_db(request)
    await _preparar(conn)
    return await listar_clientes(conn, despacho_id=current["despacho_id"])


@router.get("/{cliente_id}")
async def get_cliente_endpoint(cliente_id: str, request: Request, current: dict = Depends(get_current_user)):
    # El propio cliente puede ver su perfil; cualquier otro rol necesita
    # ser abogado/admin del mismo despacho.
    if current["role"] == "cliente" and str(current["id"]) != cliente_id:
        raise HTTPException(status_code=403, detail="No tenés acceso a este perfil")
    if current["role"] != "cliente":
        _exige_abogado_o_admin(current)

    conn = _get_db(request)
    await _preparar(conn)
    cliente = await obtener_cliente(conn, cliente_id=cliente_id, despacho_id=current["despacho_id"])
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    casos = await listar_casos_de_cliente(conn, cliente_id=cliente_id, despacho_id=current["despacho_id"])
    return {**cliente, "casos": casos}


@router.get("/{cliente_id}/riesgo")
async def get_matriz_riesgo_endpoint(cliente_id: str, request: Request, current: dict = Depends(get_current_user)):
    if current["role"] == "cliente" and str(current["id"]) != cliente_id:
        raise HTTPException(status_code=403, detail="No tenés acceso a esta información")
    if current["role"] != "cliente":
        _exige_abogado_o_admin(current)

    conn = _get_db(request)
    await _preparar(conn)
    cliente = await obtener_cliente(conn, cliente_id=cliente_id, despacho_id=current["despacho_id"])
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    return await obtener_matriz_riesgo(conn, cliente_id=cliente_id, despacho_id=current["despacho_id"])


@router.post("/{cliente_id}/riesgo")
async def set_matriz_riesgo_endpoint(
    cliente_id: str, payload: SetMatrizRiesgoRequest, request: Request, current: dict = Depends(get_current_user),
):
    _exige_abogado_o_admin(current)
    conn = _get_db(request)
    await _preparar(conn)

    try:
        return await set_matriz_riesgo(
            conn, cliente_id=cliente_id, despacho_id=current["despacho_id"], actor_id=str(current["id"]),
            tipo_persona=payload.tipo_persona, actividad_economica_riesgo=payload.actividad_economica_riesgo,
            jurisdiccion_riesgo=payload.jurisdiccion_riesgo, canal=payload.canal, es_pep=payload.es_pep,
        )
    except ClienteDeOtroDespachoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FactorInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


_ENCABEZADOS_CSV = (
    "email", "tipo_persona", "nivel_riesgo_calculado", "es_pep",
    "actividad_economica_riesgo", "jurisdiccion_riesgo", "canal",
    "evaluado_por_email", "updated_at",
)


def _reporte_a_csv(reporte: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_ENCABEZADOS_CSV)
    for c in reporte["clientes"]:
        writer.writerow(
            [c["email"], c["tipo_persona"], c["nivel_riesgo_calculado"], c["es_pep"],
             c["actividad_economica_riesgo"], c["jurisdiccion_riesgo"], c["canal"],
             c["evaluado_por_email"] or "", c["updated_at"]]
        )
    return buffer.getvalue()


@router.get("/riesgo/reporte")
async def get_reporte_riesgo_endpoint(
    request: Request, formato: str = "json", current: dict = Depends(get_current_user),
):
    _exige_abogado_o_admin(current)
    conn = _get_db(request)
    await _preparar(conn)
    reporte = await generar_reporte_riesgo(conn, despacho_id=current["despacho_id"])

    if formato == "csv":
        return Response(
            content=_reporte_a_csv(reporte),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="reporte_riesgo.csv"'},
        )
    return reporte
