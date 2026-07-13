"""
Vridik — tests/test_2fa_backup_codes.py
POST /auth/2fa/backup-codes/regenerate: códigos de respaldo nuevos para un
usuario que ya tiene el 2FA activo, sin pasar por un reset completo (que
además pisaría el autenticador ya configurado). Ver el docstring de
core/totp_2fa.py::regenerar_codigos_respaldo.

Mismo patrón que tests/test_auth_me.py: create_jwt directo (no pasa por
/auth/register) + fake mínimo de conexión asyncpg sobre una sola tabla en
memoria -- nunca PostgreSQL real acá.
"""

from __future__ import annotations

import json
import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_endpoint import router as auth_router
from core.auth import create_jwt
from core.totp_2fa import confirmar_activacion, generar_secreto, iniciar_activacion, provisioning_uri


class _FakeBackupCodesDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.auth_events: list[dict] = []

    def seed_user(self, *, email: str) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email,
            "totp_secret": None, "totp_enabled": False, "totp_backup_codes": "[]",
        }
        return self.users[user_id]

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata, ip_address, user_agent = args
            self.auth_events.append({"user_id": user_id, "actor_id": actor_id, "event_type": event_type})
        elif "totp_secret = $2" in q and "totp_enabled = false" in q:
            user_id, secreto = args
            self.users[user_id]["totp_secret"] = secreto
            self.users[user_id]["totp_enabled"] = False
        elif "totp_backup_codes = $2::jsonb" in q and "totp_enabled = true" in q:
            user_id, backup_codes_json = args
            self.users[user_id]["totp_enabled"] = True
            self.users[user_id]["totp_backup_codes"] = backup_codes_json
        elif q == "UPDATE users SET totp_backup_codes = $2::jsonb WHERE id = $1":
            user_id, backup_codes_json = args
            self.users[user_id]["totp_backup_codes"] = backup_codes_json
        return "OK"

    async def fetchrow(self, query: str, *args):
        user_id = args[0]
        u = self.users.get(user_id)
        if u is None:
            return None
        if "totp_enabled = true" in query and not u["totp_enabled"]:
            return None
        return {"totp_secret": u["totp_secret"]}


@pytest.fixture
def db():
    return _FakeBackupCodesDB()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(auth_router)
    app.state.db_connection = db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


async def _activar_2fa(db, user_id: str, email: str) -> str:
    """Deja al usuario con 2FA activo y devuelve el secreto (para generar
    códigos TOTP válidos en el test)."""
    secreto, _ = await iniciar_activacion(db, user_id=user_id, email=email)
    codigo = pyotp.totp.TOTP(secreto).now()
    await confirmar_activacion(db, user_id=user_id, codigo=codigo)
    return secreto


@pytest.mark.asyncio
async def test_regenerar_codigos_devuelve_8_codigos_nuevos(db, client):
    user = db.seed_user(email="ana@vridik.local")
    secreto = await _activar_2fa(db, user["id"], user["email"])
    codigo = pyotp.totp.TOTP(secreto).now()

    r = client.post(
        "/auth/2fa/backup-codes/regenerate",
        json={"code": codigo},
        headers={"Authorization": f"Bearer {_token_de(user)}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["codigos_respaldo"]) == 8
    assert "two_factor_enabled" not in body  # no es el contrato de /2fa/verify, no confundir


@pytest.mark.asyncio
async def test_regenerar_codigos_con_codigo_invalido_da_400(db, client):
    user = db.seed_user(email="ana@vridik.local")
    await _activar_2fa(db, user["id"], user["email"])

    r = client.post(
        "/auth/2fa/backup-codes/regenerate",
        json={"code": "000000"},
        headers={"Authorization": f"Bearer {_token_de(user)}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_regenerar_codigos_sin_2fa_activo_da_400(db, client):
    user = db.seed_user(email="sin2fa@vridik.local")

    r = client.post(
        "/auth/2fa/backup-codes/regenerate",
        json={"code": "123456"},
        headers={"Authorization": f"Bearer {_token_de(user)}"},
    )
    assert r.status_code == 400


def test_regenerar_codigos_sin_token_da_401(client):
    r = client.post("/auth/2fa/backup-codes/regenerate", json={"code": "123456"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_regenerar_codigos_no_acepta_codigo_de_respaldo(db, client):
    user = db.seed_user(email="ana@vridik.local")
    secreto, _ = await iniciar_activacion(db, user_id=user["id"], email=user["email"])
    codigos = await confirmar_activacion(db, user_id=user["id"], codigo=pyotp.totp.TOTP(secreto).now())

    r = client.post(
        "/auth/2fa/backup-codes/regenerate",
        json={"code": codigos.en_claro[0]},  # 8 dígitos -- viola min/max_length=6 del request
        headers={"Authorization": f"Bearer {_token_de(user)}"},
    )
    assert r.status_code == 422  # Pydantic rechaza el largo antes de llegar a la lógica de negocio
