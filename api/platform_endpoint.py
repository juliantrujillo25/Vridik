"""
Vridik — api/platform_endpoint.py
Fase 4 (pricing por despacho): admin de PLATAFORMA (Vridik, no de un
despacho) -- el único lugar de la app donde ver/tocar TODOS los despachos
sin scoping es correcto por diseño.

GET   /platform/despachos               lista completa con plan/uso.
PATCH /platform/despachos/{id}/plan     cambia el plan de un despacho --
                                         exclusivo del admin de plataforma;
                                         un admin de despacho nunca puede
                                         subirse el plan a sí mismo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.admin_endpoint import get_current_superadmin
from api.auth_endpoint import _get_db
from core.despachos import (
    PlanInvalidoError,
    cambiar_plan,
    ensure_despachos_table,
    listar_despachos_con_uso,
)

router = APIRouter(prefix="/platform", tags=["platform"])


class CambiarPlanRequest(BaseModel):
    plan: str


@router.get("/despachos")
async def get_despachos(request: Request, superadmin: dict = Depends(get_current_superadmin)):
    conn = _get_db(request)
    await ensure_despachos_table(conn)
    return await listar_despachos_con_uso(conn)


@router.patch("/despachos/{despacho_id}/plan")
async def patch_despacho_plan(
    despacho_id: str, payload: CambiarPlanRequest, request: Request,
    superadmin: dict = Depends(get_current_superadmin),
):
    conn = _get_db(request)
    await ensure_despachos_table(conn)
    try:
        return await cambiar_plan(conn, despacho_id=despacho_id, plan=payload.plan)
    except PlanInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
