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

Roadmap Semana 11, Fase A: api/mensajes_endpoint.py -- mensajería real
sobre un `caso` (deuda "85%" del roadmap), reemplaza al
FakeMensajesService de tests/support/fakes.py.

Roadmap Semana 11, Fase B: api/events_endpoint.py -- GET
/api/events/stream, canal SSE genérico sobre NOTIFY/LISTEN
(core/events.py). crear_mensaje_endpoint ya lo usa para `message.new`;
reconexión real (Fase C) y más tipos de evento llegan después sin
cambiar el canal.
"""

import logging
import os

import asyncpg

from api.julix_endpoint import app
from api.admin_endpoint import router as admin_router
from api.auth_endpoint import router as auth_router
from api.case_documents_endpoint import router as case_documents_router
from api.casos_endpoint import router as casos_router
from api.events_endpoint import router as events_router
from api.mensajes_endpoint import router as mensajes_router
from core.auth import ensure_auth_migration_005

logger = logging.getLogger("vridik.app")

# S1: registro/login sobre PostgreSQL real (ver api/auth_endpoint.py).
app.include_router(auth_router)

# S2: panel de administración de usuarios (solo rol admin, ver
# api/admin_endpoint.py:get_current_admin). api/admin_users_endpoint.py
# (esperaba `role` dentro del JWT, que S1 nunca emite -- nunca respondía
# nada distinto de 401 con un token real) se borró entero en el hardening
# de S12-13 (endpoint huérfano, nunca se montó acá). core/admin_users.py
# queda intacto -- api/admin_endpoint.py reusa actividad_usuario()/
# resetear_password() de ahí.
app.include_router(admin_router)

# `casos`: entidad propia del despacho legal, independiente del marketplace
# (ver core/case.py) — la generación de documentos de JuliX se ancla acá.
app.include_router(casos_router)
app.include_router(case_documents_router)

# S11 (Fase A): mensajería real entre cliente/abogado sobre un caso.
app.include_router(mensajes_router)

# S11 (Fase B): canal SSE genérico, hoy usado por mensajería.
app.include_router(events_router)


@app.on_event("startup")
async def _conectar_db() -> None:
    """Abre el pool asyncpg real que todos los routers montados esperan en
    `request.app.state.db_connection` (un asyncpg.Pool soporta el mismo
    `fetchrow`/`fetch`/`execute` que una Connection individual, adquiriendo
    una conexión del pool por llamada)."""
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        # max_size explícito (asyncpg cae a 10 si no se pasa) -- GET
        # /api/events/stream (api/events_endpoint.py) reserva una conexión
        # DEDICADA del pool durante toda la vida del stream SSE (no puede
        # usar el patrón normal de acquire-por-llamada porque necesita
        # LISTEN/NOTIFY sobre una conexión persistente). Con el default de
        # 10, un puñado de usuarios con el detalle de un caso abierto a la
        # vez ya alcanza para agotar el pool entero y colgar el resto de la
        # API (incidente real, 2026-07-12) -- 20 da margen, y
        # events_endpoint.py además pone un techo propio a cuántas de esas
        # conexiones puede usar el streaming SSE, para que nunca se coma
        # el pool completo.
        app.state.db_connection = await asyncpg.create_pool(database_url, min_size=2, max_size=20)

        # Bootstrap idempotente de migrations/005_auth_roles_refresh_tokens.sql
        # (refresh_tokens/auth_events/user_credentials/roles) -- UNA sola vez
        # acá, no en cada request (a diferencia de ensure_users_table/
        # ensure_role_column, que sí corren por request): son 24 sentencias,
        # incluido un backfill real sobre toda `users`, agregarlo al camino
        # de login/refresh/logout sería pagar ese costo en el flujo más
        # sensible de la app. Nunca existió una versión idempotente de esta
        # migración en el código (solo el .sql de referencia, que nada
        # ejecutaba en runtime) -- en logs, no crashea el arranque si falla
        # (la migración ya está aplicada en producción; esto es red de
        # seguridad para un entorno nuevo, no una dependencia dura de hoy).
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_auth_migration_005(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo aplicar el bootstrap de migrations/005_auth_roles_refresh_tokens.sql "
                "al arrancar -- si las tablas refresh_tokens/auth_events/user_credentials ya existen "
                "(caso esperado en producción hoy) esto no afecta nada; si no existen, auth va a fallar.",
                exc_info=True,
            )


@app.on_event("shutdown")
async def _cerrar_db() -> None:
    db_connection = getattr(app.state, "db_connection", None)
    if db_connection is not None:
        await db_connection.close()


__all__ = ["app"]
