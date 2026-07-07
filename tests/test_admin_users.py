"""
Vridik — tests/test_admin_users.py (Sprint S2)
Prueba core/admin_users.py sobre un fake mínimo de conexión asyncpg que
modela `users`/`user_credentials`/`refresh_tokens`/`auth_events`/`roles`
(schema_semana1_vridik.sql) en memoria — nunca PostgreSQL real. El fake
simula la unicidad case-insensitive de `email` (CITEXT en Postgres real)
comparando en minúsculas, y el `RETURNING id` de la migración con UUIDs
generados localmente.

Además prueba api/admin_users_endpoint.py con FastAPI TestClient: 403 para
no-admin, 409 para email duplicado, y que crear/reset devuelven la
contraseña temporal en la respuesta (una sola vez).
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.admin_users import (
    EmailDuplicadoError,
    RolInvalidoError,
    UsuarioNoEncontradoError,
    actividad_usuario,
    crear_usuario,
    desactivar_usuario,
    editar_usuario,
    listar_usuarios,
    resetear_password,
)

JWT_SECRET_TEST = "vridik-test-admin-secret-nunca-produccion"


class FakeAdminDB:
    """Fake mínimo de una conexión asyncpg sobre las tablas de
    schema_semana1_vridik.sql relevantes para el CRUD de S2."""

    def __init__(self):
        self.roles = {"admin": 1, "abogado": 2, "cliente": 3}
        self.users: dict[str, dict] = {}
        self.user_credentials: dict[str, dict] = {}
        self.refresh_tokens: list[dict] = []
        self.auth_events: list[dict] = []

    def _email_activo_existente(self, email: str) -> dict | None:
        email_lower = email.lower()
        for u in self.users.values():
            if u["email"].lower() == email_lower and u["deleted_at"] is None:
                return u
        return None

    async def fetchrow(self, query: str, *args):
        if "SELECT id FROM users WHERE email = $1 AND deleted_at IS NULL" in query:
            (email,) = args
            existente = self._email_activo_existente(email)
            return {"id": existente["id"]} if existente else None

        if "SELECT id FROM roles WHERE codigo = $1" in query:
            (codigo,) = args
            role_id = self.roles.get(codigo)
            return {"id": role_id} if role_id else None

        if "INSERT INTO users" in query and "RETURNING id" in query:
            email, nombre_completo, role_id = args
            user_id = str(uuid.uuid4())
            self.users[user_id] = {
                "id": user_id, "email": email, "nombre_completo": nombre_completo,
                "role_id": role_id, "must_change": True, "is_active": True,
                "last_login_at": None, "created_at": "now", "deactivated_at": None, "deleted_at": None,
            }
            return {"id": user_id}

        if "SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            if u is None or u["deleted_at"] is not None:
                return None
            return {"id": user_id}

        raise AssertionError(f"fetchrow no manejado en el fake: {query!r} args={args}")

    async def fetch(self, query: str, *args):
        if "FROM users u" in query and "JOIN roles r" in query and "ORDER BY u.created_at DESC" in query:
            codigo_por_id = {v: k for k, v in self.roles.items()}
            resultado = []
            for u in self.users.values():
                if u["deleted_at"] is not None:
                    continue
                resultado.append({
                    "id": u["id"], "email": u["email"], "nombre_completo": u["nombre_completo"],
                    "role_codigo": codigo_por_id[u["role_id"]], "is_active": u["is_active"],
                    "must_change": u["must_change"], "last_login_at": u["last_login_at"],
                    "created_at": u["created_at"],
                })
            return resultado

        if "FROM auth_events" in query and "WHERE user_id = $1" in query:
            user_id, limite = args
            eventos = [e for e in self.auth_events if e["user_id"] == user_id]
            eventos.sort(key=lambda e: e["created_at"], reverse=True)
            return eventos[:limite]

        raise AssertionError(f"fetch no manejado en el fake: {query!r} args={args}")

    async def execute(self, query: str, *args):
        if "INSERT INTO user_credentials" in query:
            user_id, password_hash, actor_id = args
            self.user_credentials[user_id] = {
                "password_hash": password_hash, "hash_algorithm": "bcrypt",
                "is_temporary": True, "updated_by": actor_id,
            }
        elif "INSERT INTO auth_events" in query:
            user_id, actor_id, event_type, metadata = args
            self._contador_evento = getattr(self, "_contador_evento", 0) + 1
            self.auth_events.append({
                "id": self._contador_evento, "user_id": user_id, "actor_id": actor_id,
                "event_type": event_type, "metadata": metadata,
                "ip_address": None, "user_agent": None, "created_at": self._contador_evento,
            })
        elif "UPDATE users SET nombre_completo" in query:
            user_id, nombre_completo = args
            self.users[user_id]["nombre_completo"] = nombre_completo
        elif "UPDATE users SET role_id" in query:
            user_id, role_id = args
            self.users[user_id]["role_id"] = role_id
        elif "UPDATE users SET is_active = false" in query:
            (user_id,) = args
            self.users[user_id]["is_active"] = False
            self.users[user_id]["deactivated_at"] = "now"
        elif "UPDATE refresh_tokens" in query:
            user_id, motivo = args
            for rt in self.refresh_tokens:
                if rt["user_id"] == user_id and rt["revoked_at"] is None:
                    rt["revoked_at"] = "now"
                    rt["revoked_reason"] = motivo
        elif "UPDATE user_credentials" in query and "SET password_hash" in query:
            user_id, password_hash, actor_id = args
            self.user_credentials[user_id]["password_hash"] = password_hash
            self.user_credentials[user_id]["is_temporary"] = True
            self.user_credentials[user_id]["updated_by"] = actor_id
        elif "UPDATE users SET must_change = true" in query:
            (user_id,) = args
            self.users[user_id]["must_change"] = True
        else:
            raise AssertionError(f"execute no manejado en el fake: {query!r} args={args}")
        return "OK"


# ---------------------------------------------------------------------------
# Pruebas de core/admin_users.py (lógica de negocio pura sobre el fake)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_crear_usuario_retorna_password_temporal_una_vez():
    db = FakeAdminDB()
    resultado = await crear_usuario(
        db, actor_id="admin-1", email="ana@vridik.local", nombre_completo="Ana Luisa", role_codigo="abogado",
    )
    assert resultado.email == "ana@vridik.local"
    assert len(resultado.password_temporal) >= 16
    assert db.users[resultado.user_id]["must_change"] is True
    assert db.user_credentials[resultado.user_id]["is_temporary"] is True
    assert any(e["event_type"] == "user_created" for e in db.auth_events)


@pytest.mark.asyncio
async def test_crear_usuario_email_duplicado_case_insensitive():
    db = FakeAdminDB()
    await crear_usuario(db, actor_id="admin-1", email="Ana@Vridik.local", nombre_completo="Ana", role_codigo="abogado")
    with pytest.raises(EmailDuplicadoError):
        await crear_usuario(db, actor_id="admin-1", email="ana@vridik.local", nombre_completo="Otra Ana", role_codigo="cliente")


@pytest.mark.asyncio
async def test_crear_usuario_rol_invalido():
    db = FakeAdminDB()
    with pytest.raises(RolInvalidoError):
        await crear_usuario(db, actor_id="admin-1", email="x@vridik.local", nombre_completo="X", role_codigo="superadmin")


@pytest.mark.asyncio
async def test_listar_usuarios_nunca_incluye_password_hash():
    db = FakeAdminDB()
    await crear_usuario(db, actor_id="admin-1", email="a@vridik.local", nombre_completo="A", role_codigo="cliente")
    usuarios = await listar_usuarios(db)
    assert len(usuarios) == 1
    assert "password_hash" not in usuarios[0]
    assert usuarios[0]["role_codigo"] == "cliente"


@pytest.mark.asyncio
async def test_editar_usuario_actualiza_nombre_y_rol():
    db = FakeAdminDB()
    creado = await crear_usuario(db, actor_id="admin-1", email="b@vridik.local", nombre_completo="B", role_codigo="cliente")
    await editar_usuario(db, actor_id="admin-1", user_id=creado.user_id, nombre_completo="B Editado", role_codigo="abogado")
    assert db.users[creado.user_id]["nombre_completo"] == "B Editado"
    codigo_por_id = {v: k for k, v in db.roles.items()}
    assert codigo_por_id[db.users[creado.user_id]["role_id"]] == "abogado"
    assert any(e["event_type"] == "user_updated" for e in db.auth_events)


@pytest.mark.asyncio
async def test_editar_usuario_inexistente_falla():
    db = FakeAdminDB()
    with pytest.raises(UsuarioNoEncontradoError):
        await editar_usuario(db, actor_id="admin-1", user_id="no-existe", nombre_completo="X")


@pytest.mark.asyncio
async def test_desactivar_usuario_revoca_refresh_tokens():
    db = FakeAdminDB()
    creado = await crear_usuario(db, actor_id="admin-1", email="c@vridik.local", nombre_completo="C", role_codigo="cliente")
    db.refresh_tokens.append({"user_id": creado.user_id, "revoked_at": None, "revoked_reason": None})

    await desactivar_usuario(db, actor_id="admin-1", user_id=creado.user_id)

    assert db.users[creado.user_id]["is_active"] is False
    assert db.refresh_tokens[0]["revoked_at"] is not None
    assert db.refresh_tokens[0]["revoked_reason"] == "user_deactivated"
    assert any(e["event_type"] == "user_deactivated" for e in db.auth_events)


@pytest.mark.asyncio
async def test_resetear_password_revoca_refresh_tokens_y_marca_must_change():
    db = FakeAdminDB()
    creado = await crear_usuario(db, actor_id="admin-1", email="d@vridik.local", nombre_completo="D", role_codigo="cliente")
    db.users[creado.user_id]["must_change"] = False  # simula que ya había cambiado su clave
    db.refresh_tokens.append({"user_id": creado.user_id, "revoked_at": None, "revoked_reason": None})

    resultado = await resetear_password(db, actor_id="admin-1", user_id=creado.user_id)

    assert len(resultado.password_temporal) >= 16
    assert resultado.password_temporal != creado.password_temporal
    assert db.users[creado.user_id]["must_change"] is True
    assert db.user_credentials[creado.user_id]["is_temporary"] is True
    assert db.refresh_tokens[0]["revoked_reason"] == "admin_reset"
    assert any(e["event_type"] == "password_reset" for e in db.auth_events)


@pytest.mark.asyncio
async def test_actividad_usuario_retorna_eventos_mas_recientes_primero():
    db = FakeAdminDB()
    creado = await crear_usuario(db, actor_id="admin-1", email="e@vridik.local", nombre_completo="E", role_codigo="cliente")
    await editar_usuario(db, actor_id="admin-1", user_id=creado.user_id, nombre_completo="E2")

    eventos = await actividad_usuario(db, user_id=creado.user_id)
    tipos = [e["event_type"] for e in eventos]
    assert tipos[0] == "user_updated"  # el más reciente primero
    assert "user_created" in tipos


# ---------------------------------------------------------------------------
# Pruebas HTTP (api/admin_users_endpoint.py) — 403 no-admin, 409 duplicado
# ---------------------------------------------------------------------------
def _token(role: str, sub: str = "admin-1") -> str:
    now = int(time.time())
    return pyjwt.encode({"sub": sub, "role": role, "iat": now, "exp": now + 900}, JWT_SECRET_TEST, algorithm="HS256")


@pytest.fixture
def app_con_router(monkeypatch):
    import api.admin_users_endpoint as admin_users_endpoint_module

    monkeypatch.setattr(admin_users_endpoint_module, "JWT_SECRET", JWT_SECRET_TEST)
    app = FastAPI()
    app.include_router(admin_users_endpoint_module.router)
    app.state.db_connection = FakeAdminDB()
    return app


def test_endpoint_crear_usuario_sin_rol_admin_responde_403(app_con_router):
    client = TestClient(app_con_router)
    resp = client.post(
        "/admin/users",
        json={"email": "x@vridik.local", "nombre_completo": "X", "role_codigo": "cliente"},
        headers={"Authorization": f"Bearer {_token('abogado')}"},
    )
    assert resp.status_code == 403


def test_endpoint_crear_usuario_admin_devuelve_password_temporal(app_con_router):
    client = TestClient(app_con_router)
    resp = client.post(
        "/admin/users",
        json={"email": "nuevo@vridik.local", "nombre_completo": "Nuevo", "role_codigo": "cliente"},
        headers={"Authorization": f"Bearer {_token('admin')}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "nuevo@vridik.local"
    assert len(body["password_temporal"]) >= 16


def test_endpoint_crear_usuario_email_duplicado_responde_409(app_con_router):
    client = TestClient(app_con_router)
    headers = {"Authorization": f"Bearer {_token('admin')}"}
    payload = {"email": "dup@vridik.local", "nombre_completo": "Dup", "role_codigo": "cliente"}
    r1 = client.post("/admin/users", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = client.post("/admin/users", json=payload, headers=headers)
    assert r2.status_code == 409


def test_endpoint_listar_usuarios_requiere_admin(app_con_router):
    client = TestClient(app_con_router)
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {_token('cliente')}"})
    assert resp.status_code == 403

    resp_admin = client.get("/admin/users", headers={"Authorization": f"Bearer {_token('admin')}"})
    assert resp_admin.status_code == 200
    assert "usuarios" in resp_admin.json()
