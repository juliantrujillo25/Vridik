"""
Vridik — tests/test_rate_limit.py
Roadmap Fase 1, Semana 12-13 (hardening): prueba core/rate_limit.py directo
contra PostgreSQL real (fixture `db` de tests/conftest.py -- se salta sin
TEST_DATABASE_URL, nunca corre contra SQLite). A diferencia de
tests/test_auth_refresh.py (fake, prueba el wiring HTTP del 429), esto
valida que las queries SQL de excede_limite_login()/excede_limite_totp()
son sintácticamente correctas y filtran bien contra un motor real -- INET,
JSONB ->> e IS NOT DISTINCT FROM no se pueden confiar a un fake.
"""

from __future__ import annotations

import pytest

from core.auth_events import registrar_evento
from core.rate_limit import MAX_FALLOS_LOGIN, MAX_FALLOS_TOTP, excede_limite_login, excede_limite_totp


@pytest.mark.asyncio
async def test_no_excede_limite_login_con_pocos_fallos(db, make_user):
    user = await make_user()
    for _ in range(MAX_FALLOS_LOGIN - 1):
        await registrar_evento(
            db, event_type="login_failed", metadata={"email": user["email"]}, ip_address="1.2.3.4",
        )
    assert await excede_limite_login(db, email=user["email"], ip_address="1.2.3.4") is False


@pytest.mark.asyncio
async def test_excede_limite_login_tras_MAX_FALLOS(db, make_user):
    user = await make_user()
    for _ in range(MAX_FALLOS_LOGIN):
        await registrar_evento(
            db, event_type="login_failed", metadata={"email": user["email"]}, ip_address="1.2.3.4",
        )
    assert await excede_limite_login(db, email=user["email"], ip_address="1.2.3.4") is True


@pytest.mark.asyncio
async def test_limite_login_es_por_email_e_ip_no_solo_email(db, make_user):
    """Los mismos fallos desde OTRA IP no deben contar para esta IP -- el
    límite es por la combinación email+IP, no solo por email."""
    user = await make_user()
    for _ in range(MAX_FALLOS_LOGIN):
        await registrar_evento(
            db, event_type="login_failed", metadata={"email": user["email"]}, ip_address="9.9.9.9",
        )
    assert await excede_limite_login(db, email=user["email"], ip_address="1.2.3.4") is False


@pytest.mark.asyncio
async def test_limite_login_ignora_fallos_de_totp(db, make_user):
    """Un fallo de código TOTP (paso 2fa) no debe contar para el límite de
    contraseña -- son dos límites independientes (10 vs 5)."""
    user = await make_user()
    for _ in range(MAX_FALLOS_LOGIN):
        await registrar_evento(
            db, event_type="login_failed", user_id=user["id"], metadata={"paso": "2fa"}, ip_address="1.2.3.4",
        )
    assert await excede_limite_login(db, email=user["email"], ip_address="1.2.3.4") is False


@pytest.mark.asyncio
async def test_no_excede_limite_totp_con_pocos_fallos(db, make_user):
    user = await make_user()
    for _ in range(MAX_FALLOS_TOTP - 1):
        await registrar_evento(db, event_type="login_failed", user_id=user["id"], metadata={"paso": "2fa"})
    assert await excede_limite_totp(db, user_id=user["id"]) is False


@pytest.mark.asyncio
async def test_excede_limite_totp_tras_MAX_FALLOS(db, make_user):
    user = await make_user()
    for _ in range(MAX_FALLOS_TOTP):
        await registrar_evento(db, event_type="login_failed", user_id=user["id"], metadata={"paso": "2fa"})
    assert await excede_limite_totp(db, user_id=user["id"]) is True


@pytest.mark.asyncio
async def test_limite_totp_es_por_usuario(db, make_user):
    """Los fallos de TOTP de un usuario no deben contar para otro."""
    victima = await make_user()
    otro = await make_user()
    for _ in range(MAX_FALLOS_TOTP):
        await registrar_evento(db, event_type="login_failed", user_id=otro["id"], metadata={"paso": "2fa"})
    assert await excede_limite_totp(db, user_id=victima["id"]) is False


@pytest.mark.asyncio
async def test_ip_desconocida_se_agrupa_consigo_misma(db, make_user):
    """Sin IP determinable (None), los intentos deben seguir agrupándose
    entre sí -- IS NOT DISTINCT FROM, no una igualdad que nunca matchea con
    NULL."""
    user = await make_user()
    for _ in range(MAX_FALLOS_LOGIN):
        await registrar_evento(
            db, event_type="login_failed", metadata={"email": user["email"]}, ip_address=None,
        )
    assert await excede_limite_login(db, email=user["email"], ip_address=None) is True
