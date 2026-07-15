"""
Vridik — core/admin.py
Sprint S2: CRUD básico de usuarios para el panel admin (api/admin_endpoint.py)
sobre la misma tabla `users` de S1 (api/auth_endpoint.py, core/auth.py) —
nunca la tabla `roles`/`user_credentials` de core/admin_users.py (schema
distinto, sin relación con los JWT reales que emite core.auth.create_jwt).

`ensure_role_column()` es idempotente (mismo patrón que
core.auth.ensure_users_table / core.totp_2fa.ensure_totp_columns): agrega
`role` a `users` si todavía no existe, con 'cliente' como default seguro
(un usuario nuevo nunca nace admin ni abogado por accidente — S6:
core/permissions.py, 'cliente' es el usuario registrado sin rol especial.
Vocabulario migrado del marketplace original -- admin/seller/customer --
al vocabulario del producto real, admin/abogado/cliente).

El `ADD COLUMN IF NOT EXISTS` de abajo es un no-op sobre una columna que ya
existe (como `role` en producción desde S2, con default histórico
`'seller'`) — por eso el `ALTER COLUMN ... SET DEFAULT` aparte, para que
los registros nuevos sí empiecen a nacer 'cliente' aunque la columna ya
estuviera creada.
"""

from __future__ import annotations


async def ensure_role_column(db_connection) -> None:
    # Migración de vocabulario de roles (dev lead): default 'cliente', no
    # 'customer' -- si la columna ya existía con el default viejo (de
    # cualquier sprint anterior), el ALTER COLUMN de abajo lo corrige.
    await db_connection.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'cliente'"
    )
    await db_connection.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'cliente'")


async def list_users(db_connection, *, despacho_id: str, skip: int, limit: int) -> list[dict]:
    """Fase 4: acotado al despacho del admin que pide la lista -- antes
    traía TODOS los usuarios de la plataforma sin importar de qué despacho
    fueran (AUDITORIA)."""
    filas = await db_connection.fetch(
        """
        SELECT id, email, role, despacho_id, is_active, created_at
        FROM users
        WHERE despacho_id = $1
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3
        """,
        despacho_id, skip, limit,
    )
    return [dict(f) for f in filas]


async def create_user(db_connection, *, email: str, password_hash: str, role: str, despacho_id: str) -> dict:
    fila = await db_connection.fetchrow(
        """
        INSERT INTO users (email, hashed_password, role, despacho_id, is_active)
        VALUES ($1, $2, $3, $4, true)
        RETURNING id, email, role, despacho_id, is_active, created_at
        """,
        email, password_hash, role, despacho_id,
    )
    # Fase C (S1-GAP-01): dual-write a user_credentials -- sin esto, un
    # usuario creado vía POST /admin/users (a diferencia de /auth/register,
    # que sí lo hace desde Fase B) quedaba sin fila en user_credentials, y
    # /auth/login no podría autenticarlo una vez que el login lea de ahí
    # como fuente real en vez de users.hashed_password.
    await db_connection.execute(
        "INSERT INTO user_credentials (user_id, password_hash) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
        fila["id"], password_hash,
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
