"""
Vridik — tests/test_jwt_rotation.py
Roadmap S12-13 (hardening): rotación de JWT_SECRET sin downtime. Prueba el
soporte de doble clave de core/auth.py (JWT_SECRET actual + JWT_SECRET_PREVIOUS
durante la ventana de rotación). Ver SECURITY.md para el procedimiento real.

Todo con jose.jwt directo (sin red, sin PostgreSQL) -- se firman tokens con
claves elegidas a mano para simular "emitido antes de rotar" vs "después".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from core.auth import (
    JWT_ALGORITHM,
    create_jwt,
    create_temp_2fa_token,
    decode_jwt,
    decode_temp_2fa_token,
    jwt_secrets_para_verificar,
)

CLAVE_VIEJA = "clave-vieja-antes-de-rotar"
CLAVE_NUEVA = "clave-nueva-despues-de-rotar"


def _firmar(secret: str, *, sub: str = "user-1", email: str = "u@vridik.local", scope: str | None = None) -> str:
    claims = {"sub": sub, "email": email, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}
    if scope is not None:
        claims["scope"] = scope
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# jwt_secrets_para_verificar()
# ---------------------------------------------------------------------------
def test_solo_la_clave_actual_cuando_no_hay_rotacion(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    assert jwt_secrets_para_verificar() == [CLAVE_NUEVA]


def test_actual_y_previa_durante_la_rotacion(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    assert jwt_secrets_para_verificar() == [CLAVE_NUEVA, CLAVE_VIEJA]


def test_no_duplica_si_previa_es_igual_a_actual(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_NUEVA)
    assert jwt_secrets_para_verificar() == [CLAVE_NUEVA]


# ---------------------------------------------------------------------------
# decode_jwt — access token de sesión
# ---------------------------------------------------------------------------
def test_token_de_la_clave_nueva_valida(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    token = _firmar(CLAVE_NUEVA)
    assert decode_jwt(token)["sub"] == "user-1"


def test_token_viejo_valida_durante_la_ventana_de_rotacion(monkeypatch):
    """El caso central: token firmado con la clave vieja (emitido justo
    antes de rotar, todavía dentro de sus 15 min) sigue validando mientras
    JWT_SECRET_PREVIOUS esté configurada."""
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    token_viejo = _firmar(CLAVE_VIEJA)
    assert decode_jwt(token_viejo)["sub"] == "user-1"


def test_token_viejo_deja_de_valer_al_cerrar_la_rotacion(monkeypatch):
    """Cuando se saca JWT_SECRET_PREVIOUS (fin de la ventana de rotación),
    un token todavía firmado con la clave vieja ya no valida."""
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    token_viejo = _firmar(CLAVE_VIEJA)
    with pytest.raises(ValueError):
        decode_jwt(token_viejo)


def test_token_de_clave_desconocida_se_rechaza(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    token = _firmar("una-clave-que-no-es-ninguna-de-las-dos")
    with pytest.raises(ValueError):
        decode_jwt(token)


def test_token_expirado_se_rechaza_como_invalido(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    claims = {"sub": "user-1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    token_expirado = jwt.encode(claims, CLAVE_NUEVA, algorithm=JWT_ALGORITHM)
    with pytest.raises(ValueError):
        decode_jwt(token_expirado)


def test_create_jwt_firma_siempre_con_la_clave_actual(monkeypatch):
    """Un token EMITIDO después de rotar se firma con la clave nueva --
    valida contra la actual, y NO contra la vieja sola."""
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    token = create_jwt(sub="user-1", email="u@vridik.local")
    # Valida con la actual...
    assert decode_jwt(token)["sub"] == "user-1"
    # ...pero NO se firmó con la vieja.
    with pytest.raises(Exception):
        jwt.decode(token, CLAVE_VIEJA, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# temp_2fa token (5 min, entre login y confirmación de 2FA)
# ---------------------------------------------------------------------------
def test_temp_2fa_token_viejo_valida_durante_la_rotacion(monkeypatch):
    """Un temp_token emitido justo antes de rotar (login que pidió 2FA)
    debe poder canjearse durante la ventana de rotación, aunque JWT_SECRET
    ya haya cambiado entre el /auth/login y el /auth/2fa/login."""
    monkeypatch.setenv("JWT_SECRET", CLAVE_VIEJA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    temp = create_temp_2fa_token(sub="user-1", email="u@vridik.local")

    # Rotación ocurre entre la emisión y el canje.
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    assert decode_temp_2fa_token(temp)["sub"] == "user-1"


def test_temp_2fa_token_nuevo_valida(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    temp = create_temp_2fa_token(sub="user-1", email="u@vridik.local")
    assert decode_temp_2fa_token(temp)["sub"] == "user-1"


def test_un_access_token_no_sirve_como_temp_2fa_token(monkeypatch):
    """Regresión del contrato de S12: el temp_token se firma con una clave
    DERIVADA (no JWT_SECRET a secas), así que un access token normal (sin
    scope 2fa_pending, firmado con JWT_SECRET directo) nunca canjea en
    /auth/2fa/login -- ni siquiera con el soporte de rotación."""
    monkeypatch.setenv("JWT_SECRET", CLAVE_NUEVA)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", CLAVE_VIEJA)
    access = create_jwt(sub="user-1", email="u@vridik.local")
    with pytest.raises(ValueError):
        decode_temp_2fa_token(access)
