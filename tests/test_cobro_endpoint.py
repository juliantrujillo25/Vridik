"""
Vridik — tests/test_cobro_endpoint.py
Fase 3 (Cobro Inteligente): prueba api/cobro_endpoint.py + core/cobro.py
end-to-end (FastAPI TestClient) sobre un fake mínimo de conexión asyncpg --
mismo estilo que tests/test_terminos_endpoint.py.

honorarios_liquidados SIEMPRE se calcula del esquema ya configurado --
nunca se acepta como input directo (mismo principio que el vencimiento de
un término, ver core/terminos.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.cobro_endpoint import router as cobro_router
from core.auth import create_jwt


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeCobroDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.cobros: dict[str, dict] = {}  # keyed by caso_id

    def seed_user(self, *, email: str, role: str = "cliente") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_caso(self, *, cliente_id: str, abogado_id: str | None = None) -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "titulo": "caso",
            "descripcion": None, "estado": "abierto", "created_at": _ahora(), "updated_at": _ahora(),
        }
        return self.casos[caso_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.startswith("INSERT INTO cobro_caso"):
            caso_id, valor_en_disputa, esquema_honorarios, monto_fijo, porcentaje_cuota_litis = args
            existente = self.cobros.get(caso_id, {})
            registro = {
                "caso_id": caso_id, "valor_en_disputa": valor_en_disputa,
                "esquema_honorarios": esquema_honorarios, "monto_fijo": monto_fijo,
                "porcentaje_cuota_litis": porcentaje_cuota_litis,
                "valor_recuperado": existente.get("valor_recuperado"),
                "honorarios_liquidados": existente.get("honorarios_liquidados"),
                "liquidado_en": existente.get("liquidado_en"),
                "created_at": existente.get("created_at", _ahora()), "updated_at": _ahora(),
            }
            self.cobros[caso_id] = registro
            return dict(registro)
        if q.strip() == f"SELECT {_COLUMNAS_TEST} FROM cobro_caso WHERE caso_id = $1":
            (caso_id,) = args
            c = self.cobros.get(caso_id)
            return dict(c) if c else None
        if q.startswith("UPDATE cobro_caso SET"):
            caso_id, valor_recuperado, honorarios = args
            registro = self.cobros.get(caso_id)
            if registro is None:
                return None
            registro["valor_recuperado"] = valor_recuperado
            registro["honorarios_liquidados"] = honorarios
            registro["liquidado_en"] = _ahora()
            return dict(registro)
        return None


_COLUMNAS_TEST = (
    "caso_id, valor_en_disputa, esquema_honorarios, monto_fijo, porcentaje_cuota_litis, "
    "valor_recuperado, honorarios_liquidados, liquidado_en, created_at, updated_at"
)


@pytest.fixture
def cdb():
    return _FakeCobroDB()


@pytest.fixture
def cclient(cdb):
    app = FastAPI()
    app.include_router(cobro_router)
    app.state.db_connection = cdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_get_cobro_sin_configurar_devuelve_nulls_no_404(cdb, cclient):
    cliente = cdb.seed_user(email="cliente1@vridik.local")
    caso = cdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = cclient.get(f"/casos/{caso['id']}/cobro", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["esquema_honorarios"] is None


def test_abogado_configura_esquema_cuota_litis(cdb, cclient):
    cliente = cdb.seed_user(email="cliente2@vridik.local")
    abogado = cdb.seed_user(email="abogado2@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"valor_en_disputa": "50000000", "esquema_honorarios": "cuota_litis", "porcentaje_cuota_litis": "20"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["esquema_honorarios"] == "cuota_litis"
    assert Decimal(body["porcentaje_cuota_litis"]) == Decimal("20")


def test_cliente_no_puede_configurar_cobro(cdb, cclient):
    cliente = cdb.seed_user(email="cliente3@vridik.local")
    caso = cdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "fijo", "monto_fijo": "1000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_cliente_puede_leer_cobro(cdb, cclient):
    cliente = cdb.seed_user(email="cliente4@vridik.local")
    abogado = cdb.seed_user(email="abogado4@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token_abogado = _token_de(abogado)
    token_cliente = _token_de(cliente)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "fijo", "monto_fijo": "2000000"},
        headers={"Authorization": f"Bearer {token_abogado}"},
    )

    r = cclient.get(f"/casos/{caso['id']}/cobro", headers={"Authorization": f"Bearer {token_cliente}"})
    assert r.status_code == 200
    assert r.json()["esquema_honorarios"] == "fijo"


def test_configurar_cuota_litis_sin_porcentaje_da_422(cdb, cclient):
    abogado = cdb.seed_user(email="abogado5@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente5@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "cuota_litis"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_liquidar_fijo_ignora_valor_recuperado_en_el_calculo(cdb, cclient):
    abogado = cdb.seed_user(email="abogado6@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente6@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "fijo", "monto_fijo": "3000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "99999999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["honorarios_liquidados"]) == Decimal("3000000")


def test_liquidar_cuota_litis_calcula_el_porcentaje(cdb, cclient):
    abogado = cdb.seed_user(email="abogado7@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente7@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "cuota_litis", "porcentaje_cuota_litis": "30"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "10000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["honorarios_liquidados"]) == Decimal("3000000.00")


def test_liquidar_mixto_suma_fijo_mas_porcentaje(cdb, cclient):
    abogado = cdb.seed_user(email="abogado8@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente8@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "mixto", "monto_fijo": "1000000", "porcentaje_cuota_litis": "10"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "5000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["honorarios_liquidados"]) == Decimal("1500000.00")


def test_liquidar_sin_esquema_configurado_da_422(cdb, cclient):
    abogado = cdb.seed_user(email="abogado9@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente9@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "1000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_liquidar_dos_veces_da_422_la_segunda(cdb, cclient):
    abogado = cdb.seed_user(email="abogado10@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cdb.seed_user(email="cliente10@vridik.local")["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "fijo", "monto_fijo": "500000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    primera = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "0"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert primera.status_code == 200, primera.text

    segunda = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "0"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert segunda.status_code == 422


def test_liquidar_lo_hace_solo_abogado_o_admin_no_cliente(cdb, cclient):
    cliente = cdb.seed_user(email="cliente11@vridik.local")
    abogado = cdb.seed_user(email="abogado11@vridik.local", role="abogado")
    caso = cdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token_abogado = _token_de(abogado)
    token_cliente = _token_de(cliente)

    cclient.post(
        f"/casos/{caso['id']}/cobro",
        json={"esquema_honorarios": "fijo", "monto_fijo": "100"},
        headers={"Authorization": f"Bearer {token_abogado}"},
    )
    r = cclient.post(
        f"/casos/{caso['id']}/cobro/liquidar",
        json={"valor_recuperado": "0"},
        headers={"Authorization": f"Bearer {token_cliente}"},
    )
    assert r.status_code == 403


def test_caso_inexistente_404(cdb, cclient):
    cliente = cdb.seed_user(email="cliente12@vridik.local")
    token = _token_de(cliente)

    r = cclient.get(f"/casos/{uuid.uuid4()}/cobro", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404
