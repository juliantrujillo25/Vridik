"""
Vridik — core/case.py
`casos`: entidad propia del despacho legal, independiente del marketplace.

Hasta ahora un "caso" ERA una orden (`orders`, ver core/case_documents.py
original) -- eso funcionaba mientras el marketplace fuera el producto real,
pero la consolidación hacia el copiloto legal (decisión del dev lead) va a
desmantelar `products`/`orders` como no esenciales. `case_documents`
dependía de `orders.id` -- sin esta entidad, desmantelar el marketplace
rompería la generación de documentos de JuliX.

Diseño:
  - `cliente_id`: quién es el cliente del caso (siempre requerido).
  - `abogado_id`: quién lo lleva -- nullable, un caso puede crearse sin
    abogado asignado todavía (lo asigna un admin después, o se autoasigna
    un abogado).
  - `despacho_id`: Fase 4 (multi-tenancy) -- denormalizado, no derivado por
    join. Un caso pertenece a exactamente un despacho; tanto `cliente_id`
    como `abogado_id` (si se asigna) deben pertenecer a ESE despacho, nunca
    a otro (ver `asignar_abogado`). Denormalizarlo acá (en vez de resolverlo
    siempre vía `cliente_id -> users.despacho_id`) evita un join extra en
    cada tabla hija (`case_documents`, `cobro_caso`, `mensajes`, `terminos`,
    `actuaciones` -- todas cuelgan de `caso_id` únicamente) si algún día
    hace falta escalar el filtro de despacho hacia abajo.
  - `estado`: 'abierto' (default) | 'en_progreso' | 'cerrado' -- ciclo de
    vida simple, sin las etapas procesales de Fase 2 del roadmap (motor de
    términos), que llegan después.
  - Ownership (mismo criterio de siempre): dueño del caso (cliente_id),
    abogado asignado (abogado_id), o admin DEL MISMO DESPACHO (Fase 4 -- un
    admin ya no ve casos de otros despachos, ver api/*_endpoint.py).

`ensure_casos_table()` es idempotente (mismo patrón que
core.order.ensure_order_tables) -- no depende de `orders` en absoluto,
solo de `users`. `ensure_casos_despacho_backfill()` es el nivel caro
(backfill + NOT NULL, una sola vez al arrancar, ver core.despachos y
app/main.py) -- separado por el mismo motivo que en core/despachos.py: no
pagar ese costo en cada request.
"""

from __future__ import annotations

from core.db_utils import conexion_dedicada, transaccion_si_disponible
from core.despachos import ensure_despachos_table

_COLUMNAS = "id, cliente_id, abogado_id, despacho_id, titulo, descripcion, estado, created_at, updated_at"

_LOCK_KEY_CASOS_BACKFILL = "vridik_casos_despacho_backfill"


class CasoError(Exception):
    """Base de errores de negocio de este módulo."""


class AbogadoDespachoDistintoError(CasoError):
    """El abogado que se intenta asignar no pertenece al despacho del caso
    -- nunca se permite un caso con cliente y abogado de despachos
    distintos (rompería el aislamiento de tenant)."""


async def ensure_casos_table(db_connection) -> None:
    await ensure_despachos_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS casos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cliente_id UUID NOT NULL REFERENCES users(id),
            abogado_id UUID REFERENCES users(id),
            despacho_id UUID REFERENCES despachos(id),
            titulo TEXT NOT NULL,
            descripcion TEXT,
            estado TEXT NOT NULL DEFAULT 'abierto'
                   CHECK (estado IN ('abierto', 'en_progreso', 'cerrado')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # despacho_id pudo no existir si `casos` ya estaba creada antes de Fase 4.
    await db_connection.execute("ALTER TABLE casos ADD COLUMN IF NOT EXISTS despacho_id UUID REFERENCES despachos(id)")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS ix_casos_cliente_id ON casos (cliente_id)")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS ix_casos_abogado_id ON casos (abogado_id)")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS ix_casos_despacho_id ON casos (despacho_id)")


