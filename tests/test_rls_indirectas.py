"""
Vridik — tests/test_rls_indirectas.py
Track Forja TF1 / roadmap T8 (core/rls.py::ensure_rls_policies_indirectas):
Row-Level Security de Postgres sobre las 5 tablas que hasta ahora solo
tenían aislamiento de aplicación -- `actuaciones`, `terminos`,
`cobro_caso`, `case_documents` y la mensajería (`conversaciones`/
`mensajes`/`conversation_reads`). Mismo criterio que tests/test_rls.py
(Postgres real, `db` deja bypass activo por defecto, se revoca acá para
probar el enforcement real) -- no repite esos tests, los extiende a las
tablas que quedaron fuera de esa primera pasada.
"""

from __future__ import annotations

import asyncpg
import pytest

from core.rls import aplicar_contexto_despacho, ensure_rls_policies, ensure_rls_policies_indirectas


async def _preparar_con_bypass(db) -> None:
    await ensure_rls_policies(db)
    await ensure_rls_policies_indirectas(db)
    await db.execute("SELECT set_config('app.bypass_rls', 'true', false)")


async def _sin_contexto(db) -> None:
    await db.execute("RESET app.bypass_rls")
    await db.execute("RESET app.despacho_id")


async def _como_despacho(db, despacho_id: str) -> None:
    await db.execute("SELECT set_config('app.bypass_rls', 'false', false)")
    await db.execute("SELECT set_config('app.despacho_id', $1, false)", str(despacho_id))


async def _crear_caso(db, *, cliente_id: str, despacho_id: str, titulo: str = "caso") -> str:
    return await db.fetchval(
        "INSERT INTO casos (cliente_id, despacho_id, titulo) VALUES ($1, $2, $3) RETURNING id",
        cliente_id, despacho_id, titulo,
    )


async def _preparar_dos_despachos_con_casos(db, make_despacho, make_user):
    despacho_a = await make_despacho()
    despacho_b = await make_despacho()
    cliente_a = await make_user(role="cliente", despacho_id=despacho_a)
    cliente_b = await make_user(role="cliente", despacho_id=despacho_b)
    caso_a = await _crear_caso(db, cliente_id=cliente_a["id"], despacho_id=despacho_a, titulo="caso A")
    caso_b = await _crear_caso(db, cliente_id=cliente_b["id"], despacho_id=despacho_b, titulo="caso B")
    return {
        "despacho_a": despacho_a, "despacho_b": despacho_b,
        "cliente_a": cliente_a, "cliente_b": cliente_b,
        "caso_a": caso_a, "caso_b": caso_b,
    }


@pytest.mark.asyncio
async def test_sin_contexto_no_ve_filas_de_ninguna_tabla_indirecta(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    ctx = await _preparar_dos_despachos_con_casos(db, make_despacho, make_user)

    await db.execute(
        "INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza) "
        "VALUES ($1, $2, 'texto', 'otro', 0.9)",
        ctx["caso_a"], ctx["cliente_a"]["id"],
    )
    await db.execute(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'termino', CURRENT_DATE, 5, CURRENT_DATE + 7)",
        ctx["caso_a"], ctx["cliente_a"]["id"],
    )
    await db.execute("INSERT INTO cobro_caso (caso_id) VALUES ($1)", ctx["caso_a"])
    await db.execute(
        "INSERT INTO case_documents (caso_id, created_by, tarea, pregunta, contenido) "
        "VALUES ($1, $2, 'tarea', 'pregunta', 'contenido')",
        ctx["caso_a"], ctx["cliente_a"]["id"],
    )

    # confirma que las filas existen de verdad antes de probar el bloqueo
    assert await db.fetchval("SELECT count(*) FROM actuaciones") == 1
    assert await db.fetchval("SELECT count(*) FROM terminos") == 1
    assert await db.fetchval("SELECT count(*) FROM cobro_caso") == 1
    assert await db.fetchval("SELECT count(*) FROM case_documents") == 1

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM actuaciones") == 0
    assert await db.fetchval("SELECT count(*) FROM terminos") == 0
    assert await db.fetchval("SELECT count(*) FROM cobro_caso") == 0
    assert await db.fetchval("SELECT count(*) FROM case_documents") == 0


