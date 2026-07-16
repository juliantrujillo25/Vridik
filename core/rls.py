"""
Vridik — core/rls.py
Hardening (roadmap Fase 4, deuda documentada desde la migración de
multi-tenancy): Row-Level Security de Postgres como SEGUNDA capa de
aislamiento entre despachos, independiente de los checks de aplicación que
ya existen (`WHERE despacho_id = $1` a mano en cada query). No reemplaza
esos checks -- los respalda: si algún día un endpoint se olvida de filtrar
por despacho, la base de datos misma rechaza la fila ajena.

Alcance de esta pasada: solo las 4 tablas que ya tienen `despacho_id` como
columna DIRECTA -- `users`, `casos`, `julix_calls`, `matriz_riesgo`. Las
que solo lo tienen indirecto vía join con `casos` (`actuaciones`,
`terminos`, `cobro_caso`, `case_documents`, `mensajes`) quedan fuera de
esta pasada, seguimiento futuro documentado.

Diseño (fail-open con narrowing explícito, decisión confirmada con el
usuario -- la alternativa era fail-closed de punta a punta, que hubiera
exigido auditar y tocar ~8 rutas de auth adicionales):
  - Cada conexión nueva arranca sin ningún GUC seteado -- `current_setting`
    con `missing_ok=true` devuelve NULL, así que por defecto NINGUNA fila
    de las 4 tablas es visible salvo que algo la angoste.
  - El middleware de conexión-por-request (`api/julix_endpoint.py`) setea
    `app.bypass_rls='true'` apenas adquiere la conexión -- ventana
    necesaria para que `_resolver_usuario` (o los handlers de
    `julix_endpoint.py` que resuelven su propio `despacho_id`) puedan leer
    `users` por PK ANTES de saber a qué despacho pertenece ese usuario
    (huevo y gallina real: no se puede angostar por `despacho_id` sin
    antes leer la fila que dice cuál es).
  - `aplicar_contexto_despacho()` angosta ese bypass inicial al despacho
    real apenas se conoce -- es la función que hace el corte real.
  - Postgres ignora las políticas RLS para el rol dueño de la tabla salvo
    que se agregue `FORCE ROW LEVEL SECURITY` -- Vridik usa un solo rol de
    DB para todo (no hay separación owner/app-role), así que sin `FORCE`
    esto sería un no-op total tanto en producción como en tests.

Riesgo residual del diseño fail-open: un endpoint FUTURO que lea/escriba
alguna de las 4 tablas sin pasar por `_resolver_usuario`/
`aplicar_contexto_despacho` heredaría el bypass en silencio (exactamente lo
que pasaba hoy con `api/julix_endpoint.py::julix_query`/`julix_stream`,
encontrado y corregido en esta misma pasada). Mitigación acordada:
`tests/test_rls_coverage.py` recorre `api/*_endpoint.py` y falla si
encuentra una ruta nueva en esa situación.
"""

from __future__ import annotations

import logging

from core.auth import ensure_users_table
from core.case import ensure_casos_table
from core.cumplimiento import ensure_matriz_riesgo_table
from core.despachos import ensure_despachos_table
from julix.ledger import ensure_julix_calls_table

logger = logging.getLogger("vridik.rls")

# Cada tabla necesita su propio chequeo de "filas pendientes de backfill"
# antes de aplicar FORCE -- users/casos/matriz_riesgo tienen despacho_id
# NOT NULL (backfilleado a NOT NULL, o NOT NULL desde su creación), un
# IS NULL llano alcanza. julix_calls es la excepción real: filas sin
# user_id (banco de evaluación S5, ver julix/ledger.py) quedan con
# despacho_id NULL A PROPÓSITO para siempre -- ahí el chequeo tiene que
# ser el mismo que usa ensure_julix_calls_despacho_backfill(), no un
# IS NULL genérico, o nunca se aplicaría FORCE en esa tabla.
_TABLAS_RLS = {
    "users": "SELECT EXISTS(SELECT 1 FROM users WHERE despacho_id IS NULL)",
    "casos": "SELECT EXISTS(SELECT 1 FROM casos WHERE despacho_id IS NULL)",
    "julix_calls": "SELECT EXISTS(SELECT 1 FROM julix_calls WHERE despacho_id IS NULL AND user_id IS NOT NULL)",
    "matriz_riesgo": "SELECT EXISTS(SELECT 1 FROM matriz_riesgo WHERE despacho_id IS NULL)",
}


