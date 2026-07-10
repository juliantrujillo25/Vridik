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
`products` — borrar un producto nunca deja imágenes huérfanas).

Sprint S7 (Vridik Abogados): `category` (especialidad legal —
CATEGORIAS_VALIDAS) y `city` búsqueda de servicios legales.
`ensure_product_search_columns()` es idempotente (mismo patrón que el
resto de `ensure_*`) y agrega índices para que filtrar por especialidad/
ciudad no haga table scan.

Desmantelamiento del marketplace (fase 2, ver Instrucciones - CLAUDE.md,
"Consolidación de producto"): este módulo quedó solo de lectura —
`create_product`/`update_product`/`soft_delete`/`add_image`/`get_image`/
`delete_image`/`set_primary` se quitaron porque solo los llamaba
api/admin_endpoint.py, que ya no gestiona productos. api/products_endpoint.py
(catálogo público) sigue usando lo que queda.
"""

from __future__ import annotations

from core.auth import ensure_users_table

CATEGORIAS_VALIDAS = ("penal", "civil", "laboral", "familia", "tributario")

_COLUMNAS = (
    "id, sku, name, description, price_cents, stock, is_active, seller_id, "
    "category, city, created_at, updated_at"
)
_IMAGE_COLUMNAS = "id, product_id, url, is_primary, position, created_at"


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


_ORDEN_PERMITIDO = {
    "price_asc": "price_cents ASC",
    "price_desc": "price_cents DESC",
    "newest": "created_at DESC",
}


async def list_products(
    db_connection, *, skip: int, limit: int, q: str | None = None, active_only: bool = True,
    seller_id: str | None = None, category: str | None = None, city: str | None = None,
    min_price: int | None = None, max_price: int | None = None, sort_by: str | None = None,
) -> list[dict]:
    """`seller_id` (S6, api/seller_endpoint.py): filtra a "mis productos"
    cuando viene; el resto de filtros son S7 (búsqueda por especialidad/
    ciudad/precio, api/products_endpoint.py). Todos `None` por default —
    no rompe ningún llamador existente. `sort_by` se resuelve contra un
    diccionario fijo de fragmentos SQL (_ORDEN_PERMITIDO), nunca se
    interpola el valor del cliente directamente en la query."""
    orden_sql = _ORDEN_PERMITIDO.get(sort_by, "created_at DESC")
    filas = await db_connection.fetch(
        f"""
        SELECT {_COLUMNAS}
        FROM products
        WHERE (NOT $1 OR is_active = true)
          AND ($2::text IS NULL OR name ILIKE '%' || $2 || '%' OR sku ILIKE '%' || $2 || '%')
          AND ($3::uuid IS NULL OR seller_id = $3::uuid)
          AND ($4::text IS NULL OR category = $4)
          AND ($5::text IS NULL OR city ILIKE $5)
          AND ($6::integer IS NULL OR price_cents >= $6)
          AND ($7::integer IS NULL OR price_cents <= $7)
        ORDER BY {orden_sql}
        OFFSET $8 LIMIT $9
        """,
        active_only, q, seller_id, category, city, min_price, max_price, skip, limit,
    )
    return [dict(f) for f in filas]


async def ensure_product_search_columns(db_connection) -> None:
    await ensure_product_table(db_connection)
    await db_connection.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS category TEXT")
    await db_connection.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS city TEXT")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products (category)")
    await db_connection.execute("CREATE INDEX IF NOT EXISTS idx_products_city ON products (city)")


async def list_categories() -> list[str]:
    """Especialidad legal: taxonomía fija (CATEGORIAS_VALIDAS), no depende
    de qué haya cargado en `products` — un cliente debe poder ver "penal"
    como opción de búsqueda aunque hoy no exista ningún abogado penalista."""
    return list(CATEGORIAS_VALIDAS)


async def list_cities(db_connection) -> list[str]:
    filas = await db_connection.fetch(
        "SELECT DISTINCT city FROM products WHERE city IS NOT NULL AND is_active = true ORDER BY city"
    )
    return [f["city"] for f in filas]


async def get_product(db_connection, product_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM products WHERE id = $1", product_id)
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
