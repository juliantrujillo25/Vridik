"""
Vridik — core/case_documents.py
Documentos de caso generados por JuliX, ligados a una orden ya existente
(`orders`, S4) — una orden ES el caso: quien la paga es el cliente del
servicio legal, y `order_items -> products.seller_id` ya identifica al
abogado (mismo criterio de ownership que api/seller_endpoint.py, sin
inventar una entidad `cases` paralela que duplicaría lo que `orders` ya
resuelve).

`ensure_case_documents_table()` es idempotente (mismo patrón que
core.order.ensure_order_tables) y llama primero a esa función porque
`case_documents.order_id` referencia `orders(id)`.

La generación real con JuliX (julix/service.py) vive en
api/case_documents_endpoint.py, no aquí — este módulo es solo la capa de
datos (idéntica separación que core/order.py vs api/orders_endpoint.py).
"""

from __future__ import annotations

from core.order import ensure_order_tables

_COLUMNAS = "id, order_id, created_by, tarea, pregunta, contenido, pdf_url, created_at"
_COLUMNAS_LISTADO = "id, order_id, created_by, tarea, pregunta, pdf_url, created_at"


async def ensure_case_documents_table(db_connection) -> None:
    await ensure_order_tables(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders(id),
            created_by UUID NOT NULL REFERENCES users(id),
            tarea TEXT NOT NULL,
            pregunta TEXT NOT NULL,
            contenido TEXT NOT NULL,
            pdf_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def insert_case_document(
    db_connection, *, order_id: str, created_by: str, tarea: str, pregunta: str, contenido: str,
    pdf_url: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO case_documents (order_id, created_by, tarea, pregunta, contenido, pdf_url)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_COLUMNAS}
        """,
        order_id, created_by, tarea, pregunta, contenido, pdf_url,
    )
    return dict(fila)


async def list_case_documents(db_connection, *, order_id: str) -> list[dict]:
    """Listado liviano (sin `contenido`, que puede pesar varios KB de texto
    generado) — el detalle completo se pide con get_case_document()."""
    filas = await db_connection.fetch(
        f"""
        SELECT {_COLUMNAS_LISTADO} FROM case_documents
        WHERE order_id = $1
        ORDER BY created_at DESC
        """,
        order_id,
    )
    return [dict(f) for f in filas]


async def get_case_document(db_connection, doc_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM case_documents WHERE id = $1", doc_id)
    return dict(fila) if fila is not None else None
