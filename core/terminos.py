"""
Vridik — core/terminos.py
Fase 2 (Copiloto Procesal): términos procesales (vencimientos) sobre un
caso, con la fecha de vencimiento SIEMPRE calculada por
procesal/calendario_judicial.py -- nunca aceptada como input directo.
Roadmap: "Semáforo de vencimientos calculados (no manuales) en el
dashboard" -- lo "calculado" es la fecha de vencimiento en sí (mismo
principio que core/totp_2fa.py con el secreto TOTP: el dato sensible
SIEMPRE lo produce el backend, nunca lo propone el cliente).

`estado` solo guarda 'pendiente'/'cumplido' (una acción humana real: el
abogado marca el término como cumplido) -- NO guarda 'vencido'. Si se
persistiera "vencido" quedaría desincronizado del reloj real apenas
pasara la fecha sin que nadie vuelva a escribir esa fila; el semáforo
(verde/amarillo/rojo por días restantes) se calcula al leer, comparando
`fecha_vencimiento` contra la fecha de hoy -- ver `dias_restantes()`.

Arranca sin ingesta automática de actuaciones -- hoy `fecha_inicio` y
`dias_habiles` los ingresa a mano un abogado o cliente (a partir de una
actuación que leyó, clasificada o no por
procesal/clasificador_actuaciones.py, opcionalmente enlazada vía
`actuacion_id`); cuando exista un feed real, esos dos datos los
completaría la ingesta en vez de un formulario, pero el cálculo del
vencimiento no cambia en absoluto.
"""

from __future__ import annotations

from datetime import date

from core.case import ensure_casos_table
from procesal.calendario_judicial import sumar_dias_habiles

_COLUMNAS = (
    "id, caso_id, created_by, descripcion, fecha_inicio, dias_habiles, "
    "fecha_vencimiento, incluye_ventana_sin_confirmar, actuacion_id, estado, created_at"
)

ESTADOS_VALIDOS = ("pendiente", "cumplido")


async def ensure_terminos_table(db_connection) -> None:
    await ensure_casos_table(db_connection)
    await db_connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS terminos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            caso_id UUID NOT NULL REFERENCES casos(id),
            created_by UUID NOT NULL REFERENCES users(id),
            descripcion TEXT NOT NULL,
            fecha_inicio DATE NOT NULL,
            dias_habiles INTEGER NOT NULL CHECK (dias_habiles > 0),
            fecha_vencimiento DATE NOT NULL,
            incluye_ventana_sin_confirmar BOOLEAN NOT NULL DEFAULT false,
            actuacion_id UUID,
            estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'cumplido')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_terminos_caso_id ON terminos (caso_id, fecha_vencimiento)"
    )


async def crear_termino(
    db_connection, *, caso_id: str, created_by: str, descripcion: str,
    fecha_inicio: date, dias_habiles: int, actuacion_id: str | None = None,
) -> dict:
    """El vencimiento SIEMPRE se calcula acá con sumar_dias_habiles() --
    nunca se acepta una fecha de vencimiento como input directo. Levanta
    ValueError si dias_habiles no es positivo (propagado desde
    sumar_dias_habiles)."""
    resultado = sumar_dias_habiles(fecha_inicio, dias_habiles)
    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO terminos (
            caso_id, created_by, descripcion, fecha_inicio, dias_habiles,
            fecha_vencimiento, incluye_ventana_sin_confirmar, actuacion_id
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING {_COLUMNAS}
        """,
        caso_id, created_by, descripcion, fecha_inicio, dias_habiles,
        resultado.fecha_vencimiento, resultado.incluye_ventana_sin_confirmar, actuacion_id,
    )
    return dict(fila)


async def list_terminos(db_connection, *, caso_id: str) -> list[dict]:
    filas = await db_connection.fetch(
        f"SELECT {_COLUMNAS} FROM terminos WHERE caso_id = $1 ORDER BY fecha_vencimiento ASC", caso_id,
    )
    return [dict(f) for f in filas]


async def get_termino(db_connection, termino_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM terminos WHERE id = $1", termino_id)
    return dict(fila) if fila is not None else None


async def marcar_estado_termino(db_connection, *, termino_id: str, estado: str) -> dict | None:
    if estado not in ESTADOS_VALIDOS:
        raise ValueError(f"estado inválido: {estado!r} (válidos: {ESTADOS_VALIDOS})")
    fila = await db_connection.fetchrow(
        f"UPDATE terminos SET estado = $2 WHERE id = $1 RETURNING {_COLUMNAS}", termino_id, estado,
    )
    return dict(fila) if fila is not None else None


def dias_restantes(fecha_vencimiento: date, *, hoy: date | None = None) -> int:
    """Días de calendario hasta el vencimiento (negativo si ya pasó) --
    base del semáforo del roadmap. Días de CALENDARIO, no hábiles: lo que
    le importa a un abogado mirando el semáforo es cuánto falta en el
    calendario real, no otro conteo hábil sobre el conteo hábil que ya
    produjo la fecha de vencimiento."""
    return (fecha_vencimiento - (hoy or date.today())).days
