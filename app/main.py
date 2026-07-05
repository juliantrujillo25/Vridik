"""
Vridik — app/main.py
Sprint S6/Railway: punto de entrada ASGI que nixpacks.toml apunta con
`uvicorn app.main:app`. Re-exporta el API de JuliX (api/julix_endpoint.py)
y es el lugar natural para montar, a futuro, el resto de routers de Vridik
(auth de S1/S2, mensajes de S11, generador, panel) a medida que existan
como apps/routers FastAPI propios.

NO SE EJECUTA EN ESTE ENTREGABLE.
"""

from api.julix_endpoint import app  # noqa: F401  (re-exportado para uvicorn app.main:app)
