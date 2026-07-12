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

`totp_secret` se cifra en reposo con Fernet (ver `_fernet()`) antes de
cualquier escritura en `users.totp_secret` — nunca se persiste en texto
plano. Clave: `TOTP_ENCRYPTION_KEY` (propia, independiente de JWT_SECRET
-- roadmap S12-13, agregada antes de la rotación de JWT_SECRET para que
esa rotación no vuelva indescifrable ningún `totp_secret` ya guardado) si
está configurada; si no, cae a derivarla de JWT_SECRET (`_fernet_legacy()`,
diseño original de S12, se mantiene solo para poder descifrar lo que ya se
haya cifrado así antes de que la variable nueva existiera).
`ensure_totp_columns()` agrega las columnas de forma idempotente (mismo
patrón que `core.auth.ensure_users_table`), ya que
`migrations/004_totp_2fa.sql` nunca se corrió contra Postgres real.

Expuesto vía HTTP en api/auth_endpoint.py (Sprint S12):
POST /auth/2fa/setup, POST /auth/2fa/verify, POST /auth/2fa/login.

Roadmap S12-13 (hardening, cerrado en la sesión que terminó S11): los
códigos de respaldo (`generar_codigos_respaldo()`) ya existían pero nadie
los guardaba ni los podía usar para entrar -- `confirmar_activacion()`
ahora los genera y persiste (columna `totp_backup_codes`, array de hashes
en JSONB) al activar el 2FA, y `verificar_login_totp()` los acepta como
alternativa al código TOTP normal (de un solo uso: el hash usado se borra
de la lista al validar). `desactivar_totp()` acepta un `actor_id`
opcional y deja un `auth_event` -- lo usa el reset administrativo
("perdí el teléfono") de api/admin_endpoint.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field

from core.auth_events import registrar_evento

try:
    import pyotp
except ImportError:  # pragma: no cover
    pyotp = None  # type: ignore

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore

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


def _requiere_cryptography() -> None:
    if Fernet is None:
        raise RuntimeError("core.totp_2fa requiere 'cryptography' instalado (pip install cryptography)")


def _fernet_legacy() -> "Fernet":
    """Clave derivada de JWT_SECRET (SHA-256 -> base64 urlsafe) -- diseño
    original de S12, ya no se usa para cifrar nada nuevo. Se conserva
    SOLO para poder descifrar `totp_secret` que ya se hayan guardado con
    ella antes de que existiera TOTP_ENCRYPTION_KEY (ver _fernet())."""
    _requiere_cryptography()
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if not jwt_secret:
        raise RuntimeError("JWT_SECRET no configurado: requerido para descifrar un totp_secret legacy")
    clave = base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode("utf-8")).digest())
    return Fernet(clave)


def _fernet() -> "Fernet":
    """Roadmap S12-13 (hardening, previo a la rotación de JWT_SECRET):
    `TOTP_ENCRYPTION_KEY` es una clave Fernet PROPIA, independiente de
    JWT_SECRET -- antes de este cambio, rotar JWT_SECRET dejaba todo
    `totp_secret` ya cifrado permanentemente indescifrable (la clave
    Fernet se derivaba de él). Sin TOTP_ENCRYPTION_KEY configurada, cae a
    _fernet_legacy() -- mismo comportamiento que antes, para no romper
    nada en un entorno que todavía no seteó la variable nueva (local,
    tests, o producción antes de que se configure)."""
    _requiere_cryptography()
    clave_directa = os.environ.get("TOTP_ENCRYPTION_KEY", "")
    if clave_directa:
        return Fernet(clave_directa.encode("utf-8"))
    return _fernet_legacy()


def _encriptar_secreto(secreto: str) -> str:
    """`totp_secret` nunca se persiste en texto plano — se cifra en reposo
    con Fernet antes de cualquier `UPDATE users SET totp_secret = ...`.
    Siempre con la clave ACTUAL (`_fernet()`, TOTP_ENCRYPTION_KEY si está
    configurada) -- nunca se vuelve a cifrar nada con la legacy."""
    return _fernet().encrypt(secreto.encode("utf-8")).decode("utf-8")


