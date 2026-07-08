"""
Vridik — core/storage.py
Sprint S7: abstracción de almacenamiento de imágenes de producto — reemplaza
el guardado directo en disco local de S5 (api/admin_endpoint.py) por un
backend configurable vía `BACKEND` ('local', default, o 'r2' — Cloudflare
R2, API compatible con S3 vía boto3).

BACKEND=r2 requiere:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME,
  R2_PUBLIC_URL (dominio público del bucket — R2 no expone URLs públicas
  por sí solo salvo que se configure un dominio custom o el subdominio
  *.r2.dev; sin R2_PUBLIC_URL no hay forma de construir la url de vuelta).

`save_file()`/`delete_file()` son el contrato único que usan
api/admin_endpoint.py y api/seller_endpoint.py — ninguno de los dos vuelve
a tocar el filesystem ni boto3 directamente. `key_from_url()` decide, a
partir de una url guardada, si es un archivo que NOSOTROS subimos (local o
R2, sin importar qué BACKEND esté activo ahora — una imagen vieja puede
seguir en el backend anterior) o una url externa (modo {"url": ...} con un
link de terceros) — en ese segundo caso nunca se borra nada.

NO SE PROBÓ CONTRA UN BUCKET R2 REAL EN ESTE ENTREGABLE (sin credenciales
reales disponibles) — el backend local (default, sin cambio de
comportamiento respecto a S5) sí está completamente probado con archivos
temporales reales (tests/test_storage.py).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore

BACKEND = os.environ.get("BACKEND", "local").strip().lower()

UPLOADS_DIR = Path("uploads")
PRODUCT_IMAGES_DIR = UPLOADS_DIR / "products"


def _r2_cliente():
    if boto3 is None:
        raise RuntimeError("BACKEND=r2 requiere 'boto3' instalado (pip install boto3)")
    account_id = os.environ.get("R2_ACCOUNT_ID", "")
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if not (account_id and access_key and secret_key):
        raise RuntimeError(
            "BACKEND=r2 requiere R2_ACCOUNT_ID, R2_ACCESS_KEY_ID y R2_SECRET_ACCESS_KEY"
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _r2_bucket() -> str:
    bucket = os.environ.get("R2_BUCKET_NAME", "")
    if not bucket:
        raise RuntimeError("BACKEND=r2 requiere R2_BUCKET_NAME")
    return bucket


def _r2_public_url_base() -> str:
    base = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("BACKEND=r2 requiere R2_PUBLIC_URL para construir la url pública")
    return base


async def save_file(key: str, content: bytes, *, content_type: str | None = None) -> str:
    """Guarda `content` bajo `key` (p.ej. "products/{product_id}/{uuid}.jpg")
    y devuelve la url pública para acceder al archivo."""
    if BACKEND == "r2":
        extra = {"ContentType": content_type} if content_type else {}
        _r2_cliente().put_object(Bucket=_r2_bucket(), Key=key, Body=content, **extra)
        return f"{_r2_public_url_base()}/{key}"

    destino = UPLOADS_DIR / key
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(content)
    return f"/uploads/{key}"


async def delete_file(key: str) -> None:
    """Borra el archivo bajo `key` en el backend ACTIVO — el llamador
    decide con key_from_url() si esta `key` corresponde de verdad a un
    archivo nuestro antes de llamar acá."""
    if BACKEND == "r2":
        _r2_cliente().delete_object(Bucket=_r2_bucket(), Key=key)
        return
    (UPLOADS_DIR / key).unlink(missing_ok=True)


def key_from_url(url: str) -> str | None:
    """Si `url` es un archivo que nosotros guardamos (local o R2, sin
    importar el BACKEND activo ahora mismo), devuelve su `key`; si es una
    url externa (modo {"url": ...} con un link de terceros), None — nunca
    se borra un archivo que no es nuestro."""
    if url.startswith("/uploads/"):
        return url[len("/uploads/"):]
    r2_public = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    if r2_public and url.startswith(f"{r2_public}/"):
        return url[len(r2_public) + 1:]
    return None


def ensure_storage() -> None:
    """Con cualquier BACKEND crea al menos ./uploads — StaticFiles
    (app/main.py) exige que el directorio exista al momento de montar, o
    falla en el arranque. Con BACKEND=local además crea
    ./uploads/products, adonde de verdad van los archivos."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    if BACKEND != "r2":
        PRODUCT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
