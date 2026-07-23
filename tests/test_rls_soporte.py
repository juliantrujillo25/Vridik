"""
Vridik — tests/test_rls_soporte.py
Auditoría de seguridad 22-jul-2026 (core/rls.py::ensure_rls_policies_soporte):
Row-Level Security de Postgres sobre las tablas de soporte que quedaron
fuera de las dos pasadas anteriores pese a contener datos sensibles/
tenant-scoped -- `refresh_tokens`/`auth_events`/`user_events` (join
indirecto vía `user_id` -> `users.despacho_id`), `pdf_jobs` (mismo join
pero `user_id` es TEXT sin FK, no siempre un UUID válido) y `despachos`
(caso especial: ES el tenant, la política compara `id` en vez de
`despacho_id`). Mismo criterio que tests/test_rls.py y tests/
test_rls_indirectas.py -- Postgres real, `db` deja bypass activo por
defecto, se revoca acá para probar el enforcement real.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from core.rls import (
    aplicar_contexto_despacho,
    ensure_rls_policies,
    ensure_rls_policies_indirectas,
    ensure_rls_policies_soporte,
)


async def _preparar_con_bypass(db) -> None:
    await ensure_rls_policies(db)
    await ensure_rls_policies_indirectas(db)
    await ensure_rls_policies_soporte(db)
    await db.execute("SELECT set_config('app.bypass_rls', 'true', false)")


async def _sin_contexto(db) -> None:
    await db.execute("RESET app.bypass_rls")
    await db.execute("RESET app.despacho_id")


async def _como_despacho(db, despacho_id: str) -> None:
    await db.execute("SELECT set_config('app.bypass_rls', 'false', false)")
    await db.execute("SELECT set_config('app.despacho_id', $1, false)", str(despacho_id))


async def _insertar_refresh_token(db, *, user_id: str) -> str:
    return await db.fetchval(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
        VALUES ($1, $2, $3, now() + interval '7 days')
        RETURNING id
        """,
        user_id, str(uuid.uuid4()), str(uuid.uuid4()),
    )


async def _insertar_auth_event(db, *, user_id: str | None, event_type: str = "login_success") -> int:
    return await db.fetchval(
        "INSERT INTO auth_events (user_id, event_type) VALUES ($1, $2) RETURNING id",
        user_id, event_type,
    )


async def _insertar_user_event(db, *, user_id: str, event_type: str = "message.new") -> int:
    return await db.fetchval(
        "INSERT INTO user_events (user_id, event_type) VALUES ($1, $2) RETURNING id",
        user_id, event_type,
    )


async def _insertar_pdf_job(db, *, user_id: str | None, query: str = "query de prueba") -> str:
    return await db.fetchval(
        "INSERT INTO pdf_jobs (query, user_id) VALUES ($1, $2) RETURNING id",
        query, user_id,
    )


@pytest.mark.asyncio
async def test_sin_contexto_no_ve_filas_de_ninguna_tabla_via_usuario(db, make_despacho, make_user):
    """auth_events no arranca vacía -- db/seed_railway.sql deja 4 filas
    ('user_created' de los usuarios seed) COMMITEADAS fuera de la
    transacción de este test (ver tests/conftest.py), así que un
    `count(*)` a secas no sirve acá -- se filtra por el id propio, mismo
    criterio que el resto de este archivo usa para refresh_tokens/
    user_events/pdf_jobs (tablas que si arrancan vacías, pero se filtra
    igual por consistencia)."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)

    rt_id = await _insertar_refresh_token(db, user_id=user_a["id"])
    ae_id = await _insertar_auth_event(db, user_id=user_a["id"])
    ue_id = await _insertar_user_event(db, user_id=user_a["id"])
    pj_id = await _insertar_pdf_job(db, user_id=user_a["id"])

    # confirma que las filas existen de verdad antes de probar el bloqueo
    assert await db.fetchval("SELECT count(*) FROM refresh_tokens WHERE id = $1", rt_id) == 1
    assert await db.fetchval("SELECT count(*) FROM auth_events WHERE id = $1", ae_id) == 1
    assert await db.fetchval("SELECT count(*) FROM user_events WHERE id = $1", ue_id) == 1
    assert await db.fetchval("SELECT count(*) FROM pdf_jobs WHERE id = $1", pj_id) == 1

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM refresh_tokens WHERE id = $1", rt_id) == 0
    assert await db.fetchval("SELECT count(*) FROM auth_events WHERE id = $1", ae_id) == 0
    assert await db.fetchval("SELECT count(*) FROM user_events WHERE id = $1", ue_id) == 0
    assert await db.fetchval("SELECT count(*) FROM pdf_jobs WHERE id = $1", pj_id) == 0


@pytest.mark.asyncio
async def test_con_despacho_correcto_ve_solo_lo_suyo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)
    user_b = await make_user(role="cliente", despacho_id=despacho_b)

    rt_a = await _insertar_refresh_token(db, user_id=user_a["id"])
    await _insertar_refresh_token(db, user_id=user_b["id"])
    ae_a = await _insertar_auth_event(db, user_id=user_a["id"])
    await _insertar_auth_event(db, user_id=user_b["id"])
    ue_a = await _insertar_user_event(db, user_id=user_a["id"])
    await _insertar_user_event(db, user_id=user_b["id"])
    pj_a = await _insertar_pdf_job(db, user_id=user_a["id"])
    await _insertar_pdf_job(db, user_id=user_b["id"])

    await _como_despacho(db, despacho_a)
    assert {str(r["id"]) for r in await db.fetch("SELECT id FROM refresh_tokens")} == {str(rt_a)}
    assert {r["id"] for r in await db.fetch("SELECT id FROM auth_events")} == {ae_a}
    assert {r["id"] for r in await db.fetch("SELECT id FROM user_events")} == {ue_a}
    assert {str(r["id"]) for r in await db.fetch("SELECT id FROM pdf_jobs")} == {str(pj_a)}


@pytest.mark.asyncio
async def test_bypass_ve_todo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)
    user_b = await make_user(role="cliente", despacho_id=despacho_b)

    await _insertar_refresh_token(db, user_id=user_a["id"])
    await _insertar_refresh_token(db, user_id=user_b["id"])

    assert await db.fetchval("SELECT count(*) FROM refresh_tokens") == 2


@pytest.mark.asyncio
async def test_insertar_refresh_token_de_usuario_ajeno_bajo_contexto_angosteado_falla(db, make_despacho, make_user):
    """WITH CHECK, no solo USING: un despacho no puede ni siquiera insertar
    un refresh_token que apunte a un usuario de otro despacho, aunque
    conociera/adivinara su user_id -- mismo tipo de regresión IDOR que
    test_rls.py/test_rls_indirectas.py ya prueban para las demás tablas."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)
    user_b = await make_user(role="cliente", despacho_id=despacho_b)

    await aplicar_contexto_despacho(db, despacho_id=despacho_a, es_superadmin=False)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        async with db.transaction():
            await _insertar_refresh_token(db, user_id=user_b["id"])

    # el mismo INSERT contra un usuario del propio despacho sí funciona
    await _insertar_refresh_token(db, user_id=user_a["id"])


