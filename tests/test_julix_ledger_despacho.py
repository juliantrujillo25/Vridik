"""
Vridik — tests/test_julix_ledger_despacho.py
Fase 4 (pricing por despacho): julix/ledger.py::requiere_confirmacion
resuelve el límite mensual según el PLAN del despacho, no un flat
compartido -- test de seguridad real: el gate de gasto depende de esto.

Postgres real (fixture `db`, rollback transaccional) -- este cálculo es
justo el que decide si JuliX genera un documento o pide confirmación, no
tiene sentido probarlo contra un fake que no ejecuta el SQL real.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.despachos import cambiar_plan, ensure_despachos_table
from julix.ledger import ensure_julix_calls_table, requiere_confirmacion


async def _sembrar_despacho(db, *, plan: str = "piloto") -> str:
    await ensure_despachos_table(db)
    despacho_id = await db.fetchval("INSERT INTO despachos (nombre) VALUES ('Ledger Test') RETURNING id")
    if plan != "piloto":
        await cambiar_plan(db, despacho_id=despacho_id, plan=plan)
    return despacho_id


async def _registrar_gasto(db, *, despacho_id: str, costo_usd: float) -> None:
    await ensure_julix_calls_table(db)
    await db.execute(
        """
        INSERT INTO julix_calls (
            user_id, caso_id, despacho_id, tarea, model, prompt_version, prompt_hash,
            input_tokens, output_tokens, costo_usd, latency_ms, status, environment, created_at
        ) VALUES (NULL, NULL, $1, 'ugpp_demanda', 'claude-sonnet-5', 1, 'x', 1000, 1000, $2, 500, 'ok', 'production', now())
        """,
        despacho_id, costo_usd,
    )


@pytest.mark.asyncio
async def test_despacho_piloto_bloquea_al_llegar_a_150(db):
    despacho_id = await _sembrar_despacho(db, plan="piloto")
    await _registrar_gasto(db, despacho_id=despacho_id, costo_usd=151.0)

    aviso_80, confirmacion_100 = await requiere_confirmacion(db, despacho_id=despacho_id)
    assert confirmacion_100 is True


@pytest.mark.asyncio
async def test_despacho_pagado_no_bloquea_con_el_mismo_gasto_que_bloquearia_a_piloto(db):
    despacho_id = await _sembrar_despacho(db, plan="pagado")
    await _registrar_gasto(db, despacho_id=despacho_id, costo_usd=151.0)

    aviso_80, confirmacion_100 = await requiere_confirmacion(db, despacho_id=despacho_id)
    assert confirmacion_100 is False


@pytest.mark.asyncio
async def test_despacho_pagado_bloquea_al_llegar_a_500(db):
    despacho_id = await _sembrar_despacho(db, plan="pagado")
    await _registrar_gasto(db, despacho_id=despacho_id, costo_usd=501.0)

    aviso_80, confirmacion_100 = await requiere_confirmacion(db, despacho_id=despacho_id)
    assert confirmacion_100 is True


@pytest.mark.asyncio
async def test_dos_despachos_no_comparten_limite(db):
    """El gasto de un despacho pagado (que ya superó los $150 que
    bloquearían a un piloto) no debe afectar a un despacho piloto
    distinto -- cada uno tiene su propio pozo, ver Fase 4 (multi-tenancy)."""
    despacho_a = await _sembrar_despacho(db, plan="pagado")
    despacho_b = await _sembrar_despacho(db, plan="piloto")

    await _registrar_gasto(db, despacho_id=despacho_a, costo_usd=300.0)

    _, confirmacion_b = await requiere_confirmacion(db, despacho_id=despacho_b)
    assert confirmacion_b is False
