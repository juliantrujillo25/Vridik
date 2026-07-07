"""
Vridik — core/totp_2fa.py
Sprint S12: 2FA opcional (TOTP, RFC 6238) para roles admin/abogado.

Diseño:
  - El secreto TOTP SIEMPRE lo genera el backend (`pyotp.random_base32()`)
    — nunca se acepta un secreto propuesto por el cliente, para que un
    cliente comprometido no pueda fijar un secreto conocido y saltarse el
    2FA por completo.
  - Flujo de activación en 2 pasos, nunca uno solo:
      1. `iniciar_activacion()` genera un secreto nuevo y lo guarda con
         `totp_enabled=false` (columna `migrations/004_totp_2fa.sql`) —
         el usuario escanea el QR (`provisioning_uri`) pero el 2FA todavía
         NO está activo.
      2. `confirmar_activacion()` exige un código válido generado con ese
         secreto antes de poner `totp_enabled=true`. Sin este segundo paso,
         un QR mal escaneado o un secreto corrupto dejaría al usuario
         bloqueado de su propia cuenta la próxima vez que inicie sesión.
  - Códigos de respaldo (`generar_codigos_respaldo`): 8 códigos de un solo
    uso para cuando el usuario pierde el dispositivo con el autenticador.
    Se devuelven en texto plano UNA sola vez (para mostrárselos al usuario)
    y se guardan solo su hash SHA-256 — igual principio que
    `refresh_tokens.token_hash` en schema_semana1_vridik.sql: el valor
    real nunca se persiste en claro.

NO SE EJECUTA CONTRA POSTGRESQL REAL EN ESTE ENTREGABLE — las funciones que
reciben `db_connection` asumen una conexión asyncpg real (mismo contrato
que el resto de Vridik); verificado con pruebas unitarias usando un fake de
conexión (ver tests/test_totp_2fa.py) y con pyotp real generando/validando
códigos TOTP de verdad (sin red, sin BD).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None  # type: ignore

ISSUER_NAME = "Vridik"
VENTANA_VALIDEZ_PASOS = 1  # tolera +-1 paso de 30s (drift de reloj del celular)
CANTIDAD_CODIGOS_RESPALDO = 8


def _requiere_pyotp() -> None:
    if pyotp is None:
        raise RuntimeError("core.totp_2fa requiere 'pyotp' instalado (pip install pyotp)")


def generar_secreto() -> str:
    """Genera un secreto TOTP nuevo en base32. SIEMPRE en el backend —
    nunca se acepta un secreto propuesto por el cliente."""
    _requiere_pyotp()
    return pyotp.random_base32()


def provisioning_uri(secreto: str, *, email: str, issuer: str = ISSUER_NAME) -> str:
    """URI `otpauth://` lista para codificar en un QR (Google
    Authenticator, Authy, etc.)."""
    _requiere_pyotp()
    return pyotp.totp.TOTP(secreto).provisioning_uri(name=email, issuer_name=issuer)


def verificar_codigo(secreto: str, codigo: str, *, ventana: int = VENTANA_VALIDEZ_PASOS) -> bool:
    """Valida un código TOTP de 6 dígitos contra el secreto. `ventana=1`
    tolera el paso anterior/siguiente de 30s (drift de reloj típico de un
    celular) sin abrir una ventana de repetición indefinida."""
    _requiere_pyotp()
    if not codigo or not codigo.isdigit():
        return False
    return pyotp.totp.TOTP(secreto).verify(codigo, valid_window=ventana)


def _hash_codigo_respaldo(codigo: str) -> str:
    """SHA-256 del código de respaldo — mismo principio que
    `refresh_tokens.token_hash`: el valor real nunca se persiste en claro."""
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


@dataclass
class CodigosRespaldo:
    """Resultado de generar códigos de respaldo: `en_claro` se muestra UNA
    sola vez al usuario (nunca se vuelve a poder leer); `hashes` es lo que
    se persiste en BD para poder validar un código futuro sin guardarlo en
    claro."""

    en_claro: list[str] = field(default_factory=list)
    hashes: list[str] = field(default_factory=list)


def generar_codigos_respaldo(cantidad: int = CANTIDAD_CODIGOS_RESPALDO) -> CodigosRespaldo:
    en_claro = [f"{secrets.randbelow(10**8):08d}" for _ in range(cantidad)]
    return CodigosRespaldo(en_claro=en_claro, hashes=[_hash_codigo_respaldo(c) for c in en_claro])


def verificar_codigo_respaldo(codigo: str, hashes_guardados: list[str]) -> bool:
    """Compara el hash del código presentado contra la lista de hashes
    guardados. El llamador es responsable de eliminar el hash usado de la
    lista tras un match (códigos de un solo uso) — esta función solo
    valida, no muta estado."""
    if not codigo:
        return False
    return _hash_codigo_respaldo(codigo) in hashes_guardados


# ---------------------------------------------------------------------------
# Helpers de orquestación sobre PostgreSQL (asyncpg). Se pasan explícitamente
# `db_connection` en vez de importar un pool global, mismo patrón que
# julix/service.py y core/feature_flag_legacy.py en el resto de Vridik.
# ---------------------------------------------------------------------------
async def iniciar_activacion(db_connection, *, user_id: str, email: str) -> tuple[str, str]:
    """Paso 1 del flujo de activación: genera un secreto nuevo, lo guarda
    con `totp_enabled=false` (migrations/004_totp_2fa.sql) y retorna
    (secreto, provisioning_uri) para que el frontend renderice el QR.
    `totp_enabled` sigue en false hasta `confirmar_activacion()`."""
    secreto = generar_secreto()
    await db_connection.execute(
        "UPDATE users SET totp_secret = $2, totp_enabled = false, totp_activado_en = NULL WHERE id = $1",
        user_id, secreto,
    )
    return secreto, provisioning_uri(secreto, email=email)


async def confirmar_activacion(db_connection, *, user_id: str, codigo: str) -> bool:
    """Paso 2: exige un código válido generado con el secreto ya guardado
    antes de poner `totp_enabled=true`. Si el código no valida, el 2FA
    sigue sin activarse (nunca se activa 'a medias')."""
    fila = await db_connection.fetchrow("SELECT totp_secret FROM users WHERE id = $1", user_id)
    if fila is None or not fila["totp_secret"]:
        return False
    if not verificar_codigo(fila["totp_secret"], codigo):
        return False
    await db_connection.execute(
        "UPDATE users SET totp_enabled = true, totp_activado_en = now() WHERE id = $1",
        user_id,
    )
    return True


async def requiere_totp(db_connection, *, user_id: str) -> bool:
    """Consultado por el flujo de login (S1/S2) tras validar la contraseña:
    si retorna True, el login debe exigir un segundo paso con
    `verificar_login_totp()` antes de emitir el JWT."""
    fila = await db_connection.fetchrow("SELECT totp_enabled FROM users WHERE id = $1", user_id)
    return bool(fila and fila["totp_enabled"])


async def verificar_login_totp(db_connection, *, user_id: str, codigo: str) -> bool:
    """Segundo paso del login cuando `requiere_totp()` es True."""
    fila = await db_connection.fetchrow(
        "SELECT totp_secret FROM users WHERE id = $1 AND totp_enabled = true", user_id,
    )
    if fila is None or not fila["totp_secret"]:
        return False
    return verificar_codigo(fila["totp_secret"], codigo)


async def desactivar_totp(db_connection, *, user_id: str) -> None:
    """Desactiva el 2FA (p.ej. a pedido del usuario, o por un admin tras
    verificar identidad por otro canal — esa verificación vive fuera de
    este módulo). Limpia el secreto: no tiene sentido conservar un secreto
    inactivo."""
    await db_connection.execute(
        "UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_activado_en = NULL WHERE id = $1",
        user_id,
    )
