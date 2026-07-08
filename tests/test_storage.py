"""
Vridik — tests/test_storage.py (Sprint S7)
Prueba core/storage.py: backend local (filesystem real, aislado en
tmp_path — nunca toca ./uploads real) y validación de configuración del
backend r2 (sin red real, nunca se llama a Cloudflare de verdad).
"""

from __future__ import annotations

import pytest

import core.storage as storage


@pytest.fixture(autouse=True)
def _backend_local_aislado(tmp_path, monkeypatch):
    """Fuerza BACKEND='local' y un UPLOADS_DIR temporal — así el test no
    depende de qué BACKEND esté configurado en el entorno real, y nunca
    toca el ./uploads real del repo."""
    monkeypatch.setattr(storage, "BACKEND", "local")
    monkeypatch.setattr(storage, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "PRODUCT_IMAGES_DIR", tmp_path / "uploads" / "products")


@pytest.mark.asyncio
async def test_save_file_local_creates_file_and_returns_url():
    url = await storage.save_file("products/abc/foo.png", b"contenido-de-prueba")
    assert url == "/uploads/products/abc/foo.png"
    assert (storage.UPLOADS_DIR / "products" / "abc" / "foo.png").read_bytes() == b"contenido-de-prueba"


@pytest.mark.asyncio
async def test_delete_file_local_removes_file():
    await storage.save_file("products/xyz/bar.png", b"data")
    ruta = storage.UPLOADS_DIR / "products" / "xyz" / "bar.png"
    assert ruta.exists()

    await storage.delete_file("products/xyz/bar.png")
    assert not ruta.exists()


@pytest.mark.asyncio
async def test_delete_file_local_missing_file_does_not_raise():
    await storage.delete_file("products/no-existe/nada.png")


def test_ensure_storage_crea_directorios_en_local():
    assert not storage.UPLOADS_DIR.exists()
    storage.ensure_storage()
    assert storage.UPLOADS_DIR.exists()
    assert storage.PRODUCT_IMAGES_DIR.exists()


def test_key_from_url_local_devuelve_key():
    assert storage.key_from_url("/uploads/products/abc/foo.png") == "products/abc/foo.png"


def test_key_from_url_externa_devuelve_none():
    assert storage.key_from_url("https://cdn.example.com/foto.jpg") is None


def test_r2_sin_credenciales_lanza_runtime_error(monkeypatch):
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeError):
        storage._r2_cliente()


def test_r2_sin_bucket_lanza_runtime_error(monkeypatch):
    monkeypatch.delenv("R2_BUCKET_NAME", raising=False)
    with pytest.raises(RuntimeError):
        storage._r2_bucket()


def test_r2_sin_public_url_lanza_runtime_error(monkeypatch):
    monkeypatch.delenv("R2_PUBLIC_URL", raising=False)
    with pytest.raises(RuntimeError):
        storage._r2_public_url_base()


@pytest.mark.asyncio
async def test_save_file_r2_usa_boto3_put_object(monkeypatch):
    """No llama a Cloudflare real — reemplaza el cliente boto3 por un fake
    que solo registra la llamada."""
    monkeypatch.setattr(storage, "BACKEND", "r2")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://pub-test.r2.dev")

    llamadas = []

    class _FakeR2Cliente:
        def put_object(self, **kwargs):
            llamadas.append(kwargs)

    monkeypatch.setattr(storage, "_r2_cliente", lambda: _FakeR2Cliente())
    monkeypatch.setattr(storage, "_r2_bucket", lambda: "vridik-test-bucket")

    url = await storage.save_file("products/abc/foo.jpg", b"contenido", content_type="image/jpeg")
    assert url == "https://pub-test.r2.dev/products/abc/foo.jpg"
    assert len(llamadas) == 1
    assert llamadas[0] == {
        "Bucket": "vridik-test-bucket", "Key": "products/abc/foo.jpg",
        "Body": b"contenido", "ContentType": "image/jpeg",
    }
