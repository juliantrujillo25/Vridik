"""
Vridik — tests/test_auth_me.py
GET /auth/me: perfil mínimo del usuario autenticado (agregado para que el
frontend pueda saber si el usuario ya tiene 2FA activado antes de ofrecerle
"activar 2FA" -- ver el docstring del endpoint en api/auth_endpoint.py).
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_endpoint import router as auth_router
from core.auth import create_jwt


class _FakeMeDB:
    def __init__(self):
        self.users: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "cliente", totp_enabled: bool = False) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role, "totp_enabled": totp_enabled}
        return self.users[user_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q == "SELECT id, email, role, totp_enabled FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        return None


@pytest.fixture
def db():
    return _FakeMeDB()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(auth_router)
    app.state.db_connection = db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_me_devuelve_perfil_con_totp_enabled_false(db, client):
    user = db.seed_user(email="cliente@vridik.local", role="cliente", totp_enabled=False)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {_token_de(user)}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == user["id"]
    assert body["email"] == "cliente@vridik.local"
    assert body["role"] == "cliente"
    assert body["totp_enabled"] is False


def test_me_refleja_totp_enabled_true(db, client):
    user = db.seed_user(email="admin@vridik.local", role="admin", totp_enabled=True)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {_token_de(user)}"})
    assert r.status_code == 200, r.text
    assert r.json()["totp_enabled"] is True


def test_me_sin_token_da_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_con_token_de_usuario_borrado_da_401(db, client):
    """El id del token ya no existe en users (p.ej. cuenta eliminada) --
    nunca debe devolver un perfil vacío ni un 500."""
    fantasma = {"id": str(uuid.uuid4()), "email": "fantasma@vridik.local"}
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {_token_de(fantasma)}"})
    assert r.status_code == 401
