"""
Vridik — tests/test_events_endpoint.py
Cobertura de api/events_endpoint.py::_generador_sse -- el generador SSE en
sí, no solo core/events.py (que ya prueba NOTIFY/LISTEN por separado, ver
tests/test_events.py). Agregado junto con el límite de conexiones
concurrentes y el timeout de vida máxima del stream (incidente real de
pool de Postgres agotado, 2026-07-12, ver docstring del módulo): sin
esto, esas dos protecciones quedaban sin ningún test que las ejerza.
"""

from __future__ import annotations

import pytest

from api import events_endpoint as events_endpoint_module
from api.events_endpoint import _generador_sse


class _FakeConn:
    def __init__(self):
        self.listeners: list[tuple[str, object]] = []

    async def execute(self, query, *args):
        return "SELECT 1"

    async def add_listener(self, canal, callback):
        self.listeners.append((canal, callback))

    async def remove_listener(self, canal, callback):
        self.listeners.remove((canal, callback))


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn
        self.adquisiciones = 0
        self.liberaciones = 0

    async def acquire(self):
        self.adquisiciones += 1
        return self._conn

    async def release(self, conn):
        self.liberaciones += 1


class _FakeRequest:
    def __init__(self, desconectado: bool):
        self._desconectado = desconectado

    async def is_disconnected(self) -> bool:
        return self._desconectado


async def _agotar(gen) -> list[str]:
    return [chunk async for chunk in gen]


@pytest.fixture(autouse=True)
def _resetear_contador_global(monkeypatch):
    """El contador de conexiones SSE activas es un global del módulo --
    se resetea a 0 antes de cada test para que no arrastre estado de otro."""
    monkeypatch.setattr(events_endpoint_module, "_conexiones_sse_activas", 0)


@pytest.mark.asyncio
async def test_generador_sse_respeta_el_limite_de_conexiones_concurrentes(monkeypatch):
    monkeypatch.setattr(
        events_endpoint_module, "_conexiones_sse_activas", events_endpoint_module._MAX_CONEXIONES_SSE_CONCURRENTES,
    )
    conn = _FakeConn()
    pool = _FakePool(conn)
    request = _FakeRequest(desconectado=True)

    chunks = await _agotar(_generador_sse(pool, user_id="user-1", last_event_id=None, request=request))

    assert chunks == ["event: resync\ndata: {}\n\n"]
    assert pool.adquisiciones == 0  # nunca se tocó el pool -- se rechazó antes de acquire()


@pytest.mark.asyncio
async def test_generador_sse_bajo_el_limite_adquiere_y_libera_la_conexion():
    conn = _FakeConn()
    pool = _FakePool(conn)
    request = _FakeRequest(desconectado=True)  # desconectado en el primer chequeo -- termina rápido

    await _agotar(_generador_sse(pool, user_id="user-1", last_event_id=None, request=request))

    assert pool.adquisiciones == 1
    assert pool.liberaciones == 1
    assert conn.listeners == []  # remove_listener se llamó -- no quedó colgado
    assert events_endpoint_module._conexiones_sse_activas == 0


@pytest.mark.asyncio
async def test_generador_sse_no_deja_el_contador_arriba_tras_terminar():
    """Dos streams consecutivos no deben ir subiendo el contador -- cada
    uno decrementa al terminar (finally), así que el segundo ve el cupo
    libre otra vez."""
    conn = _FakeConn()
    pool = _FakePool(conn)

    await _agotar(_generador_sse(pool, user_id="user-1", last_event_id=None, request=_FakeRequest(True)))
    await _agotar(_generador_sse(pool, user_id="user-1", last_event_id=None, request=_FakeRequest(True)))

    assert pool.adquisiciones == 2
    assert pool.liberaciones == 2
    assert events_endpoint_module._conexiones_sse_activas == 0


@pytest.mark.asyncio
async def test_generador_sse_corta_por_vida_maxima_del_stream(monkeypatch):
    """Aunque el cliente nunca se desconecte, el stream se corta solo
    pasada la vida máxima -- acota el peor caso de una conexión que por lo
    que sea nunca dispara request.is_disconnected()."""
    monkeypatch.setattr(events_endpoint_module, "_VIDA_MAXIMA_STREAM_SEGUNDOS", -1)
    conn = _FakeConn()
    pool = _FakePool(conn)
    request = _FakeRequest(desconectado=False)  # nunca desconectado -- solo la vida máxima puede cortar

    await _agotar(_generador_sse(pool, user_id="user-1", last_event_id=None, request=request))

    assert pool.liberaciones == 1  # se cortó y liberó, no quedó colgado para siempre
