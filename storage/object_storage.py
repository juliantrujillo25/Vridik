"""
Vridik — storage/object_storage.py
Abstracción de almacenamiento de objetos para `pdf_jobs.pdf_url` (pendiente
explícito anotado desde S10/S11-extra-6, 7 y 8: workers/pdf_worker.py
guardaba el PDF en disco local y usaba esa ruta local como `pdf_url`, lo
cual no sirve con más de una réplica del servicio API sirviendo el archivo
descargado). Esta abstracción permite elegir el backend real vía
`OBJECT_STORAGE_BACKEND` sin tocar workers/pdf_worker.py.

Backends:
  - "local" (por defecto): el PDF se queda en disco local
    (`PDF_WORKER_OUTPUT_DIR`, ver workers/pdf_worker.py) y `pdf_url` es esa
    misma ruta local — mismo comportamiento exacto que las entregas
    anteriores; cero cambio de comportamiento en Railway hasta que alguien
    configure explícitamente `OBJECT_STORAGE_BACKEND=s3`.
  - "s3": sube el PDF a un bucket S3 (o cualquier API compatible con S3,
    p.ej. Railway object storage) con `boto3` y retorna una URL firmada
    (o pública, si `OBJECT_STORAGE_S3_PUBLIC=true`).

NO SE EJECUTA CONTRA AWS NI CONTRA UN VOLUMEN REAL DE RAILWAY EN ESTE
ENTREGABLE — `S3StorageBackend` falla explícitamente en el constructor si
falta `boto3` o el bucket, en vez de intentar una llamada real "a ver si
funciona". Verificado con `py_compile` y pruebas unitarias sobre archivos
temporales (backend local) y sobre un fake de `boto3` (backend S3, sin
tocar AWS real).
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore

logger = logging.getLogger("vridik.storage.object_storage")


class ObjectStorageBackend(ABC):
    """Contrato mínimo: sube un PDF ya generado en disco y retorna la URL
    (local o remota) que se guarda en `pdf_jobs.pdf_url`."""

    @abstractmethod
    async def upload_pdf(self, ruta_local: Path, *, key: str) -> str:
        ...


class LocalStorageBackend(ObjectStorageBackend):
    """Backend por defecto (sin cambios de comportamiento respecto a
    entregas anteriores): el PDF ya está en disco local
    (`PDF_WORKER_OUTPUT_DIR`) y `pdf_url` es simplemente esa ruta local —
    suficiente para un único servicio API sirviendo el archivo, no para
    múltiples réplicas (ver nota de S11-extra-6/7/8).

    Esa ruta cruda NUNCA se expone directo al navegador (ver
    api/case_documents_endpoint.py::descargar_pdf_de_documento) -- exponerla
    por HTTP sin control de acceso sería servir documentos legales
    potencialmente confidenciales a quien tenga la URL, sin el mismo
    chequeo de ownership que protege el resto de `case_documents`."""

    async def upload_pdf(self, ruta_local: Path, *, key: str) -> str:
        return str(ruta_local)


class S3StorageBackend(ObjectStorageBackend):
    """Backend de producción real (S3 / API compatible, p.ej. Railway
    object storage): sube el PDF con `boto3` y retorna una URL firmada (o
    pública, según `OBJECT_STORAGE_S3_PUBLIC`).

    NO SE EJECUTA CONTRA AWS REAL EN ESTE ENTREGABLE: si falta `boto3` o el
    bucket, falla explícitamente en el constructor."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        region: str | None = None,
        public: bool | None = None,
        url_expira_segundos: int = 3600,
    ):
        if boto3 is None:
            raise RuntimeError(
                "S3StorageBackend requiere 'boto3' instalado (pip install boto3) — "
                "no está en requirements.txt todavía porque no se pidió explícitamente "
                "integrar S3 real; solo esta abstracción, lista para activarse."
            )
        self.bucket = bucket or os.environ.get("OBJECT_STORAGE_S3_BUCKET")
        if not self.bucket:
            raise RuntimeError(
                "OBJECT_STORAGE_S3_BUCKET no configurado — requerido para S3StorageBackend."
            )
        self.region = region or os.environ.get("OBJECT_STORAGE_S3_REGION", "us-east-1")
        self.public = (
            public
            if public is not None
            else os.environ.get("OBJECT_STORAGE_S3_PUBLIC", "false").strip().lower() == "true"
        )
        self.url_expira_segundos = url_expira_segundos
        self._cliente = boto3.client("s3", region_name=self.region)

    async def upload_pdf(self, ruta_local: Path, *, key: str) -> str:
        # boto3 es síncrono; se corre en un executor aparte para no
        # bloquear el event loop del worker (mismo patrón que
        # julix/pdf_export.py:generar_pdf en workers/pdf_worker.py).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: self._cliente.upload_file(str(ruta_local), self.bucket, key)
        )
        if self.public:
            return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
        return self._cliente.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.url_expira_segundos,
        )


def get_storage_backend() -> ObjectStorageBackend:
    """Factory: lee `OBJECT_STORAGE_BACKEND` ('local' por defecto, o 's3')
    y construye el backend correspondiente. `workers/pdf_worker.py` llama a
    esta función una vez por trabajo procesado — nunca importa
    `LocalStorageBackend`/`S3StorageBackend` directamente — así que cambiar
    de backend en Railway es solo una variable de entorno, sin tocar
    código del worker."""
    backend = os.environ.get("OBJECT_STORAGE_BACKEND", "local").strip().lower()
    if backend == "s3":
        return S3StorageBackend()
    if backend == "local":
        return LocalStorageBackend()
    raise RuntimeError(f"OBJECT_STORAGE_BACKEND desconocido: {backend!r} (usa 'local' o 's3')")
