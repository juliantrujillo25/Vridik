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
        # GET /admin/costos (julix/ledger.py) -- gasto mensual seedeable,
        # 0 por default (mes sin llamadas registradas todavía).
        self.gasto_mensual_seed: float = 0.0

    def seed(
        self, *, email: str, role: str = "abogado", is_active: bool = True, totp_enabled: bool = True,
        despacho_id: str = "despacho-1",
    ) -> dict:
        # totp_enabled=True por default: la mayoría de estos tests seedean
        # un admin y esperan que get_current_admin lo deje pasar sin
        # pensar en 2FA -- el must_enroll de S12-13 se prueba aparte, con
        # totp_enabled=False explícito.
        # despacho_id="despacho-1" por default (Fase 4): los tests de este
        # archivo asumen que admin+seller comparten despacho salvo que se
        # pase uno distinto a propósito (aislamiento cross-despacho).
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "hashed_password": "x-hash",
            "role": role, "is_active": is_active, "created_at": "2026-01-01T00:00:00+00:00",
            "deleted_at": None, "must_change": False, "totp_enabled": totp_enabled, "despacho_id": despacho_id,
            "es_superadmin": False,
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
        elif q.startswith("SELECT pg_advisory_xact_lock"):
            pass  # advisory lock real (concurrencia de la bitácora) -- no-op en el fake
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
        if "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return (
                {
                    "id": u["id"], "email": u["email"], "role": u["role"],
                    "despacho_id": u["despacho_id"], "es_superadmin": u["es_superadmin"],
                }
                if u else None
            )
        if "SELECT id FROM users WHERE email" in q:
            (email,) = args
            return next(({"id": u["id"]} for u in self.users.values() if u["email"] == email), None)
        if "SELECT id FROM users WHERE id" in q and "deleted_at IS NULL" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"]} if u and u["deleted_at"] is None else None
        if q.strip() == "SELECT id FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"]} if u else None
        if q.strip() == "SELECT totp_enabled FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return {"totp_enabled": u["totp_enabled"]} if u else None
        if "SUM(costo_usd)" in q:
            return (self.gasto_mensual_seed,)
        if "INSERT INTO users" in q and "RETURNING" in q:
            email, password_hash, role, despacho_id = args
            nuevo = self.seed(email=email, role=role, despacho_id=despacho_id)
            nuevo["hashed_password"] = password_hash
            return {k: nuevo[k] for k in ("id", "email", "role", "despacho_id", "is_active", "created_at")}
        if "UPDATE users SET role" in q:
            user_id, new_role = args
            u = self.users.get(user_id)
            if u is None:
                return None
            u["role"] = new_role
            return {k: u[k] for k in ("id", "email", "role", "is_active", "created_at")}
        return None

    async def fetchval(self, query: str, *args):
        q = query.strip()
        if q == "SELECT plan FROM despachos WHERE id = $1":
            # Sin fila de despacho real en este fake -- None cae al default
            # de core.despachos.limite_julix_mensual ('piloto', $150),
            # mismo límite que ya asumían los tests de costos existentes.
            return None
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role, despacho_id, is_active, created_at" in q and "FROM users" in q:
            despacho_id, skip, limit = args
            filas = sorted(
                (u for u in self.users.values() if u["despacho_id"] == despacho_id),
                key=lambda u: u["created_at"], reverse=True,
            )
            seleccion = filas[skip:skip + limit]
            return [{k: u[k] for k in ("id", "email", "role", "despacho_id", "is_active", "created_at")} for u in seleccion]
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
    admin_db.seed(email="vendedor1@vridik.local", role="abogado")
    token = _token_de(admin)

    r = admin_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert {"id", "email", "role", "is_active", "created_at"} <= set(body[0].keys())
    assert "hashed_password" not in body[0]


