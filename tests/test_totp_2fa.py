"""
Vridik — tests/test_totp_2fa.py (Sprint S12)
Prueba core/totp_2fa.py: generación/validación de códigos TOTP reales
(pyotp, sin red) y el flujo de activación en 2 pasos sobre un fake mínimo
de conexión asyncpg (nunca PostgreSQL real).
"""

from __future__ import annotations

import pyotp
import pytest

from core.totp_2fa import (
    confirmar_activacion,
    desactivar_totp,
    generar_codigos_respaldo,
    generar_secreto,
    iniciar_activacion,
    provisioning_uri,
    requiere_totp,
    verificar_codigo,
    verificar_codigo_respaldo,
    verificar_login_totp,
)


class _FakeUsersDB:
    """Fake mínimo de una conexión asyncpg sobre una única fila de
    `users` — suficiente para ejercitar el contrato de core/totp_2fa.py
    sin PostgreSQL real."""

    def __init__(self, user_id: str = "user-1"):
        self.filas = {
            user_id: {"totp_secret": None, "totp_enabled": False, "totp_activado_en": None},
        }

    async def execute(self, query: str, *args):
        if "totp_secret = $2" in query and "totp_enabled = false" in query:
            user_id, secreto = args
            self.filas[user_id]["totp_secret"] = secreto
            self.filas[user_id]["totp_enabled"] = False
            self.filas[user_id]["totp_activado_en"] = None
        elif "totp_enabled = true" in query:
            (user_id,) = args
            self.filas[user_id]["totp_enabled"] = True
            self.filas[user_id]["totp_activado_en"] = "now"
        elif "totp_enabled = false, totp_secret = NULL" in query:
            (user_id,) = args
            self.filas[user_id]["totp_enabled"] = False
            self.filas[user_id]["totp_secret"] = None
            self.filas[user_id]["totp_activado_en"] = None
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args):
        user_id = args[0]
        fila = self.filas.get(user_id)
        if fila is None:
            return None
        if "totp_enabled = true" in query and not fila["totp_enabled"]:
            return None  # simula el filtro real "AND totp_enabled = true" del SQL
        return fila


def test_generar_secreto_y_verificar_codigo_real():
    secreto = generar_secreto()
    assert len(secreto) >= 16
    codigo_valido = pyotp.totp.TOTP(secreto).now()
    assert verificar_codigo(secreto, codigo_valido) is True
    assert verificar_codigo(secreto, "000000") is False


def test_verificar_codigo_rechaza_no_numerico():
    secreto = generar_secreto()
    assert verificar_codigo(secreto, "abcdef") is False
    assert verificar_codigo(secreto, "") is False


def test_provisioning_uri_incluye_issuer_y_email():
    secreto = generar_secreto()
    uri = provisioning_uri(secreto, email="ana@vridik.local")
    assert uri.startswith("otpauth://totp/")
    assert "Vridik" in uri
    assert "ana%40vridik.local" in uri or "ana@vridik.local" in uri


def test_codigos_respaldo_se_pueden_verificar_por_hash_sin_guardar_texto_plano():
    resultado = generar_codigos_respaldo(cantidad=8)
    assert len(resultado.en_claro) == 8
    assert len(resultado.hashes) == 8
    assert resultado.en_claro[0] not in resultado.hashes  # nunca se guarda en claro

    for codigo in resultado.en_claro:
        assert verificar_codigo_respaldo(codigo, resultado.hashes) is True
    assert verificar_codigo_respaldo("00000000", resultado.hashes) is False


@pytest.mark.asyncio
async def test_flujo_completo_activacion_en_dos_pasos():
    db = _FakeUsersDB()

    # Paso 1: iniciar_activacion genera secreto pero NO activa el 2FA todavía
    secreto, uri = await iniciar_activacion(db, user_id="user-1", email="ana@vridik.local")
    assert db.filas["user-1"]["totp_enabled"] is False
    assert db.filas["user-1"]["totp_secret"] == secreto
    assert uri.startswith("otpauth://")

    # requiere_totp sigue False mientras no se confirme con un código válido
    assert await requiere_totp(db, user_id="user-1") is False

    # Paso 2: un código inválido NO activa el 2FA
    assert await confirmar_activacion(db, user_id="user-1", codigo="000000") is False
    assert db.filas["user-1"]["totp_enabled"] is False

    # Paso 2 con código real generado a partir del secreto guardado: activa
    codigo_real = pyotp.totp.TOTP(secreto).now()
    assert await confirmar_activacion(db, user_id="user-1", codigo=codigo_real) is True
    assert db.filas["user-1"]["totp_enabled"] is True
    assert await requiere_totp(db, user_id="user-1") is True

    # Login: verificar_login_totp valida contra el secreto ya activado
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_real) is True
    assert await verificar_login_totp(db, user_id="user-1", codigo="000000") is False

    # Desactivación: limpia secreto y enabled
    await desactivar_totp(db, user_id="user-1")
    assert db.filas["user-1"]["totp_enabled"] is False
    assert db.filas["user-1"]["totp_secret"] is None
    assert await requiere_totp(db, user_id="user-1") is False


@pytest.mark.asyncio
async def test_confirmar_activacion_sin_secreto_previo_falla():
    db = _FakeUsersDB()
    assert await confirmar_activacion(db, user_id="user-1", codigo="123456") is False


@pytest.mark.asyncio
async def test_verificar_login_totp_sin_2fa_activado_falla():
    db = _FakeUsersDB()
    secreto = generar_secreto()
    db.filas["user-1"]["totp_secret"] = secreto  # secreto existe pero enabled=False
    codigo_real = pyotp.totp.TOTP(secreto).now()
    # totp_enabled sigue False -> la query real filtra "AND totp_enabled = true"
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_real) is False
