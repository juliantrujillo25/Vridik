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

# Track Forja TF3 (vridik_architecture_v2.json::journey_loop_termino):
# tres avisos escalonados por término a medida que se acerca el
# vencimiento -- no uno solo (ver escalon_aplicable/listar_terminos_para_alertar).
# El más urgente (1) cubre también "ya vencido" (dias_restantes negativo).
DIAS_ESCALONES = (5, 3, 1)


def escalon_aplicable(dias_restantes: int) -> int | None:
    """El escalón más urgente (el umbral más chico) que `dias_restantes` ya
    alcanzó, o None si el término todavía no entra en ningún escalón de
    aviso. Pura -- sin BD, se prueba a fondo con casos límite."""
    aplicables = [umbral for umbral in DIAS_ESCALONES if dias_restantes <= umbral]
    return min(aplicables) if aplicables else None


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
    # Migración aditiva (roadmap Fase 2, alertas proactivas -- ver
    # procesal/alertas_terminos.py). Track Forja TF3 reemplazó el diseño de
    # un solo aviso por día por escalones (ver DIAS_ESCALONES) -- se deja
    # esta columna vieja sin usar (nunca se borran columnas sin necesidad
    # real) y se agrega la nueva que sí distingue QUÉ escalón fue el
    # último notificado, no solo "hoy ya se avisó".
    await db_connection.execute(
        "ALTER TABLE terminos ADD COLUMN IF NOT EXISTS ultima_alerta_enviada DATE"
    )
    await db_connection.execute(
        "ALTER TABLE terminos ADD COLUMN IF NOT EXISTS ultimo_escalon_notificado SMALLINT"
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


async def listar_terminos_para_alertar(db_connection, *, hoy: date | None = None) -> list[dict]:
    """Términos pendientes que ya alcanzaron un escalón de aviso (ver
    DIAS_ESCALONES) más urgente que el último que se les notificó -- join
    con `casos` para traer cliente_id/abogado_id en la misma consulta
    (evita N+1 en procesal/alertas_terminos.py, que llama esto una vez por
    ronda, no una vez por término). Cada fila trae `escalon`: el que hay
    que notificar ahora (y con el que se llama después a
    marcar_escalon_notificado)."""
    hoy = hoy or date.today()
    filas = await db_connection.fetch(
        """
        WITH candidatos AS (
            SELECT t.id, t.caso_id, t.descripcion, t.fecha_vencimiento,
                   t.ultimo_escalon_notificado, c.cliente_id, c.abogado_id,
                   CASE
                       WHEN t.fecha_vencimiento - $1::date <= 1 THEN 1
                       WHEN t.fecha_vencimiento - $1::date <= 3 THEN 3
                       WHEN t.fecha_vencimiento - $1::date <= 5 THEN 5
                   END AS escalon
            FROM terminos t
            JOIN casos c ON c.id = t.caso_id
            WHERE t.estado = 'pendiente'
        )
        SELECT id, caso_id, descripcion, fecha_vencimiento, cliente_id, abogado_id, escalon
        FROM candidatos
        WHERE escalon IS NOT NULL
          AND (ultimo_escalon_notificado IS NULL OR ultimo_escalon_notificado > escalon)
        ORDER BY fecha_vencimiento ASC
        """,
        hoy,
    )
    return [dict(f) for f in filas]


async def marcar_escalon_notificado(db_connection, *, termino_id: str, escalon: int) -> None:
    await db_connection.execute(
        "UPDATE terminos SET ultimo_escalon_notificado = $2 WHERE id = $1", termino_id, escalon,
    )


def dias_restantes(fecha_vencimiento: date, *, hoy: date | None = None) -> int:
    """Días de calendario hasta el vencimiento (negativo si ya pasó) --
    base del semáforo del roadmap. Días de CALENDARIO, no hábiles: lo que
    le importa a un abogado mirando el semáforo es cuánto falta en el
    calendario real, no otro conteo hábil sobre el conteo hábil que ya
    produjo la fecha de vencimiento."""
    return (fecha_vencimiento - (hoy or date.today())).days
