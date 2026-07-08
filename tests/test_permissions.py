"""
Vridik — tests/test_permissions.py (Sprint S6)
Prueba el RBAC más fino (core/permissions.py) sobre api/seller_endpoint.py
y las restricciones nuevas de api/admin_endpoint.py::get_current_seller —
end-to-end (FastAPI TestClient) sobre un fake mínimo de conexión asyncpg,
mismo estilo que tests/test_products.py y tests/test_orders.py.
"""

from __future__ import annotations

import os
import uuid

# Igual que el resto de tests/test_*.py: JWT_SECRET debe existir ANTES de
# importar core.auth (vía api.admin_endpoint/api.seller_endpoint).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_endpoint import router as admin_router
from api.seller_endpoint import router as seller_router
from core.auth import create_jwt
from core.product import CAMPOS_ACTUALIZABLES


class _FakePermissionsDB:
    """Fake de `users` (con role: admin/seller/customer, S6) + `products`
    (S3) + `orders`/`order_items` (S4) — soporta también las queries con
    JOIN de core.order.list_orders_for_seller/order_has_seller_product."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.order_items: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "customer") -> dict:
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

    def seed_order_with_item(
        self, *, user_id: str, product_id: str, quantity: int = 1, price_cents: int = 1000,
        status: str = "pending",
    ) -> dict:
        order_id = str(uuid.uuid4())
        self.orders[order_id] = {
            "id": order_id, "user_id": user_id, "status": status, "total_cents": price_cents * quantity,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        item_id = str(uuid.uuid4())
        self.order_items[item_id] = {
            "id": item_id, "order_id": order_id, "product_id": product_id,
            "quantity": quantity, "price_cents": price_cents,
        }
        return self.orders[order_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "SELECT id FROM products WHERE sku" in query:
            (sku,) = args
            return next(({"id": p["id"]} for p in self.products.values() if p["sku"] == sku), None)
        if "INSERT INTO products" in query and "RETURNING" in query:
            sku, name, description, price_cents, stock, seller_id, category, city = args
            product_id = str(uuid.uuid4())
            nuevo = {
                "id": product_id, "sku": sku, "name": name, "description": description,
                "price_cents": price_cents, "stock": stock, "is_active": True, "seller_id": seller_id,
                "category": category, "city": city,
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.products[product_id] = nuevo
            return dict(nuevo)
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
        if query.strip().startswith("SELECT EXISTS("):
            order_id, seller_id = args
            existe = any(
                item["order_id"] == order_id and self.products.get(item["product_id"], {}).get("seller_id") == seller_id
                for item in self.order_items.values()
            )
            return {"existe": existe}
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        if "FROM orders WHERE id" in query:
            (order_id,) = args
            o = self.orders.get(order_id)
            return dict(o) if o else None
        return None

    async def fetch(self, query: str, *args):
        if "JOIN order_items" in query and "JOIN products" in query and "FROM orders" in query:
            seller_id, skip, limit = args
            vistos: set[str] = set()
            resultado = []
            for item in self.order_items.values():
                producto = self.products.get(item["product_id"])
                if producto is None or producto["seller_id"] != seller_id:
                    continue
                orden = self.orders.get(item["order_id"])
                if orden is None or orden["id"] in vistos:
                    continue
                vistos.add(orden["id"])
                resultado.append(orden)
            resultado.sort(key=lambda o: o["created_at"], reverse=True)
            return [dict(o) for o in resultado[skip:skip + limit]]
        if "FROM products" in query and "JOIN" not in query:
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
        if "FROM order_items WHERE order_id" in query:
            (order_id,) = args
            items = [i for i in self.order_items.values() if i["order_id"] == order_id]
            return [dict(i) for i in items]
        return []


@pytest.fixture
def perms_db():
    return _FakePermissionsDB()


@pytest.fixture
def perms_client(perms_db):
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(seller_router)
    app.state.db_connection = perms_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_seller_cannot_update_other_seller_product(perms_db, perms_client):
    dueño = perms_db.seed_user(email="dueño@vridik.local", role="seller")
    otro = perms_db.seed_user(email="otro@vridik.local", role="seller")
    producto = perms_db.seed_product(seller_id=dueño["id"], sku="SKU-P1")
    token = _token_de(otro)

    r = perms_client.patch(
        f"/seller/products/{producto['id']}", json={"stock": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_seller_can_create_and_update_own_product(perms_db, perms_client):
    seller = perms_db.seed_user(email="seller1@vridik.local", role="seller")
    token = _token_de(seller)

    r = perms_client.post(
        "/seller/products",
        json={"sku": "SKU-P2", "name": "Producto propio", "price_cents": 2000, "stock": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["seller_id"] == seller["id"]

    r = perms_client.patch(
        f"/seller/products/{body['id']}", json={"stock": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stock"] == 50


def test_seller_can_list_only_own_products(perms_db, perms_client):
    seller1 = perms_db.seed_user(email="seller2@vridik.local", role="seller")
    seller2 = perms_db.seed_user(email="seller3@vridik.local", role="seller")
    perms_db.seed_product(seller_id=seller1["id"], sku="SKU-P3")
    perms_db.seed_product(seller_id=seller2["id"], sku="SKU-P4")
    token = _token_de(seller1)

    r = perms_client.get("/seller/products", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["sku"] == "SKU-P3"


def test_seller_can_list_orders_with_own_product(perms_db, perms_client):
    seller = perms_db.seed_user(email="seller4@vridik.local", role="seller")
    buyer = perms_db.seed_user(email="buyer1@vridik.local", role="customer")
    producto = perms_db.seed_product(seller_id=seller["id"], sku="SKU-P5", price_cents=1500)
    perms_db.seed_order_with_item(user_id=buyer["id"], product_id=producto["id"], quantity=2, price_cents=1500)
    token = _token_de(seller)

    r = perms_client.get("/seller/orders", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["user_id"] == buyer["id"]


def test_customer_cannot_access_seller_routes(perms_db, perms_client):
    customer = perms_db.seed_user(email="customer1@vridik.local", role="customer")
    token = _token_de(customer)

    r = perms_client.get("/seller/products", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_customer_cannot_access_admin_routes(perms_db, perms_client):
    customer = perms_db.seed_user(email="customer2@vridik.local", role="customer")
    token = _token_de(customer)

    r = perms_client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
