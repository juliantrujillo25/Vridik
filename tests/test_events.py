"""
Vridik — tests/test_events.py
Roadmap Semana 11, Fase B: prueba core/events.py en dos capas.

1. Fake mínimo: notificar_evento() arma la query/payload correctos --
   rápido, sin red, corre siempre.
2. PostgreSQL real (conexiones propias con asyncpg.connect, NUNCA la
   fixture `db` de conftest.py): confirma que un NOTIFY real efectivamente
   llega a un LISTEN real -- se salta sin TEST_DATABASE_URL, igual que el
   resto de tests que necesitan Postgres real.

Por qué no usar la fixture `db` para el caso 2: `db` envuelve cada test en
una transacción que termina en ROLLBACK (conftest.py, aislamiento entre
tests) -- PostgreSQL solo entrega un NOTIFY cuando la transacción que lo
emitió hace COMMIT, así que un notificar_evento(db, ...) ahí NUNCA
llegaría a ningún LISTEN, sin importar que el código esté bien. Hace
falta una conexión real con autocommit para probar la entrega de verdad.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from core.events import canal_de_usuario, notificar_evento

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore


class _FakeNotifyConn:
    def __init__(self):
        self.llamadas: list[tuple[str, tuple]] = []

    async def execute(self, query: str, *args):
        self.llamadas.append((query, args))
        return "SELECT 1"


@pytest.mark.asyncio
async def test_notificar_evento_arma_pg_notify_con_canal_y_payload_json():
    conn = _FakeNotifyConn()
    await notificar_evento(conn, user_id="user-123", tipo="message.new", payload={"caso_id": "caso-abc"})

    assert len(conn.llamadas) == 1
    query, (canal, cuerpo) = conn.llamadas[0]
    assert "pg_notify" in query
    assert canal == canal_de_usuario("user-123")
    data = json.loads(cuerpo)
    assert data == {"type": "message.new", "caso_id": "caso-abc"}


@pytest.mark.asyncio
async def test_notificar_evento_sin_payload_solo_lleva_type():
    conn = _FakeNotifyConn()
    await notificar_evento(conn, user_id="user-456", tipo="pdf.ready")

    _, (_, cuerpo) = conn.llamadas[0]
    assert json.loads(cuerpo) == {"type": "pdf.ready"}


def test_canal_de_usuario_es_estable_y_distinto_por_usuario():
    assert canal_de_usuario("a") == canal_de_usuario("a")
    assert canal_de_usuario("a") != canal_de_usuario("b")


# ---------------------------------------------------------------------------
# PostgreSQL real: NOTIFY/LISTEN de punta a punta.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_real_llega_al_listener_real():
    if asyncpg is None:
        pytest.skip("asyncpg no instalado — ver requirements-test.txt")
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no configurado: se requiere PostgreSQL real")

    escucha = await asyncpg.connect(url)
    emisor = await asyncpg.connect(url)
    try:
        cola: asyncio.Queue[str] = asyncio.Queue()
        canal = canal_de_usuario("user-test-notify-real")

        def _callback(connection, pid, channel, payload):
            cola.put_nowait(payload)

        await escucha.add_listener(canal, _callback)

        await notificar_evento(emisor, user_id="user-test-notify-real", tipo="message.new", payload={"x": 1})

        payload = await asyncio.wait_for(cola.get(), timeout=5.0)
        assert json.loads(payload) == {"type": "message.new", "x": 1}

        await escucha.remove_listener(canal, _callback)
    finally:
        await escucha.close()
        await emisor.close()
