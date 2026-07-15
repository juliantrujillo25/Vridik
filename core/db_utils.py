"""
Vridik — core/db_utils.py
Helpers de conexión compartidos entre módulos que necesitan sostener un
lock + lectura + escritura como una sola operación atómica contra
`asyncpg.Pool` -- extraídos de `core/auth_events.py` (donde nacieron para
el hash chain de la bitácora) el día que `core/despachos.py` y
`api/auth_endpoint.py::register` necesitaron el mismo patrón. Antes de esto
había un solo caller real; con tres, duplicar el mismo par de funciones ya
no tenía sentido.
"""

from __future__ import annotations

from contextlib import asynccontextmanager


@asynccontextmanager
async def conexion_dedicada(conn):
    """`conn` acá puede ser un `asyncpg.Pool` (sin `.transaction()` propio
    -- para sostener un lock+lectura+insert como una sola operación
    atómica hace falta adquirir una conexión dedicada del pool primero),
    una `Connection` individual ya adquirida, o un fake de test simple. Se
    detecta por duck typing -- nunca se asume cuál de los dos es."""
    if hasattr(conn, "acquire"):
        async with conn.acquire() as conexion:
            yield conexion
    else:
        yield conn


@asynccontextmanager
async def transaccion_si_disponible(conexion):
    """Los fakes de test (y, en teoría, cualquier conexión sin soporte
    real de transacciones) no tienen `.transaction()` -- se degrada a
    no-op ahí. Contra Postgres real (Connection de verdad) SIEMPRE hay
    `.transaction()`, así que en producción esto nunca se salta."""
    if hasattr(conexion, "transaction"):
        async with conexion.transaction():
            yield
    else:
        yield
