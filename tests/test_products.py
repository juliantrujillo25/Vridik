"""
Vridik — tests/test_products.py (Sprint S3)
Prueba api/products_endpoint.py (catálogo público, sin JWT obligatorio)
end-to-end (FastAPI TestClient) sobre un fake mínimo de conexión asyncpg.

Desmantelamiento del marketplace (fase 2): las rutas /admin/products
(crear/editar/soft-delete) se quitaron de api/admin_endpoint.py — este
archivo dejó de probarlas junto con ellas.
"""

from __future__ import annotations

import os
import uuid

# Igual que tests/test_auth.py y tests/test_admin.py: JWT_SECRET debe existir
# ANTES de importar core.auth (vía api.products_endpoint).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.products_endpoint import router as products_router
from core.auth import create_jwt


class _FakeProductsDB:
    """Fake de `users` (con `role`, S2) + `products` (S3)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.products: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "abogado") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_product(
        self, *, seller_id: str, sku: str, name: str = "Producto de prueba",
        price_cents: int = 1000, stock: int = 5, is_active: bool = True,
        category: str | None = None, city: str | None = None,
    ) -> dict:
        product_id = str(uuid.uuid4())
        self.products[product_id] = {
            "id": product_id, "sku": sku, "name": name, "description": "desc",
            "price_cents": price_cents, "stock": stock, "is_active": is_active,
            "seller_id": seller_id, "category": category, "city": city,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return self.products[product_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"role": u["role"]} if u else None
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM products" in query:
            active_only, q, seller_id, category, city, min_price, max_price, skip, limit = args
            productos = list(self.products.values())
            if active_only:
                productos = [p for p in productos if p["is_active"]]
            if q:
                q_lower = q.lower()
                productos = [p for p in productos if q_lower in p["name"].lower() or q_lower in p["sku"].lower()]
            if seller_id:
                productos = [p for p in productos if p["seller_id"] == seller_id]
            if category:
                productos = [p for p in productos if p.get("category") == category]
            if city:
                productos = [p for p in productos if (p.get("city") or "").lower() == city.lower()]
            if min_price is not None:
                productos = [p for p in productos if p["price_cents"] >= min_price]
            if max_price is not None:
                productos = [p for p in productos if p["price_cents"] <= max_price]
            productos = sorted(productos, key=lambda p: p["created_at"], reverse=True)
            return [dict(p) for p in productos[skip:skip + limit]]
        return []


@pytest.fixture
def products_db():
    return _FakeProductsDB()


@pytest.fixture
def products_client(products_db):
    app = FastAPI()
    app.include_router(products_router)
    app.state.db_connection = products_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_public_list_products_ok(products_db, products_client):
    seller = products_db.seed_user(email="vendedor@vridik.local", role="abogado")
    products_db.seed_product(seller_id=seller["id"], sku="SKU-1", name="Camiseta")
    products_db.seed_product(seller_id=seller["id"], sku="SKU-2", name="Pantalón", is_active=False)

    r = products_client.get("/products")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1  # el inactivo no aparece
    assert set(body[0].keys()) == {"id", "sku", "name", "price_cents", "stock", "category", "city", "images"}


def test_public_get_product_ok(products_db, products_client):
    seller = products_db.seed_user(email="vendedor2@vridik.local", role="abogado")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-3", name="Zapatos")

    r = products_client.get(f"/products/{producto['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sku"] == "SKU-3"
    assert body["description"] == "desc"


def test_public_get_inactive_product_404_para_anonimo(products_db, products_client):
    seller = products_db.seed_user(email="vendedor6@vridik.local", role="abogado")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-7", is_active=False)

    r = products_client.get(f"/products/{producto['id']}")
    assert r.status_code == 404


def test_admin_puede_ver_producto_inactivo(products_db, products_client):
    admin = products_db.seed_user(email="admin7@vridik.local", role="admin")
    seller = products_db.seed_user(email="vendedor8@vridik.local", role="abogado")
    producto = products_db.seed_product(seller_id=seller["id"], sku="SKU-8", is_active=False)

    r = products_client.get(
        f"/products/{producto['id']}", headers={"Authorization": f"Bearer {_token_de(admin)}"},
    )
    assert r.status_code == 200, r.text
