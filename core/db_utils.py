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


def obtener_conexion_de_request(request):
    """Hardening RLS (core/rls.py): prioriza la conexión dedicada que el
    middleware de conexión-por-request (`api/julix_endpoint.py`) ya haya
    adquirido y guardado en `request.state.db_connection` -- necesaria
    para que el GUC de sesión (`app.despacho_id`/`app.bypass_rls`, seteado
    por `core.rls.aplicar_contexto_despacho`) se mantenga estable entre
    todas las queries de un mismo request (con el `Pool` crudo, cada
    `.fetch()/.execute()` puede adquirir una conexión física distinta).

    Si no hay ninguna en `request.state` (tests con fake DB, que no pasan
    por ese middleware; o rutas que deliberadamente no pasan por él, como
    los streams SSE) cae a `request.app.state.db_connection` tal cual,
    mismo comportamiento de siempre."""
    conexion_de_request = getattr(request.state, "db_connection", None)
    if conexion_de_request is not None:
        return conexion_de_request
    return getattr(request.app.state, "db_connection", None)
