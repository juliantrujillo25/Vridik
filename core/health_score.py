"""
Vridik — core/health_score.py
Track Forja TF2 (roadmap, migración 11 de vridik_architecture_v2.json):
health-score por caso -- score de RIESGO 0-100 (0=sano, 100=crítico),
adaptación del "care-score" de la referencia Forja a un proceso legal.

Fórmula EXACTA de vridik_architecture_v2.json::gamificacion_vridik.
health_score_formula, calculada SIEMPRE en backend a partir de
`terminos`/`actuaciones` -- nunca input del cliente ni del abogado, mismo
principio que `core/cobro.py::honorarios_liquidados` (un dato que decide
prioridad/urgencia no puede ser algo que alguien proponga).

    health_score = min(100, round(
        40 * urgencia_termino
      + 25 * silencio_judicial
      + 20 * proporcion_terminos_vencidos
      + 15 * incumplimiento_previo
    ))

    urgencia_termino (del término PENDIENTE más próximo del caso):
        1.0  si vence en <=1 día  (incluye ya vencido)
        0.7  si <=3 días
        0.4  si <=5 días
        0.1  si <=15 días
        0.0  si no hay término pendiente
    silencio_judicial = min(1.0, dias_sin_actuacion / 90)
    proporcion_terminos_vencidos = terminos_vencidos_abiertos / max(1, terminos_totales)
    incumplimiento_previo = 1.0 si el caso tuvo un término que venció sin
        atender en los últimos 30 días, si no 0.0 -- se calcula directo
        sobre `terminos` (estado sigue en 'pendiente' pese a estar vencido,
        ver core/terminos.py -- no depende de la tabla `gamificacion`,
        que es fase 2 y todavía no existe).

Semáforo (UI): 0-30 verde, 31-70 amarillo, 71-100 rojo.

Migración 11 (`casos.health_score`/`health_score_actualizado_en`) vive en
`core/case.py::ensure_casos_table()`, no acá -- `COLUMNAS_CASO` (get_caso/
list_casos_for_user/crear_caso) necesita la columna creada de forma
confiable antes de correr, y ese archivo ya es quien lo garantiza."""

from __future__ import annotations

from datetime import date, datetime

PESO_URGENCIA = 40
PESO_SILENCIO = 25
PESO_VENCIDOS = 20
PESO_INCUMPLIMIENTO = 15

DIAS_VENTANA_SILENCIO = 90
DIAS_VENTANA_INCUMPLIMIENTO = 30

UMBRAL_VERDE_AMARILLO = 30
UMBRAL_AMARILLO_ROJO = 70


def _urgencia_termino(dias_restantes: int | None) -> float:
    if dias_restantes is None:
        return 0.0
    if dias_restantes <= 1:
        return 1.0
    if dias_restantes <= 3:
        return 0.7
    if dias_restantes <= 5:
        return 0.4
    if dias_restantes <= 15:
        return 0.1
    return 0.0


def _silencio_judicial(dias_sin_actuacion: int | None) -> float:
    if dias_sin_actuacion is None:
        return 0.0
    return min(1.0, dias_sin_actuacion / DIAS_VENTANA_SILENCIO)


def calcular_health_score(
    *,
    dias_restantes_termino_mas_proximo: int | None,
    dias_sin_actuacion: int | None,
    terminos_vencidos_abiertos: int,
    terminos_totales: int,
    hubo_incumplimiento_reciente: bool,
) -> int:
    """Función pura -- sin BD, sin fecha real (todo se pasa ya calculado).
    Es la que se prueba exhaustivamente con casos límite; el resto de este
    módulo solo junta los inputs desde Postgres y llama esto."""
    urgencia = _urgencia_termino(dias_restantes_termino_mas_proximo)
    silencio = _silencio_judicial(dias_sin_actuacion)
    vencidos = terminos_vencidos_abiertos / max(1, terminos_totales)
    incumplimiento = 1.0 if hubo_incumplimiento_reciente else 0.0

    score = (
        PESO_URGENCIA * urgencia
        + PESO_SILENCIO * silencio
        + PESO_VENCIDOS * vencidos
        + PESO_INCUMPLIMIENTO * incumplimiento
    )
    return min(100, round(score))


def semaforo_health_score(score: int) -> str:
    if score <= UMBRAL_VERDE_AMARILLO:
        return "verde"
    if score <= UMBRAL_AMARILLO_ROJO:
        return "amarillo"
    return "rojo"


async def recalcular_health_score(db_connection, *, caso_id: str, hoy: date | None = None) -> int:
    """Junta los inputs reales de `terminos`/`actuaciones` para UN caso,
    calcula el score y lo persiste. Se llama tanto desde el job periódico
    de alertas (todos los casos abiertos) como al cambiar un término o una
    actuación puntual (ver core/terminos.py/core/actuaciones.py)."""
    hoy = hoy or date.today()

    dias_restantes = await db_connection.fetchval(
        """
        SELECT MIN(fecha_vencimiento) - $2::date
        FROM terminos
        WHERE caso_id = $1 AND estado = 'pendiente'
        """,
        caso_id, hoy,
    )

    ultima_actuacion: datetime | None = await db_connection.fetchval(
        "SELECT MAX(created_at) FROM actuaciones WHERE caso_id = $1", caso_id,
    )
    dias_sin_actuacion = (hoy - ultima_actuacion.date()).days if ultima_actuacion else None

    vencidos_abiertos = await db_connection.fetchval(
        """
        SELECT COUNT(*) FROM terminos
        WHERE caso_id = $1 AND estado = 'pendiente' AND fecha_vencimiento < $2
        """,
        caso_id, hoy,
    )
    total = await db_connection.fetchval("SELECT COUNT(*) FROM terminos WHERE caso_id = $1", caso_id)

    hubo_incumplimiento = await db_connection.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM terminos
            WHERE caso_id = $1 AND estado = 'pendiente'
              AND fecha_vencimiento < $2
              AND fecha_vencimiento >= $2 - $3
        )
        """,
        caso_id, hoy, DIAS_VENTANA_INCUMPLIMIENTO,
    )

    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=dias_restantes,
        dias_sin_actuacion=dias_sin_actuacion,
        terminos_vencidos_abiertos=vencidos_abiertos,
        terminos_totales=total,
        hubo_incumplimiento_reciente=hubo_incumplimiento,
    )

    await db_connection.execute(
        "UPDATE casos SET health_score = $2, health_score_actualizado_en = now() WHERE id = $1",
        caso_id, score,
    )
    return score


async def recalcular_health_score_de_casos_abiertos(db_connection, *, hoy: date | None = None) -> int:
    """Nivel de job periódico (procesal/alertas_terminos.py, ya corre cada
    6h) -- recalcula todos los casos que no están cerrados. Un caso cerrado
    no necesita más recálculos (su health_score queda congelado en el
    último valor real, no se pone a 0 artificialmente -- borrar la señal de
    riesgo de un caso que se cerró CON términos vencidos sería mentir sobre
    su historia)."""
    caso_ids = await db_connection.fetch("SELECT id FROM casos WHERE estado != 'cerrado'")
    for fila in caso_ids:
        await recalcular_health_score(db_connection, caso_id=str(fila["id"]), hoy=hoy)
    return len(caso_ids)
