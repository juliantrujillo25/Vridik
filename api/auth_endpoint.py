"""
Vridik — api/auth_endpoint.py
Sprint S1: POST /auth/register y POST /auth/login sobre PostgreSQL real
(asyncpg vía `request.app.state.db_connection`, mismo contrato que
api/admin_users_endpoint.py). Password: bcrypt (core/auth.py). Token: JWT
HS256 (JWT_SECRET), mismo secreto que el resto de Vridik.

Sprint S12: 2FA TOTP opcional (core/totp_2fa.py) sobre las mismas columnas
`totp_secret`/`totp_enabled`/`totp_activado_en` de migrations/004_totp_2fa.sql.
  - POST /auth/2fa/setup  (requiere Bearer JWT ya emitido): genera un secreto
    nuevo (sin activar el 2FA todavía) y devuelve el otpauth:// URI + QR.
  - POST /auth/2fa/verify (requiere Bearer JWT): confirma el código y recién
    ahí activa `totp_enabled`.
  - POST /auth/login: si el usuario tiene `totp_enabled`, en vez del JWT
    final devuelve {"requires_2fa": true, "temp_token": ...} — un token de
    5 minutos firmado con una clave distinta a JWT_SECRET (ver
    core.auth.create_temp_2fa_token), así no sirve como access token real
    si se reenvía a otro endpoint.
  - POST /auth/2fa/login: canjea temp_token + code por el JWT final (mismo
    `create_jwt` de siempre — el esquema del JWT de sesión no cambia).

Fase B (S1-GAP-01, AUDITORIA_PARA_CLAUDE.md): refresh tokens (core/
refresh_tokens.py) sobre migrations/005_auth_roles_refresh_tokens.sql.
  - Todo punto de autenticación final (register, login sin 2FA, 2fa/login)
    ahora emite además un `refresh_token` (7 días) junto al `access_token`
    (15 min, antes 60 — ver core/auth.py). El frontend debe cambiar a un
    flujo de renovación silenciosa vía POST /auth/refresh en vez de
    depender de un access token de vida larga.
  - POST /auth/refresh: rota el refresh token (family_id) y emite un
    access_token nuevo. Reuso detectado -> revoca toda la familia,
    auth_event 'refresh_reuse_detected', 401.
  - POST /auth/logout: revoca el refresh token de la sesión actual.
  - register/login/refresh/logout escriben auth_events ('user_created',
    'login_success', 'login_failed', 'token_refresh',
    'refresh_reuse_detected', 'logout').
"""

from __future__ import annotations

import base64
import io
import os

import qrcode
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.admin import ensure_role_column
from core.auth import (
    create_jwt,
    create_temp_2fa_token,
    decode_jwt,
    decode_temp_2fa_token,
    ensure_users_table,
    hash_password,
    verify_password,
)
from core.auth_events import registrar_evento
from core.refresh_tokens import (
    ReusoDetectado,
    emitir_refresh_token,
    revocar_refresh_token,
    rotar_refresh_token,
)
from core.totp_2fa import confirmar_activacion, ensure_totp_columns, iniciar_activacion, verificar_login_totp

router = APIRouter(prefix="/auth", tags=["auth"])

# BYPASS_2FA_DEV: desactiva la exigencia de 2FA en POST /auth/login (login
# siempre devuelve el JWT normal, como en S1, incluso si el usuario tiene
# totp_enabled) sin tocar core/totp_2fa.py ni los endpoints /auth/2fa/*.
# Prod-ready (fix de seguridad post-S6): default False — SOLO se activa si
# la variable de entorno BYPASS_2FA_DEV está explícitamente en 'true'/'1'.
# Si la variable no existe (como en cualquier deploy que no la configure a
# propósito), el 2FA real queda exigido; nunca al revés.
BYPASS_2FA_DEV = os.environ.get("BYPASS_2FA_DEV", "false").strip().lower() in ("true", "1", "yes")


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: str
    password: str


