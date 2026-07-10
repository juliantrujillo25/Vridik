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
  - `estado`: 'abierto' (default) | 'en_progreso' | 'cerrado' -- ciclo de
    vida simple, sin las etapas procesales de Fase 2 del roadmap (motor de
    términos), que llegan después.
  - Ownership (mismo criterio de siempre): dueño del caso (cliente_id),
    abogado asignado (abogado_id), o admin.

`ensure_casos_table()` es idempotente (mismo patrón que
core.order.ensure_order_tables) -- no depende de `orders` en absoluto,
solo de `users`.
"""

from __future__ import annotations

_COLUMNAS = "id, cliente_id, abogado_id, titulo, descripcion, estado, created_at, updated_at"


async def ensure_casos_table(db_connection) -> None:
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS casos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cliente_id UUID NOT NULL REFERENCES users(id),
            abogado_id UUID REFERENCES users(id),
            titulo TEXT NOT NULL,
            descripcion TEXT,
            estado TEXT NOT NULL DEFAULT 'abierto'
                   CHECK (estado IN ('abierto', 'en_progreso', 'cerrado')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute("CREATE INDEX IF NOT EXISTS ix_casos_cliente_id ON casos (cliente_id)")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS ix_casos_abogado_id ON casos (abogado_id)")


async def create_caso(
    db_connection, *, cliente_id: str, titulo: str, descripcion: str | None = None, abogado_id: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO casos (cliente_id, abogado_id, titulo, descripcion)
        VALUES ($1, $2, $3, $4)
        RETURNING {_COLUMNAS}
        """,
        cliente_id, abogado_id, titulo, descripcion,
    )
    return dict(fila)


async def get_caso(db_connection, caso_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM casos WHERE id = $1", caso_id)
    return dict(fila) if fila is not None else None


async def list_casos_for_user(db_connection, *, user_id: str, is_admin: bool, skip: int = 0, limit: int = 20) -> list[dict]:
    """Admin ve todos los casos; cualquier otro usuario solo los suyos
    (como cliente O como abogado asignado -- nunca casos ajenos)."""
    if is_admin:
        filas = await db_connection.fetch(
            f"SELECT {_COLUMNAS} FROM casos ORDER BY created_at DESC OFFSET $1 LIMIT $2",
            skip, limit,
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
