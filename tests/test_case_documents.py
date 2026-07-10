"""
Vridik — tests/test_case_documents.py
Prueba api/case_documents_endpoint.py: generación de documentos de caso
con JuliX, sobre las dos rutas de anclaje que conviven (core/case.py
`casos`, nueva y preferida; `orders` del marketplace, original, se
mantiene por compatibilidad). Mismo patrón que tests/test_julix_stream.py
(JuliXService se monkeypatchea con un fake `generar_documento` async
generator) + tests/test_payments.py (fake mínimo de conexión asyncpg con
users/orders/casos/ownership) — no se toca Anthropic ni PostgreSQL reales.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.case_documents_endpoint as case_documents_module
from api.case_documents_endpoint import router as case_documents_router
from api.casos_endpoint import router as casos_router
from core.auth import create_jwt


class _FakeCaseDocumentsDB:
    """Fake de `users` (role) + `orders` (S4) + `casos` (consolidación) +
    `case_documents`. `seed_order(seller_id=...)` simula que la orden
    tiene un order_item de un producto de ese seller (sin modelar
    order_items/products completos, solo lo que order_has_seller_product()
    necesita)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.order_seller: dict[str, str] = {}
        self.casos: dict[str, dict] = {}
        self.case_documents: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "cliente") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_order(self, *, user_id: str, seller_id: str | None = None, status: str = "paid") -> dict:
        order_id = str(uuid.uuid4())
        self.orders[order_id] = {
            "id": order_id, "user_id": user_id, "status": status, "total_cents": 10000,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        if seller_id is not None:
            self.order_seller[order_id] = seller_id
        return self.orders[order_id]

    def seed_caso(self, *, cliente_id: str, abogado_id: str | None = None, titulo: str = "Caso de prueba") -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "titulo": titulo,
            "descripcion": None, "estado": "abierto",
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
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
        if q.startswith("SELECT EXISTS(") and "order_items" in q:
            order_id, seller_id = args
            existe = self.order_seller.get(order_id) == seller_id
            return {"existe": existe}
        if "FROM orders WHERE id" in q:
            (order_id,) = args
            o = self.orders.get(order_id)
            return dict(o) if o else None
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.startswith("INSERT INTO case_documents"):
            order_id, caso_id, created_by, tarea, pregunta, contenido, pdf_url = args
            doc_id = str(uuid.uuid4())
            documento = {
                "id": doc_id, "order_id": order_id, "caso_id": caso_id, "created_by": created_by, "tarea": tarea,
                "pregunta": pregunta, "contenido": contenido, "pdf_url": pdf_url,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            self.case_documents[doc_id] = documento
            return dict(documento)
        if q.startswith("SELECT") and "FROM case_documents WHERE id" in q:
            (doc_id,) = args
            d = self.case_documents.get(doc_id)
            return dict(d) if d else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM case_documents" in query and "WHERE caso_id" in query:
            (caso_id,) = args
            filas = [d for d in self.case_documents.values() if d["caso_id"] == caso_id]
            filas.sort(key=lambda d: d["created_at"], reverse=True)
            return [{k: v for k, v in f.items() if k != "contenido"} for f in filas]
        if "FROM case_documents" in query and "WHERE order_id" in query:
            (order_id,) = args
            filas = [d for d in self.case_documents.values() if d["order_id"] == order_id]
            filas.sort(key=lambda d: d["created_at"], reverse=True)
            return [{k: v for k, v in f.items() if k != "contenido"} for f in filas]
        return []


class _FakeJuliXServiceOK:
    def __init__(self, **kwargs):
        pass

    async def generar_documento(self, **kwargs):
        for fragmento in ["Primero. ", "Segundo."]:
            yield fragmento


@pytest.fixture(autouse=True)
def _fake_julix(monkeypatch):
    """Nunca se llama a Anthropic real: JuliXClient/JuliXService quedan
    reemplazados por fakes — mismo patrón que tests/test_julix_stream.py."""
    monkeypatch.setattr(case_documents_module, "JuliXClient", lambda **kwargs: object())
    monkeypatch.setattr(case_documents_module, "JuliXService", _FakeJuliXServiceOK)


@pytest.fixture
def cd_db():
    return _FakeCaseDocumentsDB()


@pytest.fixture
def cd_client(cd_db):
    app = FastAPI()
    app.include_router(casos_router)
    app.include_router(case_documents_router)
    app.state.db_connection = cd_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


# ---------------------------------------------------------------------
# Ruta original: /orders/{order_id}/documents (compatibilidad)
# ---------------------------------------------------------------------
def test_owner_can_create_document(cd_db, cd_client):
    buyer = cd_db.seed_user(email="cliente@vridik.local")
    orden = cd_db.seed_order(user_id=buyer["id"])
    token = _token_de(buyer)

    r = cd_client.post(
        f"/orders/{orden['id']}/documents",
        json={"pregunta": "¿Qué aportes debo declarar a la UGPP?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contenido"] == "Primero. Segundo."
    assert body["pdf_url"] is None
    assert body["order_id"] == orden["id"]


def test_seller_of_order_can_create_document(cd_db, cd_client):
    buyer = cd_db.seed_user(email="cliente2@vridik.local")
    seller = cd_db.seed_user(email="seller@vridik.local", role="abogado")
    orden = cd_db.seed_order(user_id=buyer["id"], seller_id=seller["id"])
    token = _token_de(seller)

    r = cd_client.post(
        f"/orders/{orden['id']}/documents",
        json={"pregunta": "¿Cómo respondo un requerimiento de la UGPP?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_unrelated_user_forbidden(cd_db, cd_client):
    buyer = cd_db.seed_user(email="cliente3@vridik.local")
    otro = cd_db.seed_user(email="otro@vridik.local")
    orden = cd_db.seed_order(user_id=buyer["id"])
    token = _token_de(otro)

    r = cd_client.post(
        f"/orders/{orden['id']}/documents",
        json={"pregunta": "texto"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_can_list_and_get_document(cd_db, cd_client):
    buyer = cd_db.seed_user(email="cliente4@vridik.local")
    admin = cd_db.seed_user(email="admin@vridik.local", role="admin")
    orden = cd_db.seed_order(user_id=buyer["id"])
    buyer_token = _token_de(buyer)
    admin_token = _token_de(admin)

    creado = cd_client.post(
        f"/orders/{orden['id']}/documents",
        json={"pregunta": "texto"},
        headers={"Authorization": f"Bearer {buyer_token}"},
    ).json()

    r_list = cd_client.get(f"/orders/{orden['id']}/documents", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1
    assert "contenido" not in r_list.json()[0]

    r_get = cd_client.get(
        f"/orders/{orden['id']}/documents/{creado['id']}", headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_get.status_code == 200
    assert r_get.json()["contenido"] == "Primero. Segundo."


def test_order_not_found_returns_404(cd_db, cd_client):
    buyer = cd_db.seed_user(email="cliente5@vridik.local")
    token = _token_de(buyer)

    r = cd_client.post(
        f"/orders/{uuid.uuid4()}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------
# Ruta nueva: /casos/{caso_id}/documents (independiente del marketplace)
# ---------------------------------------------------------------------
def test_cliente_of_caso_can_create_document(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso1@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents",
        json={"pregunta": "¿Qué aportes debo declarar a la UGPP?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contenido"] == "Primero. Segundo."
    assert body["caso_id"] == caso["id"]
    assert body["order_id"] is None


def test_abogado_asignado_puede_crear_documento(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso2@vridik.local")
    abogado = cd_db.seed_user(email="abogado_caso2@vridik.local", role="abogado")
    caso = cd_db.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_usuario_sin_relacion_al_caso_forbidden(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso3@vridik.local")
    otro = cd_db.seed_user(email="otro_caso3@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_puede_listar_y_ver_documento_de_caso(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso4@vridik.local")
    admin = cd_db.seed_user(email="admin_caso4@vridik.local", role="admin")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    cliente_token = _token_de(cliente)
    admin_token = _token_de(admin)

    creado = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"},
        headers={"Authorization": f"Bearer {cliente_token}"},
    ).json()

    r_list = cd_client.get(f"/casos/{caso['id']}/documents", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1
    assert "contenido" not in r_list.json()[0]

    r_get = cd_client.get(
        f"/casos/{caso['id']}/documents/{creado['id']}", headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_get.status_code == 200
    assert r_get.json()["contenido"] == "Primero. Segundo."


def test_caso_not_found_returns_404(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso5@vridik.local")
    token = _token_de(cliente)

    r = cd_client.post(
        f"/casos/{uuid.uuid4()}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
