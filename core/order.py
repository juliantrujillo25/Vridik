"""
Vridik — core/order.py
Sprint S4: carrito/checkout y órdenes sobre `products` (S3) y `users` (S1).

`ensure_order_tables()` es idempotente (mismo patrón que
core.product.ensure_product_table) y llama primero a
core.product.ensure_product_table() porque `order_items.product_id`
referencia `products(id)` (y esa, a su vez, `users(id)`).

`create_order()` corre en una única transacción con `SELECT ... FOR UPDATE`
por producto — evita que dos checkouts concurrentes sobrevendan el mismo
stock. Diseño en dos fases dentro de la transacción: primero se valida TODO
el carrito (bloqueando cada fila de `products`), y solo si el carrito
completo es válido se mutan stock y se insertan orden/order_items — si
cualquier ítem falla (producto inexistente/inactivo o stock insuficiente),
la función nunca llegó a escribir nada, así que no hace falta deshacer
ninguna escritura ("rollback completo" gratis por construcción).

`update_status()` restaura el stock de cada order_item cuando el nuevo
status es 'cancelled' (y la orden no estaba ya cancelada) — dentro de la
misma transacción que el cambio de estado.

`_transaccion()`: en producción `db_connection` es un asyncpg.Pool (ver
app/main.py) — un Pool NO tiene `.transaction()` propio, hay que
`.acquire()` una Connection real primero (y usar ESA conexión para todos
los statements de la transacción, nunca volver a llamar al Pool adentro,
o cada statement tomaría una conexión distinta y el `FOR UPDATE`/atomicidad
se pierde). Los fakes de tests exponen `.transaction()` directamente (no
tienen `.acquire()`), así que ahí se usa tal cual.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from core.product import ensure_product_table


@asynccontextmanager
async def _transaccion(db_connection):
    if hasattr(db_connection, "acquire"):
        async with db_connection.acquire() as conn, conn.transaction():
            yield conn
    else:
        async with db_connection.transaction():
            yield db_connection

ESTADOS_VALIDOS = ("pending", "paid", "shipped", "cancelled")

_ORDER_COLUMNAS = "id, user_id, status, total_cents, created_at, updated_at"
_ITEM_COLUMNAS = "id, order_id, product_id, quantity, price_cents"


class ProductoNoEncontradoError(Exception):
    def __init__(self, product_id: str):
        self.product_id = product_id
        super().__init__(f"Producto {product_id!r} no encontrado")


class ProductoInactivoError(Exception):
    def __init__(self, product_id: str):
        self.product_id = product_id
        super().__init__(f"Producto {product_id!r} no está activo")


class StockInsuficienteError(Exception):
    def __init__(self, product_id: str, disponible: int, solicitado: int):
        self.product_id = product_id
        self.disponible = disponible
        self.solicitado = solicitado
        super().__init__(f"Stock insuficiente para {product_id!r}: disponible={disponible}, solicitado={solicitado}")


async def ensure_order_tables(db_connection) -> None:
    await ensure_product_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled')),
            total_cents INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders(id),
            product_id UUID NOT NULL REFERENCES products(id),
            quantity INTEGER NOT NULL,
            price_cents INTEGER NOT NULL
        )
        """
    )


async def create_order(db_connection, *, user_id: str, items: list[dict]) -> dict:
    """`items`: [{"product_id": str, "quantity": int}, ...]."""
    async with _transaccion(db_connection) as conn:
        total_cents = 0
        lineas: list[dict] = []
        for item in items:
            producto = await conn.fetchrow(
                "SELECT id, price_cents, stock, is_active FROM products WHERE id = $1 FOR UPDATE",
                item["product_id"],
            )
            if producto is None:
                raise ProductoNoEncontradoError(item["product_id"])
            if not producto["is_active"]:
                raise ProductoInactivoError(item["product_id"])
            if producto["stock"] < item["quantity"]:
                raise StockInsuficienteError(item["product_id"], producto["stock"], item["quantity"])

            total_cents += producto["price_cents"] * item["quantity"]
            lineas.append({
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "price_cents": producto["price_cents"],  # snapshot: nunca el precio futuro del producto
            })

        orden = await conn.fetchrow(
            f"""
            INSERT INTO orders (user_id, status, total_cents)
            VALUES ($1, 'pending', $2)
            RETURNING {_ORDER_COLUMNAS}
            """,
            user_id, total_cents,
        )
        for linea in lineas:
            await conn.execute(
                "UPDATE products SET stock = stock - $2, updated_at = now() WHERE id = $1",
                linea["product_id"], linea["quantity"],
            )
            await conn.execute(
                f"""
                INSERT INTO order_items (order_id, product_id, quantity, price_cents)
                VALUES ($1, $2, $3, $4)
                """,
                orden["id"], linea["product_id"], linea["quantity"], linea["price_cents"],
            )
        return dict(orden)


