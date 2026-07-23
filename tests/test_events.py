"""
Vridik — tests/test_events.py
Roadmap Semana 11: prueba core/events.py en dos capas.

1. Fake mínimo: notificar_evento()/existe_evento()/listar_eventos_desde()
   arman las queries/payloads correctos -- rápido, sin red, corre siempre.
2. PostgreSQL real (conexiones propias con asyncpg.connect, NUNCA la
   fixture `db` de conftest.py): confirma que un NOTIFY real efectivamente
   llega a un LISTEN real, y que el buffer user_events (Fase C) persiste y
   se puede leer de vuelta -- se salta sin TEST_DATABASE_URL, igual que el
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
import uuid

import pytest

from core.events import canal_de_usuario, existe_evento, listar_eventos_desde, notificar_evento

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore


class _FakeNotifyConn:
    def __init__(self):
        self.llamadas: list[tuple[str, tuple]] = []
        self.user_events: list[dict] = []

    async def execute(self, query: str, *args):
        self.llamadas.append((query, args))
        return "SELECT 1"

    async def fetchrow(self, query: str, *args):
        self.llamadas.append((query, args))
        if query.strip().startswith("INSERT INTO user_events"):
            user_id, event_type, payload = args
            evento_id = len(self.user_events) + 1
            self.user_events.append({"id": evento_id, "user_id": user_id, "event_type": event_type, "payload": payload})
            return {"id": evento_id}
        return None


@pytest.mark.asyncio
async def test_notificar_evento_arma_pg_notify_con_canal_id_y_payload_json():
    conn = _FakeNotifyConn()
    evento_id = await notificar_evento(conn, user_id="user-123", tipo="message.new", payload={"caso_id": "caso-abc"})

    assert evento_id == 1
    llamadas_notify = [c for c in conn.llamadas if "pg_notify" in c[0]]
    assert len(llamadas_notify) == 1
    _, (canal, cuerpo) = llamadas_notify[0]
    assert canal == canal_de_usuario("user-123")
    data = json.loads(cuerpo)
    assert data == {"id": 1, "type": "message.new", "caso_id": "caso-abc"}


@pytest.mark.asyncio
async def test_notificar_evento_sin_payload_solo_lleva_id_y_type():
    conn = _FakeNotifyConn()
    await notificar_evento(conn, user_id="user-456", tipo="pdf.ready")

    _, (_, cuerpo) = [c for c in conn.llamadas if "pg_notify" in c[0]][0]
    data = json.loads(cuerpo)
    assert data["type"] == "pdf.ready"
    assert "id" in data


@pytest.mark.asyncio
async def test_notificar_evento_acepta_uuid_reales_en_el_payload():
    """Bug real encontrado en producción (verificación de analítica UGPP,
    16-jul-2026): asyncpg devuelve `uuid.UUID` de verdad para columnas UUID
    (no str) -- api/actuaciones_endpoint.py pasa actuacion["id"] tal cual
    en el payload, y json.dumps() sin default=str reventaba con
    "Object of type UUID is not JSON serializable", rompiendo POST
    /casos/{id}/actuaciones con 500 cada vez que había un destinatario."""
    conn = _FakeNotifyConn()
    actuacion_id = uuid.uuid4()

    evento_id = await notificar_evento(
        conn, user_id="user-uuid", tipo="actuacion.nueva",
        payload={"caso_id": "caso-abc", "actuacion_id": actuacion_id},
    )

    assert evento_id == 1
    _, (_, cuerpo) = [c for c in conn.llamadas if "pg_notify" in c[0]][0]
    data = json.loads(cuerpo)
    assert data["actuacion_id"] == str(actuacion_id)


@pytest.mark.asyncio
async def test_notificar_evento_purga_el_buffer_vencido():
    conn = _FakeNotifyConn()
    await notificar_evento(conn, user_id="user-789", tipo="message.new")

    llamadas_delete = [c for c in conn.llamadas if c[0].strip().startswith("DELETE FROM user_events")]
    assert len(llamadas_delete) == 1
    assert "24" in llamadas_delete[0][0]


def test_canal_de_usuario_es_estable_y_distinto_por_usuario():
    assert canal_de_usuario("a") == canal_de_usuario("a")
    assert canal_de_usuario("a") != canal_de_usuario("b")


# ---------------------------------------------------------------------------
# PostgreSQL real: NOTIFY/LISTEN de punta a punta + buffer de reconexión.
# ---------------------------------------------------------------------------
def _requiere_postgres_real() -> str:
    if asyncpg is None:
        pytest.skip("asyncpg no instalado — ver requirements-test.txt")
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no configurado: se requiere PostgreSQL real")
    return url


@pytest.mark.asyncio
async def test_notify_real_llega_al_listener_real():
    url = _requiere_postgres_real()

    escucha = await asyncpg.connect(url)
    emisor = await asyncpg.connect(url)
    user_id = "11111111-1111-1111-1111-111111111111"
    try:
        await emisor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_events (
                id BIGSERIAL PRIMARY KEY, user_id UUID NOT NULL, event_type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cola: asyncio.Queue[str] = asyncio.Queue()
        canal = canal_de_usuario(user_id)

        def _callback(connection, pid, channel, payload):
            cola.put_nowait(payload)

        await escucha.add_listener(canal, _callback)

        evento_id = await notificar_evento(
            emisor, user_id=user_id, tipo="message.new", payload={"x": 1},
        )

        payload = await asyncio.wait_for(cola.get(), timeout=5.0)
        assert json.loads(payload) == {"id": evento_id, "type": "message.new", "x": 1}

        await escucha.remove_listener(canal, _callback)
    finally:
        # Este user_id no corresponde a ningún usuario real -- sin este
        # cleanup, la fila queda COMMITEADA en la base de test para
        # siempre (esta conexión nunca pasa por el rollback de la fixture
        # `db`), y core.rls.ensure_rls_policies_soporte() la detecta como
        # "pendiente" (user_id que no resuelve a un usuario con
        # despacho_id) en cualquier test posterior de la misma sesión,
        # salteando FORCE ROW LEVEL SECURITY en user_events para el resto
        # de la corrida (ver tests/test_rls_soporte.py).
        await emisor.execute("DELETE FROM user_events WHERE user_id = $1", user_id)
        await escucha.close()
        await emisor.close()


@pytest.mark.asyncio
async def test_reconexion_real_replay_y_resync():
    url = _requiere_postgres_real()
    user_id = "22222222-2222-2222-2222-222222222222"

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_events (
                id BIGSERIAL PRIMARY KEY, user_id UUID NOT NULL, event_type TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        primero = await notificar_evento(conn, user_id=user_id, tipo="message.new", payload={"n": 1})
        segundo = await notificar_evento(conn, user_id=user_id, tipo="message.new", payload={"n": 2})

        # Replay: reconectando desde "primero", debe traer solo "segundo".
        assert await existe_evento(conn, user_id=user_id, evento_id=primero) is True
        pendientes = await listar_eventos_desde(conn, user_id=user_id, desde_id=primero)
        assert [p["id"] for p in pendientes] == [segundo]

        # Resync: un id que nunca existió para este usuario.
        assert await existe_evento(conn, user_id=user_id, evento_id=999_999_999) is False
    finally:
        await conn.execute("DELETE FROM user_events WHERE user_id = $1", user_id)
        await conn.close()
