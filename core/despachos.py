"""
Vridik — core/despachos.py
Fase 4 (Escalamiento): fundación de multi-tenancy real -- "despacho" es el
límite de tenant (Ley 1581 entre despachos, roadmap Fase 4).

Hasta hoy Vridik era de un solo despacho: cero concepto de tenant en el
esquema. `users.despacho_id` es la raíz de la jerarquía (todo lo demás
cuelga de `users.id` o de `casos.id`, que a su vez cuelga de
`users.id` vía `cliente_id`/`abogado_id`).

Mismo criterio que `role` (core/auth.py, core/admin.py): despacho_id NUNCA
va en el JWT -- se resuelve fresco por request desde `users.despacho_id`
(ver `api/admin_endpoint.py::_resolver_usuario`), para que mover o
desactivar un usuario tome efecto sin esperar el vencimiento del token.

Dos niveles de `ensure_*`, mismo patrón que el resto del código:
  - `ensure_despachos_table()`: barato (CREATE/ALTER IF NOT EXISTS), seguro
    de correr en cada request.
  - `ensure_despachos_backfill()`: caro (backfill real + SET NOT NULL), una
    sola vez al arrancar el proceso (ver app/main.py::_conectar_db, mismo
    patrón que ensure_auth_migration_005/ensure_bitacora_hash_chain).
"""

from __future__ import annotations

from core.db_utils import conexion_dedicada, transaccion_si_disponible

_LOCK_KEY_BACKFILL = "vridik_despachos_backfill"
_NOMBRE_DESPACHO_POR_DEFECTO = "Despacho por defecto"


async def ensure_despachos_table(conn) -> None:
    """Nivel barato: crea la tabla y la columna si no existen. No hace
    backfill ni toca NOT NULL -- eso es `ensure_despachos_backfill()`,
    a propósito en otra función para no pagar ese costo en cada request."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS despachos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre TEXT NOT NULL,
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS despacho_id UUID REFERENCES despachos(id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_users_despacho_id ON users (despacho_id)")


async def ensure_despachos_backfill(conn) -> None:
    """Sella retroactivamente los usuarios que ya existían antes de que
    este módulo existiera (despacho_id IS NULL, como cualquier entorno con
    historial previo) en un "Despacho por defecto", y recién ahí exige
    NOT NULL -- mismo principio que `core.auth_events.ensure_bitacora_
    hash_chain`: sin este paso, cualquier entorno real con usuarios previos
    tendría filas con despacho_id NULL para siempre.

    Idempotente: si no hay usuarios pendientes, el backfill es un no-op;
    `ALTER COLUMN ... SET NOT NULL` sobre una columna ya NOT NULL tampoco
    falla en Postgres, así que correr esto en cada arranque es seguro."""
    await ensure_despachos_table(conn)
    async with conexion_dedicada(conn) as conexion:
        async with transaccion_si_disponible(conexion):
            await conexion.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _LOCK_KEY_BACKFILL)
            await _backfill_despacho_por_defecto(conexion)
            await conexion.execute("ALTER TABLE users ALTER COLUMN despacho_id SET NOT NULL")


async def _backfill_despacho_por_defecto(conexion) -> None:
    hay_pendientes = await conexion.fetchval("SELECT EXISTS(SELECT 1 FROM users WHERE despacho_id IS NULL)")
    if not hay_pendientes:
        return

    despacho_id = await conexion.fetchval(
        "SELECT id FROM despachos WHERE nombre = $1 LIMIT 1", _NOMBRE_DESPACHO_POR_DEFECTO,
    )
    if despacho_id is None:
        despacho_id = await conexion.fetchval(
            "INSERT INTO despachos (nombre) VALUES ($1) RETURNING id", _NOMBRE_DESPACHO_POR_DEFECTO,
        )
    await conexion.execute("UPDATE users SET despacho_id = $1 WHERE despacho_id IS NULL", despacho_id)
