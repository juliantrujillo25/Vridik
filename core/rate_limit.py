"""
Vridik — core/rate_limit.py
Roadmap Fase 1, Semana 12-13 (hardening): rate limiting de login por
email+IP (10 fallos/15 min) y de TOTP (5 fallos/15 min).

Diseño: no se agrega estado nuevo (sin tabla de contadores, sin caché en
memoria que se perdería en cada redeploy) -- se cuenta directo sobre los
eventos que `core/auth_events.py::registrar_evento()` ya escribe en
`auth_events` como parte de la bitácora probatoria. Un intento bloqueado
por el límite ni siquiera llega a verificar la contraseña/código real.

`ip_address` puede ser None (cliente sin IP determinable, p.ej. tests o un
proxy mal configurado) -- se compara con `IS NOT DISTINCT FROM` (null-safe)
para que los intentos sin IP conocida se agrupen entre sí en vez de nunca
matchear entre sí mismos.
"""

from __future__ import annotations

MAX_FALLOS_LOGIN = 10
MAX_FALLOS_TOTP = 5
VENTANA_MINUTOS = 15


async def excede_limite_login(conn, *, email: str, ip_address: str | None) -> bool:
    """True si `email` (desde `ip_address`) acumuló >= MAX_FALLOS_LOGIN
    eventos 'login_failed' de contraseña (no de TOTP) en los últimos
    VENTANA_MINUTOS minutos."""
    conteo = await conn.fetchval(
        """
        SELECT COUNT(*) FROM auth_events
        WHERE event_type = 'login_failed'
          AND metadata->>'email' = $1
          AND ip_address IS NOT DISTINCT FROM $2::inet
          AND (metadata->>'paso') IS DISTINCT FROM '2fa'
          AND created_at > now() - ($3 * interval '1 minute')
        """,
        email, ip_address, VENTANA_MINUTOS,
    )
    return conteo >= MAX_FALLOS_LOGIN


async def excede_limite_totp(conn, *, user_id: str) -> bool:
    """True si `user_id` acumuló >= MAX_FALLOS_TOTP códigos TOTP inválidos
    en los últimos VENTANA_MINUTOS minutos. Por user_id, no por IP -- para
    llegar acá ya se pasó el paso de contraseña, así que el usuario está
    identificado con certeza."""
    conteo = await conn.fetchval(
        """
        SELECT COUNT(*) FROM auth_events
        WHERE event_type = 'login_failed'
          AND user_id = $1
          AND metadata->>'paso' = '2fa'
          AND created_at > now() - ($2 * interval '1 minute')
        """,
        user_id, VENTANA_MINUTOS,
    )
    return conteo >= MAX_FALLOS_TOTP
