"""
Vridik — tests/test_auth_refresh.py (Fase B, S1-GAP-01)
Prueba el flujo de refresh tokens de api/auth_endpoint.py (core/
refresh_tokens.py) end-to-end (FastAPI TestClient) sobre un fake mínimo de
conexión asyncpg que modela users/user_credentials/refresh_tokens/
auth_events -- mismo estilo que el resto de tests/test_*.py.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_endpoint import router as auth_router


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class _FakeAuthRefreshDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.user_credentials: dict[str, dict] = {}
        self.refresh_tokens: dict[str, dict] = {}
        self.auth_events: list[dict] = []

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO user_credentials"):
            user_id, password_hash = args
            self.user_credentials[user_id] = {"user_id": user_id, "password_hash": password_hash}
        elif q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata = args
            self.auth_events.append(
                {"user_id": user_id, "actor_id": actor_id, "event_type": event_type, "metadata": metadata},
            )
        elif "INSERT INTO refresh_tokens" in q:
            user_id, token_hash, family_id, expires_at = args
            rid = str(uuid.uuid4())
            self.refresh_tokens[rid] = {
                "id": rid, "user_id": user_id, "token_hash": token_hash, "family_id": family_id,
                "replaced_by_id": None, "expires_at": expires_at, "used_at": None,
                "revoked_at": None, "revoked_reason": None,
            }
        elif "UPDATE refresh_tokens SET used_at = now(), replaced_by_id" in q:
            replaced_by_id, rid = args
            self.refresh_tokens[rid]["used_at"] = datetime.now(timezone.utc)
            self.refresh_tokens[rid]["replaced_by_id"] = replaced_by_id
        elif "revoked_reason = 'reuse_detected'" in q:
            (family_id,) = args
            for r in self.refresh_tokens.values():
                if r["family_id"] == family_id and r["revoked_at"] is None:
                    r["revoked_at"] = datetime.now(timezone.utc)
                    r["revoked_reason"] = "reuse_detected"
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "INSERT INTO users" in q and "RETURNING id" in q:
            email, password_hash = args
            user_id = str(uuid.uuid4())
            self.users[user_id] = {
                "id": user_id, "email": email, "hashed_password": password_hash,
                "is_active": True, "totp_enabled": False,
            }
            return {"id": user_id}
        if "LEFT JOIN user_credentials" in q and "WHERE u.email" in q:
            (email,) = args
            u = next((u for u in self.users.values() if u["email"] == email), None)
            if u is None:
                return None
            creds = self.user_credentials.get(u["id"])
            return {
                "id": u["id"], "is_active": u["is_active"], "totp_enabled": u["totp_enabled"],
                "hashed_password": creds["password_hash"] if creds else None,
            }
        if "SELECT id FROM users WHERE email" in q:
            (email,) = args
            return next(({"id": u["id"]} for u in self.users.values() if u["email"] == email), None)
        if "SELECT email FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"email": u["email"]} if u else None
        if "SELECT id, user_id, family_id, used_at, revoked_at, expires_at" in q and "FROM refresh_tokens WHERE token_hash" in q:
            (token_hash,) = args
            return next(({k: v for k, v in r.items() if k != "replaced_by_id"}
                         for r in self.refresh_tokens.values() if r["token_hash"] == token_hash), None)
        if q.startswith("SELECT id FROM refresh_tokens WHERE token_hash"):
            (token_hash,) = args
            return next(({"id": r["id"]} for r in self.refresh_tokens.values() if r["token_hash"] == token_hash), None)
        if "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = $2" in q and "RETURNING user_id" in q:
            token_hash, motivo = args
            for r in self.refresh_tokens.values():
                if r["token_hash"] == token_hash and r["revoked_at"] is None:
                    r["revoked_at"] = datetime.now(timezone.utc)
                    r["revoked_reason"] = motivo
                    return {"user_id": r["user_id"]}
            return None
        return None


@pytest.fixture
def db():
    return _FakeAuthRefreshDB()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(auth_router)
    app.state.db_connection = db
    return TestClient(app)


def test_register_emite_access_y_refresh_token(db, client):
    r = client.post("/auth/register", json={"email": "nueva@vridik.local", "password": "ClaveSegura123"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "access_token" in body and "refresh_token" in body

    user_id = next(iter(db.users))
    assert user_id in db.user_credentials
    assert any(e["event_type"] == "user_created" for e in db.auth_events)


def test_login_emite_refresh_token_y_registra_evento(db, client):
    client.post("/auth/register", json={"email": "login1@vridik.local", "password": "ClaveSegura123"})
    r = client.post("/auth/login", json={"email": "login1@vridik.local", "password": "ClaveSegura123"})
    assert r.status_code == 200, r.text
    assert "refresh_token" in r.json()
    assert any(e["event_type"] == "login_success" for e in db.auth_events)


def test_login_fallido_registra_evento(db, client):
    client.post("/auth/register", json={"email": "login2@vridik.local", "password": "ClaveSegura123"})
    r = client.post("/auth/login", json={"email": "login2@vridik.local", "password": "incorrecta"})
    assert r.status_code == 401
    assert any(e["event_type"] == "login_failed" for e in db.auth_events)


def test_refresh_rota_el_token_y_emite_access_token_nuevo(db, client):
    reg = client.post("/auth/register", json={"email": "refresh1@vridik.local", "password": "ClaveSegura123"}).json()
    r = client.post("/auth/refresh", json={"refresh_token": reg["refresh_token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] != reg["refresh_token"]  # token nuevo, no el mismo
    assert any(e["event_type"] == "token_refresh" for e in db.auth_events)


def test_refresh_token_invalido_devuelve_401(client):
    r = client.post("/auth/refresh", json={"refresh_token": "esto-no-existe"})
    assert r.status_code == 401


def test_reuso_de_refresh_token_revoca_toda_la_familia(db, client):
    reg = client.post("/auth/register", json={"email": "reuso@vridik.local", "password": "ClaveSegura123"}).json()
    original = reg["refresh_token"]

    # Simular que ya pasó la ventana de gracia de 10s antes del reuso, para
    # que el segundo uso del token original se trate como robo real.
    original_hash = _hash(original)
    for r in db.refresh_tokens.values():
        if r["token_hash"] == original_hash:
            r["used_at"] = datetime.now(timezone.utc) - timedelta(seconds=60)

    r = client.post("/auth/refresh", json={"refresh_token": original})
    assert r.status_code == 401, r.text
    assert any(e["event_type"] == "refresh_reuse_detected" for e in db.auth_events)
    # Toda la familia queda revocada -- incluso el token que se emitió en la
    # primera rotación (antes de simular el reuso) ya no debe servir.
    assert all(
        r["revoked_at"] is not None for r in db.refresh_tokens.values()
    ), "todos los tokens de la familia deben quedar revocados"


def test_reuso_dentro_de_la_ventana_de_gracia_no_revoca(db, client):
    """Carrera de dos pestañas: reusar el token original a los pocos
    segundos (dentro de los 10s de gracia) no debe tratarse como ataque."""
    reg = client.post("/auth/register", json={"email": "gracia@vridik.local", "password": "ClaveSegura123"}).json()
    original = reg["refresh_token"]

    r1 = client.post("/auth/refresh", json={"refresh_token": original})
    assert r1.status_code == 200

    r2 = client.post("/auth/refresh", json={"refresh_token": original})
    assert r2.status_code == 200, r2.text
    assert not any(e["event_type"] == "refresh_reuse_detected" for e in db.auth_events)


def test_logout_revoca_el_refresh_token(db, client):
    reg = client.post("/auth/register", json={"email": "logout1@vridik.local", "password": "ClaveSegura123"}).json()

    r = client.post("/auth/logout", json={"refresh_token": reg["refresh_token"]})
    assert r.status_code == 204

    r = client.post("/auth/refresh", json={"refresh_token": reg["refresh_token"]})
    assert r.status_code == 401, "un refresh token revocado por logout no debe poder rotar"
    assert any(e["event_type"] == "logout" for e in db.auth_events)


def test_logout_es_idempotente(client):
    r = client.post("/auth/logout", json={"refresh_token": "no-existe"})
    assert r.status_code == 204
