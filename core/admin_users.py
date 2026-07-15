"""
Vridik — core/admin_users.py
Sprint S2: CRUD real del panel de administración de usuarios sobre
`schema_semana1_vridik.sql` (tablas `users`, `user_credentials`,
`refresh_tokens`, `auth_events`). Reemplaza el contrato de
`tests/support/fakes.py:FakeRolesService` (que sigue existiendo para
autorización por módulo, sin tocar) con la implementación real de negocio
que faltaba: crear, listar, editar, desactivar y resetear contraseña.

Diseño:
  - Contraseña temporal: se genera con `secrets.token_urlsafe` (nunca
    predecible), se hashea con bcrypt (mismo algoritmo que ya usa
    `core/feature_flag_legacy.py:autenticar_postgres`) y se retorna en
    texto plano UNA sola vez al llamador — para que el admin la copie y
    se la entregue al usuario. Nunca se vuelve a poder leer después.
  - `must_change=true` / `user_credentials.is_temporary=true` en toda
    contraseña generada por este módulo (creación o reset) — el usuario
    debe cambiarla en su primer login, nunca queda una temporal como
    definitiva por accidente.
  - Desactivar o resetear un usuario SIEMPRE revoca sus refresh tokens
    activos (`revoked_at`/`revoked_reason`) — un usuario desactivado o con
    contraseña reseteada no debe poder seguir usando una sesión ya
    emitida; sin esto, el efecto de "desactivar" tardaría hasta que el
    access token de 15 min expire por su cuenta.
  - Cada operación de escritura deja un `auth_events` con `actor_id` (quién
    la ejecutó) — nunca se muta `users`/`user_credentials` sin dejar
    rastro auditable, mismo principio que `core/feature_flag_legacy.py`
    con `legacy_fallback`.
  - Email duplicado: se valida ANTES del insert con un SELECT explícito
    (no se depende de capturar la excepción de constraint de PostgreSQL),
    para que el resultado sea el mismo `EmailDuplicadoError` tanto contra
    una conexión real (citext ya compara sin distinguir mayúsculas) como
    contra un fake de conexión en tests.

NO SE EJECUTA CONTRA POSTGRESQL REAL EN ESTE ENTREGABLE — verificado con
pruebas unitarias sobre un fake de conexión (ver tests/test_admin_users.py).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.auth_events import registrar_evento as _registrar_evento

try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore

ROLES_VALIDOS = {"admin", "abogado", "cliente"}
LONGITUD_PASSWORD_TEMPORAL = 16


class AdminUsersError(Exception):
    """Base de errores de negocio de este módulo — el llamador HTTP
    (api/admin_users_endpoint.py) los traduce a códigos de estado."""


class EmailDuplicadoError(AdminUsersError):
    """Email ya en uso por otro usuario no borrado (comparación
    case-insensitive vía citext en Postgres real)."""


class UsuarioNoEncontradoError(AdminUsersError):
    pass


class RolInvalidoError(AdminUsersError):
    pass


@dataclass
class UsuarioCreado:
    user_id: str
    email: str
    password_temporal: str  # texto plano, se muestra UNA sola vez


@dataclass
class ResultadoReset:
    user_id: str
    password_temporal: str  # texto plano, se muestra UNA sola vez


def _requiere_bcrypt() -> None:
    if bcrypt is None:
        raise RuntimeError("core.admin_users requiere 'bcrypt' instalado (pip install bcrypt)")


def generar_password_temporal() -> str:
    """Contraseña temporal aleatoria, nunca predecible — `secrets`, no
    `random`."""
    return secrets.token_urlsafe(LONGITUD_PASSWORD_TEMPORAL)


def _hash_password(password_plain: str) -> str:
    _requiere_bcrypt()
    return bcrypt.hashpw(password_plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def _revocar_refresh_tokens(conn, *, user_id: str, motivo: str) -> None:
    """Revoca todos los refresh tokens activos del usuario. `revoked_at`
    se marca solo si todavía no estaba revocado ni usado — no se pisa el
    motivo de una revocación/uso anterior."""
    await conn.execute(
        """
        UPDATE refresh_tokens
        SET revoked_at = now(), revoked_reason = $2
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id, motivo,
    )


async def crear_usuario(
    conn, *, actor_id: str, email: str, nombre_completo: str, role_codigo: str,
) -> UsuarioCreado:
    """Crea un usuario con contraseña temporal generada por el backend.
    `role_codigo` debe ser uno de ROLES_VALIDOS. Email duplicado (entre
    usuarios no borrados) -> EmailDuplicadoError (409 en la capa HTTP)."""
    if role_codigo not in ROLES_VALIDOS:
        raise RolInvalidoError(f"Rol inválido: {role_codigo!r} (válidos: {sorted(ROLES_VALIDOS)})")

    existente = await conn.fetchrow(
        "SELECT id FROM users WHERE email = $1 AND deleted_at IS NULL", email,
    )
    if existente is not None:
        raise EmailDuplicadoError(f"Ya existe un usuario activo con email {email!r}")

    role_row = await conn.fetchrow("SELECT id FROM roles WHERE codigo = $1", role_codigo)
    if role_row is None:
        raise RolInvalidoError(f"Rol no encontrado en la tabla roles: {role_codigo!r}")

    password_temporal = generar_password_temporal()
    password_hash = _hash_password(password_temporal)

    fila = await conn.fetchrow(
        """
        INSERT INTO users (email, nombre_completo, role_id, must_change, is_active)
        VALUES ($1, $2, $3, true, true)
        RETURNING id
        """,
        email, nombre_completo, role_row["id"],
    )
    user_id = str(fila["id"])

    await conn.execute(
        """
        INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary, updated_by)
        VALUES ($1, $2, 'bcrypt', true, $3)
        """,
        user_id, password_hash, actor_id,
    )

    await _registrar_evento(
        conn, user_id=user_id, actor_id=actor_id, event_type="user_created",
        metadata={"email": email, "role_codigo": role_codigo},
    )

    return UsuarioCreado(user_id=user_id, email=email, password_temporal=password_temporal)


