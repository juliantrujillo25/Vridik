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

Roadmap Semana 12-13 (hardening): `ip_address`/`user_agent` ya existían en
el schema (`schema_semana1_vridik.sql`/`migrations/005_...sql`) pero nunca
se escribían -- `core/rate_limit.py` los necesita para el rate limiting de
login por email+IP.
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
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO auth_events (user_id, actor_id, event_type, metadata, ip_address, user_agent)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        """,
        user_id, actor_id, event_type, json.dumps(metadata or {}), ip_address, user_agent,
    )