class Verify2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class Login2FARequest(BaseModel):
    temp_token: str
    code: str = Field(..., min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


def _get_db(request: Request):
    db_connection = getattr(request.app.state, "db_connection", None)
    if db_connection is None:
        raise HTTPException(status_code=503, detail="db_connection no configurado en app.state")
    return db_connection


def _claims_de_bearer(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta el header Authorization: Bearer <token>")
    try:
        return decode_jwt(authorization[len("Bearer "):])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _qr_base64(otpauth_uri: str) -> str:
    imagen = qrcode.make(otpauth_uri)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request):
    conn = _get_db(request)
    await ensure_users_table(conn)
    # S6: sin esto, un self-registro nuevo nace con el default viejo de
    # `role` ('seller', S2) en vez de 'customer' — ensure_role_column()
    # solo se disparaba antes desde los endpoints de admin/seller, nunca
    # desde /auth/register (el primer lugar donde en realidad se necesita).
    await ensure_role_column(conn)

    existente = await conn.fetchrow("SELECT id FROM users WHERE email = $1", payload.email)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {payload.email!r}")

    password_hash = hash_password(payload.password)
    fila = await conn.fetchrow(
        """
        INSERT INTO users (email, hashed_password, is_active)
        VALUES ($1, $2, true)
        RETURNING id
        """,
        payload.email, password_hash,
    )
    user_id = str(fila["id"])

    # Fase B: dual-write a user_credentials (Fase A ya hizo el backfill de
    # los usuarios existentes) -- users.hashed_password se sigue llenando
    # también, el cutover completo es Fase C.
    await conn.execute(
        "INSERT INTO user_credentials (user_id, password_hash) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
        user_id, password_hash,
    )
    await registrar_evento(conn, event_type="user_created", user_id=user_id, actor_id=user_id)

    token = create_jwt(sub=user_id, email=payload.email)
    refresh_token, _ = await emitir_refresh_token(conn, user_id=user_id)
    return {"access_token": token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    conn = _get_db(request)
    await ensure_users_table(conn)
    await ensure_totp_columns(conn)

    fila = await conn.fetchrow(
        "SELECT id, hashed_password, is_active, totp_enabled FROM users WHERE email = $1", payload.email,
    )
    if fila is None or not fila["hashed_password"] or not verify_password(payload.password, fila["hashed_password"]):
        # user_id=None cuando el email ni existe -- no hay a qué usuario
        # referenciar, pero el intento igual queda en la bitácora.
        await registrar_evento(
            conn, event_type="login_failed",
            user_id=str(fila["id"]) if fila else None,
            metadata={"email": payload.email},
        )
        raise HTTPException(status_code=401, detail="Email o contraseña inválidos")
    if not fila["is_active"]:
        raise HTTPException(status_code=403, detail="Usuario inactivo")

    user_id = str(fila["id"])
    if fila["totp_enabled"] and not BYPASS_2FA_DEV:
        temp_token = create_temp_2fa_token(sub=user_id, email=payload.email)
        return {"requires_2fa": True, "temp_token": temp_token}

    await registrar_evento(conn, event_type="login_success", user_id=user_id)
    token = create_jwt(sub=user_id, email=payload.email)
    refresh_token, _ = await emitir_refresh_token(conn, user_id=user_id)
    return {"access_token": token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/2fa/setup")
async def setup_2fa(request: Request, authorization: str | None = Header(default=None)):
    claims = _claims_de_bearer(authorization)
    conn = _get_db(request)
    await ensure_totp_columns(conn)

    secreto, otpauth_uri = await iniciar_activacion(conn, user_id=claims["sub"], email=claims.get("email", ""))
    return {"otpauth_uri": otpauth_uri, "qr_code_base64": _qr_base64(otpauth_uri)}


@router.post("/2fa/verify")
async def verify_2fa(payload: Verify2FARequest, request: Request, authorization: str | None = Header(default=None)):
    claims = _claims_de_bearer(authorization)
    conn = _get_db(request)
    await ensure_totp_columns(conn)

    activado = await confirmar_activacion(conn, user_id=claims["sub"], codigo=payload.code)
    if not activado:
        raise HTTPException(status_code=400, detail="Código 2FA inválido")
    return {"two_factor_enabled": True}


@router.post("/2fa/login")
async def login_2fa(payload: Login2FARequest, request: Request):
    try:
        temp_claims = decode_temp_2fa_token(payload.temp_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    conn = _get_db(request)
    await ensure_totp_columns(conn)

    user_id = temp_claims["sub"]
    email = temp_claims.get("email", "")
    valido = await verificar_login_totp(conn, user_id=user_id, codigo=payload.code)
    if not valido:
        await registrar_evento(conn, event_type="login_failed", user_id=user_id, metadata={"paso": "2fa"})
        raise HTTPException(status_code=401, detail="Código 2FA inválido")

    await registrar_evento(conn, event_type="login_success", user_id=user_id, metadata={"paso": "2fa"})
    token = create_jwt(sub=user_id, email=email)
    refresh_token, _ = await emitir_refresh_token(conn, user_id=user_id)
    return {"access_token": token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/refresh")
async def refresh(payload: RefreshRequest, request: Request):
    conn = _get_db(request)
    try:
        nuevo_refresh, user_id, _family_id = await rotar_refresh_token(conn, token_plano=payload.refresh_token)
    except ReusoDetectado as exc:
        await registrar_evento(
            conn, event_type="refresh_reuse_detected", user_id=exc.user_id,
            metadata={"accion": "toda_la_familia_revocada"},
        )
        raise HTTPException(status_code=401, detail="Refresh token inválido — sesión revocada por seguridad") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    fila = await conn.fetchrow("SELECT email FROM users WHERE id = $1", user_id)
    email = fila["email"] if fila else ""
    await registrar_evento(conn, event_type="token_refresh", user_id=user_id)
    token = create_jwt(sub=user_id, email=email)
    return {"access_token": token, "refresh_token": nuevo_refresh, "token_type": "bearer"}


@router.post("/logout", status_code=204)
async def logout(payload: LogoutRequest, request: Request):
    conn = _get_db(request)
    user_id = await revocar_refresh_token(conn, token_plano=payload.refresh_token)
    if user_id is not None:
        await registrar_evento(conn, event_type="logout", user_id=user_id)
    return None
