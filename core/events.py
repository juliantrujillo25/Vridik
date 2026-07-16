"""
Vridik — core/events.py
Roadmap Semana 11: canal de eventos genérico y multiplexado sobre
PostgreSQL NOTIFY/LISTEN (cero infra nueva, tal como pide el roadmap) --
GET /api/events/stream (api/events_endpoint.py) es el consumidor.
`message.new` es el primer tipo de evento; `pdf.ready`/`error` (Fase D) y
los de Fase 2 del roadmap (`actuacion.nueva`, `termino.alerta`) se agregan
después sin cambiar el canal ni el formato.

Patrón "notificar-y-buscar": el evento NUNCA lleva el contenido completo,
solo IDs -- quien lo recibe hace un fetch normal contra la API REST
existente (GET /casos/{id}/mensajes, etc.), que ya aplica permisos. Esto
evita duplicar lógica de autorización dentro del canal de eventos.

Un canal NOTIFY por usuario (`vridik_events_<user_id>`) en vez de uno
global filtrado en cada conexión abierta -- Postgres entrega el NOTIFY
solo a quien esté escuchando ese canal puntual, así que decidir "a quién
le importa este evento" pasa una sola vez en notificar_evento() (a partir
de quién tiene acceso al recurso -- cliente/abogado de un caso, etc.), no
en cada conexión SSE.

`pg_notify(canal, payload)` en vez de `NOTIFY canal, 'payload'` porque
NOTIFY no acepta placeholders para el nombre del canal (es un identificador
SQL, no un valor) -- pg_notify() sí lo toma como argumento normal.

Fase C (reconexión): además del NOTIFY en vivo, cada evento se guarda en
`user_events` -- un buffer con TTL de 24h (roadmap) que
api/events_endpoint.py usa para reproducir lo que un cliente se perdió
mientras estuvo desconectado (`Last-Event-ID`) o, si el buffer ya no
tiene ese ID (TTL vencido), para decidir mandarle un evento `resync` en
vez de un replay parcial. Purga oportunista en cada notificar_evento() --
sin cron nuevo, "cero infra nueva" aplica también acá.
"""

from __future__ import annotations

import json

TTL_HORAS_BUFFER = 24


def canal_de_usuario(user_id: str) -> str:
    return f"vridik_events_{user_id}"


async def ensure_events_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_events (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_user_events_user_id_id ON user_events (user_id, id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_user_events_created_at ON user_events (created_at)")


async def notificar_evento(conn, *, user_id: str, tipo: str, payload: dict | None = None) -> int:
    """Guarda el evento en el buffer (RETURNING id -- ese id es el mismo
    que viaja en el NOTIFY y en el campo `id:` de SSE, así el cliente
    puede usarlo tal cual como Last-Event-ID en la próxima reconexión) y
    lo notifica en vivo. Devuelve el id asignado."""
    # default=str: el payload suele traer IDs devueltos por asyncpg (UUID de
    # verdad, no str) tal cual salen de una fila -- p.ej. actuacion["id"] en
    # api/actuaciones_endpoint.py. Sin esto, json.dumps revienta con
    # "Object of type UUID is not JSON serializable" apenas un caller pase
    # un valor así (bug real encontrado en producción: rompía POST
    # /casos/{id}/actuaciones con 500 cada vez que había un destinatario).
    cuerpo = payload or {}
    fila = await conn.fetchrow(
        """
        INSERT INTO user_events (user_id, event_type, payload)
        VALUES ($1, $2, $3::jsonb)
        RETURNING id
        """,
        user_id, tipo, json.dumps(cuerpo, default=str),
    )
    evento_id = fila["id"]

    mensaje = json.dumps({"id": evento_id, "type": tipo, **cuerpo}, default=str)
    await conn.execute("SELECT pg_notify($1, $2)", canal_de_usuario(user_id), mensaje)

    await conn.execute(f"DELETE FROM user_events WHERE created_at < now() - interval '{TTL_HORAS_BUFFER} hours'")

    return evento_id


async def existe_evento(conn, *, user_id: str, evento_id: int) -> bool:
    """True si `evento_id` todavía está en el buffer de `user_id` -- si no
    (TTL vencido, o el cliente nunca vio ningún evento real de este
    usuario), api/events_endpoint.py manda un `resync` completo en vez de
    intentar un replay parcial que ya no puede ser fiel."""
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM user_events WHERE user_id = $1 AND id = $2)", user_id, evento_id,
        )
    )


async def listar_eventos_desde(conn, *, user_id: str, desde_id: int) -> list[dict]:
    """Eventos de `user_id` con id > desde_id, más viejo primero (orden de
    reproducción) -- llamar solo después de confirmar con existe_evento()
    que `desde_id` sigue en el buffer."""
    filas = await conn.fetch(
        "SELECT id, event_type, payload, created_at FROM user_events WHERE user_id = $1 AND id > $2 ORDER BY id ASC",
        user_id, desde_id,
    )
    return [dict(f) for f in filas]
