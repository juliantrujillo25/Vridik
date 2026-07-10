"""
Vridik — core/auth.py
Sprint S1: hash/verify de contraseña + emisión de JWT para POST /auth/register
y POST /auth/login (api/auth_endpoint.py). `ensure_users_table()` es
idempotente (CREATE TABLE IF NOT EXISTS + ALTER ADD COLUMN IF NOT EXISTS) para
no romper un `users` ya existente de otra migración (schema_semana1_vridik.sql)
que no tenga `hashed_password` como columna propia.

Sprint S12: `create_temp_2fa_token`/`decode_temp_2fa_token` emiten el token
intermedio de POST /auth/login cuando el usuario tiene 2FA activo (ver
api/auth_endpoint.py). Se firman con una clave DISTINTA a JWT_SECRET
(derivada de él) para que ese temp_token nunca sea válido como JWT de sesión
si se reenvía a otro endpoint que decodifica con JWT_SECRET a secas — el
esquema del JWT final de `create_jwt`/`decode_jwt` no cambia.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
# Fase B (S1-GAP-01): 15 min por el roadmap original (antes 60) -- ahora que
# existe POST /auth/refresh (core/refresh_tokens.py) la sesión real la
# sostiene el refresh token de 7 días, no un access token de vida larga.
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "15"))
TEMP_2FA_TOKEN_TTL_MINUTES = 5
TEMP_2FA_SCOPE = "2fa_pending"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_jwt(*, sub: str, email: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET no está configurado en el entorno")
    expira = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    claims = {"sub": sub, "email": email, "exp": expira}
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Token inválido: {exc}") from exc


def _temp_2fa_secret() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET no está configurado en el entorno")
    return hashlib.sha256(f"{JWT_SECRET}::2fa-temp".encode("utf-8")).hexdigest()


def create_temp_2fa_token(*, sub: str, email: str) -> str:
    """Token de vida corta emitido por POST /auth/login cuando el usuario
    tiene 2FA activo, en vez del JWT final. Firmado con `_temp_2fa_secret()`
    (no JWT_SECRET) para que no pueda usarse como access token real."""
    expira = datetime.now(timezone.utc) + timedelta(minutes=TEMP_2FA_TOKEN_TTL_MINUTES)
    claims = {"sub": sub, "email": email, "scope": TEMP_2FA_SCOPE, "exp": expira}
    return jwt.encode(claims, _temp_2fa_secret(), algorithm=JWT_ALGORITHM)


def decode_temp_2fa_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, _temp_2fa_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"temp_token inválido: {exc}") from exc
    if claims.get("scope") != TEMP_2FA_SCOPE:
        raise ValueError("temp_token con scope inesperado")
    return claims


async def ensure_users_table(conn) -> None:
    """Idempotente: crea `users` si no existe, y agrega `hashed_password` si
    la tabla ya existía sin esa columna (compatibilidad con S2)."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password TEXT")
