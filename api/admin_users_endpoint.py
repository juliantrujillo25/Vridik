"""
Vridik — api/admin_users_endpoint.py
Sprint S2: expone core/admin_users.py vía HTTP para el panel de
administración de usuarios. Solo el rol `admin` puede usar estas rutas
(403 para cualquier otro rol) — reutiliza el mismo JWT HMAC de S1
(`JWT_SECRET`), sin reimplementar autenticación.

Rutas:
  POST   /admin/users                  crear usuario (retorna password temporal UNA vez)
  GET    /admin/users                   listar usuarios (nunca incluye password_hash)
  PATCH  /admin/users/{user_id}         editar nombre_completo/role_codigo
  POST   /admin/users/{user_id}/desactivar  desactiva + revoca refresh tokens
  POST   /admin/users/{user_id}/reset       nueva password temporal + revoca refresh tokens
  GET    /admin/users/{user_id}/actividad   lee auth_events del usuario (paginado simple)

Errores de negocio (core/admin_users.py) se traducen a códigos HTTP:
  EmailDuplicadoError      -> 409
  UsuarioNoEncontradoError -> 404
  RolInvalidoError         -> 422

NO SE EJECUTA CONTRA POSTGRESQL REAL EN ESTE ENTREGABLE — FastAPI se
importa y se define el router, pero no se levanta ningún servidor ni se
toca PostgreSQL.
"""

from __future__ import annotations

import os

try:
    import jwt as pyjwt
except ImportError:  # pragma: no cover
    pyjwt = None  # type: ignore

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.admin_users import (
    EmailDuplicadoError,
    RolInvalidoError,
    UsuarioNoEncontradoError,
    actividad_usuario,
    crear_usuario,
    desactivar_usuario,
    editar_usuario,
    listar_usuarios,
    resetear_password,
)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

# Mismo secreto que api/julix_endpoint.py (S1): un único JWT_SECRET en todo
# Vridik. Se lee aquí de forma independiente (no se importa desde
# julix_endpoint) para que este router no dependa de que la app de JuliX
# esté montada — ambos leen la misma variable de entorno.
JWT_SECRET = os.environ.get("JWT_SECRET", "")


def _decodificar_jwt_admin(authorization: str | None) -> dict:
    """Decodifica el JWT y exige rol admin. Nunca se hace este chequeo en
    dos pasos separados (decodificar, luego checar rol en el handler) para
    que sea imposible que un endpoint nuevo olvide el chequeo de rol —
    queda centralizado en un único punto de entrada."""
    if pyjwt is None:
        raise HTTPException(status_code=500, detail="PyJWT no está instalado en el servidor")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta el header Authorization: Bearer <token>")
    token = authorization[len("Bearer "):].strip()
    try:
        claims = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}")

    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Esta acción requiere rol admin")
    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="Token sin 'sub'")
    return claims


def _get_db(request: Request):
    db_connection = getattr(request.app.state, "db_connection", None)
    if db_connection is None:
        raise HTTPException(status_code=503, detail="db_connection no configurado en app.state")
    return db_connection


class CrearUsuarioRequest(BaseModel):
    email: str
    nombre_completo: str
    role_codigo: str = Field(..., examples=["admin", "abogado", "cliente"])


class EditarUsuarioRequest(BaseModel):
    nombre_completo: str | None = None
    role_codigo: str | None = None


@router.post("", status_code=201)
async def crear_usuario_endpoint(
    payload: CrearUsuarioRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    claims = _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    try:
        resultado = await crear_usuario(
            conn,
            actor_id=claims["sub"],
            email=payload.email,
            nombre_completo=payload.nombre_completo,
            role_codigo=payload.role_codigo,
        )
    except EmailDuplicadoError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RolInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "user_id": resultado.user_id,
        "email": resultado.email,
        # Se muestra UNA sola vez en la respuesta HTTP — el frontend debe
        # presentarla al admin en un modal copiable y nunca volver a
        # solicitarla (no se puede: solo se guarda el hash).
        "password_temporal": resultado.password_temporal,
    }


@router.get("")
async def listar_usuarios_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
):
    _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    usuarios = await listar_usuarios(conn)
    return {"usuarios": usuarios}


@router.patch("/{user_id}")
async def editar_usuario_endpoint(
    user_id: str,
    payload: EditarUsuarioRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    claims = _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    try:
        await editar_usuario(
            conn,
            actor_id=claims["sub"],
            user_id=user_id,
            nombre_completo=payload.nombre_completo,
            role_codigo=payload.role_codigo,
        )
    except UsuarioNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RolInvalidoError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "ok"}


@router.post("/{user_id}/desactivar")
async def desactivar_usuario_endpoint(
    user_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    claims = _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    try:
        await desactivar_usuario(conn, actor_id=claims["sub"], user_id=user_id)
    except UsuarioNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"status": "desactivado"}


@router.post("/{user_id}/reset")
async def resetear_password_endpoint(
    user_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    claims = _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    try:
        resultado = await resetear_password(conn, actor_id=claims["sub"], user_id=user_id)
    except UsuarioNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"user_id": resultado.user_id, "password_temporal": resultado.password_temporal}


@router.get("/{user_id}/actividad")
async def actividad_usuario_endpoint(
    user_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    limite: int = 50,
):
    _decodificar_jwt_admin(authorization)
    conn = _get_db(request)
    eventos = await actividad_usuario(conn, user_id=user_id, limite=limite)
    return {"eventos": eventos}
