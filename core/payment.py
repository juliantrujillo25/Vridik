"""
Vridik — core/payment.py
Sprint S7: pagos con Wompi (core/wompi.py) sobre `orders` (S4). `payments`
guarda el historial de intentos de pago por orden — `orders.status` pasa a
'paid' recién cuando Wompi confirma un evento APPROVED con firma válida
(api/payments_endpoint.py:wompi_webhook), nunca antes.

`ensure_payment_table()` es idempotente (mismo patrón que el resto de
`ensure_*`) y llama primero a `core.order.ensure_order_tables()` porque
`payments.order_id` referencia `orders(id)`.
"""

from __future__ import annotations

from core.order import ensure_order_tables

_COLUMNAS = "id, order_id, reference, transaction_id, amount_cents, status, created_at, updated_at"


async def ensure_payment_table(db_connection) -> None:
    await ensure_order_tables(db_connection)
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders(id),
            reference TEXT NOT NULL UNIQUE,
            transaction_id TEXT,
            amount_cents INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'declined')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute("CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments (order_id)")


async def create_payment(db_connection, *, order_id: str, reference: str, amount_cents: int) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO payments (order_id, reference, amount_cents, status)
        VALUES ($1, $2, $3, 'pending')
        RETURNING {_COLUMNAS}
        """,
        order_id, reference, amount_cents,
    )
    return dict(fila)


async def get_payment_by_reference(db_connection, reference: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM payments WHERE reference = $1", reference)
    return dict(fila) if fila is not None else None


async def update_payment_status(
    db_connection, reference: str, *, status: str, transaction_id: str | None = None,
) -> dict | None:
    fila = await db_connection.fetchrow(
        f"""
        UPDATE payments SET status = $2, transaction_id = COALESCE($3, transaction_id), updated_at = now()
        WHERE reference = $1
        RETURNING {_COLUMNAS}
        """,
        reference, status, transaction_id,
    )
    return dict(fila) if fila is not None else None
