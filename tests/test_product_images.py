"""
Vridik — tests/test_product_images.py (Sprint S5)
Prueba que api/products_endpoint.py (catálogo público) incluya `images[]`
correctamente ordenadas — end-to-end (FastAPI TestClient) sobre un fake
mínimo de conexión asyncpg, mismo estilo que tests/test_products.py.

Desmantelamiento del marketplace (fase 2): las rutas de gestión
/admin/products/{id}/images (subir/borrar/marcar principal) se quitaron de
api/admin_endpoint.py — este archivo dejó de probarlas junto con ellas; las
imágenes ahora se siembran directo en el fake, sin pasar por la API.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.products_endpoint import router as products_router


class _FakeImagesDB:
    """Fake de `products` (S3) + `product_images` (S5)."""

    def __init__(self):
        self.products: dict[str, dict] = {}
        self.images: dict[str, dict] = {}

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

    def seed_image(self, *, product_id: str, url: str, is_primary: bool = False, position: int = 0) -> dict:
        image_id = str(uuid.uuid4())
        imagen = {
            "id": image_id, "product_id": product_id, "url": url,
            "is_primary": is_primary, "position": position, "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.images[image_id] = imagen
        return imagen

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM product_images" in query and "WHERE product_id" in query:
            (product_id,) = args
            imgs = [i for i in self.images.values() if i["product_id"] == product_id]
            imgs.sort(key=lambda i: (not i["is_primary"], i["position"]))
            return [dict(i) for i in imgs]
        return []


@pytest.fixture
def images_db():
    return _FakeImagesDB()


@pytest.fixture
def images_client(images_db):
    app = FastAPI()
    app.include_router(products_router)
    app.state.db_connection = images_db
    return TestClient(app)


def test_public_product_includes_images(images_db, images_client):
    producto = images_db.seed_product(seller_id=str(uuid.uuid4()), sku="SKU-IMG-2")
    images_db.seed_image(product_id=producto["id"], url="https://cdn.example.com/a.jpg", position=0)
    images_db.seed_image(product_id=producto["id"], url="https://cdn.example.com/b.jpg", is_primary=True, position=1)

    r = images_client.get(f"/products/{producto['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["images"]) == 2
    assert body["images"][0]["is_primary"] is True  # is_primary DESC primero
    assert body["images"][0]["url"] == "https://cdn.example.com/b.jpg"
    assert set(body["images"][0].keys()) == {"id", "url", "is_primary", "position"}


def test_public_product_sin_imagenes(images_db, images_client):
    producto = images_db.seed_product(seller_id=str(uuid.uuid4()), sku="SKU-IMG-3")

    r = images_client.get(f"/products/{producto['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["images"] == []
