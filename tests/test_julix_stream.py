"""
Vridik — tests/test_julix_stream.py (Sprint S11)
Prueba el endpoint SSE `GET /julix/stream` de api/julix_endpoint.py.

No se llama a Anthropic real: se monkeypatchea `api.julix_endpoint.get_service`
para devolver un servicio falso cuyo `generar_documento` es un generador
async controlado por el propio test — así se ejercita de verdad el
formateo de eventos SSE (`chunk`/`done`/`error`), el chequeo de
`request.is_disconnected()` y la autenticación JWT (header y query param),
sin depender de PostgreSQL ni del SDK de Anthropic.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import api.julix_endpoint as julix_endpoint_module
from api.julix_endpoint import app

JWT_SECRET_TEST = "vridik-test-sse-secret-nunca-usar-en-produccion"


@pytest.fixture(autouse=True)
def _jwt_secret_de_prueba(monkeypatch):
    """El módulo lee JWT_SECRET una sola vez al importarse (nivel de
    módulo) — se parchea directamente el atributo del módulo en vez de
    depender de la variable de entorno, que ya no surtiría efecto tras el
    import."""
    monkeypatch.setattr(julix_endpoint_module, "JWT_SECRET", JWT_SECRET_TEST)
    monkeypatch.setenv("JULIX_RATE_LIMIT_ENABLED", "false")
    julix_endpoint_module._rate_limit_buckets.clear()
    yield


def _token(sub: str = "user-sse-test") -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "role": "abogado", "iat": now, "exp": now + 900},
        JWT_SECRET_TEST,
        algorithm="HS256",
    )


class _FakeServiceOK:
    """Sustituye JuliXService: generar_documento produce 2 fragmentos y
    termina sin error, sin tocar Anthropic ni PostgreSQL."""

    async def generar_documento(self, **kwargs):
        for fragmento in ["Hola ", "Vridik"]:
            yield fragmento


class _FakeServiceError:
    """Simula que generar_documento truena a mitad de camino (p.ej. un
    JuliXError no domado en un chunk intermedio) — el endpoint debe emitir
    un evento `error` y cerrar el stream, nunca dejarlo colgado."""

    async def generar_documento(self, **kwargs):
        yield "Fragmento parcial"
        raise RuntimeError("fallo simulado de prueba")


@pytest.fixture
def client():
    return TestClient(app)


def test_julix_stream_sin_token_responde_401(client):
    resp = client.get(
        "/julix/stream",
        params={"tarea": "ugpp_demanda", "caso_id": "c1", "expediente_texto": "texto"},
    )
    assert resp.status_code == 401


def test_julix_stream_emite_chunks_y_done_via_header(client, monkeypatch):
    monkeypatch.setattr(julix_endpoint_module, "get_service", lambda request: _FakeServiceOK())

    resp = client.get(
        "/julix/stream",
        params={"tarea": "ugpp_demanda", "caso_id": "c1", "expediente_texto": "texto"},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert 'event: chunk\ndata: {"texto": "Hola "}' in body
    assert 'event: chunk\ndata: {"texto": "Vridik"}' in body
    assert body.strip().endswith('event: done\ndata: {}')


def test_julix_stream_acepta_token_como_query_param(client, monkeypatch):
    """EventSource del navegador no puede fijar headers propios — el token
    debe poder viajar como ?token=... y autenticar igual que el header."""
    monkeypatch.setattr(julix_endpoint_module, "get_service", lambda request: _FakeServiceOK())

    resp = client.get(
        "/julix/stream",
        params={
            "tarea": "ugpp_demanda",
            "caso_id": "c1",
            "expediente_texto": "texto",
            "token": _token(),
        },
    )
    assert resp.status_code == 200
    assert "event: chunk" in resp.text


def test_julix_stream_emite_evento_error_si_generar_documento_falla(client, monkeypatch):
    monkeypatch.setattr(julix_endpoint_module, "get_service", lambda request: _FakeServiceError())

    resp = client.get(
        "/julix/stream",
        params={"tarea": "ugpp_demanda", "caso_id": "c1", "expediente_texto": "texto"},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert 'event: chunk\ndata: {"texto": "Fragmento parcial"}' in body
    assert "event: error" in body
    assert "fallo simulado de prueba" in body
    # Un error a mitad de stream nunca debe además cerrar con "done".
    assert "event: done" not in body
