"""
Vridik — tests/test_platform_endpoint.py
Fase 4 (pricing por despacho): api/platform_endpoint.py end-to-end (FastAPI
TestClient) sobre un fake mínimo -- exclusivo del admin de PLATAFORMA
(es_superadmin), nunca de un admin de despacho normal.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.platform_endpoint import router as platform_router
from core.auth import create_jwt


class _FakePlatformDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.despachos: dict[str, dict] = {}
        self.julix_calls: list[dict] = []

    def seed_user(
        self, *, role: str = "cliente", totp_enabled: bool = True, despacho_id: str | None = None,
        es_superadmin: bool = False,
    ) -> dict:
        user_id = str(uuid.uuid4())
        if despacho_id is None:
            despacho_id = self.seed_despacho()["id"]
        self.users[user_id] = {
            "id": user_id, "email": f"{user_id}@vridik.local", "role": role, "totp_enabled": totp_enabled,
            "despacho_id": despacho_id, "es_superadmin": es_superadmin,
        }
        return self.users[user_id]

    def seed_despacho(self, *, nombre: str = "Despacho Test", plan: str = "piloto") -> dict:
        despacho_id = str(uuid.uuid4())
        self.despachos[despacho_id] = {
            "id": despacho_id, "nombre": nombre, "plan": plan, "activo": True,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        return self.despachos[despacho_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q == "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if q == "SELECT totp_enabled FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return {"totp_enabled": u["totp_enabled"]} if u else None
        if q.startswith("UPDATE despachos SET plan"):
            despacho_id, plan = args
            if despacho_id not in self.despachos:
                return None
            self.despachos[despacho_id]["plan"] = plan
            d = self.despachos[despacho_id]
            return {"id": d["id"], "nombre": d["nombre"], "plan": d["plan"], "activo": d["activo"], "created_at": d["created_at"]}
        return None

    async def fetchval(self, query: str, *args):
        q = query.strip()
        if "SELECT COALESCE(SUM(costo_usd), 0)" in q and "despacho_id = $2" in q:
            _environment, despacho_id = args
            return sum(c["costo_usd"] for c in self.julix_calls if c["despacho_id"] == despacho_id)
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if q.startswith("SELECT d.id, d.nombre, d.plan, d.activo, d.created_at"):
            resultado = []
            for d in self.despachos.values():
                cantidad = sum(1 for u in self.users.values() if u["despacho_id"] == d["id"])
                resultado.append({**d, "cantidad_usuarios": cantidad})
            return resultado
        return []


@pytest.fixture
def pdb():
    return _FakePlatformDB()


@pytest.fixture
def pclient(pdb):
    app = FastAPI()
    app.include_router(platform_router)
    app.state.db_connection = pdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_admin_de_despacho_no_alcanza_para_listar_despachos(pdb, pclient):
    admin = pdb.seed_user(role="admin")
    r = pclient.get("/platform/despachos", headers={"Authorization": f"Bearer {_token_de(admin)}"})
    assert r.status_code == 403


def test_admin_de_despacho_no_alcanza_para_cambiar_plan(pdb, pclient):
    admin = pdb.seed_user(role="admin")
    otro = pdb.seed_despacho()
    r = pclient.patch(
        f"/platform/despachos/{otro['id']}/plan",
        json={"plan": "pagado"},
        headers={"Authorization": f"Bearer {_token_de(admin)}"},
    )
    assert r.status_code == 403


def test_superadmin_sin_2fa_rechazado(pdb, pclient):
    superadmin = pdb.seed_user(es_superadmin=True, totp_enabled=False)
    r = pclient.get("/platform/despachos", headers={"Authorization": f"Bearer {_token_de(superadmin)}"})
    assert r.status_code == 403
    assert "2FA" in r.json()["detail"]


def test_superadmin_lista_todos_los_despachos(pdb, pclient):
    superadmin = pdb.seed_user(es_superadmin=True)
    otro = pdb.seed_despacho(nombre="Otro despacho", plan="pagado")
    pdb.seed_user(despacho_id=otro["id"])  # usuario del otro despacho, cuenta en cantidad_usuarios

    r = pclient.get("/platform/despachos", headers={"Authorization": f"Bearer {_token_de(superadmin)}"})
    assert r.status_code == 200, r.text
    nombres = {d["nombre"] for d in r.json()}
    assert "Otro despacho" in nombres
    fila_otro = next(d for d in r.json() if d["id"] == otro["id"])
    assert fila_otro["plan"] == "pagado"
    assert fila_otro["cantidad_usuarios"] == 1


def test_superadmin_cambia_el_plan_de_un_despacho_ajeno(pdb, pclient):
    superadmin = pdb.seed_user(es_superadmin=True)
    otro = pdb.seed_despacho(plan="piloto")

    r = pclient.patch(
        f"/platform/despachos/{otro['id']}/plan",
        json={"plan": "pagado"},
        headers={"Authorization": f"Bearer {_token_de(superadmin)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "pagado"

    # Se refleja en el listado.
    r2 = pclient.get("/platform/despachos", headers={"Authorization": f"Bearer {_token_de(superadmin)}"})
    fila = next(d for d in r2.json() if d["id"] == otro["id"])
    assert fila["plan"] == "pagado"


def test_cambiar_a_plan_invalido_da_422(pdb, pclient):
    superadmin = pdb.seed_user(es_superadmin=True)
    otro = pdb.seed_despacho()

    r = pclient.patch(
        f"/platform/despachos/{otro['id']}/plan",
        json={"plan": "premium-inventado"},
        headers={"Authorization": f"Bearer {_token_de(superadmin)}"},
    )
    assert r.status_code == 422
