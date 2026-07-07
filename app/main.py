"""
Vridik — app/main.py
Sprint S6/Railway: punto de entrada ASGI que nixpacks.toml apunta con
`uvicorn app.main:app`. Re-exporta el API de JuliX (api/julix_endpoint.py)
y monta el resto de routers de Vridik a medida que existen como
apps/routers FastAPI propios (S2: panel de administración de usuarios;
mensajes/S11 y generador quedan pendientes, ver backlog).

NO SE EJECUTA EN ESTE ENTREGABLE.
"""

from api.julix_endpoint import app
from api.admin_users_endpoint import router as admin_users_router
from api.auth_endpoint import router as auth_router

# S1: registro/login sobre PostgreSQL real (ver api/auth_endpoint.py).
app.include_router(auth_router)

# S2: panel de administración de usuarios (solo rol admin, ver
# api/admin_users_endpoint.py:_decodificar_jwt_admin).
app.include_router(admin_users_router)

__all__ = ["app"]
