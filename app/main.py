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

import asyncio
import logging
import os

import asyncpg

from api.julix_endpoint import app
from api.actuaciones_endpoint import router as actuaciones_router
from api.admin_endpoint import router as admin_router
from api.analitica_endpoint import router as analitica_router
from api.auth_endpoint import router as auth_router
from api.case_documents_endpoint import router as case_documents_router
from api.casos_endpoint import router as casos_router
from api.clientes_endpoint import router as clientes_router
from api.cobro_endpoint import router as cobro_router
from api.corpus_endpoint import router as corpus_router
from api.datos_personales_endpoint import router as datos_personales_router
from api.events_endpoint import router as events_router
from api.bitacora_endpoint import router as bitacora_router
from api.mensajes_endpoint import router as mensajes_router
from api.platform_endpoint import router as platform_router
from api.terminos_endpoint import router as terminos_router
from core.admin import ensure_role_column
from core.auth import ensure_auth_migration_005, ensure_users_table
from core.auth_events import ensure_bitacora_hash_chain
from core.case import ensure_casos_despacho_backfill
from core.despachos import ensure_despachos_backfill
from core.rls import ensure_rls_policies, ensure_rls_policies_indirectas, ensure_rls_policies_soporte
from core.terminos import ensure_terminos_table
from julix.ledger import ensure_julix_calls_despacho_backfill
from procesal.alertas_terminos import ejecutar_ronda_de_alertas

logger = logging.getLogger("vridik.app")

# Fase 2: alertas proactivas de términos en riesgo (roadmap: "0 términos
# vencidos sin alerta en 90 días", ver procesal/alertas_terminos.py) --
# "cero infra nueva": un loop de fondo dentro de este mismo proceso
# siempre-activo, no un servicio Railway con cron propio. 6h por defecto es
# más que suficiente para un aviso de vencimientos (no es un sistema de
# tiempo real) y barato en llamadas a la DB.
_INTERVALO_ALERTAS_TERMINOS_SEGUNDOS = int(
    os.environ.get("VRIDIK_INTERVALO_ALERTAS_TERMINOS_SEGUNDOS", str(6 * 60 * 60))
)

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

# S11 (Fase B): canal SSE genérico, hoy usado por mensajería y (Fase 2)
# por actuacion.nueva.
app.include_router(events_router)

# Fase 2 (Copiloto Procesal) — arranca sin proveedor de monitoreo de
# procesos contratado (decisión de negocio pendiente, ver
# procesal/__init__.py): actuaciones se registran a mano por ahora
# (clasificación IA real sobre el texto), términos siempre con
# vencimiento calculado por procesal/calendario_judicial.py, nunca a mano.
app.include_router(actuaciones_router)
app.include_router(terminos_router)

# Fase 3 (Cobro Inteligente) — arranca con lo que no depende de un
# proveedor externo (core/cobro.py): valor en disputa + esquema de
# honorarios con liquidación siempre calculada, nunca a mano. La factura
# DIAN ("integrar, no construir") sigue bloqueada en la misma clase de
# decisión de negocio que la ingesta de actuaciones de Fase 2.
app.include_router(cobro_router)

# Fase 3: bitácora sellada de notificaciones con acuse -- crece sobre
# auth_events + hash encadenado (ver core/auth_events.py).
app.include_router(bitacora_router)

# Fase 4: pricing por despacho -- admin de plataforma (Vridik, no de un
# despacho), único lugar de la app donde ver/tocar TODOS los despachos sin
# scoping es correcto por diseño (ver core/despachos.py).
app.include_router(platform_router)

# Roadmap S7: mini-herramienta de curaduría del corpus legal (3 pasos:
# extraer texto -> editar chunks -> completar metadata -> publicar). Mismo
# criterio de acceso que platform_router -- rag_chunks es corpus compartido
# de toda la plataforma, sin despacho_id (ver core/corpus_curation.py).
app.include_router(corpus_router)

