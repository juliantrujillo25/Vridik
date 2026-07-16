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

Roadmap Semana 12-13 (hardening, core/rate_limit.py): POST /auth/login
rechaza con 429 ANTES de verificar la contraseña si `email`+IP acumuló
>= 10 `login_failed` en 15 min; POST /auth/2fa/login hace lo mismo por
`user_id` a partir de 5 códigos TOTP inválidos en 15 min (ahí ya se
conoce al usuario con certeza, no hace falta IP). La IP se lee de
`X-Forwarded-For` (Railway está detrás de un proxy) con fallback a
`request.client.host`.
"""

from __future__ import annotations

import base64
import io
import os

import qrcode
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.admin import ensure_role_column, ensure_superadmin_column
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
from core.db_utils import conexion_dedicada, obtener_conexion_de_request, transaccion_si_disponible
from core.despachos import ensure_despachos_table
from core.rate_limit import excede_limite_login, excede_limite_totp
from core.refresh_tokens import (
    ReusoDetectado,
    emitir_refresh_token,
    revocar_refresh_token,
    revocar_todas_las_sesiones,
    rotar_refresh_token,
)
from core.totp_2fa import (
    confirmar_activacion,
    ensure_totp_columns,
    iniciar_activacion,
    regenerar_codigos_respaldo,
    verificar_login_totp,
)

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
    # Fase 4 (multi-tenancy): registrarse crea un despacho nuevo -- quien se
    # registra queda como su primer admin. Invitar a alguien a un despacho
    # YA existente es POST /admin/users (hereda el despacho de quien invita),
    # no este endpoint.
    nombre_despacho: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    email: str
    password: str


class Verify2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class RegenerarCodigosRequest(BaseModel):
    # A propósito solo 6 dígitos (código TOTP del autenticador) -- nunca se
    # acepta un código de respaldo acá, ver el docstring de
    # core.totp_2fa.regenerar_codigos_respaldo.
    code: str = Field(..., min_length=6, max_length=6)


class Login2FARequest(BaseModel):
    temp_token: str
    # 6 dígitos para un código TOTP normal, 8 para un código de respaldo
    # de un solo uso (core.totp_2fa.verificar_login_totp acepta ambos).
    code: str = Field(..., min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class CambiarPasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str = Field(..., min_length=8)


def _get_db(request: Request):
    # Hardening RLS (core/rls.py): prioriza la conexión dedicada del
    # middleware de conexión-por-request (api/julix_endpoint.py) sobre el
    # Pool crudo -- ver core.db_utils.obtener_conexion_de_request.
    db_connection = obtener_conexion_de_request(request)
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


def _client_ip(request: Request) -> str | None:
    """Railway está detrás de un proxy -- `request.client.host` ahí adentro
    es la IP interna del proxy, no la del cliente real. `X-Forwarded-For`
    puede traer una cadena "cliente, proxy1, proxy2"; el primer valor es el
    más cercano al cliente original. Sin ese header (tests, entornos sin
    proxy), cae a `request.client.host`."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _qr_base64(otpauth_uri: str) -> str:
    imagen = qrcode.make(otpauth_uri)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request):
    """Fase 4 (multi-tenancy): registrarse crea un despacho NUEVO -- quien
    se registra queda como su primer usuario, con `role='admin'` (antes
    nacía 'cliente' sin ningún despacho, un comportamiento que ya no tiene
    sentido: alguien que se registra por primera vez está dando de alta su
    propio despacho, no uniéndose a uno existente). Invitar a alguien a un
    despacho YA existente es `POST /admin/users` (core/admin.py::
    create_user), que hereda el despacho de quien invita -- no hace falta
    un sistema de invitaciones nuevo.

    El INSERT de `despachos` + `users` va en una única transacción real
    (una conexión dedicada del pool, no llamadas sueltas): si `conn` es el
    `asyncpg.Pool` de producción, cada `.fetchrow()`/`.execute()` suelto
    puede tomar una conexión física distinta, así que sin esto un fallo a
    mitad de camino podría dejar un despacho sin usuario o viceversa."""
    conn = _get_db(request)
    await ensure_users_table(conn)
    # S6: sin esto, un self-registro nuevo nace con el default viejo de
    # `role` ('seller', S2) en vez de 'customer' — ensure_role_column()
    # solo se disparaba antes desde los endpoints de admin/seller, nunca
    # desde /auth/register (el primer lugar donde en realidad se necesita).
    await ensure_role_column(conn)
    await ensure_despachos_table(conn)

    existente = await conn.fetchrow("SELECT id FROM users WHERE email = $1", payload.email)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {payload.email!r}")

    password_hash = hash_password(payload.password)

    async with conexion_dedicada(conn) as conexion:
        async with transaccion_si_disponible(conexion):
            despacho_id = await conexion.fetchval(
                "INSERT INTO despachos (nombre) VALUES ($1) RETURNING id", payload.nombre_despacho,
            )
            fila = await conexion.fetchrow(
                """
                INSERT INTO users (email, hashed_password, role, despacho_id, is_active)
                VALUES ($1, $2, 'admin', $3, true)
                RETURNING id
                """,
                payload.email, password_hash, despacho_id,
            )
            user_id = str(fila["id"])
            # Fase B: dual-write a user_credentials (Fase A ya hizo el
            # backfill de los usuarios existentes) -- users.hashed_password
            # se sigue llenando también, el cutover completo es Fase C.
            await conexion.execute(
                "INSERT INTO user_credentials (user_id, password_hash) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                user_id, password_hash,
            )

    await registrar_evento(
        conn, event_type="user_created", user_id=user_id, actor_id=user_id,
        metadata={"despacho_id": str(despacho_id)},
    )

    token = create_jwt(sub=user_id, email=payload.email)
    refresh_token, _ = await emitir_refresh_token(conn, user_id=user_id)
    return {"access_token": token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    conn = _get_db(request)
    await ensure_users_table(conn)
    await ensure_totp_columns(conn)

    ip_address = _client_ip(request)
    if await excede_limite_login(conn, email=payload.email, ip_address=ip_address):
        raise HTTPException(
            status_code=429, detail="Demasiados intentos fallidos. Probá de nuevo en unos minutos.",
        )

    # Fase C (S1-GAP-01): password_hash se lee de user_credentials, no de
    # users.hashed_password -- esa columna se queda (nunca se suelta, no
    # hay DDL destructivo) pero deja de ser la fuente real. LEFT JOIN, no
    # INNER: si por algún motivo faltara la fila de credentials, la fila de
    # users igual se recupera (password_hash sale NULL, falla el login
    # igual que si la contraseña no coincidiera -- nunca un 500).
    fila = await conn.fetchrow(
        """
        SELECT u.id, uc.password_hash AS hashed_password, u.is_active, u.totp_enabled
        FROM users u
        LEFT JOIN user_credentials uc ON uc.user_id = u.id
        WHERE u.email = $1
        """,
        payload.email,
    )
    if fila is None or not fila["hashed_password"] or not verify_password(payload.password, fila["hashed_password"]):
        # user_id=None cuando el email ni existe -- no hay a qué usuario
        # referenciar, pero el intento igual queda en la bitácora (y cuenta
        # para el rate limit de arriba, sea o no un email real).
        await registrar_evento(
            conn, event_type="login_failed",
            user_id=str(fila["id"]) if fila else None,
            metadata={"email": payload.email},
            ip_address=ip_address,
        )
        raise HTTPException(status_code=401, detail="Email o contraseña inválidos")
    if not fila["is_active"]:
        raise HTTPException(status_code=403, detail="Usuario inactivo")

    user_id = str(fila["id"])
    if fila["totp_enabled"] and not BYPASS_2FA_DEV:
        temp_token = create_temp_2fa_token(sub=user_id, email=payload.email)
        return {"requires_2fa": True, "temp_token": temp_token}

    await registrar_evento(conn, event_type="login_success", user_id=user_id, ip_address=ip_address)
    token = create_jwt(sub=user_id, email=payload.email)
    refresh_token, _ = await emitir_refresh_token(conn, user_id=user_id)
    return {"access_token": token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.get("/me")
async def me(request: Request, authorization: str | None = Header(default=None)):
    """Perfil mínimo del usuario autenticado -- agregado para el frontend
    (frontend/): no había ningún endpoint "quién soy" hasta ahora, y sin
    esto la UI de 2FA no tiene forma de saber si el usuario ya lo tiene
    activado antes de ofrecerle "activar 2FA" (activar de nuevo sobre uno
    ya activo pisa el secreto existente -- core.totp_2fa.iniciar_activacion
    sobreescribe totp_secret sin confirmar, sería fácil invalidar el 2FA de
    alguien por accidente sin este chequeo previo)."""
    claims = _claims_de_bearer(authorization)
    conn = _get_db(request)
    await ensure_role_column(conn)
    await ensure_totp_columns(conn)
    await ensure_despachos_table(conn)
    await ensure_superadmin_column(conn)

    # LEFT JOIN, no INNER (Fase 4) -- mismo criterio que el join a
    # user_credentials en /auth/login: nunca dejar que un despacho faltante
    # convierta una sesión válida en un 500.
    fila = await conn.fetchrow(
        """
        SELECT u.id, u.email, u.role, u.totp_enabled, u.despacho_id, d.nombre AS despacho_nombre,
               u.es_superadmin
        FROM users u
        LEFT JOIN despachos d ON d.id = u.despacho_id
        WHERE u.id = $1
        """,
        claims["sub"],
    )
    if fila is None:
        raise HTTPException(status_code=401, detail="Usuario del token no existe")
    return dict(fila)


@router.post("/password")
async def cambiar_password(
    payload: CambiarPasswordRequest, request: Request, authorization: str | None = Header(default=None),
):
    """Self-service: el usuario cambia su propia contraseña (verificando la
    actual) -- distinto de POST /admin/users/{id}/reset-password, que es
    un admin generando una temporal para OTRO usuario. Mismo dual-write de
    Fase B que register/reset (user_credentials es la fuente real que lee
    POST /auth/login; users.hashed_password se sigue llenando también).

    Revoca TODAS las sesiones activas (refresh tokens) del usuario, igual
    que un reset administrativo -- una sesión abierta con la contraseña
    vieja no debe sobrevivir al cambio, ni siquiera la que hizo el cambio
    (el frontend cierra sesión localmente después de esta llamada y pide
    volver a entrar con la contraseña nueva)."""
    claims = _claims_de_bearer(authorization)
    conn = _get_db(request)
    user_id = claims["sub"]

    fila = await conn.fetchrow(
        """
        SELECT u.id, uc.password_hash AS hashed_password
        FROM users u
        LEFT JOIN user_credentials uc ON uc.user_id = u.id
        WHERE u.id = $1
        """,
        user_id,
    )
    if fila is None or not fila["hashed_password"] or not verify_password(payload.password_actual, fila["hashed_password"]):
        raise HTTPException(status_code=401, detail="Contraseña actual incorrecta")

    nuevo_hash = hash_password(payload.password_nueva)
    await conn.execute(
        """
        INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary, updated_by)
        VALUES ($1, $2, 'bcrypt', false, $1)
        ON CONFLICT (user_id) DO UPDATE
        SET password_hash = $2, hash_algorithm = 'bcrypt', is_temporary = false, updated_at = now(), updated_by = $1
        """,
        user_id, nuevo_hash,
    )
    await conn.execute(
        "UPDATE users SET hashed_password = $2, must_change = false, updated_at = now() WHERE id = $1",
        user_id, nuevo_hash,
    )
    await revocar_todas_las_sesiones(conn, user_id=user_id, motivo="password_changed")
    await registrar_evento(conn, event_type="password_changed", user_id=user_id, actor_id=user_id)

    return {"ok": True}


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

    codigos = await confirmar_activacion(conn, user_id=claims["sub"], codigo=payload.code)
    if codigos is None:
        raise HTTPException(status_code=400, detail="Código 2FA inválido")
    # codigos.en_claro se muestra UNA sola vez acá -- después de esta
    # respuesta solo quedan los hashes, no se pueden volver a leer.
    return {"two_factor_enabled": True, "codigos_respaldo": codigos.en_claro}


@router.post("/2fa/backup-codes/regenerate")
async def regenerate_backup_codes(
    payload: RegenerarCodigosRequest, request: Request, authorization: str | None = Header(default=None),
):
    """Códigos de respaldo nuevos para un usuario que ya tiene el 2FA
    activo -- para cuando se le agotan o los perdió, sin tener que pasar
    por un reset completo (que además pisa el autenticador ya
    configurado, ver core.totp_2fa.regenerar_codigos_respaldo)."""
    claims = _claims_de_bearer(authorization)
    conn = _get_db(request)
    await ensure_totp_columns(conn)

    codigos = await regenerar_codigos_respaldo(conn, user_id=claims["sub"], codigo=payload.code)
    if codigos is None:
        raise HTTPException(status_code=400, detail="Código 2FA inválido, o el 2FA no está activo")
    return {"codigos_respaldo": codigos.en_claro}


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
    ip_address = _client_ip(request)

    if await excede_limite_totp(conn, user_id=user_id):
        raise HTTPException(
            status_code=429, detail="Demasiados códigos inválidos. Probá de nuevo en unos minutos.",
        )

    valido = await verificar_login_totp(conn, user_id=user_id, codigo=payload.code)
    if not valido:
        await registrar_evento(
            conn, event_type="login_failed", user_id=user_id, metadata={"paso": "2fa"}, ip_address=ip_address,
        )
        raise HTTPException(status_code=401, detail="Código 2FA inválido")

    await registrar_evento(conn, event_type="login_success", user_id=user_id, metadata={"paso": "2fa"}, ip_address=ip_address)
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
