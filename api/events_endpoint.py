"""
Vridik — api/events_endpoint.py
Roadmap Semana 11: GET /api/events/stream -- canal SSE genérico y
multiplexado (core/events.py) sobre PostgreSQL NOTIFY/LISTEN.

Auth: Authorization: Bearer <token>, igual que el resto de la API -- el
roadmap pide explícitamente "nunca el access token en la URL" y recomienda
fetch+ReadableStream en el cliente (el EventSource nativo del navegador no
puede mandar headers custom, así que no se soporta acá; el ticket efímero
de 30s que el roadmap ofrece como alternativa queda para cuando haga falta
un consumidor que sí dependa de EventSource).

Fase C (reconexión): el cliente manda el header `Last-Event-ID` con el
`id` del último evento SSE que vio (el mismo valor que este endpoint
manda en el campo `id:` de cada evento). Al reconectar:
  - Si ese id todavía está en el buffer (`core.events.existe_evento`,
    TTL 24h), se reproducen los eventos posteriores en orden ANTES de
    seguir con el stream en vivo -- el cliente no perdió nada.
  - Si no está (TTL vencido, o nunca hubo un evento con ese id para este
    usuario), se manda un solo evento `event: resync` -- el cliente debe
    asumir que su estado puede estar desactualizado y volver a pedir todo
    por REST (el fetch es la verdad, el stream es optimización, tal como
    lo plantea el roadmap).

Orden importante para no perder eventos en la ventana de reconexión:
`add_listener()` (Fase B) se activa ANTES de leer/reproducir el buffer,
así que cualquier evento que llegue justo en ese momento queda en la cola
en memoria en vez de perderse -- puede aparecer duplicado (una vez en el
replay del buffer, otra vez en vivo); un cliente real debe descartar por
`id` cualquier evento <= el último que ya procesó, esta primera versión
backend no lo hace por él.

El `yield ": keep-alive\n\n"` cada 25s es la plomería que hace que este
generador note `request.is_disconnected()` sin bloquearse para siempre
en la cola, y evita que un proxy intermedio corte la conexión por
inactividad.

Presupuesto de conexiones (agregado tras un incidente real, 2026-07-12):
cada stream abierto reserva UNA conexión dedicada del pool de Postgres
durante toda su vida (`pool.acquire()` más abajo) -- no puede usar el
patrón normal de acquire-por-llamada porque necesita LISTEN/NOTIFY sobre
una conexión persistente. Con tráfico real (varios usuarios con el
detalle de un caso abierto a la vez) eso solo, sin ningún bug de por
medio, alcanza para agotar el pool entero y colgar el resto de la API
-- pasó en pruebas de la mensajería en vivo. Dos mitigaciones, además de
subir max_size del pool (app/main.py):
  - `_MAX_CONEXIONES_SSE_CONCURRENTES`: techo dedicado para el streaming,
    para que nunca pueda comerse el pool completo aunque haya legítimos
    muchos usuarios conectados a la vez -- deja margen siempre para
    tráfico REST normal.
  - `_VIDA_MAXIMA_STREAM_SEGUNDOS`: cierra el stream y libera la conexión
    a los 30 minutos aunque siga "vivo" -- el cliente reconecta solo
    (ver frontend/src/api/client.ts streamEvents()). Acota el peor caso
    de una conexión que por lo que sea nunca dispara el `finally` de
    abajo (p.ej. si `request.is_disconnected()` no detecta un corte
    abrupto de red a tiempo).
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.admin_endpoint import get_current_user
from core.events import canal_de_usuario, ensure_events_table, existe_evento, listar_eventos_desde

router = APIRouter(tags=["events"])

_INTERVALO_HEARTBEAT_SEGUNDOS = 25.0
_MAX_CONEXIONES_SSE_CONCURRENTES = 12
_VIDA_MAXIMA_STREAM_SEGUNDOS = 30 * 60

# Contador en memoria del proceso -- no coordina entre instancias si algún
# día la API corre con más de un worker/réplica, pero es consistente con
# el resto del módulo ("cero infra nueva": nada de Redis solo para esto).
_conexiones_sse_activas = 0


def _formatear_evento_sse(*, evento_id: int, tipo: str, payload: dict) -> str:
    cuerpo = json.dumps({"id": evento_id, "type": tipo, **payload})
    return f"id: {evento_id}\ndata: {cuerpo}\n\n"


async def _generador_sse(pool, *, user_id: str, last_event_id: int | None, request: Request):
    global _conexiones_sse_activas

    if _conexiones_sse_activas >= _MAX_CONEXIONES_SSE_CONCURRENTES:
        # Ninguna conexión del pool se llegó a tocar -- el cliente
        # reintenta solo tras el backoff de 2s (streamEvents() en
        # client.ts trata cualquier fin de stream sin más como "reconectar").
        yield "event: resync\ndata: {}\n\n"
        return

    _conexiones_sse_activas += 1
    inicio = time.monotonic()
    conn = await pool.acquire()
    cola: asyncio.Queue[str] = asyncio.Queue()
    canal = canal_de_usuario(user_id)

    def _al_recibir_notify(connection, pid, channel, payload):
        cola.put_nowait(payload)

    try:
        await ensure_events_table(conn)
        await conn.add_listener(canal, _al_recibir_notify)

        if last_event_id is not None:
            if await existe_evento(conn, user_id=user_id, evento_id=last_event_id):
                pendientes = await listar_eventos_desde(conn, user_id=user_id, desde_id=last_event_id)
                for evento in pendientes:
                    yield _formatear_evento_sse(
                        evento_id=evento["id"], tipo=evento["event_type"], payload=json.loads(evento["payload"]),
                    )
            else:
                yield "event: resync\ndata: {}\n\n"

        while True:
            if await request.is_disconnected():
                break
            if time.monotonic() - inicio >= _VIDA_MAXIMA_STREAM_SEGUNDOS:
                break
            try:
                payload = await asyncio.wait_for(cola.get(), timeout=_INTERVALO_HEARTBEAT_SEGUNDOS)
                data = json.loads(payload)
                yield f"id: {data['id']}\ndata: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        await conn.remove_listener(canal, _al_recibir_notify)
        await pool.release(conn)
        _conexiones_sse_activas -= 1


@router.get("/api/events/stream")
async def stream_events(
    request: Request, current: dict = Depends(get_current_user), last_event_id: str | None = None,
):
    # Hardening RLS (core/rls.py): lee el Pool crudo de app.state directo,
    # NO _get_db()/obtener_conexion_de_request() -- este handler adquiere
    # su PROPIA conexión dedicada más abajo (pool.acquire(), sostenida
    # toda la vida del stream para LISTEN/NOTIFY) y necesita el Pool en sí
    # para poder llamar .acquire()/.release() sobre él; la conexión
    # per-request que _get_db() devolvería ahora no tiene esos métodos.
    pool = getattr(request.app.state, "db_connection", None)
    # El header estándar de SSE es "Last-Event-ID" (lo manda EventSource
    # solo; con fetch+ReadableStream lo tiene que mandar el cliente a
    # mano) -- se acepta también como query param ?last_event_id= para
    # un primer curl/debug manual sin tener que setear headers.
    header_value = request.headers.get("last-event-id") or last_event_id
    desde_id: int | None = None
    if header_value:
        try:
            desde_id = int(header_value)
        except ValueError:
            desde_id = None

    return StreamingResponse(
        _generador_sse(pool, user_id=str(current["id"]), last_event_id=desde_id, request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # evita que un proxy intermedio bufferee el stream
        },
    )
