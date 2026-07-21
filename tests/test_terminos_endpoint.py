"""
Vridik — tests/test_terminos_endpoint.py
Fase 2 (Copiloto Procesal): prueba api/terminos_endpoint.py +
core/terminos.py end-to-end (FastAPI TestClient) sobre un fake mínimo de
conexión asyncpg -- mismo estilo que tests/test_mensajes_endpoint.py.

No hay nada que mockear de Anthropic acá -- el vencimiento lo calcula
procesal/calendario_judicial.py (pura función, sin red), ya probado por
separado en tests/test_calendario_judicial.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.terminos_endpoint import router as terminos_router
from core.auth import create_jwt


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeTerminosDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.terminos: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": email, "role": role, "despacho_id": despacho_id, "es_superadmin": False,
        }
        return self.users[user_id]

    def seed_caso(self, *, cliente_id: str, abogado_id: str | None = None, despacho_id: str = "despacho-1") -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "despacho_id": despacho_id,
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
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.startswith("INSERT INTO terminos"):
            (caso_id, created_by, descripcion, fecha_inicio, dias_habiles,
             fecha_vencimiento, incluye_ventana_sin_confirmar, actuacion_id) = args
            termino_id = str(uuid.uuid4())
            termino = {
                "id": termino_id, "caso_id": caso_id, "created_by": created_by, "descripcion": descripcion,
                "fecha_inicio": fecha_inicio, "dias_habiles": dias_habiles,
                "fecha_vencimiento": fecha_vencimiento,
                "incluye_ventana_sin_confirmar": incluye_ventana_sin_confirmar,
                "actuacion_id": actuacion_id, "estado": "pendiente", "created_at": _ahora(),
            }
            self.terminos[termino_id] = termino
            return dict(termino)
        if q.strip() == "SELECT id, caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento, incluye_ventana_sin_confirmar, actuacion_id, estado, created_at FROM terminos WHERE id = $1":
            (termino_id,) = args
            t = self.terminos.get(termino_id)
            return dict(t) if t else None
        if q.startswith("UPDATE terminos SET estado"):
            termino_id, estado = args
            t = self.terminos.get(termino_id)
            if t is None:
                return None
            t["estado"] = estado
            return dict(t)
        return None

    async def fetch(self, query: str, *args):
        q = query.strip()
        if q.startswith("SELECT") and "FROM terminos WHERE caso_id" in q:
            (caso_id,) = args
            filas = [t for t in self.terminos.values() if t["caso_id"] == caso_id]
            filas.sort(key=lambda t: t["fecha_vencimiento"])
            return [dict(f) for f in filas]
        return []

    async def fetchval(self, query: str, *args):
        # core/health_score.py::recalcular_health_score -- este fake no
        # modela `actuaciones`, así que "sin actuaciones" es la única
        # respuesta posible acá (no afecta lo que estos tests verifican).
        q = query.strip()
        if "EXISTS(" in q:
            caso_id, hoy, ventana = args
            desde = hoy - timedelta(days=ventana)
            return any(
                t["caso_id"] == caso_id and t["estado"] == "pendiente"
                and t["fecha_vencimiento"] < hoy and t["fecha_vencimiento"] >= desde
                for t in self.terminos.values()
            )
        if "MIN(fecha_vencimiento)" in q:
            caso_id, hoy = args
            pendientes = [
                t for t in self.terminos.values() if t["caso_id"] == caso_id and t["estado"] == "pendiente"
            ]
            if not pendientes:
                return None
            return (min(t["fecha_vencimiento"] for t in pendientes) - hoy).days
        if "MAX(created_at) FROM actuaciones" in q:
            return None
        if "COUNT(*)" in q and "fecha_vencimiento <" in q:
            caso_id, hoy = args
            return sum(
                1 for t in self.terminos.values()
                if t["caso_id"] == caso_id and t["estado"] == "pendiente" and t["fecha_vencimiento"] < hoy
            )
        if "COUNT(*)" in q:
            (caso_id,) = args
            return sum(1 for t in self.terminos.values() if t["caso_id"] == caso_id)
        return None


@pytest.fixture
def tdb():
    return _FakeTerminosDB()


@pytest.fixture
def tclient(tdb):
    app = FastAPI()
    app.include_router(terminos_router)
    app.state.db_connection = tdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_crear_termino_calcula_el_vencimiento_nunca_lo_recibe_como_input(tdb, tclient):
    cliente = tdb.seed_user(email="cliente1@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "Contestar requerimiento UGPP", "fecha_inicio": "2026-02-02", "dias_habiles": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Lunes 2026-02-02 + 3 hábiles sin obstáculos -> jueves 2026-02-05
    # (mismo cálculo verificado en tests/test_calendario_judicial.py).
    assert body["fecha_vencimiento"] == "2026-02-05"
    assert body["estado"] == "pendiente"
    assert "dias_restantes" in body


def test_crear_termino_no_acepta_una_fecha_de_vencimiento_directa(tdb, tclient):
    """El request de creación no tiene ningún campo para proponer el
    vencimiento -- Pydantic lo ignora silenciosamente si alguien lo manda,
    pero el vencimiento real sigue siendo el calculado."""
    cliente = tdb.seed_user(email="cliente2@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={
            "descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 3,
            "fecha_vencimiento": "2099-01-01",  # ignorado -- no es un campo del modelo
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["fecha_vencimiento"] == "2026-02-05"


def test_crear_termino_dias_habiles_no_positivo_da_422(tdb, tclient):
    cliente = tdb.seed_user(email="cliente3@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_listar_terminos_ordena_por_vencimiento_e_incluye_dias_restantes(tdb, tclient):
    cliente = tdb.seed_user(email="cliente4@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "más lejano", "fecha_inicio": "2026-02-02", "dias_habiles": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "más cercano", "fecha_inicio": "2026-02-02", "dias_habiles": 1},
        headers={"Authorization": f"Bearer {token}"},
    )

    r = tclient.get(f"/casos/{caso['id']}/terminos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["descripcion"] == "más cercano"  # vence primero -> primero en la lista
    assert all("dias_restantes" in t for t in body)


def test_cambiar_estado_termino_a_cumplido(tdb, tclient):
    cliente = tdb.seed_user(email="cliente5@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    creado = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 1},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = tclient.patch(
        f"/casos/{caso['id']}/terminos/{creado['id']}/estado",
        json={"estado": "cumplido"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "cumplido"


def test_cambiar_estado_termino_invalido_da_422(tdb, tclient):
    cliente = tdb.seed_user(email="cliente6@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    creado = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 1},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = tclient.patch(
        f"/casos/{caso['id']}/terminos/{creado['id']}/estado",
        json={"estado": "vencido"},  # nunca un estado persistido válido, ver core/terminos.py
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_usuario_sin_relacion_al_caso_forbidden(tdb, tclient):
    cliente = tdb.seed_user(email="cliente_ajeno@vridik.local")
    otro = tdb.seed_user(email="otro@vridik.local")
    caso = tdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = tclient.post(
        f"/casos/{caso['id']}/terminos",
        json={"descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_caso_inexistente_404(tdb, tclient):
    cliente = tdb.seed_user(email="cliente_404@vridik.local")
    token = _token_de(cliente)

    r = tclient.post(
        f"/casos/{uuid.uuid4()}/terminos",
        json={"descripcion": "x", "fecha_inicio": "2026-02-02", "dias_habiles": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
