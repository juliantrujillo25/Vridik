"""
Vridik — core/case_documents.py
Documentos de caso generados por JuliX, anclados a un `caso` propio
(core/case.py), independiente del marketplace.

Desmantelamiento del marketplace (fase 4, ver Instrucciones - CLAUDE.md,
"Consolidación de producto"): el diseño original anclaba un documento a
una orden ya existente (`orders`) -- "una orden ES el caso". La columna
`order_id` (y la ruta legacy /orders/{id}/documents que la usaba) se
quitaron enteras: la tabla `case_documents` nunca llegó a crearse en
producción (nadie había llamado esas rutas todavía), así que no había
ningún documento real que migrar.

`ensure_case_documents_table()` es idempotente (mismo patrón que el
resto de `ensure_*`).
"""

from __future__ import annotations

_COLUMNAS = "id, caso_id, created_by, tarea, pregunta, contenido, pdf_url, created_at"
_COLUMNAS_LISTADO = "id, caso_id, created_by, tarea, pregunta, pdf_url, created_at"


async def ensure_case_documents_table(db_connection) -> None:
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS case_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            caso_id UUID NOT NULL REFERENCES casos(id),
            created_by UUID NOT NULL REFERENCES users(id),
            tarea TEXT NOT NULL,
            pregunta TEXT NOT NULL,
            contenido TEXT NOT NULL,
            pdf_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_case_documents_caso_id ON case_documents (caso_id)"
    )


async def insert_case_document(
    db_connection, *, caso_id: str, created_by: str, tarea: str, pregunta: str, contenido: str,
    pdf_url: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO case_documents (caso_id, created_by, tarea, pregunta, contenido, pdf_url)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_COLUMNAS}
        """,
        caso_id, created_by, tarea, pregunta, contenido, pdf_url,
    )
    return dict(fila)


async def list_case_documents(db_connection, *, caso_id: str) -> list[dict]:
    """Listado liviano (sin `contenido`, que puede pesar varios KB de texto
    generado) — el detalle completo se pide con get_case_document()."""
    filas = await db_connection.fetch(
        f"SELECT {_COLUMNAS_LISTADO} FROM case_documents WHERE caso_id = $1 ORDER BY created_at DESC",
        caso_id,
    )
    return [dict(f) for f in filas]


async def get_case_document(db_connection, doc_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM case_documents WHERE id = $1", doc_id)
    return dict(fila) if fila is not None else None