# Fase 4: SAGRILAFT lite -- vista de cliente + matriz de riesgo por cliente
# (core/clientes.py, core/cumplimiento.py). Herramienta de apoyo, no un
# motor de compliance certificado -- ver docstring de core/cumplimiento.py.
app.include_router(clientes_router)

# Fase 4: analítica UGPP sobre casos propios del despacho -- el corpus
# jurisprudencial sigue incompleto (85/400+ chunks), así que esto NO
# analiza jurisprudencia externa ni perfila jueces (advertencia SAMAI del
# roadmap), solo agrega los resultados que el propio despacho registra
# (ver core/analitica.py).
app.include_router(analitica_router)

# Roadmap T7 (Ley 1581 de 2012, derecho ARCO de Acceso) -- GET /me/datos,
# export propio en JSON (ver core/datos_personales.py). Rectificación se
# ejerce con los endpoints existentes; Supresión queda pendiente de una
# decisión de diseño (qué se anonimiza vs qué se conserva por deber
# legal), no implementada todavía a propósito.
app.include_router(datos_personales_router)


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

        # `users` + su columna `role` primero, explícito -- TODO lo que
        # sigue en este bootstrap (migración 005, backfills de
        # despacho_id) asume que ambas ya existen (hacen ALTER TABLE,
        # leen `users.role`, etc). En cualquier entorno con historial
        # (producción, siempre) eso es cierto desde hace meses, así que
        # nunca se notó -- pero en una base COMPLETAMENTE vacía (staging
        # recién creado, T6 del roadmap, encontrado ahí el 21-jul) cada
        # paso de abajo fallaba en cascada ("relation users does not
        # exist", después "column users.role does not exist") hasta que
        # un request real llamaba a estas mismas funciones de casualidad.
        # Baratas de llamar (CREATE TABLE / ALTER COLUMN, ambas IF NOT
        # EXISTS) y hacen que el arranque en frío sea silencioso en vez
        # de tirar varios CRITICAL espurios en cadena.
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_users_table(conn)
                await ensure_role_column(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo crear/verificar users o su columna role al arrancar.", exc_info=True,
            )

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

        # Fase 3: hash chain de la bitácora sellada (core/auth_events.py) --
        # migración aditiva (dos columnas nuevas), misma lógica de "una
        # sola vez al arrancar" que la migración 005 de arriba: agregar
        # dos ALTER TABLE al camino de cada login/logout no vale la pena.
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_bitacora_hash_chain(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo aplicar el bootstrap del hash chain de auth_events al arrancar -- "
                "si las columnas hash_anterior/hash_actual ya existen esto no afecta nada.",
                exc_info=True,
            )

        # Fase 4: fundación de multi-tenancy -- misma lógica de "una sola vez
        # al arrancar" que los bloques de arriba. Orden importa: despachos
        # primero (crea "Despacho por defecto" y puebla users.despacho_id),
        # recién después casos/julix_calls (leen users.despacho_id ya
        # poblado para heredarlo).
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_despachos_backfill(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo aplicar el backfill de despachos al arrancar -- si users.despacho_id "
                "ya es NOT NULL esto no afecta nada; si no, register/casos van a fallar.",
                exc_info=True,
            )

        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_casos_despacho_backfill(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo aplicar el backfill de despacho_id en casos al arrancar -- si "
                "casos.despacho_id ya es NOT NULL esto no afecta nada.",
                exc_info=True,
            )

        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_julix_calls_despacho_backfill(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudo aplicar el backfill de despacho_id en julix_calls al arrancar -- "
                "el límite mensual por despacho puede quedar mal calculado hasta el próximo arranque.",
                exc_info=True,
            )

        # Hardening RLS (core/rls.py) -- DESPUÉS de los tres backfills de
        # arriba a propósito: FORCE ROW LEVEL SECURITY sobre una tabla con
        # filas despacho_id IS NULL pendientes las dejaría invisibles para
        # todos, incluido este mismo bootstrap.
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_rls_policies(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudieron aplicar las políticas de RLS al arrancar -- el aislamiento "
                "entre despachos sigue dependiendo solo de los checks de aplicación existentes "
                "hasta el próximo arranque.",
                exc_info=True,
            )

        # Track Forja TF1 / roadmap T8 -- RLS en las 5 tablas indirectas
        # (actuaciones/terminos/cobro_caso/case_documents/mensajería).
        # Deliberadamente DESPUÉS de ensure_rls_policies(): depende de que
        # casos.despacho_id ya esté con FORCE RLS aplicado (ver docstring
        # de ensure_rls_policies_indirectas).
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_rls_policies_indirectas(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudieron aplicar las políticas de RLS de las tablas indirectas al "
                "arrancar -- actuaciones/terminos/cobro_caso/case_documents/mensajes siguen "
                "dependiendo solo de los checks de aplicación hasta el próximo arranque.",
                exc_info=True,
            )

        # Auditoría de seguridad 22-jul-2026 -- RLS en las tablas de soporte
        # que quedaron fuera de las dos pasadas anteriores (refresh_tokens/
        # auth_events/user_events/pdf_jobs/despachos). Deliberadamente
        # DESPUÉS de ensure_rls_policies_indirectas() -- mismo motivo que
        # esa (mantener un único orden lineal de las tres pasadas), no
        # porque dependa de ella; sí depende de que ensure_rls_policies()
        # ya haya corrido (users.despacho_id NOT NULL).
        try:
            async with app.state.db_connection.acquire() as conn:
                await ensure_rls_policies_soporte(conn)
        except Exception:
            logger.critical(
                "Vridik: no se pudieron aplicar las políticas de RLS de las tablas de soporte al "
                "arrancar -- refresh_tokens/auth_events/user_events/pdf_jobs/despachos siguen "
                "dependiendo solo de los checks de aplicación hasta el próximo arranque.",
                exc_info=True,
            )

        app.state._tarea_alertas_terminos = asyncio.create_task(_bucle_alertas_terminos())


