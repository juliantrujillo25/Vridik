"""
Vridik — core/refresh_tokens.py
Fase B (S1-GAP-01, AUDITORIA_PARA_CLAUDE.md): refresh tokens con rotación y
detección de reuso, sobre la tabla `refresh_tokens` de
migrations/005_auth_roles_refresh_tokens.sql.

Diseño (ver schema_semana1_vridik.sql, comentario de refresh_tokens):
  - Nunca se guarda el token en claro: solo `token_hash` (SHA-256) — mismo
    principio que `totp_secret`/códigos de respaldo en core/totp_2fa.py.
  - Rotación: cada vez que se usa un refresh token, se marca `used_at` y
    se emite uno nuevo encadenado por `replaced_by_id`, en la misma
    `family_id` (agrupa toda la cadena de una sesión).
  - Detección de reuso: si un token con `used_at` ya puesto se presenta de
    nuevo, es indicio de robo (alguien más capturó el token viejo) —
    se revoca TODA la familia (todas las sesiones derivadas de ese login)
    y se levanta `ReusoDetectado` para que el llamador registre el
    auth_event correspondiente.
  - Gracia de 10s: dos pestañas del mismo navegador pueden intentar rotar
    el mismo refresh token casi al mismo tiempo (carrera legítima, no un
    ataque). Si el reuso ocurre dentro de los 10s posteriores a la
    rotación original, se trata como carrera benigna: se emite un token
    nuevo encadenado a la misma familia en vez de revocarla.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

REFRESH_TOKEN_EXPIRE_DAYS = 7
GRACIA_REUSO_SEGUNDOS = 10


class ReusoDetectado(Exception):
    """Se presentó un refresh token ya usado fuera de la ventana de gracia
    -- toda la familia queda revocada antes de levantar esta excepción."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"Reuso de refresh token detectado para user_id={user_id}")


def _hash_token(token_plano: str) -> str:
    return hashlib.sha256(token_plano.encode("utf-8")).hexdigest()


async def emitir_refresh_token(conn, *, user_id: str, family_id: str | None = None) -> tuple[str, str]:
    """Crea un refresh token nuevo. `family_id=None` arranca una familia
    nueva (login inicial); pasar la family_id existente lo encadena como
    parte de una rotación. Devuelve (token_plano, family_id) -- el texto
    plano solo existe en este retorno, nunca se persiste."""
    token_plano = secrets.token_urlsafe(48)
    token_hash = _hash_token(token_plano)
    family = family_id or str(uuid.uuid4())
    expira = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    await conn.execute(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        user_id, token_hash, family, expira,
    )
    return token_plano, family


async def rotar_refresh_token(conn, *, token_plano: str) -> tuple[str, str, str]:
    """Valida y rota un refresh token. Devuelve (nuevo_token_plano, user_id,
    family_id). Levanta ValueError si el token es inválido/revocado/expirado,
    o ReusoDetectado (con la familia ya revocada) si se detecta reuso fuera
    de la ventana de gracia."""
    token_hash = _hash_token(token_plano)
    fila = await conn.fetchrow(
        """
        SELECT id, user_id, family_id, used_at, revoked_at, expires_at
        FROM refresh_tokens WHERE token_hash = $1
        """,
        token_hash,
    )
    if fila is None:
        raise ValueError("Refresh token inválido")
    if fila["revoked_at"] is not None:
        raise ValueError("Refresh token revocado")
    if fila["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("Refresh token expirado")

    if fila["used_at"] is not None:
        segundos_desde_uso = (datetime.now(timezone.utc) - fila["used_at"]).total_seconds()
        if segundos_desde_uso <= GRACIA_REUSO_SEGUNDOS:
            # Carrera de dos pestañas: se tolera, se emite un token nuevo
            # encadenado a la misma familia (no se puede devolver el token
            # que ya reemplazó a este porque solo se guarda su hash).
            nuevo_token, _ = await emitir_refresh_token(
                conn, user_id=str(fila["user_id"]), family_id=str(fila["family_id"]),
            )
            return nuevo_token, str(fila["user_id"]), str(fila["family_id"])

        await conn.execute(
            """
            UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = 'reuse_detected'
            WHERE family_id = $1 AND revoked_at IS NULL
            """,
            fila["family_id"],
        )
        raise ReusoDetectado(str(fila["user_id"]))

    nuevo_token, _ = await emitir_refresh_token(
        conn, user_id=str(fila["user_id"]), family_id=str(fila["family_id"]),
    )
    nuevo_hash = _hash_token(nuevo_token)
    nueva_fila = await conn.fetchrow("SELECT id FROM refresh_tokens WHERE token_hash = $1", nuevo_hash)
    await conn.execute(
        "UPDATE refresh_tokens SET used_at = now(), replaced_by_id = $1 WHERE id = $2",
        nueva_fila["id"], fila["id"],
    )
    return nuevo_token, str(fila["user_id"]), str(fila["family_id"])


async def revocar_refresh_token(conn, *, token_plano: str, motivo: str = "logout") -> str | None:
    """Revoca un único refresh token (no toda la familia -- logout de una
    sola sesión/dispositivo, no de todas). Devuelve el user_id revocado, o
    None si el token no existía o ya estaba revocado (logout idempotente:
    nunca es un error volver a llamarlo)."""
    token_hash = _hash_token(token_plano)
    fila = await conn.fetchrow(
        """
        UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = $2
        WHERE token_hash = $1 AND revoked_at IS NULL
        RETURNING user_id
        """,
        token_hash, motivo,
    )
    return str(fila["user_id"]) if fila else None


async def revocar_todas_las_sesiones(conn, *, user_id: str, motivo: str = "user_deactivated") -> None:
    """Revoca todos los refresh tokens activos de un usuario -- usado al
    desactivar una cuenta o en un reset de contraseña administrativo."""
    await conn.execute(
        """
        UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = $2
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id, motivo,
    )
