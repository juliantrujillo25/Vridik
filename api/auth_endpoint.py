"""
Vridik — api/auth_endpoint.py
Sprint S1: POST /auth/register y POST /auth/login sobre PostgreSQL real
(asyncpg vía `request.app.state.db_connection`, mismo contrato que
api/admin_users_endpoint.py). Password: bcrypt (core/auth.py). Token: JWT
HS256 (JWT_SECRET), mismo secreto que el resto de Vridik.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import create_jwt, ensure_users_table, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: str
    password: str


def _get_db(request: Request):
    db_connection = getattr(request.app.state, "db_connection", None)
    if db_connection is None:
        raise HTTPException(status_code=503, detail="db_connection no configurado en app.state")
    return db_connection


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest, request: Request):
    conn = _get_db(request)
    await ensure_users_table(conn)

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
    token = create_jwt(sub=user_id, email=payload.email)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    conn = _get_db(request)
    await ensure_users_table(conn)

    fila = await conn.fetchrow(
        "SELECT id, hashed_password, is_active FROM users WHERE email = $1", payload.email,
    )
    if fila is None or not fila["hashed_password"] or not verify_password(payload.password, fila["hashed_password"]):
        raise HTTPException(status_code=401, detail="Email o contraseña inválidos")
    if not fila["is_active"]:
        raise HTTPException(status_code=403, detail="Usuario inactivo")

    token = create_jwt(sub=str(fila["id"]), email=payload.email)
    return {"access_token": token, "token_type": "bearer"}