async def _bucle_alertas_terminos() -> None:
    """Fase 2: ver procesal/alertas_terminos.py -- corre para siempre
    mientras el proceso esté vivo (cancelada en _cerrar_db). Un ciclo que
    falla (DB momentáneamente caída, etc.) se loguea y el loop sigue en el
    próximo intervalo -- nunca tumba el proceso ni deja de reintentar.

    A diferencia de una conexión de request (ver api/julix_endpoint.py::
    _conexion_por_request), `.acquire()` acá no pasa por ningún middleware
    -- sale del pool sin `app.bypass_rls` seteado (NULL, ni 'true' ni
    'false'). Con FORCE ROW LEVEL SECURITY ya aplicado a `terminos`/`casos`
    (core/rls.py::ensure_rls_policies_indirectas), esa conexión sin GUC no
    ve ninguna fila de ninguna de las dos -- ejecutar_ronda_de_alertas()
    devolvería 0 alertas SIEMPRE, en silencio, sin error. Este loop
    legítimamente necesita ver los términos de TODOS los despachos (no hay
    un despacho_id al que angostar, notifica cruzando tenants por diseño),
    así que bypass es el estado correcto acá, no un despacho_id puntual."""
    while True:
        try:
            async with app.state.db_connection.acquire() as conn:
                await conn.execute("SELECT set_config('app.bypass_rls', 'true', false)")
                await ensure_terminos_table(conn)
                enviadas = await ejecutar_ronda_de_alertas(conn)
                if enviadas:
                    logger.info("Vridik: %s alerta(s) de término enviada(s) en esta ronda", enviadas)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Vridik: falló una ronda de alertas de términos (se reintenta en el próximo ciclo)")
        await asyncio.sleep(_INTERVALO_ALERTAS_TERMINOS_SEGUNDOS)


@app.on_event("shutdown")
async def _cerrar_db() -> None:
    tarea_alertas = getattr(app.state, "_tarea_alertas_terminos", None)
    if tarea_alertas is not None:
        tarea_alertas.cancel()

    db_connection = getattr(app.state, "db_connection", None)
    if db_connection is not None:
        await db_connection.close()


__all__ = ["app"]
