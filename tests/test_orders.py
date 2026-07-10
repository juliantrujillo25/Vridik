"""
Vridik — tests/test_orders.py (Sprint S4)
Prueba api/orders_endpoint.py (checkout/me/detalle) y las rutas
/admin/orders de api/admin_endpoint.py end-to-end (FastAPI TestClient) sobre
un fake mínimo de conexión asyncpg — mismo estilo que tests/test_products.py.
"""

from __future__ import annotations

import os
import uuid

# Igual que tests/test_auth.py, test_admin.py, test_products.py: JWT_SECRET
# debe existir ANTES de importar core.auth (vía api.admin_endpoint/
# api.orders_endpoint).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_endpoint import router as admin_router
from api.orders_endpoint import router as orders_router
from core.auth import create_jwt


class _DummyTx:
    """`db_connection.transaction()` no necesita rollback real en el fake:
    core.order.create_order() solo empieza a escribir DESPUÉS de validar
    todo el carrito, así que si algo falla nunca se llegó a escribir nada."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeOrdersDB:
    """Fake de `users` (con role, S2) + `products` (S3) + `orders`/`order_items` (S4)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.order_items: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "abogado") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_product(
        self, *, seller_id: str, sku: str, name: str = "Producto de prueba",
        price_cents: int = 1000, stock: int = 5, is_active: bool = True,
    ) -> dict:
        product_id = str(uuid.uuid4())
        self.products[product_id] = {
            "id": product_id, "sku": sku, "name": name, "price_cents": price_cents,
            "stock": stock, "is_active": is_active, "seller_id": seller_id,
        }
        return self.products[product_id]

    def transaction(self):
        return _DummyTx()

    async def execute(self, query: str, *args):
        if "UPDATE products SET stock = stock - " in query:
            product_id, cantidad = args
            self.products[product_id]["stock"] -= cantidad
            return "UPDATE 1"
        if "UPDATE products SET stock = stock + " in query:
            product_id, cantidad = args
            self.products[product_id]["stock"] += cantidad
            return "UPDATE 1"
        if "INSERT INTO order_items" in query:
            order_id, product_id, cantidad, price_cents = args
            item_id = str(uuid.uuid4())
            self.order_items[item_id] = {
                "id": item_id, "order_id": order_id, "product_id": product_id,
                "quantity": cantidad, "price_cents": price_cents,
            }
            return "INSERT 1"
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "SELECT id, price_cents, stock, is_active FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            if p is None:
                return None
            return {"id": p["id"], "price_cents": p["price_cents"], "stock": p["stock"], "is_active": p["is_active"]}
        if "INSERT INTO orders" in query and "RETURNING" in query:
            user_id, total_cents = args
            order_id = str(uuid.uuid4())
            orden = {
                "id": order_id, "user_id": user_id, "status": "pending", "total_cents": total_cents,
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.orders[order_id] = orden
            return dict(orden)
        if query.strip().startswith("UPDATE orders SET status"):
            order_id, nuevo_status = args
            o = self.orders.get(order_id)
            if o is None:
                return None
            o["status"] = nuevo_status
            return dict(o)
        if "FROM orders WHERE id" in query:
            (order_id,) = args
            o = self.orders.get(order_id)
            return dict(o) if o else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM orders" in query and "WHERE user_id" in query:
            user_id, skip, limit = args
            ordenes = [o for o in self.orders.values() if o["user_id"] == user_id]
            ordenes = sorted(ordenes, key=lambda o: o["created_at"], reverse=True)
            return [dict(o) for o in ordenes[skip:skip + limit]]
        if "FROM orders" in query and "status = $1" in query:
            status, skip, limit = args
            ordenes = list(self.orders.values())
            if status:
                ordenes = [o for o in ordenes if o["status"] == status]
            ordenes = sorted(ordenes, key=lambda o: o["created_at"], reverse=True)
            return [dict(o) for o in ordenes[skip:skip + limit]]
        if "FROM order_items WHERE order_id" in query:
            (order_id,) = args
            items = [i for i in self.order_items.values() if i["order_id"] == order_id]
            return [dict(i) for i in items]
        return []


@pytest.fixture
def orders_db():
    return _FakeOrdersDB()


@pytest.fixture
def orders_client(orders_db):
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(orders_router)
    app.state.db_connection = orders_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_checkout_creates_order_and_decrements_stock(orders_db, orders_client):
    seller = orders_db.seed_user(email="seller_a@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_a@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-A", price_cents=1500, stock=10)
    token = _token_de(buyer)

    r = orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 3}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_cents"] == 4500
    assert body["status"] == "pending"
    assert orders_db.products[producto["id"]]["stock"] == 7


def test_checkout_insufficient_stock_fails(orders_db, orders_client):
    seller = orders_db.seed_user(email="seller_b@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_b@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-B", stock=2)
    token = _token_de(buyer)

    r = orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 5}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert orders_db.products[producto["id"]]["stock"] == 2  # nunca se tocó
    assert len(orders_db.orders) == 0  # tampoco se creó la orden


def test_user_can_list_own_orders(orders_db, orders_client):
    seller = orders_db.seed_user(email="seller_c@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_c@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-C", stock=10)
    token = _token_de(buyer)

    orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 1}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = orders_client.get("/orders/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["user_id"] == buyer["id"]


def test_user_cannot_see_other_order(orders_db, orders_client):
    seller = orders_db.seed_user(email="seller_d@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_d@vridik.local", role="abogado")
    otro = orders_db.seed_user(email="otro_d@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-D", stock=10)

    r = orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 1}]},
        headers={"Authorization": f"Bearer {_token_de(buyer)}"},
    )
    order_id = r.json()["order_id"]

    r = orders_client.get(f"/orders/{order_id}", headers={"Authorization": f"Bearer {_token_de(otro)}"})
    assert r.status_code == 403


def test_admin_can_list_all_orders(orders_db, orders_client):
    admin = orders_db.seed_user(email="admin_e@vridik.local", role="admin")
    seller = orders_db.seed_user(email="seller_e@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_e@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-E", stock=10)

    orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 1}]},
        headers={"Authorization": f"Bearer {_token_de(buyer)}"},
    )
    r = orders_client.get("/admin/orders", headers={"Authorization": f"Bearer {_token_de(admin)}"})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_admin_can_update_status_and_restore_stock_on_cancel(orders_db, orders_client):
    admin = orders_db.seed_user(email="admin_f@vridik.local", role="admin")
    seller = orders_db.seed_user(email="seller_f@vridik.local", role="abogado")
    buyer = orders_db.seed_user(email="buyer_f@vridik.local", role="abogado")
    producto = orders_db.seed_product(seller_id=seller["id"], sku="SKU-F", stock=10)

    r = orders_client.post(
        "/orders/checkout", json={"items": [{"product_id": producto["id"], "quantity": 4}]},
        headers={"Authorization": f"Bearer {_token_de(buyer)}"},
    )
    order_id = r.json()["order_id"]
    assert orders_db.products[producto["id"]]["stock"] == 6

    r = orders_client.patch(
        f"/admin/orders/{order_id}/status", json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {_token_de(admin)}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert orders_db.products[producto["id"]]["stock"] == 10  # restaurado
