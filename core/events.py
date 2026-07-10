"""
Vridik — core/events.py
Roadmap Semana 11, Fase B: canal de eventos genérico y multiplexado sobre
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
"""

from __future__ import annotations

import json


def canal_de_usuario(user_id: str) -> str:
    return f"vridik_events_{user_id}"


async def notificar_evento(conn, *, user_id: str, tipo: str, payload: dict | None = None) -> None:
    """`conn` puede ser el Pool o una Connection cualquiera -- a diferencia
    de escuchar_eventos() (api/events_endpoint.py), notificar no necesita
    una conexión dedicada, cualquier conexión del pool sirve para un
    `pg_notify()` puntual."""
    cuerpo = json.dumps({"type": tipo, **(payload or {})})
    await conn.execute("SELECT pg_notify($1, $2)", canal_de_usuario(user_id), cuerpo)
