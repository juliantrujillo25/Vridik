"""
Vridik — tests/test_clientes_endpoint.py
Fase 4 (SAGRILAFT lite): api/clientes_endpoint.py end-to-end (FastAPI
TestClient) sobre un fake mínimo -- mismo estilo que
tests/test_cobro_endpoint.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.clientes_endpoint import router as clientes_router
from core.auth import create_jwt


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeClientesDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.matrices: dict[str, dict] = {}  # keyed by cliente_id

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "role": role, "despacho_id": despacho_id, "es_superadmin": False,
        }
        return self.users[user_id]

    def seed_caso(self, *, cliente_id: str, despacho_id: str = "despacho-1") -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": None, "despacho_id": despacho_id,
            "titulo": "caso", "descripcion": None, "estado": "abierto", "created_at": _ahora(), "updated_at": _ahora(),
        }
        return self.casos[caso_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if q.strip() == "SELECT id FROM users WHERE id = $1 AND despacho_id = $2 AND role = 'cliente'":
            cliente_id, despacho_id = args
            u = self.users.get(cliente_id)
            if u and u["despacho_id"] == despacho_id and u["role"] == "cliente":
                return {"id": u["id"]}
            return None
        if q.strip() == "SELECT id, email, created_at FROM users WHERE id = $1 AND despacho_id = $2 AND role = 'cliente'":
            cliente_id, despacho_id = args
            u = self.users.get(cliente_id)
            if u and u["despacho_id"] == despacho_id and u["role"] == "cliente":
                return {"id": u["id"], "email": u["email"], "created_at": _ahora()}
            return None
        if q.startswith("INSERT INTO matriz_riesgo"):
            (
                cliente_id, despacho_id, tipo_persona, actividad_economica_riesgo,
                jurisdiccion_riesgo, canal, es_pep, nivel_riesgo_calculado, actor_id,
            ) = args
            registro = {
                "cliente_id": cliente_id, "despacho_id": despacho_id, "tipo_persona": tipo_persona,
                "actividad_economica_riesgo": actividad_economica_riesgo, "jurisdiccion_riesgo": jurisdiccion_riesgo,
                "canal": canal, "es_pep": es_pep, "nivel_riesgo_calculado": nivel_riesgo_calculado,
                "evaluado_por": actor_id, "created_at": _ahora(), "updated_at": _ahora(),
            }
            self.matrices[cliente_id] = registro
            return dict(registro)
        if q.startswith("SELECT cliente_id, despacho_id, tipo_persona"):
            cliente_id, despacho_id = args
            m = self.matrices.get(cliente_id)
            if m and m["despacho_id"] == despacho_id:
                return dict(m)
            return None
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if q.startswith("SELECT id, email, created_at") and "FROM users" in q and "role = 'cliente'" in q:
            (despacho_id,) = args
            return [
                {"id": u["id"], "email": u["email"], "created_at": _ahora()}
                for u in self.users.values() if u["despacho_id"] == despacho_id and u["role"] == "cliente"
            ]
        if "FROM casos" in q and "cliente_id = $1 AND despacho_id = $2" in q:
            cliente_id, despacho_id = args
            return [
                dict(c) for c in self.casos.values()
                if c["cliente_id"] == cliente_id and c["despacho_id"] == despacho_id
            ]
        if "FROM matriz_riesgo m" in q:
            (despacho_id,) = args
            filas = []
            for m in self.matrices.values():
                if m["despacho_id"] != despacho_id:
                    continue
                cliente = self.users.get(m["cliente_id"])
                evaluador = self.users.get(m["evaluado_por"])
                filas.append({
                    "cliente_id": m["cliente_id"], "email": cliente["email"],
                    "tipo_persona": m["tipo_persona"], "actividad_economica_riesgo": m["actividad_economica_riesgo"],
                    "jurisdiccion_riesgo": m["jurisdiccion_riesgo"], "canal": m["canal"], "es_pep": m["es_pep"],
                    "nivel_riesgo_calculado": m["nivel_riesgo_calculado"],
                    "evaluado_por_email": evaluador["email"] if evaluador else None,
                    "updated_at": m["updated_at"],
                })
            orden = {"alto": 0, "medio": 1, "bajo": 2}
            filas.sort(key=lambda f: (orden[f["nivel_riesgo_calculado"]], f["email"]))
            return filas
        return []

    async def fetchval(self, query: str, *args):
        q = query.strip()
        if q == "SELECT count(*) FROM users WHERE despacho_id = $1 AND role = 'cliente'":
            (despacho_id,) = args
            return sum(1 for u in self.users.values() if u["despacho_id"] == despacho_id and u["role"] == "cliente")
        return None


@pytest.fixture
def cdb():
    return _FakeClientesDB()


@pytest.fixture
def cclient(cdb):
    app = FastAPI()
    app.include_router(clientes_router)
    app.state.db_connection = cdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


# ---------------------------------------------------------------------------
# GET /clientes
# ---------------------------------------------------------------------------
def test_cliente_no_puede_listar_clientes(cdb, cclient):
    cliente = cdb.seed_user(email="cliente1@vridik.local")
    r = cclient.get("/clientes", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 403


def test_abogado_lista_los_clientes_de_su_despacho(cdb, cclient):
    abogado = cdb.seed_user(email="abogado1@vridik.local", role="abogado")
    cdb.seed_user(email="cliente1@vridik.local", despacho_id="despacho-1")
    cdb.seed_user(email="cliente-ajeno@vridik.local", despacho_id="despacho-2")

    r = cclient.get("/clientes", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    emails = {c["email"] for c in r.json()}
    assert "cliente1@vridik.local" in emails
    assert "cliente-ajeno@vridik.local" not in emails


# ---------------------------------------------------------------------------
# GET /clientes/{id}
# ---------------------------------------------------------------------------
def test_cliente_ve_su_propio_perfil(cdb, cclient):
    cliente = cdb.seed_user(email="cliente2@vridik.local")
    r = cclient.get(f"/clientes/{cliente['id']}", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "cliente2@vridik.local"
    assert r.json()["casos"] == []


def test_cliente_no_ve_el_perfil_de_otro_cliente(cdb, cclient):
    cliente1 = cdb.seed_user(email="cliente3@vridik.local")
    cliente2 = cdb.seed_user(email="cliente4@vridik.local")
    r = cclient.get(f"/clientes/{cliente2['id']}", headers={"Authorization": f"Bearer {_token_de(cliente1)}"})
    assert r.status_code == 403


def test_abogado_ve_perfil_de_cliente_de_su_despacho_con_sus_casos(cdb, cclient):
    abogado = cdb.seed_user(email="abogado2@vridik.local", role="abogado")
    cliente = cdb.seed_user(email="cliente5@vridik.local")
    cdb.seed_caso(cliente_id=cliente["id"])

    r = cclient.get(f"/clientes/{cliente['id']}", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    assert len(r.json()["casos"]) == 1


def test_abogado_no_ve_cliente_de_otro_despacho(cdb, cclient):
    abogado = cdb.seed_user(email="abogado3@vridik.local", role="abogado", despacho_id="despacho-1")
    cliente_ajeno = cdb.seed_user(email="cliente-ajeno2@vridik.local", despacho_id="despacho-2")

    r = cclient.get(f"/clientes/{cliente_ajeno['id']}", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /clientes/{id}/riesgo
# ---------------------------------------------------------------------------
def test_cliente_no_puede_evaluar_su_propio_riesgo(cdb, cclient):
    cliente = cdb.seed_user(email="cliente6@vridik.local")
    payload = {
        "tipo_persona": "natural", "actividad_economica_riesgo": "bajo",
        "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": False,
    }
    r = cclient.post(
        f"/clientes/{cliente['id']}/riesgo", json=payload, headers={"Authorization": f"Bearer {_token_de(cliente)}"},
    )
    assert r.status_code == 403


def test_abogado_evalua_el_riesgo_de_un_cliente_propio(cdb, cclient):
    abogado = cdb.seed_user(email="abogado4@vridik.local", role="abogado")
    cliente = cdb.seed_user(email="cliente7@vridik.local")
    payload = {
        "tipo_persona": "natural", "actividad_economica_riesgo": "bajo",
        "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": True,
    }
    r = cclient.post(
        f"/clientes/{cliente['id']}/riesgo", json=payload, headers={"Authorization": f"Bearer {_token_de(abogado)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nivel_riesgo_calculado"] == "alto"  # PEP fuerza alto


def test_abogado_no_puede_evaluar_riesgo_de_cliente_de_otro_despacho(cdb, cclient):
    abogado = cdb.seed_user(email="abogado5@vridik.local", role="abogado", despacho_id="despacho-1")
    cliente_ajeno = cdb.seed_user(email="cliente-ajeno3@vridik.local", despacho_id="despacho-2")
    payload = {
        "tipo_persona": "natural", "actividad_economica_riesgo": "bajo",
        "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": False,
    }
    r = cclient.post(
        f"/clientes/{cliente_ajeno['id']}/riesgo", json=payload,
        headers={"Authorization": f"Bearer {_token_de(abogado)}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /clientes/{id}/riesgo
# ---------------------------------------------------------------------------
def test_cliente_puede_leer_su_propio_nivel_de_riesgo_ya_evaluado(cdb, cclient):
    abogado = cdb.seed_user(email="abogado6@vridik.local", role="abogado")
    cliente = cdb.seed_user(email="cliente8@vridik.local")
    payload = {
        "tipo_persona": "natural", "actividad_economica_riesgo": "medio",
        "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": False,
    }
    cclient.post(
        f"/clientes/{cliente['id']}/riesgo", json=payload, headers={"Authorization": f"Bearer {_token_de(abogado)}"},
    )

    r = cclient.get(f"/clientes/{cliente['id']}/riesgo", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 200, r.text
    assert r.json()["nivel_riesgo_calculado"] == "medio"


def test_riesgo_sin_evaluar_todavia_devuelve_null_no_404(cdb, cclient):
    abogado = cdb.seed_user(email="abogado7@vridik.local", role="abogado")
    cliente = cdb.seed_user(email="cliente9@vridik.local")

    r = cclient.get(f"/clientes/{cliente['id']}/riesgo", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    assert r.json() is None


# ---------------------------------------------------------------------------
# GET /clientes/riesgo/reporte
# ---------------------------------------------------------------------------
def test_cliente_no_puede_ver_el_reporte_de_riesgo(cdb, cclient):
    cliente = cdb.seed_user(email="cliente10@vridik.local")
    r = cclient.get("/clientes/riesgo/reporte", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 403


def test_reporte_de_riesgo_resume_y_ordena_por_nivel(cdb, cclient):
    abogado = cdb.seed_user(email="abogado8@vridik.local", role="abogado")
    cliente_bajo = cdb.seed_user(email="cliente-bajo@vridik.local")
    cliente_alto = cdb.seed_user(email="cliente-alto@vridik.local")
    cdb.seed_user(email="cliente-sin-evaluar@vridik.local")  # nunca evaluado

    for cliente, es_pep in ((cliente_bajo, False), (cliente_alto, True)):
        cclient.post(
            f"/clientes/{cliente['id']}/riesgo",
            json={
                "tipo_persona": "natural", "actividad_economica_riesgo": "bajo",
                "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": es_pep,
            },
            headers={"Authorization": f"Bearer {_token_de(abogado)}"},
        )

    r = cclient.get("/clientes/riesgo/reporte", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_clientes"] == 3
    assert data["total_evaluados"] == 2
    assert data["total_sin_evaluar"] == 1
    assert data["total_pep"] == 1
    assert [c["email"] for c in data["clientes"]] == ["cliente-alto@vridik.local", "cliente-bajo@vridik.local"]


def test_reporte_de_riesgo_como_csv(cdb, cclient):
    abogado = cdb.seed_user(email="abogado9@vridik.local", role="abogado")
    cliente = cdb.seed_user(email="cliente-csv@vridik.local")
    cclient.post(
        f"/clientes/{cliente['id']}/riesgo",
        json={
            "tipo_persona": "natural", "actividad_economica_riesgo": "bajo",
            "jurisdiccion_riesgo": "bajo", "canal": "presencial", "es_pep": False,
        },
        headers={"Authorization": f"Bearer {_token_de(abogado)}"},
    )

    r = cclient.get(
        "/clientes/riesgo/reporte?formato=csv", headers={"Authorization": f"Bearer {_token_de(abogado)}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "cliente-csv@vridik.local" in r.text
