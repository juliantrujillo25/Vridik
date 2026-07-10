"""
Vridik — app/main.py
Sprint S6/Railway: punto de entrada ASGI que nixpacks.toml apunta con
`uvicorn app.main:app`. Re-exporta el API de JuliX (api/julix_endpoint.py)
y monta el resto de routers de Vridik.

Desmantelamiento del marketplace (ver Instrucciones - CLAUDE.md,
"Consolidación de producto") — completo:
  - fase 1: api/seller_endpoint.py (S6, vista "propia" de un seller) —
    la pieza más aislada, nadie más lo importaba.
  - fase 2: gestión admin de productos/órdenes/imágenes, dentro de
    api/admin_endpoint.py.
  - fase 3: pagos con Wompi (api/payments_endpoint.py, core/payment.py,
    core/wompi.py) — sin transacciones reales en producción y
    dependían por completo de `orders`.
  - fase 4: api/products_endpoint.py, core/product.py,
    api/orders_endpoint.py, core/order.py, core/permissions.py (sin
    llamadores tras lo anterior), core/storage.py + el mount /uploads
    (exclusivo de imágenes de producto, S5) — todos se borraron
    enteros. La ruta legacy /orders/{id}/documents de case_documents
    también se quitó (la tabla nunca llegó a crearse en producción, no
    había ningún documento real anclado a una orden). Todo queda
    recuperable en el historial de git.

api/admin_endpoint.py (gestión de usuarios) y api/casos_endpoint.py +
api/case_documents_endpoint.py (el copiloto legal, `casos`) son lo que
queda montado además de auth y JuliX.
"""

import os

import asyncpg

from api.julix_endpoint import app
from api.admin_endpoint import router as admin_router
from api.auth_endpoint import router as auth_router
from api.case_documents_endpoint import router as case_documents_router
from api.casos_endpoint import router as casos_router

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

# `casos`: entidad propia del despacho legal, independiente del marketplace
# (ver core/case.py) — la generación de documentos de JuliX se ancla acá.
app.include_router(casos_router)
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
