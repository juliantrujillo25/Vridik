"""
Vridik — core/actuaciones.py
Fase 2 (Copiloto Procesal): persistencia de actuaciones judiciales ya
clasificadas (procesal/clasificador_actuaciones.py) sobre un `caso`
(core/case.py) -- mismo patrón que core/mensajes.py: una actuación
cuelga siempre de un caso, nunca existe suelta.

No depende de un feed de actuaciones en vivo (Fase 2 sigue sin proveedor
de monitoreo contratado, ver procesal/__init__.py) -- hoy se registra a
mano (un abogado o cliente pega el texto que leyó en el portal de la
Rama Judicial o recibió por notificación), pero el esquema es el mismo
que usaría una ingesta automática después: cuando exista, cambia QUIÉN
llama a `insert_actuacion()`, nunca la tabla ni el contrato.
"""

from __future__ import annotations

from core.case import ensure_casos_table

_COLUMNAS = (
    "id, caso_id, created_by, texto, categoria, confianza, texto_bruto_clasificacion, "
    "resultado, tipo_resolucion_ugpp, created_at"
)

RESULTADOS_VALIDOS = ("favorable", "desfavorable", "parcial")


class ActuacionError(Exception):
    """Base de errores de negocio de este módulo."""


class ActuacionNoEsFalloError(ActuacionError):
    """resultado/tipo_resolucion_ugpp solo tienen sentido sobre una
    actuación clasificada como 'fallo' -- un auto admisorio o un traslado
    no tienen un "resultado" que registrar."""


async def ensure_actuaciones_table(db_connection) -> None:
    await ensure_casos_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS actuaciones (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            caso_id UUID NOT NULL REFERENCES casos(id),
            created_by UUID NOT NULL REFERENCES users(id),
            texto TEXT NOT NULL,
            categoria TEXT NOT NULL
                CHECK (categoria IN ('auto_admisorio', 'requerimiento', 'fallo', 'traslado', 'otro')),
            confianza NUMERIC(4,3) NOT NULL,
            texto_bruto_clasificacion TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # resultado/tipo_resolucion_ugpp (roadmap Fase 4: analítica UGPP) --
    # nunca los propone la clasificación automática (Haiku solo clasifica
    # categoria/confianza) -- los marca a mano el abogado/admin después de
    # leer el fallo, vía set_resultado_actuacion(). tipo_resolucion_ugpp es
    # texto libre a propósito: las siglas reales (RQI/RCD/RDO/RDC...) no
    # están confirmadas con el despacho, un CHECK fijo arriesgaría rechazar
    # una categorización legal válida.
    await db_connection.execute("ALTER TABLE actuaciones ADD COLUMN IF NOT EXISTS resultado TEXT")
    await db_connection.execute(
        """
        DO $$ BEGIN
            ALTER TABLE actuaciones ADD CONSTRAINT actuaciones_resultado_check
                CHECK (resultado IS NULL OR resultado IN ('favorable', 'desfavorable', 'parcial'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    await db_connection.execute("ALTER TABLE actuaciones ADD COLUMN IF NOT EXISTS tipo_resolucion_ugpp TEXT")
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_actuaciones_caso_id ON actuaciones (caso_id, created_at DESC)"
    )


async def insert_actuacion(
    db_connection, *, caso_id: str, created_by: str, texto: str,
    categoria: str, confianza: float, texto_bruto: str | None,
) -> dict:
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza, texto_bruto_clasificacion)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_COLUMNAS}
        """,
        caso_id, created_by, texto, categoria, confianza, texto_bruto,
    )
    return dict(fila)


async def list_actuaciones(db_connection, *, caso_id: str) -> list[dict]:
    filas = await db_connection.fetch(
        f"SELECT {_COLUMNAS} FROM actuaciones WHERE caso_id = $1 ORDER BY created_at DESC", caso_id,
    )
    return [dict(f) for f in filas]


async def get_actuacion(db_connection, actuacion_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM actuaciones WHERE id = $1", actuacion_id)
    return dict(fila) if fila is not None else None


async def set_resultado_actuacion(
    db_connection, *, actuacion_id: str, resultado: str, tipo_resolucion_ugpp: str | None,
) -> dict | None:
    """Solo se puede marcar sobre una actuación ya clasificada como 'fallo'
    -- devuelve None si la actuación no existe (el llamador decide si eso
    es 404), levanta ActuacionNoEsFalloError si existe pero no es un fallo."""
    actuacion = await get_actuacion(db_connection, actuacion_id)
    if actuacion is None:
        return None
    if actuacion["categoria"] != "fallo":
        raise ActuacionNoEsFalloError(
            f"La actuación {actuacion_id!r} es {actuacion['categoria']!r}, no 'fallo' -- no tiene resultado que registrar"
        )

    fila = await db_connection.fetchrow(
        f"""
        UPDATE actuaciones SET resultado = $2, tipo_resolucion_ugpp = $3 WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        actuacion_id, resultado, tipo_resolucion_ugpp,
    )
    return dict(fila) if fila is not None else None
