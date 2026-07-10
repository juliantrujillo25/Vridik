"""
Vridik — api/events_endpoint.py
Roadmap Semana 11, Fase B: GET /api/events/stream -- canal SSE genérico y
multiplexado (core/events.py) sobre PostgreSQL NOTIFY/LISTEN.

Auth: Authorization: Bearer <token>, igual que el resto de la API -- el
roadmap pide explícitamente "nunca el access token en la URL" y recomienda
fetch+ReadableStream en el cliente (el EventSource nativo del navegador no
puede mandar headers custom, así que no se soporta acá; el ticket efímero
de 30s que el roadmap ofrece como alternativa queda para cuando haga falta
un consumidor que sí dependa de EventSource).

Reconexión real (Last-Event-ID + buffer `user_events` de 24h + evento
`resync`) es Fase C -- esta primera versión reenvía cada NOTIFY tal cual
apenas llega, sin buffer de recuperación: si el cliente estuvo
desconectado, se pierde lo que pasó mientras tanto (aceptable para esta
fase: el REST normal sigue siendo la fuente de verdad, el stream es pura
optimización de latencia).

El `yield ": keep-alive\n\n"` cada 25s SÍ es necesario desde esta fase
(no se puede diferir a la C): sin heartbeat, un proxy/load balancer
intermedio (Railway incluido) puede cortar una conexión HTTP que no
manda bytes por un rato largo, y es también el mecanismo con el que este
generador nota que el cliente se desconectó (`request.is_disconnected()`
se chequea en cada vuelta del loop, no solo al bloquear en la cola).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.events import canal_de_usuario

router = APIRouter(tags=["events"])

_INTERVALO_HEARTBEAT_SEGUNDOS = 25.0


async def _generador_sse(pool, *, user_id: str, request: Request):
    conn = await pool.acquire()
    cola: asyncio.Queue[str] = asyncio.Queue()
    canal = canal_de_usuario(user_id)

    def _al_recibir_notify(connection, pid, channel, payload):
        cola.put_nowait(payload)

    await conn.add_listener(canal, _al_recibir_notify)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(cola.get(), timeout=_INTERVALO_HEARTBEAT_SEGUNDOS)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        await conn.remove_listener(canal, _al_recibir_notify)
        await pool.release(conn)


@router.get("/api/events/stream")
async def stream_events(request: Request, current: dict = Depends(get_current_user)):
    pool = _get_db(request)
    return StreamingResponse(
        _generador_sse(pool, user_id=str(current["id"]), request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # evita que un proxy intermedio bufferee el stream
        },
    )
