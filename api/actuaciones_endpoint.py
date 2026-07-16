"""
Vridik — api/actuaciones_endpoint.py
Fase 2 (Copiloto Procesal): POST/GET /casos/{caso_id}/actuaciones --
clasifica (procesal/clasificador_actuaciones.py, sobre Haiku) y persiste
(core/actuaciones.py) una actuación judicial. Mismo criterio de
ownership que api/mensajes_endpoint.py (cliente del caso, abogado
asignado, o admin) y mismo patrón de notificación S11 al otro
participante del caso (roadmap Fase 2: "canal de eventos de la S11").

Arranca sin ingesta automática (Fase 2 sigue sin proveedor de monitoreo
de procesos contratado, ver procesal/__init__.py) -- el texto de la
actuación lo pega a mano quien la lea primero (cliente o abogado);
cuando exista una ingesta real, solo cambia el llamador de este mismo
endpoint, no su contrato.

OJO: cada POST dispara una llamada real a Claude (Haiku, barata pero
real -- ver julix/client.py) igual que la generación de documentos.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.actuaciones import (
    RESULTADOS_VALIDOS,
    ActuacionNoEsFalloError,
    ensure_actuaciones_table,
    get_actuacion,
    insert_actuacion,
    list_actuaciones,
    set_resultado_actuacion,
)
from core.auth_events import ensure_bitacora_hash_chain, registrar_evento
from core.case import ensure_casos_table, get_caso
from core.events import notificar_evento
from julix.client import JuliXClient
from julix.errors import JuliXError
from procesal.clasificador_actuaciones import clasificar_actuacion

router = APIRouter(tags=["actuaciones"])

ENVIRONMENT = os.environ.get("VRIDIK_ENVIRONMENT", "staging")


class CrearActuacionRequest(BaseModel):
    texto: str = Field(..., min_length=1)


class SetResultadoActuacionRequest(BaseModel):
    resultado: str
    tipo_resolucion_ugpp: str | None = None


def _exige_acceso_a_caso(caso: dict, current: dict) -> None:
    # Fase 4: un admin ya no ve casos de otros despachos.
    if current["role"] == "admin" and str(caso["despacho_id"]) == str(current["despacho_id"]):
        return
    if str(caso["cliente_id"]) == str(current["id"]):
        return
    if caso["abogado_id"] is not None and str(caso["abogado_id"]) == str(current["id"]):
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a las actuaciones de este caso")


async def _caso_con_acceso(conn, caso_id: str, current: dict) -> dict:
    caso = await get_caso(conn, caso_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    _exige_acceso_a_caso(caso, current)
    return caso


async def _preparar(conn) -> None:
    await ensure_casos_table(conn)
    await ensure_actuaciones_table(conn)
    await ensure_bitacora_hash_chain(conn)


@router.post("/casos/{caso_id}/actuaciones", status_code=201)
async def crear_actuacion_endpoint(
    caso_id: str, payload: CrearActuacionRequest, request: Request, current: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await _preparar(conn)
    caso = await _caso_con_acceso(conn, caso_id, current)

    client = JuliXClient(environment=ENVIRONMENT, db_connection=conn)
    try:
        resultado = await clasificar_actuacion(
            client, texto_actuacion=payload.texto, user_id=str(current["id"]), caso_id=caso_id,
        )
    except JuliXError as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo clasificar la actuación: {exc}") from exc

    actuacion = await insert_actuacion(
        conn, caso_id=caso_id, created_by=str(current["id"]), texto=payload.texto,
        categoria=resultado.categoria, confianza=resultado.confianza, texto_bruto=resultado.texto_bruto,
    )

    autor_id = str(current["id"])
    destinatarios = {str(caso["cliente_id"]), str(caso["abogado_id"])} if caso["abogado_id"] else {str(caso["cliente_id"])}
    destinatarios.discard(autor_id)
    for user_id in destinatarios:
        await notificar_evento(
            conn, user_id=user_id, tipo="actuacion.nueva",
            payload={"caso_id": caso_id, "actuacion_id": actuacion["id"], "categoria": actuacion["categoria"]},
        )
        # Fase 3: además del aviso en vivo por SSE (arriba, se pierde si
        # nadie está conectado en ese momento), deja un registro SELLADO
        # y encadenado en la bitácora -- es lo que el cliente puede
        # confirmar después con /bitacora/eventos/{id}/acuse, y lo que
        # queda como prueba de que se le notificó, aunque nunca haya
        # estado con la app abierta.
        await registrar_evento(
            conn, event_type="actuacion_notificada", user_id=user_id, actor_id=autor_id,
            metadata={"caso_id": caso_id, "actuacion_id": actuacion["id"], "categoria": actuacion["categoria"]},
        )

    return actuacion


@router.get("/casos/{caso_id}/actuaciones")
async def listar_actuaciones_endpoint(caso_id: str, request: Request, current: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)
    return await list_actuaciones(conn, caso_id=caso_id)


@router.patch("/casos/{caso_id}/actuaciones/{actuacion_id}/resultado")
async def set_resultado_actuacion_endpoint(
    caso_id: str, actuacion_id: str, payload: SetResultadoActuacionRequest,
    request: Request, current: dict = Depends(get_current_user),
):
    # Roadmap Fase 4 (analítica UGPP): el resultado de un fallo es un juicio
    # legal del despacho -- nunca lo marca el cliente, mismo principio que
    # "el cliente nunca configura su propio cobro" (core/cobro.py).
    if current["role"] not in ("abogado", "admin"):
        raise HTTPException(status_code=403, detail="Solo un abogado o admin puede registrar el resultado de un fallo")
    if payload.resultado not in RESULTADOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Resultado inválido (válidos: {RESULTADOS_VALIDOS})")

    conn = _get_db(request)
    await _preparar(conn)
    await _caso_con_acceso(conn, caso_id, current)

    actuacion = await get_actuacion(conn, actuacion_id)
    if actuacion is None or str(actuacion["caso_id"]) != caso_id:
        raise HTTPException(status_code=404, detail="Actuación no encontrada en este caso")

    try:
        return await set_resultado_actuacion(
            conn, actuacion_id=actuacion_id, resultado=payload.resultado,
            tipo_resolucion_ugpp=payload.tipo_resolucion_ugpp,
        )
    except ActuacionNoEsFalloError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
