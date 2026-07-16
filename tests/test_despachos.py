"""
Vridik — tests/test_despachos.py
Fase 4 (multi-tenancy): core/despachos.py -- backfill de despacho_id sobre
Postgres real (fixture `db` de conftest.py, rollback transaccional).
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.despachos import (
    PlanInvalidoError,
    cambiar_plan,
    ensure_despachos_backfill,
    ensure_despachos_table,
    limite_julix_mensual,
)


@pytest.mark.asyncio
async def test_backfill_asigna_despacho_por_defecto_a_usuarios_sin_despacho(db):
    """Simula el escenario real: un usuario insertado ANTES de que
    despacho_id existiera (columna todavía sin agregar, `ensure_despachos_
    backfill` la crea acá adentro) no debe quedar sin despacho después del
    backfill."""
    fila = await db.fetchrow(
        """
        INSERT INTO users (email, hashed_password, is_active)
        VALUES ('backfill-despacho-test@vridik.local', 'x-hash', true)
        RETURNING id
        """
    )
    user_id = fila["id"]

    await ensure_despachos_backfill(db)

    actualizado = await db.fetchrow("SELECT despacho_id FROM users WHERE id = $1", user_id)
    assert actualizado["despacho_id"] is not None

    despacho = await db.fetchrow("SELECT nombre FROM despachos WHERE id = $1", actualizado["despacho_id"])
    assert despacho["nombre"] == "Despacho por defecto"


@pytest.mark.asyncio
async def test_backfill_es_idempotente(db):
    """Correr el backfill dos veces seguidas no debe fallar (SET NOT NULL
    sobre una columna ya NOT NULL es un no-op en Postgres) ni duplicar
    "Despacho por defecto"."""
    await db.fetchrow(
        """
        INSERT INTO users (email, hashed_password, is_active)
        VALUES ('backfill-idempotente@vridik.local', 'x-hash', true)
        RETURNING id
        """
    )

    await ensure_despachos_backfill(db)
    await ensure_despachos_backfill(db)  # segunda corrida -- no debe romper nada

    total = await db.fetchval("SELECT COUNT(*) FROM despachos WHERE nombre = 'Despacho por defecto'")
    assert total == 1


# ---------------------------------------------------------------------------
# Pricing por despacho (Fase 4, pasada siguiente a la fundación de
# multi-tenancy): plan de un despacho y su límite mensual de JuliX.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_despacho_nuevo_nace_en_plan_piloto_con_limite_150(db):
    await ensure_despachos_table(db)
    despacho_id = await db.fetchval("INSERT INTO despachos (nombre) VALUES ('Piloto Test') RETURNING id")
    limite = await limite_julix_mensual(db, despacho_id)
    assert limite == 150.0


@pytest.mark.asyncio
async def test_cambiar_plan_a_pagado_sube_el_limite_a_500(db):
    await ensure_despachos_table(db)
    despacho_id = await db.fetchval("INSERT INTO despachos (nombre) VALUES ('Pagado Test') RETURNING id")

    actualizado = await cambiar_plan(db, despacho_id=despacho_id, plan="pagado")
    assert actualizado["plan"] == "pagado"

    limite = await limite_julix_mensual(db, despacho_id)
    assert limite == 500.0


@pytest.mark.asyncio
async def test_cambiar_plan_invalido_rechazado(db):
    await ensure_despachos_table(db)
    despacho_id = await db.fetchval("INSERT INTO despachos (nombre) VALUES ('Plan Invalido Test') RETURNING id")

    with pytest.raises(PlanInvalidoError):
        await cambiar_plan(db, despacho_id=despacho_id, plan="premium-inventado")

    # No debe haber tocado el plan real (sigue en 'piloto', el default).
    limite = await limite_julix_mensual(db, despacho_id)
    assert limite == 150.0


@pytest.mark.asyncio
async def test_cambiar_plan_despacho_inexistente_rechazado(db):
    await ensure_despachos_table(db)
    with pytest.raises(PlanInvalidoError):
        await cambiar_plan(db, despacho_id="00000000-0000-0000-0000-000000000000", plan="pagado")
