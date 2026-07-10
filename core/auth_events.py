"""
Vridik — core/auth_events.py
Fase B (S1-GAP-01, AUDITORIA_PARA_CLAUDE.md): embrión de la bitácora
probatoria del roadmap (Fase 3: bitácora sellada con hash encadenado).

`registrar_evento()` es append-only por convención de aplicación — nunca se
hace UPDATE/DELETE sobre `auth_events` desde código de negocio, solo INSERT.
Falla silenciosamente nunca: si la tabla no existe todavía (Fase A no
aplicada en algún entorno), levanta el error de Postgres tal cual, no lo
traga -- registrar un evento de auditoría es parte del contrato, no un
best-effort.
"""

from __future__ import annotations

import json


async def registrar_evento(
    conn,
    *,
    event_type: str,
    user_id: str | None = None,
    actor_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        user_id, actor_id, event_type, json.dumps(metadata or {}),
    )
