"""
Vridik — core/case_documents.py
Documentos de caso generados por JuliX.

Diseño original (marketplace): un documento se generaba sobre una orden
ya existente (`orders`) -- "una orden ES el caso". Con la consolidación
hacia el copiloto legal (decisión del dev lead, `orders`/`products` se
desmantelan como no esenciales), un documento ahora se ancla a un `caso`
propio (core/case.py), independiente del marketplace.

Migración sin romper nada: `order_id` se queda (ahora NULLABLE, antes
NOT NULL) para los documentos que ya existan sobre órdenes reales; los
documentos nuevos usan `caso_id`. Exactamente uno de los dos debe estar
presente (CHECK a nivel de aplicación en api/case_documents_endpoint.py
-- Postgres no valida "exactamente uno" con un CHECK simple sin repetir
lógica, se prefirió mantenerlo en la capa que ya conoce el contexto de
la llamada).

`ensure_case_documents_table()` es idempotente. Ya no depende
obligatoriamente de `orders` -- llama a `ensure_order_tables()` igual
(por compatibilidad con filas existentes que sí tienen order_id), pero
`casos` (core/case.py) es la ruta nueva, sin esa dependencia.
"""

from __future__ import annotations

from core.order import ensure_order_tables

_COLUMNAS = "id, order_id, caso_id, created_by, tarea, pregunta, contenido, pdf_url, created_at"
_COLUMNAS_LISTADO = "id, order_id, caso_id, created_by, tarea, pregunta, pdf_url, created_at"


async def ensure_case_documents_table(db_connection) -> None:
    await ensure_order_tables(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID REFERENCES orders(id),
            created_by UUID NOT NULL REFERENCES users(id),
            tarea TEXT NOT NULL,
            pregunta TEXT NOT NULL,
            contenido TEXT NOT NULL,
            pdf_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Idempotente sobre una tabla que ya existiera con order_id NOT NULL
    # (diseño original) -- relaja la restricción para que caso_id pueda
    # ser la única referencia presente en documentos nuevos.
    await db_connection.execute("ALTER TABLE case_documents ALTER COLUMN order_id DROP NOT NULL")
    await db_connection.execute("ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS caso_id UUID REFERENCES casos(id)")
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_case_documents_caso_id ON case_documents (caso_id)"
    )


async def insert_case_document(
    db_connection, *, created_by: str, tarea: str, pregunta: str, contenido: str,
    order_id: str | None = None, caso_id: str | None = None, pdf_url: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO case_documents (order_id, caso_id, created_by, tarea, pregunta, contenido, pdf_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING {_COLUMNAS}
        """,
        order_id, caso_id, created_by, tarea, pregunta, contenido, pdf_url,
    )
    return dict(fila)


async def list_case_documents(
    db_connection, *, order_id: str | None = None, caso_id: str | None = None,
) -> list[dict]:
    """Listado liviano (sin `contenido`, que puede pesar varios KB de texto
    generado) — el detalle completo se pide con get_case_document()."""
    if caso_id is not None:
        filas = await db_connection.fetch(
            f"SELECT {_COLUMNAS_LISTADO} FROM case_documents WHERE caso_id = $1 ORDER BY created_at DESC",
            caso_id,
        )
    else:
        filas = await db_connection.fetch(
            f"SELECT {_COLUMNAS_LISTADO} FROM case_documents WHERE order_id = $1 ORDER BY created_at DESC",
            order_id,
        )
    return [dict(f) for f in filas]


async def get_case_document(db_connection, doc_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM case_documents WHERE id = $1", doc_id)
    return dict(fila) if fila is not None else None
