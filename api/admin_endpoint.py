"""
Vridik — api/admin_endpoint.py
Sprint S2: panel admin (CRUD básico de usuarios) sobre la misma tabla
`users`/JWT de S1 (api/auth_endpoint.py) — reemplaza a api/admin_users_endpoint.py
(schema `roles`/`user_credentials` distinto, nunca compatible con los JWT
reales que emite core.auth.create_jwt: esperaba `role` DENTRO del JWT, que
S1 nunca emite). Ese archivo y core/admin_users.py quedan intactos en el
repo pero dejan de montarse en app/main.py.

GET   /admin/users              lista paginada (skip/limit)
POST  /admin/users              crea usuario (role: seller|admin)
PATCH /admin/users/{id}/role    cambia el rol (un admin no puede cambiarse a sí mismo)

`get_current_admin()` reutiliza el JWT de S1 (core.auth.decode_jwt vía
api.auth_endpoint._claims_de_bearer): 401 si el token falta/es inválido,
403 si es válido pero `role` (columna `users.role`, no el JWT) no es 'admin'.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth_endpoint import _claims_de_bearer, _get_db
from core.admin import change_role, create_user, ensure_role_column, list_users
from core.auth import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: Literal["seller", "admin"] = "seller"


class ChangeRoleRequest(BaseModel):
    role: Literal["seller", "admin"]


async def get_current_admin(request: Request, authorization: str | None = Header(default=None)) -> dict:
    claims = _claims_de_bearer(authorization)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin 'sub'")

    conn = _get_db(request)
    await ensure_role_column(conn)
    fila = await conn.fetchrow("SELECT id, email, role FROM users WHERE id = $1", user_id)
    if fila is None:
        raise HTTPException(status_code=401, detail="Usuario del token no existe")
    if fila["role"] != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return dict(fila)


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
