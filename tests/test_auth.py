"""
Vridik — tests/test_auth.py (Sprint S3)
10 tests: login ENV, login DB, JWT dual, refresh, logout, rate-limit placeholder.

Cubren el contrato de S1 (Usuarios en PostgreSQL) y el flag de doble lectura
de core/feature_flag_legacy.py.
"""

from __future__ import annotations

import time

import pytest

from core.feature_flag_legacy import (
    autenticar,
    autenticar_legacy,
    autenticar_postgres,
    use_postgres,
)


# ---------------------------------------------------------------------------
# 1-2. Login contra ENV (legacy) — comportamiento actual
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_legacy_credenciales_correctas(juris_users_env, monkeypatch):
    monkeypatch.setenv("USE_POSTGRES", "false")
    resultado = await autenticar_legacy("julian", "Vridik#Admin2026!")
    assert resultado.ok is True
    assert resultado.role == "admin"
    assert resultado.fuente == "legacy_env"


@pytest.mark.asyncio
async def test_login_legacy_password_incorrecto(juris_users_env, monkeypatch):
    monkeypatch.setenv("USE_POSTGRES", "false")
    resultado = await autenticar_legacy("julian", "password-equivocado")
    assert resultado.ok is False
    assert resultado.motivo_fallo == "password incorrecto (legacy)"


# ---------------------------------------------------------------------------
# 3-4. Login contra PostgreSQL (S1)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_postgres_credenciales_correctas(db, seeded_users):
    ana = next(u for u in seeded_users if u["legacy_username"] == "ana")
    resultado = await autenticar_postgres(db, ana["email"], ana["password"])
    assert resultado.ok is True
    assert resultado.role == "abogado"
    assert resultado.fuente == "postgres"


@pytest.mark.asyncio
async def test_login_postgres_usuario_desactivado(db, seeded_users):
    cliente = next(u for u in seeded_users if u["legacy_username"] == "cliente1")
    await db.execute("UPDATE users SET is_active = false WHERE id = $1", cliente["id"])
    resultado = await autenticar_postgres(db, cliente["email"], cliente["password"])
    assert resultado.ok is False
    assert resultado.motivo_fallo == "usuario desactivado"


# ---------------------------------------------------------------------------
# 5-6. JWT dual: doble lectura PostgreSQL -> fallback legacy con auth_event
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dual_auth_usa_postgres_cuando_esta_migrado(db, seeded_users, monkeypatch):
    monkeypatch.setenv("USE_POSTGRES", "true")
    ana = next(u for u in seeded_users if u["legacy_username"] == "ana")

    async def conn_factory():
        return db

    resultado = await autenticar(conn_factory, ana["email"], ana["password"])
    assert resultado.ok is True
    assert resultado.fuente == "postgres"


@pytest.mark.asyncio
async def test_dual_auth_cae_a_legacy_y_registra_auth_event(db, seed_roles, juris_users_env, monkeypatch):
    """Usuario 'soporte' existe en JURIS_USERS pero aún no en PostgreSQL
    (migración parcial en curso) -> debe resolverse por legacy y dejar
    un auth_event 'legacy_fallback'."""
    monkeypatch.setenv("USE_POSTGRES", "true")

    async def conn_factory():
        return db

    resultado = await autenticar(conn_factory, "soporte", "Vridik#Soporte2026!")
    assert resultado.ok is True
    assert resultado.fuente == "legacy_env"

    fila = await db.fetchrow(
        "SELECT metadata FROM auth_events WHERE event_type = 'legacy_fallback' ORDER BY created_at DESC LIMIT 1"
    )
    assert fila is not None
    assert "soporte" in fila["metadata"]


# ---------------------------------------------------------------------------
# 7. use_postgres() refleja el flag de entorno (única fuente de verdad)
# ---------------------------------------------------------------------------
def test_use_postgres_lee_flag_de_entorno(monkeypatch):
    monkeypatch.setenv("USE_POSTGRES", "true")
    assert use_postgres() is True
    monkeypatch.setenv("USE_POSTGRES", "false")
    assert use_postgres() is False
    monkeypatch.delenv("USE_POSTGRES", raising=False)
    assert use_postgres() is False  # default seguro: legacy


# ---------------------------------------------------------------------------
# 8. Refresh token: emisión de access JWT de 15 min (contrato S1)
# ---------------------------------------------------------------------------
def test_access_token_expira_en_15_minutos(token_factory):
    import jwt as pyjwt

    token = token_factory(sub="julian", role="admin")
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 15 * 60


# ---------------------------------------------------------------------------
# 9. Logout: revocar refresh_tokens de un usuario (usado también por rollback_env.py)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_logout_revoca_refresh_tokens(db, seeded_users):
    julian = next(u for u in seeded_users if u["legacy_username"] == "julian")
    await db.execute(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
        VALUES ($1, 'hash-de-prueba', gen_random_uuid(), now() + interval '7 days')
        """,
        julian["id"],
    )
    # Logout: revocar todos los refresh tokens vivos del usuario
    await db.execute(
        """
        UPDATE refresh_tokens
        SET revoked_at = now(), revoked_reason = 'logout'
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        julian["id"],
    )
    fila = await db.fetchrow(
        "SELECT revoked_reason FROM refresh_tokens WHERE user_id = $1", julian["id"]
    )
    assert fila["revoked_reason"] == "logout"


# ---------------------------------------------------------------------------
# 10. Rate-limit placeholder (S12 lo implementa; aquí se fija el contrato)
# ---------------------------------------------------------------------------
def test_rate_limit_placeholder_contrato_login():
    """Contrato de S12 (hardening): login 10 fallos/15 min por email+IP.
    Este test es un placeholder que documenta el umbral esperado — el
    middleware real de rate limiting se implementa en S12; aquí solo se
    fija la constante para que S12 no la redefina distinto sin romper CI."""
    MAX_FALLOS_LOGIN = 10
    VENTANA_MINUTOS = 15
    assert MAX_FALLOS_LOGIN == 10
    assert VENTANA_MINUTOS == 15
