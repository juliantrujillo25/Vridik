"""
Vridik — tests/test_rls.py
Hardening (core/rls.py): Row-Level Security de Postgres como SEGUNDA capa
de aislamiento entre despachos, sobre las 4 tablas con `despacho_id`
directo (`users`, `casos`, `julix_calls`, `matriz_riesgo`). No reemplaza
los checks de aplicación que ya existen -- prueba que la base de datos
misma respalda esos checks, incluso si algún endpoint se olvidara de
filtrar por despacho.

Postgres real (fixture `db`, rollback transaccional) -- RLS no existe
contra un fake, esto tiene que correr contra SQL de verdad. `db` deja
`app.bypass_rls='true'` seteado por defecto (tests/conftest.py) para que
los ~300 tests que no prueban RLS en sí sigan funcionando -- estos tests
lo revocan explícitamente para probar el enforcement real.

`ensure_rls_policies()` termina reseteando `app.bypass_rls` (para no
devolver la conexión de bootstrap "sucia" al pool en producción) -- acá
hay que volver a setearlo después de llamarla y antes de sembrar datos con
`make_despacho`/`make_user` (que sí necesitan bypass activo para poder
escribir en `users`).
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import asyncpg
import pytest

from core.admin import change_role
from core.rls import aplicar_contexto_despacho, ensure_rls_policies


async def _preparar_con_bypass(db) -> None:
    await ensure_rls_policies(db)
    await db.execute("SELECT set_config('app.bypass_rls', 'true', false)")


async def _sin_contexto(db) -> None:
    await db.execute("RESET app.bypass_rls")
    await db.execute("RESET app.despacho_id")


async def _como_despacho(db, despacho_id: str) -> None:
    await db.execute("SELECT set_config('app.bypass_rls', 'false', false)")
    await db.execute("SELECT set_config('app.despacho_id', $1, false)", str(despacho_id))


@pytest.mark.asyncio
async def test_sin_contexto_no_ve_filas_de_users_ni_casos(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso_id = await db.fetchval(
        "INSERT INTO casos (cliente_id, despacho_id, titulo) VALUES ($1, $2, 'caso') RETURNING id",
        cliente["id"], despacho_id,
    )

    # confirma que la fila existe de verdad antes de probar el bloqueo
    assert await db.fetchval("SELECT count(*) FROM users WHERE id = $1", cliente["id"]) == 1
    assert await db.fetchval("SELECT count(*) FROM casos WHERE id = $1", caso_id) == 1

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM users WHERE id = $1", cliente["id"]) == 0
    assert await db.fetchval("SELECT count(*) FROM casos WHERE id = $1", caso_id) == 0


@pytest.mark.asyncio
async def test_con_despacho_id_correcto_ve_solo_lo_suyo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    cliente_a = await make_user(role="cliente", despacho_id=despacho_a)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)
    caso_a = await db.fetchval(
        "INSERT INTO casos (cliente_id, despacho_id, titulo) VALUES ($1, $2, 'caso A') RETURNING id",
        cliente_a["id"], despacho_a,
    )
    await db.fetchval(
        "INSERT INTO casos (cliente_id, despacho_id, titulo) VALUES ($1, $2, 'caso B') RETURNING id",
        cliente_b["id"], despacho_b,
    )

    await _como_despacho(db, despacho_a)
    casos_visibles = await db.fetch("SELECT id FROM casos")
    assert {str(c["id"]) for c in casos_visibles} == {str(caso_a)}

    usuarios_visibles = await db.fetch("SELECT id FROM users WHERE role = 'cliente'")
    assert str(cliente_b["id"]) not in {str(u["id"]) for u in usuarios_visibles}


@pytest.mark.asyncio
async def test_bypass_ve_todo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    cliente_a = await make_user(role="cliente", despacho_id=despacho_a)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)

    ids_visibles = {str(u["id"]) for u in await db.fetch("SELECT id FROM users WHERE role = 'cliente'")}
    assert {cliente_a["id"], cliente_b["id"]}.issubset(ids_visibles)


@pytest.mark.asyncio
async def test_idor_cambiar_rol_de_usuario_de_otro_despacho_afecta_cero_filas(db, make_despacho, make_user):
    """Hoy (sin RLS), un admin del Despacho A que conoce/adivina un
    user_id del Despacho B puede cambiarle el rol vía PATCH
    /admin/users/{id}/role -- core/admin.py::change_role nunca filtró por
    despacho_id. Con el contexto angosteado, la fila de B es invisible
    para la conexión de A -- change_role() devuelve None (0 filas
    afectadas), lo mismo que si el usuario no existiera."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    await make_user(role="admin", despacho_id=despacho_a)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)

    await _como_despacho(db, despacho_a)
    resultado = await change_role(db, user_id=cliente_b["id"], new_role="admin")
    assert resultado is None

    await _preparar_con_bypass(db)
    rol_real = await db.fetchval("SELECT role FROM users WHERE id = $1", cliente_b["id"])
    assert rol_real == "cliente"  # nunca se tocó


@pytest.mark.asyncio
async def test_julix_calls_respeta_el_contexto_angosteado_no_el_bypass(db, make_despacho, make_user):
    """Regresión del hallazgo real de esta pasada: api/julix_endpoint.py
    (julix_query/julix_stream) decodifica su propio JWT y resuelve
    despacho_id sin pasar por api/admin_endpoint.py::_resolver_usuario --
    sin llamar aplicar_contexto_despacho() ahí, la conexión del request se
    quedaba en bypass_rls='true' (el default del middleware) de punta a
    punta, y julix_calls (la tabla que ese endpoint escribe) quedaba con
    RLS efectivamente desactivado. Simula exactamente esa secuencia:
    aplicar_contexto_despacho(despacho=A) y confirmar que un INSERT en
    julix_calls con despacho_id=B (el bug real, si el narrowing nunca se
    hubiera llamado) queda rechazado por la política WITH CHECK."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()

    await aplicar_contexto_despacho(db, despacho_id=despacho_a, es_superadmin=False)

    # Savepoint (async with db.transaction() anidada dentro de la
    # transacción ya abierta por la fixture db) -- sin esto, el error de
    # RLS abortaría TODA la transacción del test, y el INSERT válido de
    # abajo fallaría también con "current transaction is aborted".
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO julix_calls (
                    user_id, caso_id, despacho_id, tarea, model, prompt_version, prompt_hash,
                    input_tokens, output_tokens, costo_usd, latency_ms, status, environment, created_at
                ) VALUES (NULL, NULL, $1, 'ugpp_demanda', 'claude-sonnet-5', 1, 'x', 1, 1, 0.01, 100, 'ok', 'production', now())
                """,
                despacho_b,
            )

    # el mismo INSERT con el despacho angosteado real sí funciona
    await db.execute(
        """
        INSERT INTO julix_calls (
            user_id, caso_id, despacho_id, tarea, model, prompt_version, prompt_hash,
            input_tokens, output_tokens, costo_usd, latency_ms, status, environment, created_at
        ) VALUES (NULL, NULL, $1, 'ugpp_demanda', 'claude-sonnet-5', 1, 'x', 1, 1, 0.01, 100, 'ok', 'production', now())
        """,
        despacho_a,
    )