def _desencriptar_secreto(secreto_cifrado: str) -> str:
    """Intenta con la clave actual primero. Si falla Y hay una
    TOTP_ENCRYPTION_KEY configurada (o sea: la clave actual YA NO es la
    legacy), reintenta con la legacy antes de fallar de verdad -- cubre
    exactamente el caso de un `totp_secret` que se cifró ANTES de que
    TOTP_ENCRYPTION_KEY existiera. Sin esto, activar la variable nueva
    en un entorno con usuarios ya enrolados los dejaría sin poder
    loguearse hasta re-enrolarse a mano."""
    try:
        return _fernet().decrypt(secreto_cifrado.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        if not os.environ.get("TOTP_ENCRYPTION_KEY", ""):
            raise
        return _fernet_legacy().decrypt(secreto_cifrado.encode("utf-8")).decode("utf-8")


async def ensure_totp_columns(db_connection) -> None:
    """Idempotente (mismo patrón que core.auth.ensure_users_table): agrega
    las columnas de 2FA a `users` si todavía no existen — la migración
    migrations/004_totp_2fa.sql documenta el mismo cambio pero nunca se
    corrió contra el Postgres real de Railway."""
    await db_connection.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS totp_secret TEXT,
            ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS totp_activado_en TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS totp_backup_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )


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
        user_id, _encriptar_secreto(secreto),
    )
    return secreto, provisioning_uri(secreto, email=email)


async def confirmar_activacion(db_connection, *, user_id: str, codigo: str) -> CodigosRespaldo | None:
    """Paso 2: exige un código válido generado con el secreto ya guardado
    antes de poner `totp_enabled=true`. Si el código no valida, el 2FA
    sigue sin activarse (nunca se activa 'a medias'). Al activar, genera y
    persiste los códigos de respaldo (hashes) y devuelve el objeto
    completo (con los códigos en claro) para que el caller se los muestre
    al usuario UNA sola vez -- después de esta respuesta no se pueden
    volver a leer."""
    fila = await db_connection.fetchrow("SELECT totp_secret FROM users WHERE id = $1", user_id)
    if fila is None or not fila["totp_secret"]:
        return None
    if not verificar_codigo(_desencriptar_secreto(fila["totp_secret"]), codigo):
        return None
    codigos = generar_codigos_respaldo()
    await db_connection.execute(
        """
        UPDATE users
        SET totp_enabled = true, totp_activado_en = now(), totp_backup_codes = $2::jsonb
        WHERE id = $1
        """,
        user_id, json.dumps(codigos.hashes),
    )
    return codigos


async def requiere_totp(db_connection, *, user_id: str) -> bool:
    """Consultado por el flujo de login (S1/S2) tras validar la contraseña:
    si retorna True, el login debe exigir un segundo paso con
    `verificar_login_totp()` antes de emitir el JWT."""
    fila = await db_connection.fetchrow("SELECT totp_enabled FROM users WHERE id = $1", user_id)
    return bool(fila and fila["totp_enabled"])


async def verificar_login_totp(db_connection, *, user_id: str, codigo: str) -> bool:
    """Segundo paso del login cuando `requiere_totp()` es True. Acepta un
    código TOTP de 6 dígitos normal O uno de los códigos de respaldo de un
    solo uso (para cuando el usuario perdió el dispositivo) -- si matchea
    un código de respaldo, ese hash se borra de la lista antes de devolver
    True, así no puede reusarse."""
    fila = await db_connection.fetchrow(
        "SELECT totp_secret, totp_backup_codes FROM users WHERE id = $1 AND totp_enabled = true", user_id,
    )
    if fila is None or not fila["totp_secret"]:
        return False
    if verificar_codigo(_desencriptar_secreto(fila["totp_secret"]), codigo):
        return True

    hashes_guardados = json.loads(fila["totp_backup_codes"] or "[]")
    if not verificar_codigo_respaldo(codigo, hashes_guardados):
        return False
    hash_usado = _hash_codigo_respaldo(codigo)
    hashes_restantes = [h for h in hashes_guardados if h != hash_usado]
    await db_connection.execute(
        "UPDATE users SET totp_backup_codes = $2::jsonb WHERE id = $1", user_id, json.dumps(hashes_restantes),
    )
    return True


async def desactivar_totp(db_connection, *, user_id: str, actor_id: str | None = None) -> None:
    """Desactiva el 2FA (p.ej. a pedido del usuario, o por un admin tras
    verificar identidad por otro canal — esa verificación vive fuera de
    este módulo). Limpia el secreto y los códigos de respaldo: no tiene
    sentido conservar credenciales inactivas. `actor_id` (opcional, para
    cuando lo dispara un admin distinto del propio usuario) deja un
    `auth_event` -- el reset administrativo ("perdí el teléfono",
    api/admin_endpoint.py) depende de este rastro de auditoría."""
    await db_connection.execute(
        """
        UPDATE users
        SET totp_enabled = false, totp_secret = NULL, totp_activado_en = NULL, totp_backup_codes = '[]'::jsonb
        WHERE id = $1
        """,
        user_id,
    )
    await registrar_evento(
        db_connection, event_type="totp_reset", user_id=user_id, actor_id=actor_id or user_id,
    )
