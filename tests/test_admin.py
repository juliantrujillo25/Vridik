"""
Vridik — tests/test_admin.py (Sprint S2)
Prueba api/admin_endpoint.py end-to-end (FastAPI TestClient) sobre un fake
mínimo de conexión asyncpg — mismo estilo que tests/test_auth.py
(_FakeAuth2FADB) y tests/test_admin_users.py (FakeAdminDB): nunca PostgreSQL
real. Los tokens se emiten con core.auth.create_jwt, igual que S1 — el JWT
nunca lleva `role`; get_current_admin lo resuelve consultando `users.role`.
"""

from __future__ import annotations

import os
import uuid

# S2 importa core.auth (vía api.admin_endpoint) — mismo requisito que
# tests/test_auth.py: JWT_SECRET debe existir ANTES del import, no solo vía
# el autouse `_env_base` de conftest.py (que llega demasiado tarde).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_endpoint import router as admin_router
from core.auth import create_jwt


class _FakeAdminDB:
    """Fake mínimo de la tabla `users` de S1 + columna `role` (S2)."""

    def __init__(self):
        self.users: dict[str, dict] = {}

    def seed(self, *, email: str, role: str = "seller", is_active: bool = True) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "hashed_password": "x-hash",
            "role": role, "is_active": is_active, "created_at": "2026-01-01T00:00:00+00:00",
        }
        return self.users[user_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"], "email": u["email"], "role": u["role"]} if u else None
        if "SELECT id FROM users WHERE email" in query:
            (email,) = args
            return next(({"id": u["id"]} for u in self.users.values() if u["email"] == email), None)
        if "INSERT INTO users" in query and "RETURNING" in query:
            email, password_hash, role = args
            nuevo = self.seed(email=email, role=role)
            nuevo["hashed_password"] = password_hash
            return {k: nuevo[k] for k in ("id", "email", "role", "is_active", "created_at")}
        if "UPDATE users SET role" in query:
            user_id, new_role = args
            u = self.users.get(user_id)
            if u is None:
                return None
            u["role"] = new_role
            return {k: u[k] for k in ("id", "email", "role", "is_active", "created_at")}
        return None

    async def fetch(self, query: str, *args):
        if "SELECT id, email, role, is_active, created_at" in query and "FROM users" in query:
            skip, limit = args
            filas = sorted(self.users.values(), key=lambda u: u["created_at"], reverse=True)
            seleccion = filas[skip:skip + limit]
            return [{k: u[k] for k in ("id", "email", "role", "is_active", "created_at")} for u in seleccion]
        return []


@pytest.fixture
def admin_db():
    return _FakeAdminDB()


@pytest.fixture
def admin_client(admin_db):
    app = FastAPI()
    app.include_router(admin_router)
    app.state.db_connection = admin_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_admin_list_users_ok(admin_db, admin_client):
    admin = admin_db.seed(email="admin@vridik.local", role="admin")
    admin_db.seed(email="vendedor1@vridik.local", role="seller")
    token = _token_de(admin)

    r = admin_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert {"id", "email", "role", "is_active", "created_at"} <= set(body[0].keys())
    assert "hashed_password" not in body[0]


def test_admin_list_users_forbidden(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor2@vridik.local", role="seller")
    token = _token_de(seller)

    r = admin_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_create_user(admin_db, admin_client):
    admin = admin_db.seed(email="admin2@vridik.local", role="admin")
    token = _token_de(admin)

    r = admin_client.post(
        "/admin/users",
        json={"email": "nuevo_seller@vridik.local", "password": "Clave#Segura123", "role": "seller"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "nuevo_seller@vridik.local"
    assert body["role"] == "seller"
    assert "password" not in body
    assert "hashed_password" not in body


def test_admin_change_role(admin_db, admin_client):
    admin = admin_db.seed(email="admin3@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor3@vridik.local", role="seller")
    token = _token_de(admin)

    r = admin_client.patch(
        f"/admin/users/{seller['id']}/role",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"

    # Un admin no puede cambiarse el rol a sí mismo.
    r = admin_client.patch(
        f"/admin/users/{admin['id']}/role",
        json={"role": "seller"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
