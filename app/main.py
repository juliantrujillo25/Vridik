"""
Vridik — app/main.py
Sprint S6/Railway: punto de entrada ASGI que nixpacks.toml apunta con
`uvicorn app.main:app`. Re-exporta el API de JuliX (api/julix_endpoint.py)
y monta el resto de routers de Vridik a medida que existen como
apps/routers FastAPI propios (S2: panel de administración de usuarios vía
api/admin_endpoint.py; S3: catálogo público de productos vía
api/products_endpoint.py; S4: checkout/órdenes vía api/orders_endpoint.py;
mensajes/S11 y generador quedan pendientes, ver backlog).

Sprint S5: /uploads sirve archivos estáticos desde ./uploads (imágenes de
producto). Nota: en Railway el filesystem del contenedor es efímero (sin
volumen montado), así que lo subido con BACKEND=local no sobrevive un
redeploy — BACKEND=r2 (S7, core/storage.py) es lo que persiste de verdad.

Sprint S6 (core/permissions.py): RBAC más fino admin/seller/customer — vista
"propia" de un seller sobre sus productos/órdenes vía api/seller_endpoint.py.

Sprint S7 (Vridik Abogados): `ensure_storage()` (core/storage.py) reemplaza
la creación inline de ./uploads/products — con BACKEND=r2 es un no-op, no
hace falta directorio local. Pagos con Wompi vía api/payments_endpoint.py.
"""

import os

import asyncpg
from fastapi.staticfiles import StaticFiles

from api.julix_endpoint import app
from api.admin_endpoint import router as admin_router
from api.auth_endpoint import router as auth_router
from api.case_documents_endpoint import router as case_documents_router
from api.orders_endpoint import router as orders_router
from api.payments_endpoint import router as payments_router
from api.products_endpoint import router as products_router
from api.seller_endpoint import router as seller_router
from core.storage import UPLOADS_DIR, ensure_storage

ensure_storage()
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# S1: registro/login sobre PostgreSQL real (ver api/auth_endpoint.py).
app.include_router(auth_router)

# S2: panel de administración de usuarios (solo rol admin, ver
# api/admin_endpoint.py:get_current_admin). Reemplaza a
# api/admin_users_endpoint.py, que esperaba `role` dentro del JWT — S1 nunca
# lo emite, así que ese router nunca respondía nada distinto de 401 con un
# token real. api/admin_users_endpoint.py y core/admin_users.py quedan en el
# repo (y sus tests siguen pasando, arman su propia app FastAPI aislada) pero
# ya no se montan aquí.
app.include_router(admin_router)

# S3: catálogo de productos, endpoints públicos (ver core/product.py). La
# gestión (crear/editar/soft-delete) vive en api/admin_endpoint.py, ya
# montado arriba.
app.include_router(products_router)

# S4: checkout y consulta de órdenes propias (ver core/order.py). La gestión
# admin (listar todas/cambiar status) vive en api/admin_endpoint.py, ya
# montado arriba.
app.include_router(orders_router)

# S6: vista "propia" de un seller sobre sus productos/órdenes (ver
# core/permissions.py). Requiere role in ('abogado', 'admin') (vocabulario
# migrado del marketplace original -- 'seller' -- al vocabulario del
# producto real).
app.include_router(seller_router)

# S7: pagos con Wompi (ver core/payment.py, core/wompi.py). POST
# /webhooks/wompi es público (lo llama Wompi directo, sin JWT) — se
# autentica con la firma HMAC del evento, no con Authorization.
app.include_router(payments_router)

# Documentos de caso generados por JuliX sobre una orden ya existente (ver
# core/case_documents.py: una orden ES el caso, mismo criterio de ownership
# que api/seller_endpoint.py — sin tabla `cases` paralela).
app.include_router(case_documents_router)


@app.on_event("startup")
async def _conectar_db() -> None:
    """Abre el pool asyncpg real que api/auth_endpoint.py y
    api/admin_users_endpoint.py esperan en `request.app.state.db_connection`
    (un asyncpg.Pool soporta el mismo `fetchrow`/`fetch`/`execute` que una
    Connection individual, adquiriendo una conexión del pool por llamada)."""
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        app.state.db_connection = await asyncpg.create_pool(database_url)


@app.on_event("shutdown")
async def _cerrar_db() -> None:
    db_connection = getattr(app.state, "db_connection", None)
    if db_connection is not None:
        await db_connection.close()


__all__ = ["app"]
