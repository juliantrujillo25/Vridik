"""
Vridik — core/admin.py
Sprint S2: CRUD básico de usuarios para el panel admin (api/admin_endpoint.py)
sobre la misma tabla `users` de S1 (api/auth_endpoint.py, core/auth.py) —
nunca la tabla `roles`/`user_credentials` de core/admin_users.py (schema
distinto, sin relación con los JWT reales que emite core.auth.create_jwt).

`ensure_role_column()` es idempotente (mismo patrón que
core.auth.ensure_users_table / core.totp_2fa.ensure_totp_columns): agrega
`role` a `users` si todavía no existe, con 'seller' como default seguro (un
usuario nuevo nunca nace admin por accidente).
"""

from __future__ import annotations


async def ensure_role_column(db_connection) -> None:
    await db_connection.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'seller'"
    )


async def list_users(db_connection, *, skip: int, limit: int) -> list[dict]:
    filas = await db_connection.fetch(
        """
        SELECT id, email, role, is_active, created_at
        FROM users
        ORDER BY created_at DESC
        OFFSET $1 LIMIT $2
        """,
        skip, limit,
    )
    return [dict(f) for f in filas]


async def create_user(db_connection, *, email: str, password_hash: str, role: str) -> dict:
    fila = await db_connection.fetchrow(
        """
        INSERT INTO users (email, hashed_password, role, is_active)
        VALUES ($1, $2, $3, true)
        RETURNING id, email, role, is_active, created_at
        """,
        email, password_hash, role,
    )
    return dict(fila)


async def change_role(db_connection, *, user_id: str, new_role: str) -> dict | None:
    """Retorna el usuario actualizado, o None si `user_id` no existe —
    el llamador (api/admin_endpoint.py) decide si eso es un 404."""
    fila = await db_connection.fetchrow(
        """
        UPDATE users SET role = $2 WHERE id = $1
        RETURNING id, email, role, is_active, created_at
        """,
        user_id, new_role,
    )
    return dict(fila) if fila is not None else None
