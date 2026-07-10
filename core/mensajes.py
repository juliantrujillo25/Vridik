"""
Vridik — core/mensajes.py
Roadmap Semana 11, Fase A: backend real de Mensajes (deuda "85%" del
roadmap -- "Chat interno con adjuntos, sin polling/tiempo real"). Mismas
firmas de función que tests/support/fakes.py::FakeMensajesService
(crear/marcar_leido/no_leidos_para/borrar) para que las Fases B-D (SSE
encima) no tengan que tocar esta capa de datos.

Una conversación cuelga siempre de un `caso` (core/case.py) -- mensajería
entre cliente y abogado sobre un caso puntual. Ownership: mismo criterio
que api/case_documents_endpoint.py (cliente del caso, abogado asignado, o
admin) -- se valida en api/mensajes_endpoint.py, no acá (este módulo no
conoce roles, solo persiste).

No-leídos por CURSOR TEMPORAL (`conversation_reads`: conversacion_id,
user_id, last_read_at) en vez de una fila de lectura por mensaje -- es el
diseño que pide el roadmap S11 ("cursor temporal... marcado solo con
conversación abierta y pestaña visible"), más barato de mantener que
marcar cada mensaje individualmente. `marcar_leido(mensaje_id, user_id)`
internamente avanza el cursor hasta el `created_at` de ese mensaje (nunca
lo retrocede -- GREATEST()).
"""

from __future__ import annotations

from core.case import ensure_casos_table

_COLUMNAS_MENSAJE = "id, conversacion_id, autor_id, texto, adjunto_url, borrado, created_at"


async def ensure_mensajes_tables(db_connection) -> None:
    await ensure_casos_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversaciones (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            caso_id UUID NOT NULL REFERENCES casos(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Un caso tiene a lo sumo una conversación -- get_or_create_conversacion()
    # depende de esta unicidad para no crear duplicadas bajo carrera.
    await db_connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_conversaciones_caso_id ON conversaciones (caso_id)"
    )
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mensajes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversacion_id UUID NOT NULL REFERENCES conversaciones(id),
            autor_id UUID NOT NULL REFERENCES users(id),
            texto TEXT NOT NULL,
            adjunto_url TEXT,
            borrado BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_mensajes_conversacion_id ON mensajes (conversacion_id, created_at)"
    )
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_reads (
            conversacion_id UUID NOT NULL REFERENCES conversaciones(id),
            user_id UUID NOT NULL REFERENCES users(id),
            last_read_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity',
            PRIMARY KEY (conversacion_id, user_id)
        )
        """
    )


async def get_or_create_conversacion(db_connection, *, caso_id: str) -> dict:
    fila = await db_connection.fetchrow(
        "SELECT id, caso_id, created_at FROM conversaciones WHERE caso_id = $1", caso_id,
    )
    if fila is not None:
        return dict(fila)
    fila = await db_connection.fetchrow(
        """
        INSERT INTO conversaciones (caso_id) VALUES ($1)
        ON CONFLICT (caso_id) DO UPDATE SET caso_id = EXCLUDED.caso_id
        RETURNING id, caso_id, created_at
        """,
        caso_id,
    )
    return dict(fila)


async def crear_mensaje(
    db_connection, *, conversacion_id: str, autor_id: str, texto: str, adjunto_url: str | None = None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO mensajes (conversacion_id, autor_id, texto, adjunto_url)
        VALUES ($1, $2, $3, $4)
        RETURNING {_COLUMNAS_MENSAJE}
        """,
        conversacion_id, autor_id, texto, adjunto_url,
    )
    return dict(fila)


async def listar_mensajes(db_connection, *, conversacion_id: str, skip: int = 0, limit: int = 50) -> list[dict]:
    filas = await db_connection.fetch(
        f"""
        SELECT {_COLUMNAS_MENSAJE} FROM mensajes
        WHERE conversacion_id = $1
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3
        """,
        conversacion_id, skip, limit,
    )
    return [dict(f) for f in filas]


async def get_mensaje(db_connection, mensaje_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS_MENSAJE} FROM mensajes WHERE id = $1", mensaje_id)
    return dict(fila) if fila is not None else None


async def marcar_leido(db_connection, *, mensaje_id: str, user_id: str) -> bool:
    mensaje = await get_mensaje(db_connection, mensaje_id)
    if mensaje is None:
        return False
    await db_connection.execute(
        """
        INSERT INTO conversation_reads (conversacion_id, user_id, last_read_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (conversacion_id, user_id)
        DO UPDATE SET last_read_at = GREATEST(conversation_reads.last_read_at, EXCLUDED.last_read_at)
        """,
        mensaje["conversacion_id"], user_id, mensaje["created_at"],
    )
    return True


async def no_leidos_para(db_connection, *, user_id: str, conversacion_id: str) -> int:
    return await db_connection.fetchval(
        """
        SELECT COUNT(*) FROM mensajes m
        LEFT JOIN conversation_reads cr
          ON cr.conversacion_id = m.conversacion_id AND cr.user_id = $1
        WHERE m.conversacion_id = $2
          AND m.borrado = false
          AND m.autor_id != $1
          AND m.created_at > COALESCE(cr.last_read_at, '-infinity'::timestamptz)
        """,
        user_id, conversacion_id,
    )


async def borrar_mensaje(db_connection, *, mensaje_id: str, actor_id: str) -> bool:
    """Soft delete -- solo el autor puede borrar su propio mensaje (mismo
    criterio que FakeMensajesService.borrar())."""
    fila = await db_connection.fetchrow(
        "UPDATE mensajes SET borrado = true WHERE id = $1 AND autor_id = $2 RETURNING id",
        mensaje_id, actor_id,
    )
    return fila is not None