@pytest.mark.asyncio
async def test_con_despacho_correcto_ve_solo_lo_suyo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    ctx = await _preparar_dos_despachos_con_casos(db, make_despacho, make_user)

    act_a = await db.fetchval(
        "INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza) "
        "VALUES ($1, $2, 'de A', 'otro', 0.9) RETURNING id",
        ctx["caso_a"], ctx["cliente_a"]["id"],
    )
    await db.fetchval(
        "INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza) "
        "VALUES ($1, $2, 'de B', 'otro', 0.9) RETURNING id",
        ctx["caso_b"], ctx["cliente_b"]["id"],
    )

    await _como_despacho(db, ctx["despacho_a"])
    visibles = await db.fetch("SELECT id FROM actuaciones")
    assert {str(r["id"]) for r in visibles} == {str(act_a)}


@pytest.mark.asyncio
async def test_bypass_ve_todo(db, make_despacho, make_user):
    await _preparar_con_bypass(db)
    ctx = await _preparar_dos_despachos_con_casos(db, make_despacho, make_user)

    await db.execute("INSERT INTO cobro_caso (caso_id) VALUES ($1)", ctx["caso_a"])
    await db.execute("INSERT INTO cobro_caso (caso_id) VALUES ($1)", ctx["caso_b"])

    filas = await db.fetch("SELECT caso_id FROM cobro_caso")
    assert {str(f["caso_id"]) for f in filas} == {str(ctx["caso_a"]), str(ctx["caso_b"])}


@pytest.mark.asyncio
async def test_insertar_termino_en_caso_ajeno_bajo_contexto_angosteado_falla(db, make_despacho, make_user):
    """WITH CHECK, no solo USING: un despacho no puede ni siquiera INSERTAR
    una fila que apunte al caso de otro despacho, aunque conociera/adivinara
    su caso_id -- mismo tipo de regresión IDOR que test_rls.py prueba para
    julix_calls."""
    await _preparar_con_bypass(db)
    ctx = await _preparar_dos_despachos_con_casos(db, make_despacho, make_user)

    await aplicar_contexto_despacho(db, despacho_id=ctx["despacho_a"], es_superadmin=False)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        async with db.transaction():
            await db.execute(
                "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
                "VALUES ($1, $2, 'intento cruzado', CURRENT_DATE, 5, CURRENT_DATE + 7)",
                ctx["caso_b"], ctx["cliente_a"]["id"],
            )

    # el mismo INSERT contra el propio caso sí funciona
    await db.execute(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'intento propio', CURRENT_DATE, 5, CURRENT_DATE + 7)",
        ctx["caso_a"], ctx["cliente_a"]["id"],
    )


@pytest.mark.asyncio
async def test_mensajes_respeta_el_contexto_via_conversaciones(db, make_despacho, make_user):
    """mensajes no tiene caso_id propio -- el join real es mensajes ->
    conversaciones -> casos (ver core/mensajes.py). Este test es el que
    prueba que ese join extra funciona de verdad, no solo que compila."""
    await _preparar_con_bypass(db)
    ctx = await _preparar_dos_despachos_con_casos(db, make_despacho, make_user)

    conv_a = await db.fetchval(
        "INSERT INTO conversaciones (caso_id) VALUES ($1) RETURNING id", ctx["caso_a"],
    )
    conv_b = await db.fetchval(
        "INSERT INTO conversaciones (caso_id) VALUES ($1) RETURNING id", ctx["caso_b"],
    )
    msg_a = await db.fetchval(
        "INSERT INTO mensajes (conversacion_id, autor_id, texto) VALUES ($1, $2, 'de A') RETURNING id",
        conv_a, ctx["cliente_a"]["id"],
    )
    await db.fetchval(
        "INSERT INTO mensajes (conversacion_id, autor_id, texto) VALUES ($1, $2, 'de B') RETURNING id",
        conv_b, ctx["cliente_b"]["id"],
    )
    await db.execute(
        "INSERT INTO conversation_reads (conversacion_id, user_id) VALUES ($1, $2)",
        conv_a, ctx["cliente_a"]["id"],
    )
    await db.execute(
        "INSERT INTO conversation_reads (conversacion_id, user_id) VALUES ($1, $2)",
        conv_b, ctx["cliente_b"]["id"],
    )

    await _sin_contexto(db)
    assert await db.fetchval("SELECT count(*) FROM mensajes") == 0
    assert await db.fetchval("SELECT count(*) FROM conversaciones") == 0
    assert await db.fetchval("SELECT count(*) FROM conversation_reads") == 0

    await _como_despacho(db, ctx["despacho_a"])
    visibles = await db.fetch("SELECT id FROM mensajes")
    assert {str(r["id"]) for r in visibles} == {str(msg_a)}
    conversaciones_visibles = await db.fetch("SELECT id FROM conversaciones")
    assert {str(r["id"]) for r in conversaciones_visibles} == {str(conv_a)}
