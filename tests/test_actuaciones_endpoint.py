"""
Vridik — tests/test_actuaciones_endpoint.py
Fase 2 (Copiloto Procesal): prueba api/actuaciones_endpoint.py +
core/actuaciones.py end-to-end (FastAPI TestClient) sobre un fake mínimo
de conexión asyncpg -- mismo estilo que tests/test_mensajes_endpoint.py.

Nunca se llama a Anthropic real: se monkeypatchea `clasificar_actuacion`
(la función de alto nivel que usa el endpoint), mismo patrón que
tests/test_case_documents.py monkeypatchea JuliXService -- no hace falta
fakear el SDK crudo para probar el endpoint HTTP en sí (eso ya lo prueba
tests/test_clasificador_actuaciones.py por separado).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.actuaciones_endpoint as actuaciones_module
from api.actuaciones_endpoint import router as actuaciones_router
from core.auth import create_jwt
from julix.errors import JuliXTimeoutError
from procesal.clasificador_actuaciones import ResultadoClasificacion


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeActuacionesDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.actuaciones: dict[str, dict] = {}
        self.user_events: list[dict] = []
        self.notificaciones: list[tuple[str, str]] = []
        self.auth_events: list[dict] = []

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "role": role, "despacho_id": despacho_id, "es_superadmin": False,
        }
        return self.users[user_id]

    def seed_caso(self, *, cliente_id: str, abogado_id: str | None = None, despacho_id: str = "despacho-1") -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "despacho_id": despacho_id,
            "titulo": "caso", "descripcion": None, "estado": "abierto", "created_at": _ahora(), "updated_at": _ahora(),
        }
        return self.casos[caso_id]

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("SELECT pg_notify"):
            canal, payload = args
            self.notificaciones.append((canal, payload))
        elif q.startswith("SELECT pg_advisory_xact_lock"):
            pass  # advisory lock real de la bitácora (Fase 3) -- no-op en el fake
        elif q.startswith("UPDATE auth_events SET hash_anterior"):
            hash_anterior, hash_actual, evento_id = args
            e = next((e for e in self.auth_events if e["id"] == evento_id), None)
            if e is not None:
                e["hash_anterior"] = hash_anterior
                e["hash_actual"] = hash_actual
        return "OK"

    async def fetchval(self, query: str, *args):
        q = query.strip()
        if q == "SELECT EXISTS(SELECT 1 FROM auth_events WHERE hash_actual IS NULL)":
            return any(e["hash_actual"] is None for e in self.auth_events)
        return False

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata, ip_address, user_agent, created_at, hash_anterior, hash_actual = args
            evento_id = len(self.auth_events) + 1
            evento = {
                "id": evento_id, "user_id": user_id, "actor_id": actor_id, "event_type": event_type,
                "metadata": metadata, "ip_address": ip_address, "user_agent": user_agent,
                "created_at": created_at, "hash_anterior": hash_anterior, "hash_actual": hash_actual,
            }
            self.auth_events.append(evento)
            return dict(evento)
        if q == "SELECT hash_actual FROM auth_events ORDER BY id DESC LIMIT 1":
            if not self.auth_events:
                return None
            return {"hash_actual": self.auth_events[-1]["hash_actual"]}
        if q.startswith("INSERT INTO user_events"):
            user_id, event_type, payload = args
            evento_id = len(self.user_events) + 1
            self.user_events.append({"id": evento_id, "user_id": user_id, "event_type": event_type})
            return {"id": evento_id}
        if "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.strip().startswith("INSERT INTO actuaciones"):
            caso_id, created_by, texto, categoria, confianza, texto_bruto = args
            actuacion_id = str(uuid.uuid4())
            actuacion = {
                "id": actuacion_id, "caso_id": caso_id, "created_by": created_by, "texto": texto,
                "categoria": categoria, "confianza": confianza, "texto_bruto_clasificacion": texto_bruto,
                "created_at": _ahora(),
            }
            self.actuaciones[actuacion_id] = actuacion
            return dict(actuacion)
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if q.startswith("SELECT") and "FROM actuaciones WHERE caso_id" in q:
            (caso_id,) = args
            filas = [a for a in self.actuaciones.values() if a["caso_id"] == caso_id]
            filas.sort(key=lambda a: a["created_at"], reverse=True)
            return [dict(f) for f in filas]
        return []


@pytest.fixture
def adb():
    return _FakeActuacionesDB()


@pytest.fixture
def aclient(adb):
    app = FastAPI()
    app.include_router(actuaciones_router)
    app.state.db_connection = adb
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fake_clasificador(monkeypatch):
    """Nunca se llama a Anthropic real -- se reemplaza clasificar_actuacion
    (la función de alto nivel que usa el endpoint) por un fake que siempre
    devuelve 'auto_admisorio', salvo que un test la vuelva a monkeypatchear
    con otra cosa (ver test de fallo de JuliX)."""
    async def _fake(client, *, texto_actuacion, user_id, caso_id=None, prompt_version=None):
        return ResultadoClasificacion(
            categoria="auto_admisorio", confianza=0.91,
            texto_bruto='{"categoria": "auto_admisorio", "confianza": 0.91}',
        )
    monkeypatch.setattr(actuaciones_module, "JuliXClient", lambda **kwargs: object())
    monkeypatch.setattr(actuaciones_module, "clasificar_actuacion", _fake)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_cliente_crea_y_lista_actuacion(adb, aclient):
    cliente = adb.seed_user(email="cliente1@vridik.local")
    caso = adb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = aclient.post(
        f"/casos/{caso['id']}/actuaciones",
        json={"texto": "Por medio del presente auto se admite la demanda..."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["categoria"] == "auto_admisorio"
    assert body["confianza"] == pytest.approx(0.91)
    assert body["created_by"] == cliente["id"]

    r = aclient.get(f"/casos/{caso['id']}/actuaciones", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_crear_actuacion_notifica_al_otro_participante(adb, aclient):
    cliente = adb.seed_user(email="cliente_notif@vridik.local")
    abogado = adb.seed_user(email="abogado_notif@vridik.local", role="abogado")
    caso = adb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(cliente)

    r = aclient.post(
        f"/casos/{caso['id']}/actuaciones", json={"texto": "texto de la actuación"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text

    assert len(adb.user_events) == 1
    evento = adb.user_events[0]
    assert evento["user_id"] == abogado["id"]  # nunca al propio autor
    assert evento["event_type"] == "actuacion.nueva"


def test_crear_actuacion_sin_abogado_asignado_no_notifica_a_nadie(adb, aclient):
    cliente = adb.seed_user(email="cliente_solo@vridik.local")
    caso = adb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    aclient.post(
        f"/casos/{caso['id']}/actuaciones", json={"texto": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert adb.user_events == []


def test_usuario_sin_relacion_al_caso_forbidden(adb, aclient):
    cliente = adb.seed_user(email="cliente_ajeno@vridik.local")
    otro = adb.seed_user(email="otro@vridik.local")
    caso = adb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = aclient.post(
        f"/casos/{caso['id']}/actuaciones", json={"texto": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_caso_inexistente_404(adb, aclient):
    cliente = adb.seed_user(email="cliente_404@vridik.local")
    token = _token_de(cliente)

    r = aclient.post(
        f"/casos/{uuid.uuid4()}/actuaciones", json={"texto": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_fallo_de_clasificacion_devuelve_502_y_no_persiste_nada(adb, aclient, monkeypatch):
    """Un timeout/rate-limit/etc. de JuliX (ver julix/errors.py) nunca se
    disfraza de éxito -- se propaga como 502 y la actuación no queda
    guardada a medias."""
    async def _fake_falla(client, *, texto_actuacion, user_id, caso_id=None, prompt_version=None):
        raise JuliXTimeoutError("timeout simulado")

    monkeypatch.setattr(actuaciones_module, "clasificar_actuacion", _fake_falla)

    cliente = adb.seed_user(email="cliente_falla@vridik.local")
    caso = adb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = aclient.post(
        f"/casos/{caso['id']}/actuaciones", json={"texto": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 502
    assert adb.actuaciones == {}
