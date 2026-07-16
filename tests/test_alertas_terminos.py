"""
Vridik — tests/test_alertas_terminos.py
Fase 2 (Copiloto Procesal): alertas proactivas de términos en riesgo.

Dos capas, mismo criterio que tests/test_events.py:
1. Fake mínimo: procesal/alertas_terminos.py::ejecutar_ronda_de_alertas()
   arma los destinatarios y las notificaciones correctas -- rápido, sin
   red, corre siempre.
2. PostgreSQL real (fixture `db` de conftest.py, con rollback transaccional
   -- acá SÍ es apropiada porque no se prueba la entrega NOTIFY en vivo,
   solo el filtrado/idempotencia de core/terminos.py::listar_terminos_para_
   alertar): confirma el JOIN con `casos` y el filtro por fecha/estado/
   ultima_alerta_enviada contra SQL real, no una reimplementación en Python.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.case import create_caso, ensure_casos_table
from core.terminos import (
    crear_termino,
    ensure_terminos_table,
    listar_terminos_para_alertar,
    marcar_alerta_enviada,
)
from procesal.alertas_terminos import ejecutar_ronda_de_alertas


# ---------------------------------------------------------------------------
# Fake: orquestación de ejecutar_ronda_de_alertas (destinatarios, notify, marcado).
# ---------------------------------------------------------------------------
class _FakeAlertasConn:
    def __init__(self, filas_en_riesgo: list[dict]):
        self._filas_en_riesgo = filas_en_riesgo
        self.user_events: list[dict] = []
        self.marcados: list[str] = []
        self.notificaciones: list[tuple[str, str]] = []  # (canal, payload)

    async def fetch(self, query: str, *args):
        if "FROM terminos t" in query and "JOIN casos c" in query:
            return [dict(f) for f in self._filas_en_riesgo]
        return []

    async def fetchrow(self, query: str, *args):
        if query.strip().startswith("INSERT INTO user_events"):
            user_id, event_type, payload = args
            evento_id = len(self.user_events) + 1
            self.user_events.append({"id": evento_id, "user_id": user_id, "event_type": event_type})
            return {"id": evento_id}
        return None

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("UPDATE terminos SET ultima_alerta_enviada"):
            termino_id, _hoy = args
            self.marcados.append(termino_id)
        elif "pg_notify" in q:
            canal, payload = args
            self.notificaciones.append((canal, payload))
        return "OK"


@pytest.mark.asyncio
async def test_ejecutar_ronda_notifica_a_cliente_y_abogado():
    fila = {
        "id": "termino-1", "caso_id": "caso-1", "descripcion": "Contestar requerimiento",
        "fecha_vencimiento": date(2026, 7, 20), "cliente_id": "cliente-1", "abogado_id": "abogado-1",
    }
    conn = _FakeAlertasConn([fila])

    enviadas = await ejecutar_ronda_de_alertas(conn)

    assert enviadas == 1
    destinatarios = {e["user_id"] for e in conn.user_events}
    assert destinatarios == {"cliente-1", "abogado-1"}
    assert all(e["event_type"] == "termino.alerta" for e in conn.user_events)
    assert conn.marcados == ["termino-1"]


@pytest.mark.asyncio
async def test_ejecutar_ronda_sin_abogado_asignado_solo_notifica_al_cliente():
    fila = {
        "id": "termino-2", "caso_id": "caso-2", "descripcion": "x",
        "fecha_vencimiento": date(2026, 7, 20), "cliente_id": "cliente-2", "abogado_id": None,
    }
    conn = _FakeAlertasConn([fila])

    await ejecutar_ronda_de_alertas(conn)

    assert [e["user_id"] for e in conn.user_events] == ["cliente-2"]


@pytest.mark.asyncio
async def test_ejecutar_ronda_sin_terminos_en_riesgo_no_notifica_nada():
    conn = _FakeAlertasConn([])

    enviadas = await ejecutar_ronda_de_alertas(conn)

    assert enviadas == 0
    assert conn.user_events == []
    assert conn.marcados == []


@pytest.mark.asyncio
async def test_ejecutar_ronda_marca_alerta_enviada_para_cada_termino_procesado():
    filas = [
        {"id": "t-1", "caso_id": "c-1", "descripcion": "a", "fecha_vencimiento": date(2026, 7, 18),
         "cliente_id": "cli-1", "abogado_id": None},
        {"id": "t-2", "caso_id": "c-2", "descripcion": "b", "fecha_vencimiento": date(2026, 7, 19),
         "cliente_id": "cli-2", "abogado_id": "abo-2"},
    ]
    conn = _FakeAlertasConn(filas)

    enviadas = await ejecutar_ronda_de_alertas(conn)

    assert enviadas == 2
    assert set(conn.marcados) == {"t-1", "t-2"}


# ---------------------------------------------------------------------------
# PostgreSQL real: filtrado/idempotencia de listar_terminos_para_alertar.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_listar_terminos_para_alertar_incluye_solo_pendientes_en_riesgo_no_avisados_hoy(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_terminos_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    caso = await create_caso(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba", abogado_id=abogado["id"],
    )

    hoy = date.today()
    # En riesgo (vence en 2 días -- dentro del umbral de 3): debe salir.
    en_riesgo = await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="en riesgo",
        fecha_inicio=hoy - timedelta(days=5), dias_habiles=1,
    )
    # Lejos (vence muy después): no debe salir.
    await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="lejos",
        fecha_inicio=hoy, dias_habiles=30,
    )
    # Ya avisado hoy: no debe volver a salir aunque esté en riesgo.
    ya_avisado = await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="ya avisado",
        fecha_inicio=hoy - timedelta(days=5), dias_habiles=1,
    )
    await marcar_alerta_enviada(db, termino_id=ya_avisado["id"], hoy=hoy)

    filas = await listar_terminos_para_alertar(db, hoy=hoy)
    ids = {f["id"] for f in filas}

    assert str(en_riesgo["id"]) in {str(i) for i in ids}
    assert str(ya_avisado["id"]) not in {str(i) for i in ids}
    encontrada = next(f for f in filas if str(f["id"]) == str(en_riesgo["id"]))
    assert str(encontrada["cliente_id"]) == cliente["id"]
    assert str(encontrada["abogado_id"]) == abogado["id"]


@pytest.mark.asyncio
async def test_marcar_alerta_enviada_hace_que_desaparezca_de_la_proxima_ronda(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_terminos_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso = await create_caso(db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba")
    hoy = date.today()
    termino = await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="vencido",
        fecha_inicio=hoy - timedelta(days=10), dias_habiles=1,
    )

    antes = await listar_terminos_para_alertar(db, hoy=hoy)
    assert str(termino["id"]) in {str(f["id"]) for f in antes}

    await marcar_alerta_enviada(db, termino_id=termino["id"], hoy=hoy)

    despues = await listar_terminos_para_alertar(db, hoy=hoy)
    assert str(termino["id"]) not in {str(f["id"]) for f in despues}


@pytest.mark.asyncio
async def test_ejecutar_ronda_de_alertas_extremo_a_extremo_contra_postgres_real(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_terminos_table(db)
    await ensure_events_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    caso = await create_caso(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba", abogado_id=abogado["id"],
    )
    hoy = date.today()
    await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="vencido",
        fecha_inicio=hoy - timedelta(days=10), dias_habiles=1,
    )

    primera_ronda = await ejecutar_ronda_de_alertas(db)
    assert primera_ronda == 1

    # Idempotencia: correr la ronda otra vez el mismo día no debe volver a
    # notificar el mismo término (ver core/terminos.py::UMBRAL_DIAS_RIESGO
    # y el filtro por ultima_alerta_enviada).
    segunda_ronda = await ejecutar_ronda_de_alertas(db)
    assert segunda_ronda == 0