async def listar_usuarios(conn) -> list[dict]:
    """Nunca selecciona `password_hash` — el listado del panel admin no
    debe poder filtrar credenciales ni por accidente (SELECT * evitado
    deliberadamente)."""
    filas = await conn.fetch(
        """
        SELECT u.id, u.email, u.nombre_completo, r.codigo AS role_codigo,
               u.is_active, u.must_change, u.last_login_at, u.created_at
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.deleted_at IS NULL
        ORDER BY u.created_at DESC
        """
    )
    return [dict(f) for f in filas]


async def editar_usuario(
    conn, *, actor_id: str, user_id: str, nombre_completo: str | None = None, role_codigo: str | None = None,
) -> None:
    fila = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL", user_id)
    if fila is None:
        raise UsuarioNoEncontradoError(f"Usuario no encontrado: {user_id}")

    cambios: dict = {}
    if nombre_completo is not None:
        await conn.execute(
            "UPDATE users SET nombre_completo = $2, updated_at = now() WHERE id = $1", user_id, nombre_completo,
        )
        cambios["nombre_completo"] = nombre_completo
    if role_codigo is not None:
        if role_codigo not in ROLES_VALIDOS:
            raise RolInvalidoError(f"Rol inválido: {role_codigo!r} (válidos: {sorted(ROLES_VALIDOS)})")
        role_row = await conn.fetchrow("SELECT id FROM roles WHERE codigo = $1", role_codigo)
        if role_row is None:
            raise RolInvalidoError(f"Rol no encontrado en la tabla roles: {role_codigo!r}")
        await conn.execute(
            "UPDATE users SET role_id = $2, updated_at = now() WHERE id = $1", user_id, role_row["id"],
        )
        cambios["role_codigo"] = role_codigo

    if cambios:
        await _registrar_evento(conn, user_id=user_id, actor_id=actor_id, event_type="user_updated", metadata=cambios)


async def desactivar_usuario(conn, *, actor_id: str, user_id: str) -> None:
    """Soft-desactivación (`is_active=false`, `deactivated_at=now()`) +
    revocación inmediata de refresh tokens — el efecto surte en el
    siguiente intento de refresh, no hay que esperar 15 min a que expire
    el access token en circulación."""
    fila = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL", user_id)
    if fila is None:
        raise UsuarioNoEncontradoError(f"Usuario no encontrado: {user_id}")

    await conn.execute(
        "UPDATE users SET is_active = false, deactivated_at = now(), updated_at = now() WHERE id = $1", user_id,
    )
    await _revocar_refresh_tokens(conn, user_id=user_id, motivo="user_deactivated")
    await _registrar_evento(conn, user_id=user_id, actor_id=actor_id, event_type="user_deactivated")


async def resetear_password(conn, *, actor_id: str, user_id: str) -> ResultadoReset:
    """Genera una nueva contraseña temporal, la marca `is_temporary=true`
    (fuerza cambio en el próximo login vía `must_change`) y revoca los
    refresh tokens activos — una sesión ya abierta con la contraseña
    anterior no debe sobrevivir a un reset administrativo.

    Escribe la contraseña nueva tanto en `user_credentials` como en
    `users.hashed_password` (dual-write, mismo patrón de Fase B en
    api/auth_endpoint.py) -- POST /auth/login todavía lee
    `users.hashed_password` como fuente real (el cutover completo a
    `user_credentials` es Fase C); sin esto el reset no tendría efecto en
    el login real. El upsert en `user_credentials` cubre también usuarios
    creados por api/admin_endpoint.py::post_users, que hoy no escribe ahí."""
    fila = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL", user_id)
    if fila is None:
        raise UsuarioNoEncontradoError(f"Usuario no encontrado: {user_id}")

    password_temporal = generar_password_temporal()
    password_hash = _hash_password(password_temporal)

    await conn.execute(
        """
        INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary, updated_by)
        VALUES ($1, $2, 'bcrypt', true, $3)
        ON CONFLICT (user_id) DO UPDATE
        SET password_hash = $2, hash_algorithm = 'bcrypt', is_temporary = true, updated_at = now(), updated_by = $3
        """,
        user_id, password_hash, actor_id,
    )
    await conn.execute(
        "UPDATE users SET hashed_password = $2, must_change = true, updated_at = now() WHERE id = $1",
        user_id, password_hash,
    )
    await _revocar_refresh_tokens(conn, user_id=user_id, motivo="admin_reset")
    await _registrar_evento(conn, user_id=user_id, actor_id=actor_id, event_type="password_reset")

    return ResultadoReset(user_id=user_id, password_temporal=password_temporal)


async def actividad_usuario(conn, *, user_id: str, limite: int = 50) -> list[dict]:
    """Sección "Actividad" del panel (pedida explícitamente en S2): lee
    `auth_events` del usuario, más recientes primero."""
    filas = await conn.fetch(
        """
        SELECT id, event_type, metadata, ip_address, user_agent, created_at
        FROM auth_events
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id, limite,
    )
    return [dict(f) for f in filas]