def test_admin_list_users_forbidden(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor2@vridik.local", role="abogado")
    token = _token_de(seller)

    r = admin_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_create_user(admin_db, admin_client):
    admin = admin_db.seed(email="admin2@vridik.local", role="admin")
    token = _token_de(admin)

    r = admin_client.post(
        "/admin/users",
        json={"email": "nuevo_seller@vridik.local", "password": "Clave#Segura123", "role": "abogado"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "nuevo_seller@vridik.local"
    assert body["role"] == "abogado"
    assert "password" not in body
    assert "hashed_password" not in body
    # Fase 4: el usuario creado hereda el despacho del admin que lo crea --
    # nunca se acepta un despacho_id del cliente.
    assert body["despacho_id"] == admin["despacho_id"]


def test_admin_create_user_ignora_despacho_id_del_cliente(admin_db, admin_client):
    """Aunque el request intente mandar un despacho_id, el servidor lo
    ignora -- siempre hereda del admin que actúa."""
    admin = admin_db.seed(email="admin2b@vridik.local", role="admin", despacho_id="despacho-real")
    token = _token_de(admin)

    r = admin_client.post(
        "/admin/users",
        json={
            "email": "nuevo_seller2@vridik.local", "password": "Clave#Segura123", "role": "abogado",
            "despacho_id": "despacho-ajeno",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["despacho_id"] == "despacho-real"


def test_admin_change_role(admin_db, admin_client):
    admin = admin_db.seed(email="admin3@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor3@vridik.local", role="abogado")
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
        json={"role": "abogado"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_admin_get_user_actividad(admin_db, admin_client):
    admin = admin_db.seed(email="admin4@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor4@vridik.local", role="abogado")
    admin_db.seed_evento(user_id=seller["id"], event_type="login_success", created_at="2026-01-02T00:00:00+00:00")
    admin_db.seed_evento(user_id=seller["id"], event_type="login_failed", created_at="2026-01-01T00:00:00+00:00")
    token = _token_de(admin)

    r = admin_client.get(f"/admin/users/{seller['id']}/actividad", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert body[0]["event_type"] == "login_success"  # más reciente primero


def test_admin_get_user_actividad_forbidden_para_no_admin(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor5@vridik.local", role="abogado")
    token = _token_de(seller)

    r = admin_client.get(f"/admin/users/{seller['id']}/actividad", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_reset_password_genera_temporal_y_revoca_sesiones(admin_db, admin_client):
    admin = admin_db.seed(email="admin5@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor6@vridik.local", role="abogado")
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


def test_admin_reset_2fa_desactiva_y_deja_auth_event(admin_db, admin_client):
    """Roadmap S12-13 (hardening): 'perdí el teléfono' -- un admin puede
    desactivar el 2FA de otro usuario, dejando un auth_event 'totp_reset'
    con el admin como actor."""
    admin = admin_db.seed(email="admin7@vridik.local", role="admin")
    seller = admin_db.seed(email="vendedor7@vridik.local", role="abogado")
    token = _token_de(admin)

    r = admin_client.post(f"/admin/users/{seller['id']}/reset-2fa", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json() == {"user_id": seller["id"], "two_factor_enabled": False}

    evento = next(e for e in admin_db.auth_events if e.get("event_type") == "totp_reset")
    assert evento["user_id"] == seller["id"]
    assert evento["actor_id"] == admin["id"]


def test_admin_reset_2fa_usuario_inexistente_404(admin_db, admin_client):
    admin = admin_db.seed(email="admin8@vridik.local", role="admin")
    token = _token_de(admin)

    r = admin_client.post(f"/admin/users/{uuid.uuid4()}/reset-2fa", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_admin_reset_2fa_forbidden_para_no_admin(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor8@vridik.local", role="abogado")
    token = _token_de(seller)

    r = admin_client.post(f"/admin/users/{seller['id']}/reset-2fa", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_sin_2fa_no_puede_usar_el_panel(admin_db, admin_client):
    """Roadmap S12-13 (hardening, must_enroll): un admin sin 2FA activado
    queda bloqueado de CUALQUIER ruta /admin/* -- 403, no 401 (el token
    es válido, el rol es correcto, falta el segundo factor)."""
    admin_sin_2fa = admin_db.seed(email="admin9@vridik.local", role="admin", totp_enabled=False)
    token = _token_de(admin_sin_2fa)

    r = admin_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert "2FA" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /admin/costos -- widget de costos (roadmap S4/S6, julix/ledger.py)
# ---------------------------------------------------------------------------
def test_admin_costos_sin_llamadas_del_mes_da_gasto_cero(admin_db, admin_client):
    admin = admin_db.seed(email="admin-costos1@vridik.local", role="admin")
    token = _token_de(admin)

    r = admin_client.get("/admin/costos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gasto_mensual_usd"] == 0.0
    assert body["limite_mensual_usd"] == 150.0
    assert body["aviso_80"] is False
    assert body["confirmacion_100"] is False


def test_admin_costos_refleja_el_gasto_acumulado(admin_db, admin_client):
    admin = admin_db.seed(email="admin-costos2@vridik.local", role="admin")
    admin_db.gasto_mensual_seed = 42.5
    token = _token_de(admin)

    r = admin_client.get("/admin/costos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["gasto_mensual_usd"] == 42.5


def test_admin_costos_marca_aviso_80_por_ciento(admin_db, admin_client):
    admin = admin_db.seed(email="admin-costos3@vridik.local", role="admin")
    admin_db.gasto_mensual_seed = 130.0  # 130/150 = 86.6% -- por encima del umbral del 80%
    token = _token_de(admin)

    r = admin_client.get("/admin/costos", headers={"Authorization": f"Bearer {token}"})
    body = r.json()
    assert body["aviso_80"] is True
    assert body["confirmacion_100"] is False


def test_admin_costos_marca_confirmacion_100_por_ciento_pero_nunca_bloquea(admin_db, admin_client):
    """El límite es blando: al 100% se exige confirmación por documento en
    la UI de generación, pero este endpoint solo informa -- nunca devuelve
    un error ni impide nada por sí mismo."""
    admin = admin_db.seed(email="admin-costos4@vridik.local", role="admin")
    admin_db.gasto_mensual_seed = 200.0  # por encima del límite de 150
    token = _token_de(admin)

    r = admin_client.get("/admin/costos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["aviso_80"] is True
    assert body["confirmacion_100"] is True


def test_admin_costos_forbidden_para_no_admin(admin_db, admin_client):
    seller = admin_db.seed(email="vendedor-costos@vridik.local", role="abogado")
    token = _token_de(seller)

    r = admin_client.get("/admin/costos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_costos_sin_token_da_401(admin_client):
    r = admin_client.get("/admin/costos")
    assert r.status_code == 401
