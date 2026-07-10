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
    """Fake mínimo de la tabla `users` de S1 + columna `role` (S2), más
    user_credentials/refresh_tokens/auth_events (S2-GAP-01, Fase A/B)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.user_credentials: dict[str, dict] = {}
        self.refresh_tokens: dict[str, dict] = {}
        self.auth_events: list[dict] = []

    def seed(self, *, email: str, role: str = "seller", is_active: bool = True) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "hashed_password": "x-hash",
            "role": role, "is_active": is_active, "created_at": "2026-01-01T00:00:00+00:00",
            "deleted_at": None, "must_change": False,
        }
        return self.users[user_id]

    def seed_refresh_token(self, *, user_id: str) -> str:
        rid = str(uuid.uuid4())
        self.refresh_tokens[rid] = {"id": rid, "user_id": user_id, "revoked_at": None}
        return rid

    def seed_evento(self, *, user_id: str, event_type: str, created_at: str) -> None:
        self.auth_events.append({"user_id": user_id, "event_type": event_type, "created_at": created_at})

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO user_credentials"):
            user_id, password_hash, *_resto = args
            self.user_credentials[user_id] = {"user_id": user_id, "password_hash": password_hash}
        elif q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata = args
            self.auth_events.append(
                {"user_id": user_id, "actor_id": actor_id, "event_type": event_type, "metadata": metadata},
            )
        elif q.startswith("UPDATE users SET hashed_password"):
            user_id, password_hash = args
            self.users[user_id]["hashed_password"] = password_hash
            self.users[user_id]["must_change"] = True
        elif "UPDATE refresh_tokens" in q and "WHERE user_id" in q:
            user_id, _motivo = args
            for r in self.refresh_tokens.values():
                if r["user_id"] == user_id and r["revoked_at"] is None:
                    r["revoked_at"] = "now"
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"], "email": u["email"], "role": u["role"]} if u else None
        if "SELECT id FROM users WHERE email" in q:
            (email,) = args
            return next(({"id": u["id"]} for u in self.users.values() if u["email"] == email), None)
        if "SELECT id FROM users WHERE id" in q and "deleted_at IS NULL" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"]} if u and u["deleted_at"] is None else None
        if "INSERT INTO users" in q and "RETURNING" in q:
            email, password_hash, role = args
            nuevo = self.seed(email=email, role=role)
            nuevo["hashed_password"] = password_hash
            return {k: nuevo[k] for k in ("id", "email", "role", "is_active", "created_at")}
        if "UPDATE users SET role" in q:
            user_id, new_role = args
            u = self.users.get(user_id)
            if u is None:
                return None
            u["role"] = new_role
            return {k: u[k] for k in ("id", "email", "role", "is_active", "created_at")}
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role, is_active, created_at" in q and "FROM users" in q:
            skip, limit = args
            filas = sorted(self.users.values(), key=lambda u: u["created_at"], reverse=True)
            seleccion = filas[skip:skip + limit]
            return [{k: u[k] for k in ("id", "email", "role", "is_active", "created_at")} for u in seleccion]
        if q.startswith("SELECT id, event_type, metadata, ip_address, user_agent, created_at"):
            user_id, limite = args
            eventos = [e for e in self.auth_events if e.get("user_id") == user_id]
            eventos.sort(key=lambda e: e["created_at"], reverse=True)
            return [dict(e) for e in eventos[:limite]]
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


def test_admin_get_user_actividad(admin_db, admin_client):
    admin = admin_db.seed(email="admin4@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor4@vridik.local", role="seller")
    admin_db.seed_evento(user_id=seller["id"], event_type="login_success", created_at="2026-01-02T00:00:00+00:00")
    admin_db.seed_evento(user_id=seller["id"], event_type="login_failed", created_at="2026-01-01T00:00:00+00:00")
    token = _token_de(admin)

    r = admin_client.get(f"/admin/users/{seller['id']}/actividad", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert body[0]["event_type"] == "login_success"  # más reciente primero


def test_admin_get_user_actividad_forbidden_para_no_admin(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor5@vridik.local", role="seller")
    token = _token_de(seller)

    r = admin_client.get(f"/admin/users/{seller['id']}/actividad", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_reset_password_genera_temporal_y_revoca_sesiones(admin_db, admin_client):
    admin = admin_db.seed(email="admin5@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor6@vridik.local", role="seller")
    refresh_id = admin_db.seed_refresh_token(user_id=seller["id"])
    token = _token_de(admin)

    r = admin_client.post(f"/admin/users/{seller['id']}/reset-password", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == seller["id"]
    assert len(body["password_temporal"]) > 0

    # El reset debe afectar la contraseña real que usa /auth/login
    # (users.hashed_password), no solo la tabla user_credentials.
    assert admin_db.users[seller["id"]]["hashed_password"] != "x-hash"
    assert admin_db.users[seller["id"]]["must_change"] is True
    assert admin_db.refresh_tokens[refresh_id]["revoked_at"] is not None
    assert any(e.get("event_type") == "password_reset" for e in admin_db.auth_events)


def test_admin_reset_password_usuario_inexistente_404(admin_db, admin_client):
    admin = admin_db.seed(email="admin6@vridik.local", role="admin")
    token = _token_de(admin)

    r = admin_client.post(
        f"/admin/users/{uuid.uuid4()}/reset-password", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
