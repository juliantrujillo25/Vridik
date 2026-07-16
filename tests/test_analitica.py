"""
Vridik — tests/test_analitica.py
Fase 4 (roadmap: "línea decisional UGPP") -- core/analitica.py contra
Postgres real. Sobre casos PROPIOS del despacho (nunca corpus externo ni
datos por juez).
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.actuaciones import ensure_actuaciones_table, insert_actuacion, set_resultado_actuacion
from core.analitica import generar_analitica_ugpp
from core.case import create_caso, ensure_casos_table
from core.cobro import ensure_cobro_table, liquidar_honorarios, set_cobro


async def _crear_caso_ugpp(db, *, despacho_id: str, cliente_id: str, abogado_id: str) -> dict:
    return await create_caso(
        db, cliente_id=cliente_id, despacho_id=despacho_id, titulo="caso ugpp",
        abogado_id=abogado_id, materia="ugpp",
    )


@pytest.mark.asyncio
async def test_analitica_vacia_sin_casos_ugpp(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_id = await make_despacho()

    reporte = await generar_analitica_ugpp(db, despacho_id=despacho_id)
    assert reporte["total_casos_ugpp"] == 0
    assert reporte["total_con_resultado"] == 0
    assert reporte["tasa_exito"] is None
    assert reporte["tiempo_promedio_dias_hasta_fallo"] is None
    assert reporte["por_tipo_resolucion"] == []
    assert reporte["valor_recuperado_total"] == 0


@pytest.mark.asyncio
async def test_analitica_cuenta_resultados_y_calcula_tasa_de_exito(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    for resultado in ("favorable", "favorable", "desfavorable", "parcial"):
        caso = await _crear_caso_ugpp(db, despacho_id=despacho_id, cliente_id=cliente["id"], abogado_id=abogado["id"])
        actuacion = await insert_actuacion(
            db, caso_id=caso["id"], created_by=abogado["id"], texto="fallo", categoria="fallo",
            confianza=0.9, texto_bruto=None,
        )
        await set_resultado_actuacion(
            db, actuacion_id=actuacion["id"], resultado=resultado, tipo_resolucion_ugpp="RQI",
        )

    reporte = await generar_analitica_ugpp(db, despacho_id=despacho_id)
    assert reporte["total_casos_ugpp"] == 4
    assert reporte["total_con_resultado"] == 4
    assert reporte["conteo_por_resultado"] == {"favorable": 2, "desfavorable": 1, "parcial": 1}
    assert reporte["tasa_exito"] == pytest.approx(0.5)
    assert len(reporte["por_tipo_resolucion"]) == 1
    assert reporte["por_tipo_resolucion"][0]["tipo_resolucion_ugpp"] == "RQI"
    assert reporte["por_tipo_resolucion"][0]["total"] == 4


@pytest.mark.asyncio
async def test_analitica_agrupa_por_tipo_de_resolucion_distintos(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    for tipo, resultado in (("RQI", "favorable"), ("RQI", "desfavorable"), ("RCD", "favorable")):
        caso = await _crear_caso_ugpp(db, despacho_id=despacho_id, cliente_id=cliente["id"], abogado_id=abogado["id"])
        actuacion = await insert_actuacion(
            db, caso_id=caso["id"], created_by=abogado["id"], texto="fallo", categoria="fallo",
            confianza=0.9, texto_bruto=None,
        )
        await set_resultado_actuacion(db, actuacion_id=actuacion["id"], resultado=resultado, tipo_resolucion_ugpp=tipo)

    reporte = await generar_analitica_ugpp(db, despacho_id=despacho_id)
    por_tipo = {f["tipo_resolucion_ugpp"]: f for f in reporte["por_tipo_resolucion"]}
    assert por_tipo["RQI"]["total"] == 2
    assert por_tipo["RQI"]["favorable"] == 1
    assert por_tipo["RQI"]["desfavorable"] == 1
    assert por_tipo["RCD"]["total"] == 1
    assert por_tipo["RCD"]["favorable"] == 1


@pytest.mark.asyncio
async def test_analitica_ignora_fallos_sin_resultado_y_casos_no_ugpp(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    # fallo sin resultado todavía -- cuenta como "registrado" pero no en la tasa de éxito
    caso_ugpp = await _crear_caso_ugpp(db, despacho_id=despacho_id, cliente_id=cliente["id"], abogado_id=abogado["id"])
    await insert_actuacion(
        db, caso_id=caso_ugpp["id"], created_by=abogado["id"], texto="fallo", categoria="fallo",
        confianza=0.9, texto_bruto=None,
    )

    # caso de otra materia -- ni siquiera debería aparecer en total_casos_ugpp
    caso_laboral = await create_caso(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="caso laboral",
        abogado_id=abogado["id"], materia="laboral",
    )
    actuacion_laboral = await insert_actuacion(
        db, caso_id=caso_laboral["id"], created_by=abogado["id"], texto="fallo", categoria="fallo",
        confianza=0.9, texto_bruto=None,
    )
    await set_resultado_actuacion(db, actuacion_id=actuacion_laboral["id"], resultado="favorable", tipo_resolucion_ugpp=None)

    reporte = await generar_analitica_ugpp(db, despacho_id=despacho_id)
    assert reporte["total_casos_ugpp"] == 1
    assert reporte["total_fallos_registrados"] == 1
    assert reporte["total_con_resultado"] == 0
    assert reporte["tasa_exito"] is None


@pytest.mark.asyncio
async def test_analitica_no_mezcla_despachos(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    abogado_b = await make_user(role="abogado", despacho_id=despacho_b)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)

    caso_b = await _crear_caso_ugpp(db, despacho_id=despacho_b, cliente_id=cliente_b["id"], abogado_id=abogado_b["id"])
    actuacion = await insert_actuacion(
        db, caso_id=caso_b["id"], created_by=abogado_b["id"], texto="fallo", categoria="fallo",
        confianza=0.9, texto_bruto=None,
    )
    await set_resultado_actuacion(db, actuacion_id=actuacion["id"], resultado="favorable", tipo_resolucion_ugpp="RQI")

    reporte_a = await generar_analitica_ugpp(db, despacho_id=despacho_a)
    assert reporte_a["total_casos_ugpp"] == 0
    assert reporte_a["por_tipo_resolucion"] == []


@pytest.mark.asyncio
async def test_analitica_suma_valor_recuperado_de_casos_ugpp_liquidados(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_cobro_table(db)
    despacho_id = await make_despacho()
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    cliente = await make_user(role="cliente", despacho_id=despacho_id)

    caso = await _crear_caso_ugpp(db, despacho_id=despacho_id, cliente_id=cliente["id"], abogado_id=abogado["id"])
    await set_cobro(db, caso_id=caso["id"], esquema_honorarios="fijo", monto_fijo=Decimal("1000000"))
    await liquidar_honorarios(db, caso_id=caso["id"], valor_recuperado=Decimal("5000000"))

    reporte = await generar_analitica_ugpp(db, despacho_id=despacho_id)
    assert reporte["casos_liquidados"] == 1
    assert reporte["valor_recuperado_total"] == pytest.approx(5000000.0)
    assert reporte["valor_recuperado_promedio"] == pytest.approx(5000000.0)
