"""
Vridik — core/product.py
Sprint S3: catálogo de productos sobre la misma `users` de S1/S2
(api/auth_endpoint.py, api/admin_endpoint.py) — `seller_id` referencia
`users.id` (FK), nunca una tabla `roles` separada.

`ensure_product_table()` es idempotente (mismo patrón que
core.auth.ensure_users_table / core.totp_2fa.ensure_totp_columns /
core.admin.ensure_role_column): crea `products` si no existe. Llama primero
a `ensure_users_table()` porque `seller_id UUID REFERENCES users(id)` exige
que `users` ya exista.

Sprint S5: imágenes de producto (`product_images`, `ON DELETE CASCADE` desde
`products` — borrar un producto nunca deja imágenes huérfanas). Un producto
puede tener como máximo una imagen `is_primary=true` a la vez: `add_image()`
y `set_primary()` desmarcan cualquier otra antes de marcar la nueva.
`UPLOADS_DIR`/`PRODUCT_IMAGES_DIR` centralizan la ruta local de subida —
la usan tanto app/main.py (mount de StaticFiles + creación del directorio)
como api/admin_endpoint.py (guardar/borrar el archivo), para que ambos
apunten siempre al mismo lugar.
"""

from __future__ import annotations

from pathlib import Path

from core.auth import ensure_users_table

CAMPOS_ACTUALIZABLES = ("name", "description", "price_cents", "stock", "is_active")

_COLUMNAS = "id, sku, name, description, price_cents, stock, is_active, seller_id, created_at, updated_at"
_IMAGE_COLUMNAS = "id, product_id, url, is_primary, position, created_at"

UPLOADS_DIR = Path("uploads")
PRODUCT_IMAGES_DIR = UPLOADS_DIR / "products"


async def ensure_product_table(db_connection) -> None:
    await ensure_users_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
            stock INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            seller_id UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def list_products(
    db_connection, *, skip: int, limit: int, q: str | None = None, active_only: bool = True,
    seller_id: str | None = None,
) -> list[dict]:
    """`seller_id` (S6, api/seller_endpoint.py): filtra a "mis productos"
    cuando viene; `None` (default, todos los llamadores de S3) no filtra —
    no rompe el catálogo público existente."""
    filas = await db_connection.fetch(
        f"""
        SELECT {_COLUMNAS}
        FROM products
        WHERE (NOT $1 OR is_active = true)
          AND ($2::text IS NULL OR name ILIKE '%' || $2 || '%' OR sku ILIKE '%' || $2 || '%')
          AND ($3::text IS NULL OR seller_id = $3)
        ORDER BY created_at DESC
        OFFSET $4 LIMIT $5
        """,
        active_only, q, seller_id, skip, limit,
    )
    return [dict(f) for f in filas]


async def get_product(db_connection, product_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM products WHERE id = $1", product_id)
    return dict(fila) if fila is not None else None


async def create_product(
    db_connection, *, sku: str, name: str, description: str | None, price_cents: int, stock: int, seller_id: str,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO products (sku, name, description, price_cents, stock, seller_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_COLUMNAS}
        """,
        sku, name, description, price_cents, stock, seller_id,
    )
    return dict(fila)


async def update_product(db_connection, product_id: str, cambios: dict) -> dict | None:
    """`cambios` trae únicamente las claves de CAMPOS_ACTUALIZABLES que el
    llamador quiere modificar (ver api/admin_endpoint.py: payload.model_dump
    con exclude_unset=True) — un PATCH parcial nunca sobrescribe con None los
    campos que el cliente no envió."""
    campos = [c for c in CAMPOS_ACTUALIZABLES if c in cambios]
    if not campos:
        return await get_product(db_connection, product_id)

    set_clause = ", ".join(f"{campo} = ${i + 2}" for i, campo in enumerate(campos))
    valores = [cambios[campo] for campo in campos]
    fila = await db_connection.fetchrow(
        f"""
        UPDATE products SET {set_clause}, updated_at = now()
        WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        product_id, *valores,
    )
    return dict(fila) if fila is not None else None


async def soft_delete(db_connection, product_id: str) -> dict | None:
    fila = await db_connection.fetchrow(
        f"""
        UPDATE products SET is_active = false, updated_at = now()
        WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        product_id,
    )
    return dict(fila) if fila is not None else None


async def ensure_product_images_table(db_connection) -> None:
    await ensure_product_table(db_connection)
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS product_images (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            is_primary BOOLEAN NOT NULL DEFAULT false,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def add_image(db_connection, *, product_id: str, url: str, is_primary: bool = False) -> dict:
    """Si `is_primary=True`, primero desmarca cualquier otra imagen principal
    del mismo producto — nunca puede haber dos principales a la vez."""
    if is_primary:
        await db_connection.execute(
            "UPDATE product_images SET is_primary = false WHERE product_id = $1", product_id,
        )
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO product_images (product_id, url, is_primary)
        VALUES ($1, $2, $3)
        RETURNING {_IMAGE_COLUMNAS}
        """,
        product_id, url, is_primary,
    )
    return dict(fila)


async def list_images(db_connection, product_id: str) -> list[dict]:
    filas = await db_connection.fetch(
        f"""
        SELECT {_IMAGE_COLUMNAS} FROM product_images
        WHERE product_id = $1
        ORDER BY is_primary DESC, position ASC
        """,
        product_id,
    )
    return [dict(f) for f in filas]


async def get_image(db_connection, image_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_IMAGE_COLUMNAS} FROM product_images WHERE id = $1", image_id)
    return dict(fila) if fila is not None else None


async def delete_image(db_connection, image_id: str) -> dict | None:
    fila = await db_connection.fetchrow(
        f"DELETE FROM product_images WHERE id = $1 RETURNING {_IMAGE_COLUMNAS}", image_id,
    )
    return dict(fila) if fila is not None else None


async def set_primary(db_connection, image_id: str) -> dict | None:
    """Desmarca cualquier otra imagen principal del mismo producto y marca
    `image_id` como la única principal."""
    imagen = await get_image(db_connection, image_id)
    if imagen is None:
        return None
    await db_connection.execute(
        "UPDATE product_images SET is_primary = false WHERE product_id = $1", imagen["product_id"],
    )
    fila = await db_connection.fetchrow(
        f"UPDATE product_images SET is_primary = true WHERE id = $1 RETURNING {_IMAGE_COLUMNAS}", image_id,
    )
    return dict(fila)
