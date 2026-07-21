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


class _FakeBoto3ConCliente:
    """Como _FakeBoto3 pero registra con qué kwargs se llamó client() --
    necesario para probar que endpoint_url (R2) se le pasa a boto3 de
    verdad, no solo que se guarda en el backend."""

    def __init__(self, cliente):
        self.cliente = cliente
        self.llamadas: list[dict] = []

    def client(self, servicio, **kwargs):
        self.llamadas.append(kwargs)
        return self.cliente


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


# ---------------------------------------------------------------------------
# Cloudflare R2 (proveedor elegido, T5 del roadmap 21-jul): compatible con
# la API S3 pero no es AWS -- endpoint custom + sin el formato de URL
# pública de AWS, ver el docstring de S3StorageBackend.
# ---------------------------------------------------------------------------
def test_s3_backend_region_por_defecto_es_auto_no_us_east_1(monkeypatch):
    """R2 no tiene regiones reales como AWS -- 'auto' es lo que Cloudflare
    documenta usar, distinto del default histórico de AWS puro."""
    monkeypatch.delenv("OBJECT_STORAGE_S3_REGION", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_S3_ENDPOINT_URL", raising=False)
    fake_cliente = _FakeS3Client()
    fake_boto3 = _FakeBoto3ConCliente(fake_cliente)
    monkeypatch.setattr(object_storage_module, "boto3", fake_boto3)

    S3StorageBackend(bucket="vridik-pdfs")

    assert fake_boto3.llamadas == [{"region_name": "auto"}]


def test_s3_backend_pasa_endpoint_url_a_boto3(monkeypatch):
    """Sin esto, boto3 apunta a AWS real -- el bucket de R2 no existe ahí."""
    fake_cliente = _FakeS3Client()
    fake_boto3 = _FakeBoto3ConCliente(fake_cliente)
    monkeypatch.setattr(object_storage_module, "boto3", fake_boto3)

    S3StorageBackend(
        bucket="vridik-pdfs",
        endpoint_url="https://abc123.r2.cloudflarestorage.com",
    )

    assert fake_boto3.llamadas == [
        {"region_name": "auto", "endpoint_url": "https://abc123.r2.cloudflarestorage.com"}
    ]


def test_s3_backend_publico_con_endpoint_custom_sin_public_base_url_falla_explicito(monkeypatch):
    """R2 no expone bucket.s3.region.amazonaws.com -- si alguien prende
    modo público con un endpoint custom sin darle la URL pública real
    (r2.dev o dominio propio), debe fallar rápido, no generar una URL de
    AWS que en R2 no funciona."""
    fake_cliente = _FakeS3Client()
    monkeypatch.setattr(object_storage_module, "boto3", _FakeBoto3ConCliente(fake_cliente))

    with pytest.raises(RuntimeError, match="OBJECT_STORAGE_S3_PUBLIC_BASE_URL"):
        S3StorageBackend(
            bucket="vridik-pdfs",
            endpoint_url="https://abc123.r2.cloudflarestorage.com",
            public=True,
        )


@pytest.mark.asyncio
async def test_s3_backend_publico_con_public_base_url_usa_esa_url(monkeypatch, tmp_path):
    fake_cliente = _FakeS3Client()
    monkeypatch.setattr(object_storage_module, "boto3", _FakeBoto3ConCliente(fake_cliente))
    ruta = tmp_path / "documento.pdf"
    ruta.write_bytes(b"%PDF-fake")

    backend = S3StorageBackend(
        bucket="vridik-pdfs",
        endpoint_url="https://abc123.r2.cloudflarestorage.com",
        public=True,
        public_base_url="https://pub-xxxx.r2.dev/",
    )
    url = await backend.upload_pdf(ruta, key="pdf_job_123.pdf")

    assert url == "https://pub-xxxx.r2.dev/pdf_job_123.pdf"
