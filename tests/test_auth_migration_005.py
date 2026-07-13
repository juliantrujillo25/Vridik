"""
Vridik — tests/test_auth_migration_005.py
core.auth.ensure_auth_migration_005() -- bootstrap idempotente de
migrations/005_auth_roles_refresh_tokens.sql (roles, user_credentials,
refresh_tokens, auth_events). Nunca existió una versión ejecutable de esta
migración en el código (solo el .sql de referencia) -- mismo hueco que
julix_calls antes de ensure_julix_calls_table(). Se llama una sola vez al
arrancar el proceso (app/main.py), no en cada request; estos tests solo
verifican que la función en sí es correcta e idempotente contra un fake de
conexión, no el wiring de app/main.py.
"""

from __future__ import annotations

import pytest

from core.auth import ensure_auth_migration_005


class _FakeConn:
    def __init__(self):
        self.ejecutadas: list[str] = []

    async def execute(self, query: str, *args):
        self.ejecutadas.append(query.strip())
        return "OK"


@pytest.mark.asyncio
async def test_ensure_auth_migration_005_crea_las_cuatro_tablas():
    conn = _FakeConn()
    await ensure_auth_migration_005(conn)

    for tabla in ("roles", "user_credentials", "refresh_tokens", "auth_events"):
        assert any(
            q.startswith(f"CREATE TABLE IF NOT EXISTS {tabla}") for q in conn.ejecutadas
        ), f"falta el CREATE TABLE IF NOT EXISTS de {tabla}"


@pytest.mark.asyncio
async def test_ensure_auth_migration_005_hace_backfill_de_role_id():
    conn = _FakeConn()
    await ensure_auth_migration_005(conn)

    assert any(
        q.startswith("UPDATE users SET role_id") and "WHERE role_id IS NULL" in q for q in conn.ejecutadas
    )


@pytest.mark.asyncio
async def test_ensure_auth_migration_005_semillas_roles_con_on_conflict_do_nothing():
    """Los 3 roles (admin/seller/customer) se insertan con ON CONFLICT DO
    NOTHING -- correrlo de nuevo no debe intentar duplicar ni fallar por
    violar el UNIQUE de `codigo`."""
    conn = _FakeConn()
    await ensure_auth_migration_005(conn)

    insert_roles = next(q for q in conn.ejecutadas if q.startswith("INSERT INTO roles"))
    assert "ON CONFLICT (id) DO NOTHING" in insert_roles
    assert "admin" in insert_roles and "seller" in insert_roles and "customer" in insert_roles


@pytest.mark.asyncio
async def test_ensure_auth_migration_005_es_idempotente():
    """Correrla dos veces (arranque + un redeploy sin cambios de esquema)
    no debe fallar -- todo el DDL es IF NOT EXISTS / ON CONFLICT."""
    conn = _FakeConn()
    await ensure_auth_migration_005(conn)
    primera_pasada = len(conn.ejecutadas)
    await ensure_auth_migration_005(conn)

    assert len(conn.ejecutadas) == primera_pasada * 2
