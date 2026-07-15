"""
Vridik — tests/test_despachos.py
Fase 4 (multi-tenancy): core/despachos.py -- backfill de despacho_id sobre
Postgres real (fixture `db` de conftest.py, rollback transaccional).
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.despachos import ensure_despachos_backfill


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
