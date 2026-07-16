"""
Vridik — api/analitica_endpoint.py
Fase 4 (roadmap: "Analítica de línea decisional UGPP"): GET /analitica/ugpp
resume los casos UGPP del PROPIO despacho (core/analitica.py) -- nunca
jurisprudencia externa (corpus incompleto) ni datos por juez (advertencia
SAMAI). Abogado o admin únicamente, mismo criterio que /clientes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.actuaciones import ensure_actuaciones_table
from core.analitica import generar_analitica_ugpp
from core.case import ensure_casos_table
from core.cobro import ensure_cobro_table

router = APIRouter(prefix="/analitica", tags=["analitica"])


@router.get("/ugpp")
async def get_analitica_ugpp_endpoint(request: Request, current: dict = Depends(get_current_user)):
    if current["role"] not in ("abogado", "admin"):
        raise HTTPException(status_code=403, detail="Solo un abogado o admin del despacho puede ver esta sección")

    conn = _get_db(request)
    await ensure_casos_table(conn)
    await ensure_actuaciones_table(conn)
    await ensure_cobro_table(conn)
    return await generar_analitica_ugpp(conn, despacho_id=current["despacho_id"])
