"""
Vridik — tests/test_product_images.py (Sprint S5)
Prueba las rutas /admin/products/{id}/images de api/admin_endpoint.py y que
api/products_endpoint.py incluya `images[]` — end-to-end (FastAPI
TestClient) sobre un fake mínimo de conexión asyncpg, mismo estilo que
tests/test_products.py. Solo cubre el modo {"url": ...} (JSON) — el modo
multipart/file se prueba manualmente contra Railway (no vale la pena fakear
un filesystem real para pytest).
"""

from __future__ import annotations

import os
import uuid

# Igual que el resto de tests/test_*.py: JWT_SECRET debe existir ANTES de
# importar core.auth (vía api.admin_endpoint/api.products_endpoint).
os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_endpoint import router as admin_router
from api.products_endpoint import router as products_router
from core.auth import create_jwt


class _FakeImagesDB:
    """Fake de `users` (con role, S2) + `products` (S3) + `product_images` (S5)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.products: dict[str, dict] = {}
        self.images: dict[str, dict] = {}

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
            "id": product_id, "sku": sku, "name": name, "description": "desc",
            "price_cents": price_cents, "stock": stock, "is_active": is_active,
            "seller_id": seller_id,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return self.products[product_id]

    async def execute(self, query: str, *args):
        if "UPDATE product_images SET is_primary = false WHERE product_id" in query:
            (product_id,) = args
            for img in self.images.values():
                if img["product_id"] == product_id:
                    img["is_primary"] = False
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM products WHERE id" in query:
            (product_id,) = args
            p = self.products.get(product_id)
            return dict(p) if p else None
        if "INSERT INTO product_images" in query and "RETURNING" in query:
            product_id, url, is_primary = args
            image_id = str(uuid.uuid4())
            imagen = {
                "id": image_id, "product_id": product_id, "url": url,
                "is_primary": is_primary, "position": 0, "created_at": "2026-01-01T00:00:00+00:00",
            }
            self.images[image_id] = imagen
            return dict(imagen)
        if query.strip().startswith("DELETE FROM product_images"):
            (image_id,) = args
            img = self.images.pop(image_id, None)
            return dict(img) if img else None
        if query.strip().startswith("UPDATE product_images SET is_primary = true"):
            (image_id,) = args
            img = self.images.get(image_id)
            if img is None:
                return None
            img["is_primary"] = True
            return dict(img)
        if "FROM product_images WHERE id" in query:
            (image_id,) = args
            img = self.images.get(image_id)
            return dict(img) if img else None
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
    app.include_router(admin_router)
    app.include_router(products_router)
    app.state.db_connection = images_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_admin_upload_image_url_ok(images_db, images_client):
    admin = images_db.seed_user(email="admin_img1@vridik.local", role="admin")
    seller = images_db.seed_user(email="seller_img1@vridik.local", role="abogado")
    producto = images_db.seed_product(seller_id=seller["id"], sku="SKU-IMG-1")
    token = _token_de(admin)

    r = images_client.post(
        f"/admin/products/{producto['id']}/images",
        json={"url": "https://cdn.example.com/foto.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["url"] == "https://cdn.example.com/foto.jpg"
    assert body["product_id"] == producto["id"]
    assert body["is_primary"] is False


def test_public_product_includes_images(images_db, images_client):
    admin = images_db.seed_user(email="admin_img2@vridik.local", role="admin")
    seller = images_db.seed_user(email="seller_img2@vridik.local", role="abogado")
    producto = images_db.seed_product(seller_id=seller["id"], sku="SKU-IMG-2")
    token = _token_de(admin)

    images_client.post(
        f"/admin/products/{producto['id']}/images", json={"url": "https://cdn.example.com/a.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    images_client.post(
        f"/admin/products/{producto['id']}/images",
        json={"url": "https://cdn.example.com/b.jpg", "is_primary": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    r = images_client.get(f"/products/{producto['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["images"]) == 2
    assert body["images"][0]["is_primary"] is True  # is_primary DESC primero
    assert body["images"][0]["url"] == "https://cdn.example.com/b.jpg"
    assert set(body["images"][0].keys()) == {"id", "url", "is_primary", "position"}


def test_admin_delete_image(images_db, images_client):
    admin = images_db.seed_user(email="admin_img3@vridik.local", role="admin")
    seller = images_db.seed_user(email="seller_img3@vridik.local", role="abogado")
    producto = images_db.seed_product(seller_id=seller["id"], sku="SKU-IMG-3")
    token = _token_de(admin)

    r = images_client.post(
        f"/admin/products/{producto['id']}/images", json={"url": "https://cdn.example.com/c.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    image_id = r.json()["id"]

    r = images_client.delete(
        f"/admin/products/{producto['id']}/images/{image_id}", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204
    assert image_id not in images_db.images

    r = images_client.get(f"/products/{producto['id']}")
    assert r.json()["images"] == []


def test_non_admin_upload_forbidden(images_db, images_client):
    seller = images_db.seed_user(email="seller_img4@vridik.local", role="abogado")
    producto = images_db.seed_product(seller_id=seller["id"], sku="SKU-IMG-4")
    token = _token_de(seller)

    r = images_client.post(
        f"/admin/products/{producto['id']}/images", json={"url": "https://cdn.example.com/d.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
