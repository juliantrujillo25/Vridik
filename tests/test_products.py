"""
Vridik — tests/test_products.py (Sprint S3)
Prueba api/products_endpoint.py (público) y las rutas /admin/products de
api/admin_endpoint.py (S2) end-to-end (FastAPI TestClient) sobre un fake
mínimo de conexión asyncpg — mismo estilo que tests/test_admin.py.
"""

from __future__ import annotations

import os
import uuid

# Igual que tests/test_auth.py y tests/test_admin.py: JWT_SECRET debe existir
# ANTES de importar core.auth (vía api.admin_endpoint/api.products_endpoint).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_endpoint import router as admin_router
from api.products_endpoint import router as products_router
from core.auth import create_jwt
from core.product import CAMPOS_ACTUALIZABLES


class _FakeProductsDB:
    """Fake de `users` (con `role`, S2) + `products` (S3)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.products: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "seller") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_product(
        self, *, seller_id: str, sku: str, name: str = "Producto de prueba",
        price_cents: int = 1000, stock: int = 5, is_active: bool = True,
    ) -> dict:
        product_id = str(uuid.uuid4())
        self.products[product_id] = {
            "id": product_id, "sku": sku, "name": name, "description": "desc",
            "price_cents": price_cents, "stock": stock, "is_active": is_active,
            "seller_id": seller_id,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return self.products[product_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "SELECT role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"role": u["role"]} if u else None
        if "SELECT id FROM products WHERE sku" in query:
            (sku,) = args
            return next(({"id": p["id"]} for p in self.products.values() if p["sku"] == sku), None)
        if "INSERT INTO products" in query and "RETURNING" in query:
            sku, name, description, price_cents, stock, seller_id = args
            nuevo = self.seed_product(seller_id=seller_id, sku=sku, name=name, price_cents=price_cents, stock=stock)
            nuevo["description"] = description
            return dict(nuevo)
        if "UPDATE products SET is_active = false" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            if p is None:
                return None
            p["is_active"] = False
            return dict(p)
        if query.strip().startswith("UPDATE products SET"):
            product_id, *valores = args
            p = self.products.get(product_id)
            if p is None:
                return None
            restantes = list(valores)
            for campo in CAMPOS_ACTUALIZABLES:
                if f"{campo} = $" in query:
                    p[campo] = restantes.pop(0)
            return dict(p)
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM products" in query:
            active_only, q, seller_id, skip, limit = args
            productos = list(self.products.values())
            if active_only:
                productos = [p for p in productos if p["is_active"]]
            if q:
                q_lower = q.lower()
                productos = [p for p in productos if q_lower in p["name"].lower() or q_lower in p["sku"].lower()]
            if seller_id:
                productos = [p for p in productos if p["seller_id"] == seller_id]
            productos = sorted(productos, key=lambda p: p["created_at"], reverse=True)
            return [dict(p) for p in productos[skip:skip + limit]]
        return []


@pytest.fixture
def products_db():
    return _FakeProductsDB()


@pytest.fixture
def products_client(products_db):
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(products_router)
    app.state.db_connection = products_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_public_list_products_ok(products_db, products_client):
    seller = products_db.seed_user(email="vendedor@vridik.local", role="seller")
    products_db.seed_product(seller_id=seller["id"], sku="SKU-1", name="Camiseta")
    products_db.seed_product(seller_id=seller["id"], sku="SKU-2", name="Pantalón", is_active=False)

    r = products_client.get("/products")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1  # el inactivo no aparece
    assert set(body[0].keys()) == {"id", "sku", "name", "price_cents", "stock"}


def test_public_get_product_ok(products_db, products_client):
    seller = products_db.seed_user(email="vendedor2@vridik.local", role="seller")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-3", name="Zapatos")

    r = products_client.get(f"/products/{producto['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sku"] == "SKU-3"
    assert body["description"] == "desc"


def test_admin_create_product(products_db, products_client):
    admin = products_db.seed_user(email="admin@vridik.local", role="admin")
    seller = products_db.seed_user(email="vendedor3@vridik.local", role="seller")
    token = _token_de(admin)

    r = products_client.post(
        "/admin/products",
        json={
            "sku": "SKU-NEW", "name": "Producto nuevo", "description": "Descripción",
            "price_cents": 5000, "stock": 10, "seller_id": seller["id"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sku"] == "SKU-NEW"
    assert body["seller_id"] == seller["id"]


def test_seller_update_own_product_ok(products_db, products_client):
    seller = products_db.seed_user(email="vendedor4@vridik.local", role="seller")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-4")
    token = _token_de(seller)

    r = products_client.patch(
        f"/admin/products/{producto['id']}", json={"stock": 99},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stock"] == 99


def test_seller_update_other_product_forbidden(products_db, products_client):
    dueño = products_db.seed_user(email="dueño@vridik.local", role="seller")
    otro_seller = products_db.seed_user(email="otro@vridik.local", role="seller")
    producto = products_db.seed_product(seller_id=dueño["id"], sku="SKU-5")
    token = _token_de(otro_seller)

    r = products_client.patch(
        f"/admin/products/{producto['id']}", json={"stock": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_soft_delete(products_db, products_client):
    admin = products_db.seed_user(email="admin2@vridik.local", role="admin")
    seller = products_db.seed_user(email="vendedor5@vridik.local", role="seller")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-6")
    token = _token_de(admin)

    r = products_client.delete(
        f"/admin/products/{producto['id']}", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204
    assert products_db.products[producto["id"]]["is_active"] is False

    # El catálogo público ya no lo lista.
    r = products_client.get("/products")
    assert producto["id"] not in [p["id"] for p in r.json()]
