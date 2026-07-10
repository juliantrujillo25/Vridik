"""
Vridik — api/admin_endpoint.py
Sprint S2: panel admin (CRUD básico de usuarios) sobre la misma tabla
`users`/JWT de S1 (api/auth_endpoint.py) — reemplaza a api/admin_users_endpoint.py
(schema `roles`/`user_credentials` distinto, nunca compatible con los JWT
reales que emite core.auth.create_jwt: esperaba `role` DENTRO del JWT, que
S1 nunca emite). Ese archivo y core/admin_users.py quedan intactos en el
repo pero dejan de montarse en app/main.py.

GET   /admin/users                       lista paginada (skip/limit)
POST  /admin/users                       crea usuario (role: cliente|abogado|admin)
PATCH /admin/users/{id}/role             cambia el rol (un admin no puede cambiarse a sí mismo)
GET   /admin/users/{id}/actividad        auth_events del usuario (S2-GAP-01)
POST  /admin/users/{id}/reset-password   contraseña temporal + revoca sesiones (S2-GAP-01)
POST  /admin/users/{id}/reset-2fa        desactiva el 2FA de otro usuario -- "perdí el
                                          teléfono" (roadmap S12-13, hardening)

`get_current_admin()` reutiliza el JWT de S1 (core.auth.decode_jwt vía
api.auth_endpoint._claims_de_bearer): 401 si el token falta/es inválido,
403 si es válido pero `role` (columna `users.role`, no el JWT) no es 'admin'.

Desmantelamiento del marketplace (ver Instrucciones - CLAUDE.md,
"Consolidación de producto") — completo: la gestión de productos
(POST/PATCH/DELETE /admin/products, S3), órdenes (GET/PATCH
/admin/orders, S4) e imágenes (POST/DELETE/POST-primary
/admin/products/{id}/images, S5) se quitó de este archivo en la fase
2, junto con `get_current_seller()` (S6). El catálogo público
(api/products_endpoint.py, core/product.py) y el checkout
(api/orders_endpoint.py, core/order.py) se borraron enteros en la
fase 4 -- ya nada de este archivo depende de ellos.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth_endpoint import _claims_de_bearer, _get_db
from core.admin import change_role, create_user, ensure_role_column, list_users
from core.admin_users import UsuarioNoEncontradoError, actividad_usuario, resetear_password
from core.auth import hash_password
from core.totp_2fa import desactivar_totp, ensure_totp_columns

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: Literal["cliente", "abogado", "admin"] = "cliente"


class ChangeRoleRequest(BaseModel):
    role: Literal["cliente", "abogado", "admin"]


async def _resolver_usuario(request: Request, authorization: str | None) -> dict:
    claims = _claims_de_bearer(authorization)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin 'sub'")

    conn = _get_db(request)
    await ensure_role_column(conn)
    fila = await conn.fetchrow("SELECT id, email, role FROM users WHERE id = $1", user_id)
    if fila is None:
        raise HTTPException(status_code=401, detail="Usuario del token no existe")
    return dict(fila)


async def get_current_admin(request: Request, authorization: str | None = Header(default=None)) -> dict:
    usuario = await _resolver_usuario(request, authorization)
    if usuario["role"] != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")

    # Roadmap S12-13 (hardening, must_enroll): 2FA obligatorio para admin.
    # Query separada (no se suma a _resolver_usuario, que también usa
    # get_current_user sin este requisito) para no tocar el contrato de
    # ningún otro caller. Rechaza ANTES de dejar pasar cualquier acción del
    # panel -- pero /auth/2fa/setup y /auth/2fa/verify usan get_current_user,
    # así que un admin sin 2FA todavía puede autoenrolarse con su mismo
    # token, nunca queda completamente afuera de su cuenta.
    conn = _get_db(request)
    await ensure_totp_columns(conn)
    fila_2fa = await conn.fetchrow("SELECT totp_enabled FROM users WHERE id = $1", usuario["id"])
    if fila_2fa is None or not fila_2fa["totp_enabled"]:
        raise HTTPException(
            status_code=403,
            detail=(
                "Tu cuenta admin requiere 2FA activado (roadmap S12-13). "
                "Configuralo con POST /auth/2fa/setup y POST /auth/2fa/verify antes de usar el panel."
            ),
        )
    return usuario


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Cualquier usuario autenticado, sin importar el rol."""
    return await _resolver_usuario(request, authorization)


@router.get("/users")
async def get_users(
    request: Request, skip: int = 0, limit: int = 20, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    return await list_users(conn, skip=skip, limit=limit)


@router.post("/users", status_code=201)
async def post_users(
    payload: CreateUserRequest, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    existente = await conn.fetchrow("SELECT id FROM users WHERE email = $1", payload.email)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {payload.email!r}")

    password_hash = hash_password(payload.password)
    return await create_user(conn, email=payload.email, password_hash=password_hash, role=payload.role)


@router.patch("/users/{user_id}/role")
async def patch_user_role(
    user_id: str, payload: ChangeRoleRequest, request: Request, admin: dict = Depends(get_current_admin),
):
    if user_id == str(admin["id"]):
        raise HTTPException(status_code=400, detail="No puedes cambiar tu propio rol")

    conn = _get_db(request)
    actualizado = await change_role(conn, user_id=user_id, new_role=payload.role)
    if actualizado is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return actualizado


@router.get("/users/{user_id}/actividad")
async def get_user_actividad(
    user_id: str, request: Request, limite: int = 50, admin: dict = Depends(get_current_admin),
):
    """S2-GAP-01 (AUDITORIA_PARA_CLAUDE.md): lee auth_events del usuario,
    más recientes primero (core.admin_users.actividad_usuario, ya
    implementado y probado -- solo faltaba montarlo en el router real)."""
    conn = _get_db(request)
    return await actividad_usuario(conn, user_id=user_id, limite=limite)


@router.post("/users/{user_id}/reset-password")
async def post_user_reset_password(
    user_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    """S2-GAP-01: contraseña temporal nueva + revoca refresh tokens activos
    + fuerza must_change. La password_temporal se devuelve en texto plano
    UNA sola vez -- nunca se puede volver a leer después de esta respuesta."""
    conn = _get_db(request)
    try:
        resultado = await resetear_password(conn, actor_id=str(admin["id"]), user_id=user_id)
    except UsuarioNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user_id": resultado.user_id, "password_temporal": resultado.password_temporal}


@router.post("/users/{user_id}/reset-2fa")
async def post_user_reset_2fa(
    user_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    """Roadmap S12-13 (hardening): "perdí el teléfono" -- desactiva el 2FA
    de otro usuario para que pueda volver a entrar con contraseña sola y
    reactivarlo desde cero (nuevo secreto, nuevos códigos de respaldo). No
    reactiva nada por sí solo; el usuario tiene que correr
    POST /auth/2fa/setup de nuevo."""
    conn = _get_db(request)
    await ensure_totp_columns(conn)
    existe = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
    if existe is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    await desactivar_totp(conn, user_id=user_id, actor_id=str(admin["id"]))
    return {"user_id": user_id, "two_factor_enabled": False}
