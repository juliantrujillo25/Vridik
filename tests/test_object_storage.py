"""
Vridik — tests/test_object_storage.py (Sprint S11-extra-9)
Prueba storage/object_storage.py: la abstracción de backend para
`pdf_jobs.pdf_url` (local por defecto, S3 como stub listo para producción).

No se ejecuta contra AWS real: el backend S3 se prueba con un fake mínimo
de `boto3` inyectado vía monkeypatch — nunca se llama a la red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import storage.object_storage as object_storage_module
from storage.object_storage import (
    LocalStorageBackend,
    S3StorageBackend,
    get_storage_backend,
)


@pytest.mark.asyncio
async def test_local_backend_retorna_la_misma_ruta_local(tmp_path):
    ruta = tmp_path / "documento.pdf"
    ruta.write_bytes(b"%PDF-fake")
    backend = LocalStorageBackend()
    url = await backend.upload_pdf(ruta, key=ruta.name)
    assert url == str(ruta)


def test_get_storage_backend_por_defecto_es_local(monkeypatch):
    monkeypatch.delenv("OBJECT_STORAGE_BACKEND", raising=False)
    backend = get_storage_backend()
    assert isinstance(backend, LocalStorageBackend)


def test_get_storage_backend_desconocido_falla_explicito(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "azure")
    with pytest.raises(RuntimeError, match="desconocido"):
        get_storage_backend()


def test_s3_backend_sin_boto3_falla_explicito(monkeypatch):
    """Si boto3 no está instalado, S3StorageBackend debe fallar rápido y
    claro — nunca debe intentar seguir como si nada."""
    monkeypatch.setattr(object_storage_module, "boto3", None)
    with pytest.raises(RuntimeError, match="boto3"):
        S3StorageBackend(bucket="vridik-pdfs")


def test_s3_backend_sin_bucket_falla_explicito(monkeypatch):
    class _FakeBoto3:
        @staticmethod
        def client(*a, **kw):
            return object()

    monkeypatch.setattr(object_storage_module, "boto3", _FakeBoto3())
    monkeypatch.delenv("OBJECT_STORAGE_S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="OBJECT_STORAGE_S3_BUCKET"):
        S3StorageBackend()


class _FakeS3Client:
    """Fake mínimo de boto3.client('s3', ...) — nunca toca la red."""

    def __init__(self):
        self.subidas: list[tuple[str, str, str]] = []

    def upload_file(self, ruta_local: str, bucket: str, key: str) -> None:
        self.subidas.append((ruta_local, bucket, key))

    def generate_presigned_url(self, operacion, *, Params, ExpiresIn):
        return f"https://{Params['Bucket']}.s3.fake/{Params['Key']}?expires={ExpiresIn}"


@pytest.mark.asyncio
async def test_s3_backend_sube_y_retorna_url_firmada(monkeypatch, tmp_path):
    fake_cliente = _FakeS3Client()

    class _FakeBoto3:
        @staticmethod
        def client(*a, **kw):
            return fake_cliente

    monkeypatch.setattr(object_storage_module, "boto3", _FakeBoto3())
    ruta = tmp_path / "documento.pdf"
    ruta.write_bytes(b"%PDF-fake")

    backend = S3StorageBackend(bucket="vridik-pdfs", region="us-east-1", public=False)
    url = await backend.upload_pdf(ruta, key="pdf_job_123.pdf")

    assert fake_cliente.subidas == [(str(ruta), "vridik-pdfs", "pdf_job_123.pdf")]
    assert url == "https://vridik-pdfs.s3.fake/pdf_job_123.pdf?expires=3600"


@pytest.mark.asyncio
async def test_s3_backend_publico_retorna_url_directa_sin_firmar(monkeypatch, tmp_path):
    fake_cliente = _FakeS3Client()

    class _FakeBoto3:
        @staticmethod
        def client(*a, **kw):
            return fake_cliente

    monkeypatch.setattr(object_storage_module, "boto3", _FakeBoto3())
    ruta = tmp_path / "documento.pdf"
    ruta.write_bytes(b"%PDF-fake")

    backend = S3StorageBackend(bucket="vridik-pdfs", region="us-east-1", public=True)
    url = await backend.upload_pdf(ruta, key="pdf_job_123.pdf")

    assert url == "https://vridik-pdfs.s3.us-east-1.amazonaws.com/pdf_job_123.pdf"
