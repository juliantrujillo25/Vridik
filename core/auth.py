"""
Vridik — core/auth.py
Sprint S1: hash/verify de contraseña + emisión de JWT para POST /auth/register
y POST /auth/login (api/auth_endpoint.py). `ensure_users_table()` es
idempotente (CREATE TABLE IF NOT EXISTS + ALTER ADD COLUMN IF NOT EXISTS) para
no romper un `users` ya existente de otra migración (schema_semana1_vridik.sql)
que no tenga `hashed_password` como columna propia.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

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
