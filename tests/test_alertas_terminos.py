"""
Vridik — tests/test_alertas_terminos.py
Fase 2 (Copiloto Procesal) + Track Forja TF3: alertas proactivas de
términos, escalonadas en tres avisos (T-5/T-3/T-1, ver
core/terminos.py::DIAS_ESCALONES) en vez de un solo aviso repetido.

Capas, mismo criterio que tests/test_events.py:
1. Pura: core/terminos.py::escalon_aplicable() con casos límite en cada
   frontera de escalón -- es la que decide qué escalón corresponde.
2. Fake mínimo: procesal/alertas_terminos.py::ejecutar_ronda_de_alertas()
   arma los destinatarios y las notificaciones correctas -- rápido, sin
   red, corre siempre.
3. PostgreSQL real (fixture `db` de conftest.py, con rollback transaccional
   -- acá SÍ es apropiada porque no se prueba la entrega NOTIFY en vivo,
   solo el filtrado/idempotencia de core/terminos.py::listar_terminos_para_
   alertar): confirma el JOIN con `casos` y el filtro por escalón contra
   SQL real, no una reimplementación en Python -- incluye el caso central
   de TF3: un término que ya se notificó en un escalón flojo (T-5) vuelve
   a aparecer cuando alcanza uno más urgente (T-3), pero uno ya notificado
   en el escalón más urgente (T-1) no vuelve a aparecer nunca.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest

from core.case import create_caso, ensure_casos_table
from core.events import ensure_events_table
from core.rls import ensure_rls_policies, ensure_rls_policies_indirectas
from core.terminos import (
    crear_termino,
    ensure_terminos_table,
    escalon_aplicable,
    listar_terminos_para_alertar,
    marcar_escalon_notificado,
)
from procesal.alertas_terminos import ejecutar_ronda_de_alertas


# ---------------------------------------------------------------------------
# Pura: escalon_aplicable en cada frontera.
# ---------------------------------------------------------------------------
def test_escalon_aplicable_en_cada_frontera():
    casos = [
        (10, None),   # lejos -- ningún escalón todavía
        (6, None),
        (5, 5),        # justo en T-5
        (4, 5),
        (3, 3),        # justo en T-3
        (2, 3),
        (1, 1),        # justo en T-1
        (0, 1),        # vence hoy
        (-1, 1),       # ya vencido -- sigue siendo el escalón más urgente
        (-30, 1),
    ]
    for dias, esperado in casos:
        assert escalon_aplicable(dias) == esperado, f"dias_restantes={dias}"


# ---------------------------------------------------------------------------
# Fake: orquestación de ejecutar_ronda_de_alertas (destinatarios, notify, marcado).
# ---------------------------------------------------------------------------
class _FakeAlertasConn:
    def __init__(self, filas_en_riesgo: list[dict]):
        self._filas_en_riesgo = filas_en_riesgo
        self.user_events: list[dict] = []
        self.marcados: list[tuple[str, int]] = []
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
        if q.startswith("UPDATE terminos SET ultimo_escalon_notificado"):
            termino_id, escalon = args
            self.marcados.append((termino_id, escalon))
        elif "pg_notify" in q:
            canal, payload = args
            self.notificaciones.append((canal, payload))
        return "OK"


@pytest.mark.asyncio
async def test_ejecutar_ronda_notifica_a_cliente_y_abogado():
    fila = {
        "id": "termino-1", "caso_id": "caso-1", "descripcion": "Contestar requerimiento",
        "fecha_vencimiento": date(2026, 7, 20), "cliente_id": "cliente-1", "abogado_id": "abogado-1",
        "escalon": 3,
    }
    conn = _FakeAlertasConn([fila])

    enviadas = await ejecutar_ronda_de_alertas(conn)

    assert enviadas == 1
    destinatarios = {e["user_id"] for e in conn.user_events}
    assert destinatarios == {"cliente-1", "abogado-1"}
    assert all(e["event_type"] == "termino.por_vencer" for e in conn.user_events)
    assert conn.marcados == [("termino-1", 3)]


@pytest.mark.asyncio
async def test_ejecutar_ronda_sin_abogado_asignado_solo_notifica_al_cliente():
    fila = {
        "id": "termino-2", "caso_id": "caso-2", "descripcion": "x",
        "fecha_vencimiento": date(2026, 7, 20), "cliente_id": "cliente-2", "abogado_id": None,
        "escalon": 1,
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
async def test_ejecutar_ronda_marca_el_escalon_notificado_para_cada_termino_procesado():
    filas = [
        {"id": "t-1", "caso_id": "c-1", "descripcion": "a", "fecha_vencimiento": date(2026, 7, 18),
         "cliente_id": "cli-1", "abogado_id": None, "escalon": 1},
        {"id": "t-2", "caso_id": "c-2", "descripcion": "b", "fecha_vencimiento": date(2026, 7, 19),
         "cliente_id": "cli-2", "abogado_id": "abo-2", "escalon": 5},
    ]
    conn = _FakeAlertasConn(filas)

    enviadas = await ejecutar_ronda_de_alertas(conn)

    assert enviadas == 2
    assert set(conn.marcados) == {("t-1", 1), ("t-2", 5)}


# ---------------------------------------------------------------------------
# PostgreSQL real: filtrado/idempotencia de listar_terminos_para_alertar.
# ---------------------------------------------------------------------------
async def _crear_termino_directo(db, *, caso_id: str, created_by: str, fecha_vencimiento: date) -> str:
    """INSERT directo (sin pasar por sumar_dias_habiles) para controlar
    fecha_vencimiento con precisión -- lo que estos tests necesitan probar
    es el filtro por escalón, no el cálculo de días hábiles (ya cubierto
    en tests/test_calendario_judicial.py)."""
    return await db.fetchval(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'termino', $3, 1, $3) RETURNING id",
        caso_id, created_by, fecha_vencimiento,
    )


@pytest.mark.asyncio
async def test_listar_terminos_para_alertar_respeta_escalon_ya_notificado(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_terminos_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    caso = await create_caso(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba", abogado_id=abogado["id"],
    )
    hoy = date.today()

    # En riesgo (vence en 2 días -- escalón 3), nunca notificado: debe salir.
    en_riesgo = await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy + timedelta(days=2))
    # Lejos (vence muy después): no debe salir, ningún escalón aplica.
    await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy + timedelta(days=30))
    # Ya notificado exactamente en el escalón que le toca ahora: no debe repetirse.
    ya_notificado = await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy + timedelta(days=2))
    await marcar_escalon_notificado(db, termino_id=ya_notificado, escalon=3)
    # Notificado en un escalón más flojo (T-5) que el que le toca ahora (T-3): SÍ debe reaparecer.
    escalo = await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy + timedelta(days=2))
    await marcar_escalon_notificado(db, termino_id=escalo, escalon=5)

    filas = await listar_terminos_para_alertar(db, hoy=hoy)
    ids = {str(f["id"]) for f in filas}

    assert str(en_riesgo) in ids
    assert str(ya_notificado) not in ids
    assert str(escalo) in ids
    encontrada = next(f for f in filas if str(f["id"]) == str(en_riesgo))
    assert encontrada["escalon"] == 3
    assert str(encontrada["cliente_id"]) == cliente["id"]
    assert str(encontrada["abogado_id"]) == abogado["id"]


@pytest.mark.asyncio
async def test_marcar_escalon_notificado_en_el_mas_urgente_no_vuelve_a_aparecer_nunca(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_terminos_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso = await create_caso(db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba")
    hoy = date.today()
    termino = await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy - timedelta(days=1))

    antes = await listar_terminos_para_alertar(db, hoy=hoy)
    assert str(termino) in {str(f["id"]) for f in antes}

    await marcar_escalon_notificado(db, termino_id=termino, escalon=1)

    # Escalón 1 es el más urgente que existe -- no hay ningún escalón más
    # chico al que pueda "escalar" después, así que nunca vuelve a salir.
    despues = await listar_terminos_para_alertar(db, hoy=hoy)
    assert str(termino) not in {str(f["id"]) for f in despues}
    mas_tarde = await listar_terminos_para_alertar(db, hoy=hoy + timedelta(days=5))
    assert str(termino) not in {str(f["id"]) for f in mas_tarde}


@pytest.mark.asyncio
async def test_escalonamiento_notifica_de_nuevo_al_llegar_a_un_escalon_mas_urgente(db, make_despacho, make_user):
    """El caso central de TF3: un mismo término recibe MÁS de un aviso a
    medida que se acerca el vencimiento (T-5 primero, T-3 después) -- no
    uno solo como en el diseño de Fase 2."""
    await ensure_casos_table(db)
    await ensure_terminos_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso = await create_caso(db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba")
    hoy = date.today()
    termino = await _crear_termino_directo(db, caso_id=caso["id"], created_by=cliente["id"], fecha_vencimiento=hoy + timedelta(days=5))

    ronda_t5 = await listar_terminos_para_alertar(db, hoy=hoy)
    fila_t5 = next(f for f in ronda_t5 if str(f["id"]) == str(termino))
    assert fila_t5["escalon"] == 5
    await marcar_escalon_notificado(db, termino_id=termino, escalon=5)

    # Mismo día, mismo escalón: no se repite.
    ronda_mismo_dia = await listar_terminos_para_alertar(db, hoy=hoy)
    assert str(termino) not in {str(f["id"]) for f in ronda_mismo_dia}

    # Pasan 2 días -- ahora está a T-3, un escalón más urgente que el
    # último notificado (5): debe reaparecer.
    hoy_mas_tarde = hoy + timedelta(days=2)
    ronda_t3 = await listar_terminos_para_alertar(db, hoy=hoy_mas_tarde)
    fila_t3 = next(f for f in ronda_t3 if str(f["id"]) == str(termino))
    assert fila_t3["escalon"] == 3


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
    # notificar el mismo escalón (ver core/terminos.py::DIAS_ESCALONES y
    # el filtro por ultimo_escalon_notificado).
    segunda_ronda = await ejecutar_ronda_de_alertas(db)
    assert segunda_ronda == 0


@pytest.mark.asyncio
async def test_ronda_sin_ningun_guc_seteado_no_ve_nada_bajo_rls(db, make_despacho, make_user):
    """Regresión: `_bucle_alertas_terminos()` (app/main.py) adquiere su
    conexión directo de `app.state.db_connection.acquire()`, sin pasar por
    el middleware de conexión-por-request -- nunca queda con `app.
    bypass_rls` seteado (NULL, ni 'true' ni 'false'), a diferencia de la
    fixture `db` de conftest.py que sí lo deja en 'true' por defecto para
    los ~300 tests que no prueban RLS en sí.

    Con `terminos`/`casos` bajo FORCE ROW LEVEL SECURITY (core/rls.py::
    ensure_rls_policies_indirectas, Track Forja TF1), una conexión sin
    ningún GUC no matchea ninguna rama de la política (`bypass_rls='true'`
    OR `despacho_id` coincide) -- ve CERO filas de ambas tablas. Sin el fix
    (`await conn.execute(\"SELECT set_config('app.bypass_rls', 'true',
    false)\")` justo después de `.acquire()` en app/main.py),
    ejecutar_ronda_de_alertas() devolvería 0 SIEMPRE en producción, en
    silencio, aunque hubiera términos vencidos reales -- exactamente el bug
    que este test reproduce y que el fix corrige."""
    await ensure_rls_policies(db)
    await ensure_rls_policies_indirectas(db)
    await db.execute("SELECT set_config('app.bypass_rls', 'true', false)")
    await ensure_events_table(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso = await create_caso(db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba")
    hoy = date.today()
    await crear_termino(
        db, caso_id=caso["id"], created_by=cliente["id"], descripcion="vencido",
        fecha_inicio=hoy - timedelta(days=10), dias_habiles=1,
    )

    # Estado real de `.acquire()`: sin bypass_rls, sin despacho_id -- NADA.
    await db.execute("RESET app.bypass_rls")
    await db.execute("RESET app.despacho_id")

    ronda_sin_contexto = await ejecutar_ronda_de_alertas(db)
    assert ronda_sin_contexto == 0, (
        "reproduce el bug: sin bypass, la conexión no ve el término vencido bajo RLS"
    )

    # El fix real (app/main.py::_bucle_alertas_terminos): setear bypass_rls
    # apenas se adquiere la conexión, antes de correr la ronda.
    await db.execute("SELECT set_config('app.bypass_rls', 'true', false)")
    ronda_con_bypass = await ejecutar_ronda_de_alertas(db)
    assert ronda_con_bypass == 1, "con el fix aplicado, la ronda sí ve y notifica el término vencido"
