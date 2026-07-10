"""
Vridik — tests/test_totp_2fa.py (Sprint S12)
Prueba core/totp_2fa.py: generación/validación de códigos TOTP reales
(pyotp, sin red) y el flujo de activación en 2 pasos sobre un fake mínimo
de conexión asyncpg (nunca PostgreSQL real).

Roadmap S12-13 (hardening): suma pruebas de códigos de respaldo
generados/persistidos al confirmar la activación, aceptados como
alternativa de un solo uso en el login, y del reset administrativo
("perdí el teléfono") dejando un auth_event.
"""

from __future__ import annotations

import json

import pyotp
import pytest

from core.totp_2fa import (
    _desencriptar_secreto,
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
    sin PostgreSQL real. `totp_backup_codes` se guarda como texto JSON
    (mismo comportamiento que asyncpg sin codec para JSONB)."""

    def __init__(self, user_id: str = "user-1"):
        self.filas = {
            user_id: {
                "totp_secret": None, "totp_enabled": False, "totp_activado_en": None,
                "totp_backup_codes": "[]",
            },
        }
        self.auth_events: list[dict] = []

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata, ip_address, user_agent = args
            self.auth_events.append({"user_id": user_id, "actor_id": actor_id, "event_type": event_type})
        elif "totp_secret = $2" in query and "totp_enabled = false" in query:
            user_id, secreto = args
            self.filas[user_id]["totp_secret"] = secreto
            self.filas[user_id]["totp_enabled"] = False
            self.filas[user_id]["totp_activado_en"] = None
        elif "totp_backup_codes = $2::jsonb" in query and "totp_enabled = true" in query:
            user_id, backup_codes_json = args
            self.filas[user_id]["totp_enabled"] = True
            self.filas[user_id]["totp_activado_en"] = "now"
            self.filas[user_id]["totp_backup_codes"] = backup_codes_json
        elif query.strip().startswith("UPDATE users SET totp_backup_codes = $2::jsonb WHERE id = $1"):
            user_id, backup_codes_json = args
            self.filas[user_id]["totp_backup_codes"] = backup_codes_json
        elif "totp_enabled = false, totp_secret = NULL" in query:
            (user_id,) = args
            self.filas[user_id]["totp_enabled"] = False
            self.filas[user_id]["totp_secret"] = None
            self.filas[user_id]["totp_activado_en"] = None
            self.filas[user_id]["totp_backup_codes"] = "[]"
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
    # Cifrado en reposo (Fernet, S12): nunca se guarda en texto plano, pero
    # descifra exactamente al secreto devuelto para el QR.
    assert db.filas["user-1"]["totp_secret"] != secreto
    assert _desencriptar_secreto(db.filas["user-1"]["totp_secret"]) == secreto
    assert uri.startswith("otpauth://")

    # requiere_totp sigue False mientras no se confirme con un código válido
    assert await requiere_totp(db, user_id="user-1") is False

    # Paso 2: un código inválido NO activa el 2FA (roadmap S12-13: ahora
    # devuelve None, no False -- confirmar_activacion() también genera
    # códigos de respaldo cuando activa de verdad).
    assert await confirmar_activacion(db, user_id="user-1", codigo="000000") is None
    assert db.filas["user-1"]["totp_enabled"] is False

    # Paso 2 con código real generado a partir del secreto guardado: activa
    # y devuelve los códigos de respaldo generados (8, en claro, una sola vez).
    codigo_real = pyotp.totp.TOTP(secreto).now()
    codigos = await confirmar_activacion(db, user_id="user-1", codigo=codigo_real)
    assert codigos is not None
    assert len(codigos.en_claro) == 8
    assert db.filas["user-1"]["totp_enabled"] is True
    assert await requiere_totp(db, user_id="user-1") is True
    assert json.loads(db.filas["user-1"]["totp_backup_codes"]) == codigos.hashes

    # Login: verificar_login_totp valida contra el secreto ya activado
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_real) is True
    assert await verificar_login_totp(db, user_id="user-1", codigo="000000") is False

    # Login con un código de respaldo: funciona una vez, y ese código queda
    # consumido -- reusarlo ya no sirve.
    codigo_respaldo = codigos.en_claro[0]
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_respaldo) is True
    assert len(json.loads(db.filas["user-1"]["totp_backup_codes"])) == 7
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_respaldo) is False

    # Desactivación: limpia secreto, enabled y códigos de respaldo; deja
    # un auth_event 'totp_reset' (reset administrativo, "perdí el teléfono").
    await desactivar_totp(db, user_id="user-1", actor_id="admin-1")
    assert db.filas["user-1"]["totp_enabled"] is False
    assert db.filas["user-1"]["totp_secret"] is None
    assert db.filas["user-1"]["totp_backup_codes"] == "[]"
    assert await requiere_totp(db, user_id="user-1") is False
    assert any(
        e["event_type"] == "totp_reset" and e["user_id"] == "user-1" and e["actor_id"] == "admin-1"
        for e in db.auth_events
    )


@pytest.mark.asyncio
async def test_confirmar_activacion_sin_secreto_previo_falla():
    db = _FakeUsersDB()
    assert await confirmar_activacion(db, user_id="user-1", codigo="123456") is None


@pytest.mark.asyncio
async def test_verificar_login_totp_sin_2fa_activado_falla():
    db = _FakeUsersDB()
    secreto = generar_secreto()
    db.filas["user-1"]["totp_secret"] = secreto  # secreto existe pero enabled=False
    codigo_real = pyotp.totp.TOTP(secreto).now()
    # totp_enabled sigue False -> la query real filtra "AND totp_enabled = true"
    assert await verificar_login_totp(db, user_id="user-1", codigo=codigo_real) is False


@pytest.mark.asyncio
async def test_verificar_login_totp_codigo_respaldo_invalido_falla():
    db = _FakeUsersDB()
    secreto, _ = await iniciar_activacion(db, user_id="user-1", email="ana@vridik.local")
    codigo_real = pyotp.totp.TOTP(secreto).now()
    await confirmar_activacion(db, user_id="user-1", codigo=codigo_real)

    assert await verificar_login_totp(db, user_id="user-1", codigo="00000000") is False


@pytest.mark.asyncio
async def test_desactivar_totp_sin_actor_explicito_usa_el_propio_usuario():
    """Cuando el propio usuario desactiva su 2FA (no un admin), actor_id
    queda como el mismo user_id -- el auth_event igual identifica quién lo
    hizo, sin necesitar un actor separado."""
    db = _FakeUsersDB()
    await desactivar_totp(db, user_id="user-1")
    evento = next(e for e in db.auth_events if e["event_type"] == "totp_reset")
    assert evento["actor_id"] == "user-1"
