"""
Vridik — api/datos_personales_endpoint.py
Roadmap T7 (Ley 1581 de 2012, derecho ARCO de Acceso): GET /me/datos --
export completo en JSON de los datos personales que Vridik tiene de la
cuenta autenticada. Mismo criterio de auth que el resto del producto
(get_current_user) -- nunca expone datos de otro usuario, ver
core/datos_personales.py::exportar_datos_de_usuario, que solo trae filas
donde el usuario autenticado es el dueño real del dato.

Rectificación y Supresión: ver el docstring de core/datos_personales.py
-- rectificación ya se ejerce con los endpoints existentes, supresión
queda pendiente de una decisión de diseño (qué se anonimiza vs qué se
conserva por deber legal) antes de escribir el DELETE/UPDATE real.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.actuaciones import ensure_actuaciones_table
from core.auth_events import ensure_bitacora_hash_chain
from core.case import ensure_casos_table
from core.case_documents import ensure_case_documents_table
from core.datos_personales import exportar_datos_de_usuario
from core.mensajes import ensure_mensajes_tables
from core.terminos import ensure_terminos_table

router = APIRouter(tags=["datos-personales"])


async def _preparar(conn) -> None:
    await ensure_casos_table(conn)
    await ensure_actuaciones_table(conn)
    await ensure_terminos_table(conn)
    await ensure_case_documents_table(conn)
    await ensure_mensajes_tables(conn)
    await ensure_bitacora_hash_chain(conn)


@router.get("/me/datos")
async def exportar_mis_datos_endpoint(request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await _preparar(conn)
    return await exportar_datos_de_usuario(conn, user_id=str(current["id"]))
