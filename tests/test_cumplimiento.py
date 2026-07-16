"""
Vridik — tests/test_cumplimiento.py
Fase 4 (SAGRILAFT lite): core/cumplimiento.py::calcular_nivel_riesgo --
función pura, casos borde de la heurística documentada en el módulo.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.cumplimiento import (
    ClienteDeOtroDespachoError,
    FactorInvalidoError,
    calcular_nivel_riesgo,
    ensure_matriz_riesgo_table,
    generar_reporte_riesgo,
    obtener_matriz_riesgo,
    set_matriz_riesgo,
)
from core.despachos import ensure_despachos_table


def test_pep_da_alto_pese_a_todos_los_demas_factores_bajos():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="bajo", jurisdiccion_riesgo="bajo", canal="presencial", es_pep=True,
    )
    assert nivel == "alto"


def test_sin_pep_y_todo_bajo_da_bajo():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="bajo", jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )
    assert nivel == "bajo"


def test_un_factor_alto_eleva_el_nivel_global_aunque_los_demas_sean_bajos():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="alto", jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )
    assert nivel == "alto"


def test_jurisdiccion_alta_eleva_el_nivel_global():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="bajo", jurisdiccion_riesgo="alto", canal="presencial", es_pep=False,
    )
    assert nivel == "alto"


def test_canal_no_presencial_eleva_a_medio_aunque_los_demas_sean_bajos():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="bajo", jurisdiccion_riesgo="bajo", canal="no_presencial", es_pep=False,
    )
    assert nivel == "medio"


def test_canal_no_presencial_no_baja_un_factor_ya_alto():
    nivel = calcular_nivel_riesgo(
        actividad_economica_riesgo="alto", jurisdiccion_riesgo="bajo", canal="no_presencial", es_pep=False,
    )
    assert nivel == "alto"


def test_actividad_economica_invalida_rechazada():
    with pytest.raises(FactorInvalidoError):
        calcular_nivel_riesgo(
            actividad_economica_riesgo="extremo", jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
        )


def test_jurisdiccion_invalida_rechazada():
    with pytest.raises(FactorInvalidoError):
        calcular_nivel_riesgo(
            actividad_economica_riesgo="bajo", jurisdiccion_riesgo="extremo", canal="presencial", es_pep=False,
        )


def test_canal_invalido_rechazado():
    with pytest.raises(FactorInvalidoError):
        calcular_nivel_riesgo(
            actividad_economica_riesgo="bajo", jurisdiccion_riesgo="bajo", canal="remoto", es_pep=False,
        )


# ---------------------------------------------------------------------------
# Postgres real (fixture `db`, rollback transaccional) -- confirma que el
# esquema (CHECK constraints, upsert por cliente_id) funciona de verdad, no
# solo el fake de tests/test_clientes_endpoint.py.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_y_obtener_matriz_riesgo_contra_postgres_real(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    guardada = await set_matriz_riesgo(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, actor_id=abogado["id"],
        tipo_persona="natural", actividad_economica_riesgo="bajo",
        jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )
    assert guardada["nivel_riesgo_calculado"] == "bajo"

    leida = await obtener_matriz_riesgo(db, cliente_id=cliente["id"], despacho_id=despacho_id)
    assert leida["nivel_riesgo_calculado"] == "bajo"
    assert leida["evaluado_por"] == uuid.UUID(abogado["id"])


@pytest.mark.asyncio
async def test_set_matriz_riesgo_es_upsert_no_duplica_fila(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    await set_matriz_riesgo(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, actor_id=abogado["id"],
        tipo_persona="natural", actividad_economica_riesgo="bajo",
        jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )
    actualizada = await set_matriz_riesgo(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, actor_id=abogado["id"],
        tipo_persona="natural", actividad_economica_riesgo="alto",
        jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )
    assert actualizada["nivel_riesgo_calculado"] == "alto"

    total = await db.fetchval("SELECT COUNT(*) FROM matriz_riesgo WHERE cliente_id = $1", cliente["id"])
    assert total == 1


@pytest.mark.asyncio
async def test_set_matriz_riesgo_rechaza_cliente_de_otro_despacho(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    abogado_a = await make_user(role="abogado", despacho_id=despacho_a)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)

    with pytest.raises(ClienteDeOtroDespachoError):
        await set_matriz_riesgo(
            db, cliente_id=cliente_b["id"], despacho_id=despacho_a, actor_id=abogado_a["id"],
            tipo_persona="natural", actividad_economica_riesgo="bajo",
            jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
        )


@pytest.mark.asyncio
async def test_ensure_matriz_riesgo_table_es_idempotente(db):
    await ensure_despachos_table(db)
    await ensure_matriz_riesgo_table(db)
    await ensure_matriz_riesgo_table(db)  # segunda corrida -- no debe romper nada


# ---------------------------------------------------------------------------
# generar_reporte_riesgo (roadmap Fase 4: "reportes Supersociedades")
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reporte_riesgo_cuenta_evaluados_y_sin_evaluar(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    evaluado = await make_user(role="cliente", despacho_id=despacho_id)
    await make_user(role="cliente", despacho_id=despacho_id)  # sin evaluar

    await set_matriz_riesgo(
        db, cliente_id=evaluado["id"], despacho_id=despacho_id, actor_id=abogado["id"],
        tipo_persona="natural", actividad_economica_riesgo="bajo",
        jurisdiccion_riesgo="bajo", canal="presencial", es_pep=False,
    )

    reporte = await generar_reporte_riesgo(db, despacho_id=despacho_id)
    assert reporte["total_clientes"] == 2
    assert reporte["total_evaluados"] == 1
    assert reporte["total_sin_evaluar"] == 1
    assert reporte["conteo_por_nivel"] == {"bajo": 1, "medio": 0, "alto": 0}
    assert reporte["total_pep"] == 0
    assert len(reporte["clientes"]) == 1
    assert reporte["clientes"][0]["cliente_id"] == uuid.UUID(evaluado["id"])
    assert reporte["clientes"][0]["evaluado_por_email"] == abogado["email"]


@pytest.mark.asyncio
async def test_reporte_riesgo_ordena_de_mayor_a_menor_riesgo(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente_bajo = await make_user(role="cliente", despacho_id=despacho_id)
    cliente_alto = await make_user(role="cliente", despacho_id=despacho_id)
    cliente_medio = await make_user(role="cliente", despacho_id=despacho_id)

    for cliente, canal, es_pep in (
        (cliente_bajo, "presencial", False),
        (cliente_alto, "presencial", True),
        (cliente_medio, "no_presencial", False),
    ):
        await set_matriz_riesgo(
            db, cliente_id=cliente["id"], despacho_id=despacho_id, actor_id=abogado["id"],
            tipo_persona="natural", actividad_economica_riesgo="bajo",
            jurisdiccion_riesgo="bajo", canal=canal, es_pep=es_pep,
        )

    reporte = await generar_reporte_riesgo(db, despacho_id=despacho_id)
    niveles = [c["nivel_riesgo_calculado"] for c in reporte["clientes"]]
    assert niveles == ["alto", "medio", "bajo"]
    assert reporte["total_pep"] == 1
    assert reporte["conteo_por_nivel"] == {"bajo": 1, "medio": 1, "alto": 1}


@pytest.mark.asyncio
async def test_reporte_riesgo_no_mezcla_clientes_de_otro_despacho(db, make_despacho, make_user):
    await ensure_matriz_riesgo_table(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    abogado_b = await make_user(role="abogado", despacho_id=despacho_b)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)

    await set_matriz_riesgo(
        db, cliente_id=cliente_b["id"], despacho_id=despacho_b, actor_id=abogado_b["id"],
        tipo_persona="natural", actividad_economica_riesgo="alto",
        jurisdiccion_riesgo="alto", canal="presencial", es_pep=True,
    )

    reporte_a = await generar_reporte_riesgo(db, despacho_id=despacho_a)
    assert reporte_a["total_clientes"] == 0
    assert reporte_a["clientes"] == []