async def ensure_rls_policies(conn) -> None:
    """Idempotente. Debe correr DESPUÉS de los backfills de despacho_id
    (`ensure_despachos_backfill`/`ensure_casos_despacho_backfill`/
    `ensure_julix_calls_despacho_backfill` en `app/main.py`) -- `FORCE ROW
    LEVEL SECURITY` sobre una tabla con filas `despacho_id IS NULL`
    pendientes las dejaría invisibles para todos, incluido el bootstrap.

    `conn` es una conexión ya adquirida del pool (mismo patrón que el
    resto de los `ensure_*_backfill` en `app/main.py`) -- se le setea
    bypass propio acá mismo, porque los chequeos de "filas pendientes" de
    abajo son SELECTs normales, sujetos a RLS apenas la política ya existe
    de una corrida anterior (arranques posteriores al primero)."""
    await conn.execute("SELECT set_config('app.bypass_rls', 'true', false)")

    # matriz_riesgo nunca se crea en el bootstrap normal (solo perezosa,
    # la primera vez que alguien pega a /clientes) -- sin esto, ALTER
    # TABLE explotaría con "relation does not exist" en una base fresca.
    await ensure_users_table(conn)
    await ensure_despachos_table(conn)  # agrega users.despacho_id
    await ensure_casos_table(conn)
    await ensure_julix_calls_table(conn)
    await ensure_matriz_riesgo_table(conn)

    for tabla, query_pendientes in _TABLAS_RLS.items():
        hay_pendientes = await conn.fetchval(query_pendientes)
        if hay_pendientes:
            logger.critical(
                "Vridik/RLS: %s tiene filas con despacho_id pendiente de backfill -- "
                "se salta FORCE ROW LEVEL SECURITY en esta pasada para no esconderlas "
                "por accidente, se reintenta en el próximo arranque.",
                tabla,
            )
            continue

        await conn.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        await conn.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
        await conn.execute(
            f"""
            DO $$ BEGIN
                CREATE POLICY {tabla}_tenant_isolation ON {tabla}
                    USING (
                        despacho_id::text = current_setting('app.despacho_id', true)
                        OR current_setting('app.bypass_rls', true) = 'true'
                    )
                    WITH CHECK (
                        despacho_id::text = current_setting('app.despacho_id', true)
                        OR current_setting('app.bypass_rls', true) = 'true'
                    );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """
        )

    # No deja esta conexión "sucia" de vuelta al pool -- aunque el
    # middleware de conexión-por-request también resetea/vuelve a setear
    # bypass en cada request nueva (self-healing), esta conexión de
    # bootstrap nunca pasa por ese middleware.
    await conn.execute("RESET app.bypass_rls")


async def aplicar_contexto_despacho(conn, *, despacho_id: str | None, es_superadmin: bool) -> None:
    """Angosta el bypass inicial (seteado por el middleware de conexión
    por request en `api/julix_endpoint.py`) al despacho real del usuario
    autenticado. Se llama en el único momento en que YA se sabe a qué
    despacho pertenece quien pide -- `api/admin_endpoint.py::
    _resolver_usuario`, y los handlers de `api/julix_endpoint.py` que
    resuelven su propio `despacho_id` de forma independiente
    (`julix_query`; `julix_stream` maneja su propia conexión dedicada,
    mismo motivo que `api/events_endpoint.py`, y llama esto sobre ESA
    conexión).

    Un superadmin de plataforma se queda con el bypass activo -- ya
    documentado en el resto de la app como el único rol que legítimamente
    ve todos los despachos sin scoping (`api/platform_endpoint.py`).

    `despacho_id=None` (usuario legacy sin despacho asignado, no debería
    pasar tras el backfill de Fase 4 pero no se asume imposible) también
    deja el bypass tal cual -- angostar a un valor inexistente bloquearía
    silenciosamente a ese usuario de todo, peor que el comportamiento de
    hoy sin RLS."""
    if es_superadmin or despacho_id is None:
        return
    await conn.execute("SELECT set_config('app.bypass_rls', 'false', false)")
    await conn.execute("SELECT set_config('app.despacho_id', $1, false)", str(despacho_id))