@pytest.mark.asyncio
async def test_auth_events_con_user_id_null_solo_visible_bajo_bypass(db, make_despacho, make_user):
    """login_failed contra un email que no existe guarda user_id=NULL a
    propósito (api/auth_endpoint.py::login) -- esa fila no debe volverse
    visible bajo NINGÚN contexto angosteado (no hay despacho al que
    atribuirla), solo bajo bypass."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)

    ae_null = await _insertar_auth_event(db, user_id=None, event_type="login_failed")
    ae_a = await _insertar_auth_event(db, user_id=user_a["id"])

    await _como_despacho(db, despacho_a)
    visibles_ids = {ae_null, ae_a}
    assert {r["id"] for r in await db.fetch("SELECT id FROM auth_events")} & visibles_ids == {ae_a}

    # db/seed_railway.sql deja filas propias en auth_events (ver docstring
    # del test de arriba) -- se filtra por id en vez de un count(*) a secas.
    await _preparar_con_bypass(db)
    ids_bajo_bypass = {r["id"] for r in await db.fetch("SELECT id FROM auth_events WHERE id = ANY($1)", list(visibles_ids))}
    assert ids_bajo_bypass == visibles_ids


@pytest.mark.asyncio
async def test_pdf_jobs_con_user_id_no_uuid_no_explota_y_queda_invisible(db, make_despacho, make_user):
    """pdf_jobs.user_id es TEXT sin FK -- workers/pdf_worker.py documenta
    que puede no ser un UUID real (p.ej. el fallback 'usuario_desconocido').
    El cast blindado con CASE+regex (core/rls.py::_REGEX_UUID) no debe
    reventar el SELECT/INSERT entero; la fila simplemente queda invisible
    fuera de bypass, igual que una fila con user_id NULL."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    user_a = await make_user(role="cliente", despacho_id=despacho_a)

    pj_valido = await _insertar_pdf_job(db, user_id=user_a["id"])
    await _insertar_pdf_job(db, user_id="usuario_desconocido")
    await _insertar_pdf_job(db, user_id=None)

    assert await db.fetchval("SELECT count(*) FROM pdf_jobs") == 3

    await _como_despacho(db, despacho_a)
    assert {str(r["id"]) for r in await db.fetch("SELECT id FROM pdf_jobs")} == {str(pj_valido)}

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM pdf_jobs") == 0


@pytest.mark.asyncio
async def test_despachos_respeta_el_contexto_por_id_propio(db, make_despacho):
    """despachos ES el tenant -- la política compara `id` directo, no una
    columna despacho_id propia. Sin contexto, ni siquiera el propio
    despacho es visible; con el despacho correcto angosteado, solo esa
    fila (nunca la de otro despacho)."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM despachos WHERE id = $1", despacho_a) == 0

    await _como_despacho(db, despacho_a)
    visibles = {str(r["id"]) for r in await db.fetch("SELECT id FROM despachos")}
    assert visibles == {str(despacho_a)}
    assert str(despacho_b) not in visibles


@pytest.mark.asyncio
async def test_actualizar_despacho_ajeno_bajo_contexto_angosteado_afecta_cero_filas(db, make_despacho):
    """WITH CHECK sobre despachos: un despacho no puede modificar la fila
    de otro aunque conozca/adivine su id -- mismo tipo de regresión IDOR
    que test_rls.py ya prueba (test_idor_cambiar_rol_de_usuario_de_otro_
    despacho_afecta_cero_filas) para users."""
    await _preparar_con_bypass(db)
    despacho_a = await make_despacho()
    despacho_b = await make_despacho(nombre="Despacho B original")

    await _como_despacho(db, despacho_a)
    resultado = await db.execute("UPDATE despachos SET nombre = 'hackeado' WHERE id = $1", despacho_b)
    assert resultado == "UPDATE 0"

    await _preparar_con_bypass(db)
    nombre_real = await db.fetchval("SELECT nombre FROM despachos WHERE id = $1", despacho_b)
    assert nombre_real == "Despacho B original"
