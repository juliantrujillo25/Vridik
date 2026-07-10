"""
Vridik — tests/test_casos.py
Prueba api/casos_endpoint.py end-to-end (FastAPI TestClient) sobre un fake
mínimo de conexión asyncpg — entidad `casos` (core/case.py), independiente
del marketplace (ver Instrucciones - CLAUDE.md, "Consolidación de
producto").
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.casos_endpoint import router as casos_router
from core.auth import create_jwt


class _FakeCasosDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "cliente") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if q.startswith("INSERT INTO casos"):
            cliente_id, abogado_id, titulo, descripcion = args
            caso_id = str(uuid.uuid4())
            caso = {
                "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "titulo": titulo,
                "descripcion": descripcion, "estado": "abierto",
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.casos[caso_id] = caso
            return dict(caso)
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.startswith("UPDATE casos SET abogado_id"):
            caso_id, abogado_id = args
            c = self.casos.get(caso_id)
            if c is None:
                return None
            c["abogado_id"] = abogado_id
            return dict(c)
        if q.startswith("UPDATE casos SET estado"):
            caso_id, estado = args
            c = self.casos.get(caso_id)
            if c is None:
                return None
            c["estado"] = estado
            return dict(c)
        return None

    async def fetch(self, query: str, *args):
        if "FROM casos" in query and "cliente_id = $1 OR abogado_id = $1" in query:
            user_id, skip, limit = args
            filas = [c for c in self.casos.values() if c["cliente_id"] == user_id or c["abogado_id"] == user_id]
            filas.sort(key=lambda c: c["created_at"], reverse=True)
            return [dict(c) for c in filas[skip:skip + limit]]
        if "FROM casos" in query and "ORDER BY created_at DESC OFFSET" in query:
            skip, limit = args
            filas = sorted(self.casos.values(), key=lambda c: c["created_at"], reverse=True)
            return [dict(c) for c in filas[skip:skip + limit]]
        return []


@pytest.fixture
def casos_db():
    return _FakeCasosDB()


@pytest.fixture
def casos_client(casos_db):
    app = FastAPI()
    app.include_router(casos_router)
    app.state.db_connection = casos_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_cliente_crea_caso_para_si_mismo(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente1@vridik.local")
    token = _token_de(cliente)

    r = casos_client.post(
        "/casos", json={"titulo": "Requerimiento UGPP 2024"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cliente_id"] == cliente["id"]
    assert body["abogado_id"] is None
    assert body["estado"] == "abierto"


def test_cliente_no_puede_crear_caso_para_otro(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente2@vridik.local")
    otro = casos_db.seed_user(email="otro2@vridik.local")
    token = _token_de(cliente)

    r = casos_client.post(
        "/casos", json={"titulo": "x", "cliente_id": otro["id"]}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_puede_crear_caso_para_otro_cliente(casos_db, casos_client):
    admin = casos_db.seed_user(email="admin3@vridik.local", role="admin")
    cliente = casos_db.seed_user(email="cliente3@vridik.local")
    token = _token_de(admin)

    r = casos_client.post(
        "/casos", json={"titulo": "x", "cliente_id": cliente["id"]}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["cliente_id"] == cliente["id"]


def test_listar_casos_solo_los_propios(casos_db, casos_client):
    cliente1 = casos_db.seed_user(email="cliente4@vridik.local")
    cliente2 = casos_db.seed_user(email="cliente5@vridik.local")
    token1 = _token_de(cliente1)

    casos_client.post("/casos", json={"titulo": "mio"}, headers={"Authorization": f"Bearer {token1}"})
    casos_client.post(
        "/casos", json={"titulo": "ajeno"},
        headers={"Authorization": f"Bearer {_token_de(cliente2)}"},
    )

    r = casos_client.get("/casos", headers={"Authorization": f"Bearer {token1}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["titulo"] == "mio"


def test_admin_ve_todos_los_casos(casos_db, casos_client):
    admin = casos_db.seed_user(email="admin6@vridik.local", role="admin")
    cliente = casos_db.seed_user(email="cliente6@vridik.local")
    casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    )

    r = casos_client.get("/casos", headers={"Authorization": f"Bearer {_token_de(admin)}"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_abogado_asignado_puede_ver_detalle(casos_db, casos_client):
    admin = casos_db.seed_user(email="admin7@vridik.local", role="admin")
    cliente = casos_db.seed_user(email="cliente7@vridik.local")
    abogado = casos_db.seed_user(email="abogado7@vridik.local", role="abogado")

    caso = casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    ).json()

    r = casos_client.patch(
        f"/casos/{caso['id']}/abogado", json={"abogado_id": abogado["id"]},
        headers={"Authorization": f"Bearer {_token_de(admin)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["abogado_id"] == abogado["id"]

    r_detalle = casos_client.get(f"/casos/{caso['id']}", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r_detalle.status_code == 200


def test_no_admin_no_puede_asignar_abogado(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente8@vridik.local")
    abogado = casos_db.seed_user(email="abogado8@vridik.local", role="abogado")
    caso = casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    ).json()

    r = casos_client.patch(
        f"/casos/{caso['id']}/abogado", json={"abogado_id": abogado["id"]},
        headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    )
    assert r.status_code == 403


def test_cliente_puede_cambiar_estado_de_su_caso(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente9@vridik.local")
    caso = casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    ).json()

    r = casos_client.patch(
        f"/casos/{caso['id']}/estado", json={"estado": "en_progreso"},
        headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "en_progreso"


def test_estado_invalido_rechazado(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente10@vridik.local")
    caso = casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    ).json()

    r = casos_client.patch(
        f"/casos/{caso['id']}/estado", json={"estado": "no-existe"},
        headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    )
    assert r.status_code == 422


def test_usuario_sin_relacion_no_puede_ver_caso(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente11@vridik.local")
    otro = casos_db.seed_user(email="otro11@vridik.local")
    caso = casos_client.post(
        "/casos", json={"titulo": "caso"}, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    ).json()

    r = casos_client.get(f"/casos/{caso['id']}", headers={"Authorization": f"Bearer {_token_de(otro)}"})
    assert r.status_code == 403


def test_caso_inexistente_404(casos_db, casos_client):
    cliente = casos_db.seed_user(email="cliente12@vridik.local")
    r = casos_client.get(f"/casos/{uuid.uuid4()}", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 404
