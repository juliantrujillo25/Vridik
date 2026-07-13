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

Roadmap S12-13 (hardening): rotación de JWT_SECRET sin downtime. Los
secretos se leen en CADA llamada (no como constante de módulo) por dos
motivos: (1) que una rotación vía variable de entorno + redeploy tome
efecto sin depender de reimportar el módulo, (2) que los tests puedan
monkeypatchear las claves. Firmar usa siempre la clave ACTUAL
(`_jwt_secret_actual()`); verificar acepta la actual Y la anterior
(`JWT_SECRET_PREVIOUS`, si está configurada -- ver
`jwt_secrets_para_verificar()` y SECURITY.md) para que un token emitido
justo antes de rotar, todavía dentro de sus 15 min de vida, siga
validando durante la ventana de rotación.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext

JWT_ALGORITHM = "HS256"
# Fase B (S1-GAP-01): 15 min por el roadmap original (antes 60) -- ahora que
# existe POST /auth/refresh (core/refresh_tokens.py) la sesión real la
# sostiene el refresh token de 7 días, no un access token de vida larga.
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "15"))
TEMP_2FA_TOKEN_TTL_MINUTES = 5
TEMP_2FA_SCOPE = "2fa_pending"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _jwt_secret_actual() -> str:
    """La clave con la que se FIRMAN los tokens nuevos -- siempre la actual
    (JWT_SECRET), nunca la anterior."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET no está configurado en el entorno")
    return secret


def jwt_secrets_para_verificar() -> list[str]:
    """Claves con las que se ACEPTA verificar un token entrante: la actual
    primero y, si está configurada, la anterior (JWT_SECRET_PREVIOUS).
    Fuera de una rotación, JWT_SECRET_PREVIOUS no está seteada y esto
    devuelve solo la clave actual -- comportamiento idéntico al de antes.
    Público a propósito: api/julix_endpoint.py lo reutiliza para no
    duplicar la lista de claves de la ventana de rotación."""
    claves = [_jwt_secret_actual()]
    previa = os.environ.get("JWT_SECRET_PREVIOUS", "")
    if previa and previa != claves[0]:
        claves.append(previa)
    return claves


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_jwt(*, sub: str, email: str) -> str:
    expira = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    claims = {"sub": sub, "email": email, "exp": expira}
    return jwt.encode(claims, _jwt_secret_actual(), algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    ultima_exc: JWTError | None = None
    for secret in jwt_secrets_para_verificar():
        try:
            return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except ExpiredSignatureError as exc:
            # Firma válida con esta clave pero el token expiró -- es un
            # resultado definitivo, no tiene sentido probar la otra clave.
            raise ValueError(f"Token inválido: {exc}") from exc
        except JWTError as exc:
            ultima_exc = exc
    raise ValueError(f"Token inválido: {ultima_exc}")


def _temp_2fa_secret_de(jwt_secret: str) -> str:
    return hashlib.sha256(f"{jwt_secret}::2fa-temp".encode("utf-8")).hexdigest()


def create_temp_2fa_token(*, sub: str, email: str) -> str:
    """Token de vida corta emitido por POST /auth/login cuando el usuario
    tiene 2FA activo, en vez del JWT final. Firmado con una clave derivada
    de la actual (no JWT_SECRET a secas) para que no pueda usarse como
    access token real."""
    expira = datetime.now(timezone.utc) + timedelta(minutes=TEMP_2FA_TOKEN_TTL_MINUTES)
    claims = {"sub": sub, "email": email, "scope": TEMP_2FA_SCOPE, "exp": expira}
    return jwt.encode(claims, _temp_2fa_secret_de(_jwt_secret_actual()), algorithm=JWT_ALGORITHM)


def decode_temp_2fa_token(token: str) -> dict:
    ultima_exc: JWTError | None = None
    for jwt_secret in jwt_secrets_para_verificar():
        try:
            claims = jwt.decode(token, _temp_2fa_secret_de(jwt_secret), algorithms=[JWT_ALGORITHM])
        except ExpiredSignatureError as exc:
            raise ValueError(f"temp_token inválido: {exc}") from exc
        except JWTError as exc:
            ultima_exc = exc
            continue
        if claims.get("scope") != TEMP_2FA_SCOPE:
            raise ValueError("temp_token con scope inesperado")
        return claims
    raise ValueError(f"temp_token inválido: {ultima_exc}")


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


async def ensure_auth_migration_005(conn) -> None:
    """Bootstrap idempotente de migrations/005_auth_roles_refresh_tokens.sql
    (roles, user_credentials, refresh_tokens, auth_events -- las tres
    últimas son load-bearing hoy: refresh_tokens sostiene toda sesión
    activa, auth_events alimenta el rate limiting de login y el reset de
    2FA, user_credentials es la fuente real de password_hash en varios
    flujos de admin). A diferencia de ensure_users_table()/ensure_role_column()
    (que SÍ se llaman en cada request, patrón establecido en este
    proyecto), esta se llama UNA sola vez al arrancar el proceso
    (app/main.py) -- son 24 sentencias, incluido un UPDATE de backfill
    real sobre toda `users`; correrlas en cada login/refresh/logout sería
    agregar ese costo al camino más sensible de la app para un beneficio
    que solo importa si el proceso arranca contra una base nueva.

    Nunca existió una versión idempotente de esta migración en el código
    -- solo el .sql de referencia, que nada ejecutaba en runtime (mismo
    hueco que julix_calls antes de ensure_julix_calls_table()). En
    producción la migración ya se aplicó (login/refresh/logout llevan
    toda la sesión funcionando en base a estas tablas) -- esto es una red
    de seguridad para que un entorno nuevo (staging futuro, disaster
    recovery) no vuelva a depender de correr el .sql a mano."""
    await conn.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id          SMALLINT PRIMARY KEY,
            codigo      TEXT NOT NULL UNIQUE,
            nombre      TEXT NOT NULL,
            descripcion TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO roles (id, codigo, nombre, descripcion) VALUES
            (1, 'admin',    'Administrador', 'Acceso total: gestión de usuarios, productos, órdenes, pagos'),
            (2, 'seller',   'Vendedor',      'Gestión de sus propios productos y pedidos'),
            (3, 'customer', 'Cliente',       'Compra servicios, ve sus pedidos')
        ON CONFLICT (id) DO NOTHING
        """
    )

    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id SMALLINT REFERENCES roles(id)")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS nombre_completo TEXT")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change BOOLEAN NOT NULL DEFAULT false")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    await conn.execute(
        "UPDATE users SET role_id = (SELECT id FROM roles WHERE codigo = users.role) WHERE role_id IS NULL"
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_users_role_id ON users (role_id)")
    await conn.execute("ALTER TABLE users ALTER COLUMN email TYPE CITEXT")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id        UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            password_hash  TEXT NOT NULL,
            hash_algorithm TEXT NOT NULL DEFAULT 'bcrypt'
                           CHECK (hash_algorithm IN ('argon2id', 'bcrypt')),
            is_temporary   BOOLEAN NOT NULL DEFAULT false,
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by     UUID REFERENCES users(id)
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO user_credentials (user_id, password_hash, hash_algorithm)
        SELECT id, hashed_password, 'bcrypt' FROM users
        WHERE hashed_password IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING
        """
    )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash      TEXT NOT NULL UNIQUE,
            family_id       UUID NOT NULL,
            replaced_by_id  UUID REFERENCES refresh_tokens(id),
            issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at      TIMESTAMPTZ NOT NULL,
            used_at         TIMESTAMPTZ,
            revoked_at      TIMESTAMPTZ,
            revoked_reason  TEXT,
            user_agent      TEXT,
            ip_address      INET
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_family_id ON refresh_tokens (family_id)")
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_refresh_tokens_expires_at ON refresh_tokens (expires_at)
            WHERE revoked_at IS NULL
        """
    )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_events (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
            event_type  TEXT NOT NULL,
            metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
            ip_address  INET,
            user_agent  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_auth_events_user_id_created_at ON auth_events (user_id, created_at DESC)"
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_auth_events_event_type ON auth_events (event_type)")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_auth_events_created_at ON auth_events (created_at DESC)")
