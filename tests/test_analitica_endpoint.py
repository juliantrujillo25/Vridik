"""
Vridik — tests/test_analitica_endpoint.py
Fase 4 (roadmap: "línea decisional UGPP"): api/analitica_endpoint.py
end-to-end (FastAPI TestClient) sobre un fake mínimo -- mismo estilo que
tests/test_clientes_endpoint.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.analitica_endpoint import router as analitica_router
from core.auth import create_jwt


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class _FakeAnaliticaDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.actuaciones: dict[str, dict] = {}
        self.cobros: dict[str, dict] = {}  # keyed by caso_id

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "role": role, "despacho_id": despacho_id, "es_superadmin": False,
        }
        return self.users[user_id]

    def seed_caso(self, *, despacho_id: str = "despacho-1", materia: str | None = "ugpp", created_at: datetime | None = None) -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "despacho_id": despacho_id, "materia": materia, "created_at": created_at or _ahora(),
        }
        return self.casos[caso_id]

    def seed_actuacion(
        self, *, caso_id: str, categoria: str = "fallo", resultado: str | None = None,
        tipo_resolucion_ugpp: str | None = None, created_at: datetime | None = None,
    ) -> dict:
        actuacion_id = str(uuid.uuid4())
        self.actuaciones[actuacion_id] = {
            "id": actuacion_id, "caso_id": caso_id, "categoria": categoria, "resultado": resultado,
            "tipo_resolucion_ugpp": tipo_resolucion_ugpp, "created_at": created_at or _ahora(),
        }
        return self.actuaciones[actuacion_id]

    def seed_cobro(self, *, caso_id: str, valor_recuperado: float | None, liquidado: bool = True) -> None:
        self.cobros[caso_id] = {"valor_recuperado": valor_recuperado, "liquidado_en": _ahora() if liquidado else None}

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchval(self, query: str, *args):
        q = query.strip()
        if q == "SELECT count(*) FROM casos WHERE despacho_id = $1 AND materia = 'ugpp'":
            (despacho_id,) = args
            return sum(1 for c in self.casos.values() if c["despacho_id"] == despacho_id and c["materia"] == "ugpp")
        return None

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if "FROM actuaciones a" in q and "JOIN casos c" in q:
            (despacho_id,) = args
            filas = []
            for a in self.actuaciones.values():
                c = self.casos.get(a["caso_id"])
                if c and c["despacho_id"] == despacho_id and c["materia"] == "ugpp" and a["categoria"] == "fallo":
                    filas.append({
                        "resultado": a["resultado"], "tipo_resolucion_ugpp": a["tipo_resolucion_ugpp"],
                        "fallo_created_at": a["created_at"], "caso_created_at": c["created_at"],
                    })
            return filas
        if "FROM cobro_caso cb" in q:
            (despacho_id,) = args
            filas = []
            for caso_id, cb in self.cobros.items():
                c = self.casos.get(caso_id)
                if c and c["despacho_id"] == despacho_id and c["materia"] == "ugpp" and cb["liquidado_en"] is not None:
                    filas.append({"valor_recuperado": cb["valor_recuperado"]})
            return filas
        return []


@pytest.fixture
def adb():
    return _FakeAnaliticaDB()


@pytest.fixture
def aclient(adb):
    app = FastAPI()
    app.include_router(analitica_router)
    app.state.db_connection = adb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_cliente_no_puede_ver_la_analitica(adb, aclient):
    cliente = adb.seed_user(email="cliente1@vridik.local")
    r = aclient.get("/analitica/ugpp", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 403


def test_analitica_vacia_sin_casos_ugpp(adb, aclient):
    abogado = adb.seed_user(email="abogado1@vridik.local", role="abogado")
    r = aclient.get("/analitica/ugpp", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_casos_ugpp"] == 0
    assert data["tasa_exito"] is None
    assert data["por_tipo_resolucion"] == []


def test_analitica_agrega_resultados_y_calcula_tasa_de_exito(adb, aclient):
    abogado = adb.seed_user(email="abogado2@vridik.local", role="abogado")

    caso1 = adb.seed_caso(created_at=_ahora() - timedelta(days=10))
    adb.seed_actuacion(caso_id=caso1["id"], resultado="favorable", tipo_resolucion_ugpp="RQI")

    caso2 = adb.seed_caso(created_at=_ahora() - timedelta(days=20))
    adb.seed_actuacion(caso_id=caso2["id"], resultado="desfavorable", tipo_resolucion_ugpp="RQI")

    caso3 = adb.seed_caso()
    adb.seed_actuacion(caso_id=caso3["id"], categoria="fallo", resultado=None)  # sin resultado todavía

    r = aclient.get("/analitica/ugpp", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_casos_ugpp"] == 3
    assert data["total_fallos_registrados"] == 3
    assert data["total_con_resultado"] == 2
    assert data["conteo_por_resultado"] == {"favorable": 1, "desfavorable": 1, "parcial": 0}
    assert data["tasa_exito"] == pytest.approx(0.5)
    assert data["por_tipo_resolucion"] == [
        {"tipo_resolucion_ugpp": "RQI", "total": 2, "favorable": 1, "desfavorable": 1, "parcial": 0}
    ]


def test_analitica_no_mezcla_despachos(adb, aclient):
    abogado_a = adb.seed_user(email="abogado3@vridik.local", role="abogado", despacho_id="despacho-a")
    caso_b = adb.seed_caso(despacho_id="despacho-b")
    adb.seed_actuacion(caso_id=caso_b["id"], resultado="favorable")

    r = aclient.get("/analitica/ugpp", headers={"Authorization": f"Bearer {_token_de(abogado_a)}"})
    assert r.status_code == 200, r.text
    assert r.json()["total_casos_ugpp"] == 0


def test_analitica_suma_valor_recuperado(adb, aclient):
    abogado = adb.seed_user(email="abogado4@vridik.local", role="abogado")
    caso = adb.seed_caso()
    adb.seed_cobro(caso_id=caso["id"], valor_recuperado=5_000_000)

    r = aclient.get("/analitica/ugpp", headers={"Authorization": f"Bearer {_token_de(abogado)}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["casos_liquidados"] == 1
    assert data["valor_recuperado_total"] == pytest.approx(5_000_000)
