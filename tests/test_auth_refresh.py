"""
Vridik — tests/test_auth_refresh.py (Fase B, S1-GAP-01)
Prueba el flujo de refresh tokens de api/auth_endpoint.py (core/
refresh_tokens.py) end-to-end (FastAPI TestClient) sobre un fake mínimo de
conexión asyncpg que modela users/user_credentials/refresh_tokens/
auth_events -- mismo estilo que el resto de tests/test_*.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from core.rate_limit import MAX_FALLOS_LOGIN

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
        elif q.startswith("UPDATE users SET hashed_password"):
            user_id, password_hash = args
            self.users[user_id]["hashed_password"] = password_hash
        elif "UPDATE refresh_tokens SET revoked_at = now(), revoked_reason = $2" in q and "WHERE user_id = $1" in q:
            user_id, motivo = args
            for r in self.refresh_tokens.values():
                if r["user_id"] == user_id and r["revoked_at"] is None:
                    r["revoked_at"] = datetime.now(timezone.utc)
                    r["revoked_reason"] = motivo
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
        if "LEFT JOIN user_credentials" in q and "WHERE u.id = $1" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            if u is None:
                return None
            creds = self.user_credentials.get(user_id)
            return {"id": u["id"], "hashed_password": creds["password_hash"] if creds else None}
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

    async def fetchval(self, query: str, *args):
        """Cuenta eventos 'login_failed' para core/rate_limit.py — no
        implementa la ventana de VENTANA_MINUTOS (los tests corren en
        milisegundos, siempre caen adentro) ni el `IS NOT DISTINCT FROM`
        de Postgres para ip_address (acá alcanza con == de Python, None
        incluido)."""
        q = query.strip()
        if "auth_events" in q and "event_type = 'login_failed'" in q and "metadata->>'email'" in q:
            email, ip_address, _ventana = args
            return sum(
                1 for e in self.auth_events
                if e["event_type"] == "login_failed"
                and json.loads(e["metadata"]).get("email") == email
                and e["ip_address"] == ip_address
                and json.loads(e["metadata"]).get("paso") != "2fa"
            )
        if "auth_events" in q and "event_type = 'login_failed'" in q and "metadata->>'paso' = '2fa'" in q:
            user_id, _ventana = args
            return sum(
                1 for e in self.auth_events
                if e["event_type"] == "login_failed"
                and e["user_id"] == user_id
                and json.loads(e["metadata"]).get("paso") == "2fa"
            )
        return 0


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


def test_login_bloqueado_tras_MAX_FALLOS_LOGIN_intentos(db, client):
    """Roadmap Semana 12-13: 10 fallos de contraseña en 15 min para el mismo
    email+IP bloquean el siguiente intento con 429 -- incluso si ese
    siguiente intento trae la contraseña correcta (el bloqueo es previo a
    verificarla)."""
    email = "login3@vridik.local"
    password = "ClaveSegura123"
    client.post("/auth/register", json={"email": email, "password": password})

    for _ in range(MAX_FALLOS_LOGIN):
        r = client.post("/auth/login", json={"email": email, "password": "incorrecta"})
        assert r.status_code == 401

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 429, r.text


def test_login_email_distinto_no_comparte_el_limite(db, client):
    """El límite es por email+IP -- fallar 10 veces con un email no debe
    bloquear el login (correcto) de otro email desde la misma IP."""
    client.post("/auth/register", json={"email": "login4a@vridik.local", "password": "ClaveSegura123"})
    client.post("/auth/register", json={"email": "login4b@vridik.local", "password": "ClaveSegura123"})

    for _ in range(MAX_FALLOS_LOGIN):
        client.post("/auth/login", json={"email": "login4a@vridik.local", "password": "incorrecta"})

    r = client.post("/auth/login", json={"email": "login4b@vridik.local", "password": "ClaveSegura123"})
    assert r.status_code == 200, r.text


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


# ---------------------------------------------------------------------------
# Self-service: POST /auth/password (distinto de POST /admin/users/{id}/
# reset-password, que es un admin reseteando la de OTRO usuario).
# ---------------------------------------------------------------------------
def test_cambiar_password_ok_y_permite_login_con_la_nueva(db, client):
    reg = client.post("/auth/register", json={"email": "cambio1@vridik.local", "password": "ClaveVieja123"}).json()
    token = reg["access_token"]

    r = client.post(
        "/auth/password",
        json={"password_actual": "ClaveVieja123", "password_nueva": "ClaveNueva456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # La vieja ya no sirve, la nueva sí.
    r_vieja = client.post("/auth/login", json={"email": "cambio1@vridik.local", "password": "ClaveVieja123"})
    assert r_vieja.status_code == 401

    r_nueva = client.post("/auth/login", json={"email": "cambio1@vridik.local", "password": "ClaveNueva456"})
    assert r_nueva.status_code == 200, r_nueva.text

    assert any(e["event_type"] == "password_changed" for e in db.auth_events)


def test_cambiar_password_actual_incorrecta_rechazado(db, client):
    reg = client.post("/auth/register", json={"email": "cambio2@vridik.local", "password": "ClaveVieja123"}).json()
    token = reg["access_token"]

    r = client.post(
        "/auth/password",
        json={"password_actual": "esto-no-es", "password_nueva": "ClaveNueva456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401

    # No cambió nada -- la vieja sigue sirviendo.
    r_vieja = client.post("/auth/login", json={"email": "cambio2@vridik.local", "password": "ClaveVieja123"})
    assert r_vieja.status_code == 200


def test_cambiar_password_revoca_todas_las_sesiones(db, client):
    reg = client.post("/auth/register", json={"email": "cambio3@vridik.local", "password": "ClaveVieja123"}).json()
    token = reg["access_token"]
    refresh_token_original = reg["refresh_token"]

    r = client.post(
        "/auth/password",
        json={"password_actual": "ClaveVieja123", "password_nueva": "ClaveNueva456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    r_refresh = client.post("/auth/refresh", json={"refresh_token": refresh_token_original})
    assert r_refresh.status_code == 401, "el refresh token de la sesión previa al cambio no debe sobrevivir"


def test_cambiar_password_nueva_muy_corta_rechazado(client):
    reg = client.post("/auth/register", json={"email": "cambio4@vridik.local", "password": "ClaveVieja123"}).json()
    r = client.post(
        "/auth/password",
        json={"password_actual": "ClaveVieja123", "password_nueva": "corta"},
        headers={"Authorization": f"Bearer {reg['access_token']}"},
    )
    assert r.status_code == 422


def test_cambiar_password_sin_token_rechazado(client):
    r = client.post(
        "/auth/password", json={"password_actual": "x", "password_nueva": "ClaveNueva456"},
    )
    assert r.status_code == 401