async def list_orders_by_user(db_connection, *, user_id: str, skip: int = 0, limit: int = 20) -> list[dict]:
    filas = await db_connection.fetch(
        f"""
        SELECT {_ORDER_COLUMNAS} FROM orders
        WHERE user_id = $1
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3
        """,
        user_id, skip, limit,
    )
    return [dict(f) for f in filas]


async def list_all_orders(db_connection, *, skip: int = 0, limit: int = 20, status: str | None = None) -> list[dict]:
    filas = await db_connection.fetch(
        f"""
        SELECT {_ORDER_COLUMNAS} FROM orders
        WHERE ($1::text IS NULL OR status = $1)
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3
        """,
        status, skip, limit,
    )
    return [dict(f) for f in filas]


async def get_order(db_connection, order_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_ORDER_COLUMNAS} FROM orders WHERE id = $1", order_id)
    return dict(fila) if fila is not None else None


async def get_order_items(db_connection, order_id: str) -> list[dict]:
    filas = await db_connection.fetch(f"SELECT {_ITEM_COLUMNAS} FROM order_items WHERE order_id = $1", order_id)
    return [dict(f) for f in filas]


async def list_orders_for_seller(db_connection, *, seller_id: str, skip: int = 0, limit: int = 20) -> list[dict]:
    """S6 (api/seller_endpoint.py): órdenes que contienen AL MENOS un
    producto de `seller_id` — join manual order_items -> products, nunca
    expone una orden ajena que no tenga ningún producto del seller."""
    filas = await db_connection.fetch(
        """
        SELECT DISTINCT o.id, o.user_id, o.status, o.total_cents, o.created_at, o.updated_at
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id
        WHERE p.seller_id = $1
        ORDER BY o.created_at DESC
        OFFSET $2 LIMIT $3
        """,
        seller_id, skip, limit,
    )
    return [dict(f) for f in filas]


async def order_has_seller_product(db_connection, order_id: str, seller_id: str) -> bool:
    """S6: True si al menos un order_item de `order_id` es de un producto
    de `seller_id` — usado por GET /seller/orders/{id} para decidir 403."""
    fila = await db_connection.fetchrow(
        """
        SELECT EXISTS(
            SELECT 1 FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = $1 AND p.seller_id = $2
        ) AS existe
        """,
        order_id, seller_id,
    )
    return bool(fila["existe"]) if fila is not None else False


async def update_status(db_connection, order_id: str, new_status: str) -> dict | None:
    """Si `new_status == 'cancelled'` (y la orden no estaba ya cancelada),
    restaura el stock de cada order_item antes de marcar la orden — todo en
    la misma transacción que el cambio de estado."""
    async with _transaccion(db_connection) as conn:
        orden = await conn.fetchrow(
            f"SELECT {_ORDER_COLUMNAS} FROM orders WHERE id = $1 FOR UPDATE", order_id,
        )
        if orden is None:
            return None

        if new_status == "cancelled" and orden["status"] != "cancelled":
            items = await get_order_items(conn, order_id)
            for item in items:
                await conn.execute(
                    "UPDATE products SET stock = stock + $2, updated_at = now() WHERE id = $1",
                    item["product_id"], item["quantity"],
                )

        actualizada = await conn.fetchrow(
            f"""
            UPDATE orders SET status = $2, updated_at = now()
            WHERE id = $1
            RETURNING {_ORDER_COLUMNAS}
            """,
            order_id, new_status,
        )
        return dict(actualizada)
