"""
Vridik — tests/test_health_score.py
Track Forja TF2: core/health_score.py. Dos capas:
  - Puras (sin BD): calcular_health_score() con casos límite -- es la
    función que decide el número que ve un abogado, se prueba a fondo.
  - Con Postgres real (fixture `db`): recalcular_health_score() junta los
    inputs reales de terminos/actuaciones y persiste en casos.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.case import ensure_casos_table
from core.health_score import (
    calcular_health_score,
    recalcular_health_score,
    recalcular_health_score_de_casos_abiertos,
    semaforo_health_score,
)


# --- puras: calcular_health_score -----------------------------------------

def test_caso_sano_sin_terminos_ni_actuaciones_score_bajo():
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=None,
        dias_sin_actuacion=None,
        terminos_vencidos_abiertos=0,
        terminos_totales=0,
        hubo_incumplimiento_reciente=False,
    )
    assert score == 0


def test_termino_vence_manana_urgencia_maxima():
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=1,
        dias_sin_actuacion=None,
        terminos_vencidos_abiertos=0,
        terminos_totales=1,
        hubo_incumplimiento_reciente=False,
    )
    # 40*1.0 + 20*(0/1) = 40
    assert score == 40


def test_termino_ya_vencido_cuenta_como_urgencia_maxima_y_como_vencido():
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=-2,  # ya vencido
        dias_sin_actuacion=None,
        terminos_vencidos_abiertos=1,
        terminos_totales=1,
        hubo_incumplimiento_reciente=False,
    )
    # 40*1.0 (dias_restantes<=1) + 20*(1/1) = 60
    assert score == 60


def test_todos_los_terminos_vencidos_y_silencio_largo_y_racha_rota_score_cerca_de_100():
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=-10,
        dias_sin_actuacion=120,  # supera la ventana de 90, se topa en 1.0
        terminos_vencidos_abiertos=3,
        terminos_totales=3,
        hubo_incumplimiento_reciente=True,
    )
    # 40*1.0 + 25*1.0 + 20*1.0 + 15*1.0 = 100
    assert score == 100


def test_score_nunca_supera_100_aunque_la_suma_de_pesos_de_mas():
    # combinación imposible en la práctica, pero la función debe topar igual
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=0,
        dias_sin_actuacion=1000,
        terminos_vencidos_abiertos=50,
        terminos_totales=1,
        hubo_incumplimiento_reciente=True,
    )
    assert score == 100


def test_urgencia_escalones_exactos():
    casos = [
        (1, 40), (3, 28), (5, 16), (15, 4), (16, 0), (100, 0),
    ]
    for dias, esperado in casos:
        score = calcular_health_score(
            dias_restantes_termino_mas_proximo=dias,
            dias_sin_actuacion=None,
            terminos_vencidos_abiertos=0,
            terminos_totales=1,
            hubo_incumplimiento_reciente=False,
        )
        assert score == esperado, f"dias_restantes={dias}: esperado {esperado}, obtuve {score}"


def test_silencio_judicial_se_topa_en_90_dias():
    score_90 = calcular_health_score(
        dias_restantes_termino_mas_proximo=None, dias_sin_actuacion=90,
        terminos_vencidos_abiertos=0, terminos_totales=0, hubo_incumplimiento_reciente=False,
    )
    score_200 = calcular_health_score(
        dias_restantes_termino_mas_proximo=None, dias_sin_actuacion=200,
        terminos_vencidos_abiertos=0, terminos_totales=0, hubo_incumplimiento_reciente=False,
    )
    assert score_90 == score_200 == 25  # 25*1.0


def test_proporcion_terminos_vencidos_nunca_divide_por_cero():
    score = calcular_health_score(
        dias_restantes_termino_mas_proximo=None, dias_sin_actuacion=None,
        terminos_vencidos_abiertos=0, terminos_totales=0, hubo_incumplimiento_reciente=False,
    )
    assert score == 0  # no explota con terminos_totales=0


# --- puras: semaforo_health_score -----------------------------------------

def test_semaforo_verde_amarillo_rojo():
    assert semaforo_health_score(0) == "verde"
    assert semaforo_health_score(30) == "verde"
    assert semaforo_health_score(31) == "amarillo"
    assert semaforo_health_score(70) == "amarillo"
    assert semaforo_health_score(71) == "rojo"
    assert semaforo_health_score(100) == "rojo"


# --- con Postgres real: recalcular_health_score ---------------------------

async def _crear_caso(db, *, cliente_id: str, despacho_id: str, estado: str = "abierto") -> str:
    return await db.fetchval(
        "INSERT INTO casos (cliente_id, despacho_id, titulo, estado) VALUES ($1, $2, 'caso', $3) RETURNING id",
        cliente_id, despacho_id, estado,
    )


@pytest.mark.asyncio
async def test_recalcular_sin_terminos_ni_actuaciones_da_cero(db, make_despacho, make_user):
    await ensure_casos_table(db)
    despacho = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho)
    caso_id = await _crear_caso(db, cliente_id=cliente["id"], despacho_id=despacho)

    score = await recalcular_health_score(db, caso_id=caso_id)
    assert score == 0

    persistido = await db.fetchrow(
        "SELECT health_score, health_score_actualizado_en FROM casos WHERE id = $1", caso_id,
    )
    assert persistido["health_score"] == 0
    assert persistido["health_score_actualizado_en"] is not None


@pytest.mark.asyncio
async def test_recalcular_con_termino_vencido_sube_el_score(db, make_despacho, make_user):
    from core.terminos import ensure_terminos_table

    await ensure_casos_table(db)
    await ensure_terminos_table(db)
    despacho = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho)
    caso_id = await _crear_caso(db, cliente_id=cliente["id"], despacho_id=despacho)

    hoy = date.today()
    await db.execute(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'vencido', $3, 5, $4)",
        caso_id, cliente["id"], hoy - timedelta(days=10), hoy - timedelta(days=2),
    )

    score = await recalcular_health_score(db, caso_id=caso_id, hoy=hoy)
    # dias_restantes=-2 -> urgencia 1.0 (40) + vencidos 1/1 (20) = 60. El
    # mismo término vencido hace también True a incumplimiento_previo (+15,
    # ver core/health_score.py: "pendiente" y vencido hace <30 días, sin
    # tabla `gamificacion` para distinguir una racha rota de un vencido que
    # sigue abierto) -> 60 + 15 = 75.
    assert score == 75


@pytest.mark.asyncio
async def test_termino_cumplido_no_cuenta_como_vencido(db, make_despacho, make_user):
    from core.terminos import ensure_terminos_table, marcar_estado_termino

    await ensure_casos_table(db)
    await ensure_terminos_table(db)
    despacho = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho)
    caso_id = await _crear_caso(db, cliente_id=cliente["id"], despacho_id=despacho)

    hoy = date.today()
    termino_id = await db.fetchval(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'cumplido a tiempo', $3, 5, $4) RETURNING id",
        caso_id, cliente["id"], hoy - timedelta(days=10), hoy - timedelta(days=2),
    )
    await marcar_estado_termino(db, termino_id=termino_id, estado="cumplido")

    score = await recalcular_health_score(db, caso_id=caso_id, hoy=hoy)
    # el termino cumplido no es "pendiente" -> ni urgencia ni vencidos lo cuentan
    assert score == 0


@pytest.mark.asyncio
async def test_recalcular_todos_los_casos_abiertos_salta_los_cerrados(db, make_despacho, make_user):
    await ensure_casos_table(db)
    despacho = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho)
    abierto = await _crear_caso(db, cliente_id=cliente["id"], despacho_id=despacho, estado="abierto")
    cerrado = await _crear_caso(db, cliente_id=cliente["id"], despacho_id=despacho, estado="cerrado")

    cantidad = await recalcular_health_score_de_casos_abiertos(db)
    assert cantidad == 1

    fila_abierto = await db.fetchrow("SELECT health_score FROM casos WHERE id = $1", abierto)
    fila_cerrado = await db.fetchrow("SELECT health_score FROM casos WHERE id = $1", cerrado)
    assert fila_abierto["health_score"] == 0  # sí se calculó
    assert fila_cerrado["health_score"] is None  # nunca se tocó