async def ensure_casos_despacho_backfill(db_connection) -> None:
    """Nivel caro -- corre DESPUÉS de `core.despachos.ensure_despachos_
    backfill` (depende de que `users.despacho_id` ya esté poblado). Cada
    caso hereda el despacho de su `cliente_id` -- no hace falta inventar un
    default nuevo, a diferencia del backfill de `users`."""
    await ensure_casos_table(db_connection)
    async with conexion_dedicada(db_connection) as conexion:
        async with transaccion_si_disponible(conexion):
            await conexion.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _LOCK_KEY_CASOS_BACKFILL)
            hay_pendientes = await conexion.fetchval(
                "SELECT EXISTS(SELECT 1 FROM casos WHERE despacho_id IS NULL)"
            )
            if hay_pendientes:
                await conexion.execute(
                    """
                    UPDATE casos SET despacho_id = (SELECT despacho_id FROM users WHERE users.id = casos.cliente_id)
                    WHERE despacho_id IS NULL
                    """
                )
            await conexion.execute("ALTER TABLE casos ALTER COLUMN despacho_id SET NOT NULL")


async def create_caso(
    db_connection, *, cliente_id: str, despacho_id: str, titulo: str,
    descripcion: str | None = None, abogado_id: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO casos (cliente_id, abogado_id, despacho_id, titulo, descripcion)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING {_COLUMNAS}
        """,
        cliente_id, abogado_id, despacho_id, titulo, descripcion,
    )
    return dict(fila)


async def get_caso(db_connection, caso_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM casos WHERE id = $1", caso_id)
    return dict(fila) if fila is not None else None


async def list_casos_for_user(
    db_connection, *, user_id: str, is_admin: bool, despacho_id: str | None = None,
    skip: int = 0, limit: int = 20,
) -> list[dict]:
    """Admin ve todos los casos DE SU DESPACHO (Fase 4 -- antes veía todos
    los casos de la plataforma, ver AUDITORIA); cualquier otro usuario solo
    los suyos (como cliente O como abogado asignado -- nunca casos ajenos,
    y por construcción esos casos ya son de su propio despacho)."""
    if is_admin:
        filas = await db_connection.fetch(
            f"SELECT {_COLUMNAS} FROM casos WHERE despacho_id = $1 ORDER BY created_at DESC OFFSET $2 LIMIT $3",
            despacho_id, skip, limit,
        )
    else:
        filas = await db_connection.fetch(
            f"""
            SELECT {_COLUMNAS} FROM casos
            WHERE cliente_id = $1 OR abogado_id = $1
            ORDER BY created_at DESC
            OFFSET $2 LIMIT $3
            """,
            user_id, skip, limit,
        )
    return [dict(f) for f in filas]


async def asignar_abogado(db_connection, *, caso_id: str, abogado_id: str) -> dict | None:
    """Rechaza asignar un abogado que no pertenece al despacho del caso --
    sin esto, un caso quedaría con cliente y abogado de despachos
    distintos, un agujero real en el aislamiento de tenant."""
    caso = await get_caso(db_connection, caso_id)
    if caso is None:
        return None

    abogado = await db_connection.fetchrow("SELECT despacho_id FROM users WHERE id = $1", abogado_id)
    if abogado is None or str(abogado["despacho_id"]) != str(caso["despacho_id"]):
        raise AbogadoDespachoDistintoError(
            f"El abogado {abogado_id!r} no pertenece al despacho de este caso"
        )

    fila = await db_connection.fetchrow(
        f"""
        UPDATE casos SET abogado_id = $2, updated_at = now() WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        caso_id, abogado_id,
    )
    return dict(fila) if fila is not None else None


async def cambiar_estado(db_connection, *, caso_id: str, estado: str) -> dict | None:
    fila = await db_connection.fetchrow(
        f"""
        UPDATE casos SET estado = $2, updated_at = now() WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        caso_id, estado,
    )
    return dict(fila) if fila is not None else None
