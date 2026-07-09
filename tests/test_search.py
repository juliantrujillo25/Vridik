"""
Vridik — tests/test_search.py (Sprint S7, Vridik Abogados)
Prueba los filtros de búsqueda de GET /products (?category=&city=&
min_price=&max_price=&sort_by=) y los nuevos GET /products/categories,
GET /products/cities — end-to-end (FastAPI TestClient) sobre un fake
mínimo, mismo estilo que tests/test_products.py.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.products_endpoint import router as products_router
from core.product import CATEGORIAS_VALIDAS


class _FakeSearchDB:
    def __init__(self):
        self.products: dict[str, dict] = {}

    def seed_product(
        self, *, seller_id: str, sku: str, name: str = "Servicio legal",
        category: str = "civil", city: str = "Bogotá", price_cents: int = 100000,
        stock: int = 1, is_active: bool = True,
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
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        return None

    async def fetch(self, query: str, *args):
        if "SELECT DISTINCT city FROM products" in query:
            ciudades = sorted({p["city"] for p in self.products.values() if p["city"] and p["is_active"]})
            return [{"city": c} for c in ciudades]
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
                productos = [p for p in productos if p["category"] == category]
            if city:
                productos = [p for p in productos if p["city"].lower() == city.lower()]
            if min_price is not None:
                productos = [p for p in productos if p["price_cents"] >= min_price]
            if max_price is not None:
                productos = [p for p in productos if p["price_cents"] <= max_price]
            # sort_by no viaja como parámetro $N -- core.product.list_products lo
            # resuelve a un fragmento SQL fijo e interpola el ORDER BY en el texto
            # de la query (ver _ORDEN_PERMITIDO); el fake debe inspeccionar ese
            # texto para simular el mismo comportamiento.
            if "ORDER BY price_cents ASC" in query:
                productos = sorted(productos, key=lambda p: p["price_cents"])
            elif "ORDER BY price_cents DESC" in query:
                productos = sorted(productos, key=lambda p: p["price_cents"], reverse=True)
            else:
                productos = sorted(productos, key=lambda p: p["created_at"], reverse=True)
            return [dict(p) for p in productos[skip:skip + limit]]
        if "FROM product_images WHERE product_id" in query:
            return []
        return []


@pytest.fixture
def search_db():
    return _FakeSearchDB()


@pytest.fixture
def search_client(search_db):
    app = FastAPI()
    app.include_router(products_router)
    app.state.db_connection = search_db
    return TestClient(app)


def test_search_by_category_and_city(search_db, search_client):
    seller_id = str(uuid.uuid4())
    search_db.seed_product(seller_id=seller_id, sku="AB-1", category="penal", city="Cali")
    search_db.seed_product(seller_id=seller_id, sku="AB-2", category="civil", city="Cali")
    search_db.seed_product(seller_id=seller_id, sku="AB-3", category="penal", city="Bogotá")

    r = search_client.get("/products", params={"category": "penal", "city": "Cali"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["sku"] == "AB-1"
    assert body[0]["category"] == "penal"
    assert body[0]["city"] == "Cali"


def test_search_by_price_range(search_db, search_client):
    seller_id = str(uuid.uuid4())
    search_db.seed_product(seller_id=seller_id, sku="PR-1", price_cents=50000)
    search_db.seed_product(seller_id=seller_id, sku="PR-2", price_cents=150000)
    search_db.seed_product(seller_id=seller_id, sku="PR-3", price_cents=300000)

    r = search_client.get("/products", params={"min_price": 100000, "max_price": 200000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["sku"] == "PR-2"


def test_search_sort_by_price_asc(search_db, search_client):
    seller_id = str(uuid.uuid4())
    search_db.seed_product(seller_id=seller_id, sku="ORD-1", price_cents=300000)
    search_db.seed_product(seller_id=seller_id, sku="ORD-2", price_cents=100000)
    search_db.seed_product(seller_id=seller_id, sku="ORD-3", price_cents=200000)

    r = search_client.get("/products", params={"sort_by": "price_asc"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["sku"] for p in body] == ["ORD-2", "ORD-3", "ORD-1"]


def test_get_categories_devuelve_taxonomia_fija(search_client):
    r = search_client.get("/products/categories")
    assert r.status_code == 200, r.text
    assert set(r.json()) == set(CATEGORIAS_VALIDAS)


def test_get_cities_devuelve_ciudades_distintas(search_db, search_client):
    seller_id = str(uuid.uuid4())
    search_db.seed_product(seller_id=seller_id, sku="CT-1", city="Cali")
    search_db.seed_product(seller_id=seller_id, sku="CT-2", city="Medellín")
    search_db.seed_product(seller_id=seller_id, sku="CT-3", city="Cali")

    r = search_client.get("/products/cities")
    assert r.status_code == 200, r.text
    assert r.json() == ["Cali", "Medellín"]


def test_categories_route_no_colisiona_con_product_id(search_client):
    """GET /products/categories nunca debe interpretarse como
    GET /products/{product_id} con product_id="categories" — si la ruta
    quedara mal ordenada, esto devolvería 404 en vez de la lista fija."""
    r = search_client.get("/products/categories")
    assert r.status_code == 200
    assert r.json() != []
