"""
Vridik — core/feature_flag_legacy.py
Sprint S1/S2: feature flag de la migración ENV -> PostgreSQL, con el patrón
de "doble lectura" descrito en el roadmap (preparación -> doble lectura con
evento legacy_fallback -> corte tras 48h limpias -> ROLLBACK.md).

Flag principal: USE_POSTGRES (env var, string 'true'/'false').
  - USE_POSTGRES=false -> comportamiento actual: autenticación 100% contra
    JURIS_USERS en ENV (tal como funciona hoy en producción).
  - USE_POSTGRES=true  -> autenticación contra PostgreSQL (users +
    user_credentials, ver schema_semana1_vridik.sql), con fallback automático
    a ENV si la consulta a PostgreSQL falla o el usuario no aparece — cada
    fallback deja un auth_event 'legacy_fallback' que es la señal que decide
    cuándo cortar el flag definitivamente (48h sin fallbacks, ver S1).

El middleware de JWT (`DualAuthJWTMiddleware`) es quien "prueba ambos": en la
ventana de migración, primero intenta validar/resolver el usuario contra
PostgreSQL y, solo si eso falla, intenta el camino legacy. Nunca al revés
(PostgreSQL es la fuente de verdad objetivo; ENV es la red de seguridad).

NO SE EJECUTA CONTRA UNA BASE DE DATOS REAL EN ESTE ENTREGABLE — esqueleto de
referencia para S1/S2, pensado para conectarse al framework ASGI real de
Vridik (FastAPI) en la implementación final.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore


def use_postgres() -> bool:
    """Única función que debe consultarse en todo el código para decidir la
    fuente de autenticación. Nunca leer USE_POSTGRES directamente fuera de
    este módulo — así el corte de S1 es un cambio en un solo lugar."""
    return os.environ.get("USE_POSTGRES", "false").strip().lower() == "true"


@dataclass
class AuthResult:
    ok: bool
    user_id: str | None
    role: str | None
    fuente: str  # 'postgres' | 'legacy_env'
    motivo_fallo: str | None = None


# ---------------------------------------------------------------------------
# Camino legacy: JURIS_USERS en ENV (comportamiento actual, USE_POSTGRES=false)
# ---------------------------------------------------------------------------
def _parse_juris_users_env() -> dict[str, tuple[str, str]]:
    """Devuelve {username: (password_plain, role)} desde JURIS_USERS.
    Mismo formato que consume migrations/migrate_users.py:
    'user:pass:role,user:pass:role'."""
    raw = os.environ.get("JURIS_USERS", "")
    usuarios: dict[str, tuple[str, str]] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        partes = chunk.split(":")
        if len(partes) != 3:
            continue
        username, password, role = (p.strip() for p in partes)
        usuarios[username] = (password, role)
    return usuarios


async def autenticar_legacy(username: str, password_plain: str) -> AuthResult:
    usuarios = _parse_juris_users_env()
    entrada = usuarios.get(username)
    if entrada is None:
        return AuthResult(False, None, None, "legacy_env", "usuario no encontrado en JURIS_USERS")
    password_esperado, role = entrada
    if password_plain != password_esperado:
        return AuthResult(False, None, None, "legacy_env", "password incorrecto (legacy)")
    # En el camino legacy no hay UUID real; se usa el propio username como
    # identificador estable, igual que hoy en producción.
    return AuthResult(True, username, role, "legacy_env")


# ---------------------------------------------------------------------------
# Camino PostgreSQL (objetivo, USE_POSTGRES=true)
# ---------------------------------------------------------------------------
async def autenticar_postgres(conn, email_o_legacy_username: str, password_plain: str) -> AuthResult:
    """`conn` es una conexión asyncpg (o pool) ya abierta hacia PostgreSQL.
    Busca primero por email, luego por legacy_username (puente de migración,
    ver users.legacy_username en schema_semana1_vridik.sql)."""
    if bcrypt is None:
        return AuthResult(False, None, None, "postgres", "bcrypt no disponible")

    row = await conn.fetchrow(
        """
        SELECT u.id, u.is_active, r.codigo AS role_codigo, uc.password_hash
        FROM users u
        JOIN roles r ON r.id = u.role_id
        JOIN user_credentials uc ON uc.user_id = u.id
        WHERE (u.email = $1 OR u.legacy_username = $1)
          AND u.deleted_at IS NULL
        """,
        email_o_legacy_username,
    )
    if row is None:
        return AuthResult(False, None, None, "postgres", "usuario no encontrado en PostgreSQL")
    if not row["is_active"]:
        return AuthResult(False, None, None, "postgres", "usuario desactivado")

    if not bcrypt.checkpw(password_plain.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return AuthResult(False, None, None, "postgres", "password incorrecto (postgres)")

    return AuthResult(True, str(row["id"]), row["role_codigo"], "postgres")


async def _registrar_legacy_fallback(conn, *, username: str, motivo_postgres: str | None) -> None:
    """Deja constancia en auth_events de que se usó el camino legacy mientras
    USE_POSTGRES=true. Esta es la métrica que decide el corte de S1: cuando
    pasan 48h sin filas nuevas de este tipo, se apaga el fallback."""
    await conn.execute(
        """
        INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
        VALUES (NULL, NULL, 'legacy_fallback', $1::jsonb)
        """,
        json.dumps({"legacy_username": username, "motivo_postgres": motivo_postgres}),
    )


async def autenticar(conn_factory: Callable[[], Awaitable] | None, username: str, password_plain: str) -> AuthResult:
    """Punto de entrada único para el resto de Vridik (login endpoint,
    tests de S3, etc.). Decide la fuente según el flag y aplica doble
    lectura mientras USE_POSTGRES=true.

    `conn_factory` es un callable async que retorna una conexión/pool a
    PostgreSQL; se recibe como parámetro (en vez de importarlo aquí) para
    que este módulo sea trivialmente testeable con PostgreSQL real en los
    fixtures de S3, sin mocks de conexión."""

    if not use_postgres():
        return await autenticar_legacy(username, password_plain)

    if conn_factory is None:
        raise RuntimeError("USE_POSTGRES=true pero no se proporcionó conn_factory")

    conn = await conn_factory()
    resultado_pg = await autenticar_postgres(conn, username, password_plain)
    if resultado_pg.ok:
        return resultado_pg

    # Doble lectura: PostgreSQL falló (usuario no migrado aún, credencial
    # incorrecta, o desactivado) -> se prueba el camino legacy como red de
    # seguridad, y se deja rastro auditable del fallback.
    resultado_legacy = await autenticar_legacy(username, password_plain)
    if resultado_legacy.ok:
        await _registrar_legacy_fallback(conn, username=username, motivo_postgres=resultado_pg.motivo_fallo)
    return resultado_legacy if resultado_legacy.ok else resultado_pg


# ---------------------------------------------------------------------------
# Middleware ASGI: "prueba ambos" a nivel de request autenticado por JWT
# ---------------------------------------------------------------------------
class DualAuthJWTMiddleware:
    """Middleware ASGI genérico (compatible con FastAPI/Starlette) que valida
    el JWT de la request. Durante la ventana de migración (USE_POSTGRES=true)
    intenta resolver el `sub` del token contra PostgreSQL primero; si el
    usuario no existe ahí todavía (migración parcial, ver migrate_users.py en
    curso), cae al resolutor legacy basado en JURIS_USERS.

    No decodifica ni valida la firma del JWT aquí (eso sigue en el
    interceptor/validador existente de Vridik) — este middleware solo decide
    DÓNDE resolver la identidad del `sub` una vez el token ya es válido.
    """

    def __init__(self, app, *, conn_factory: Callable[[], Awaitable] | None, resolve_role_legacy: Callable[[str], str | None] | None = None):
        self.app = app
        self.conn_factory = conn_factory
        self.resolve_role_legacy = resolve_role_legacy or (lambda sub: None)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        jwt_claims = scope.get("state", {}).get("jwt_claims")  # ya validado por el interceptor existente
        if jwt_claims is None:
            await self.app(scope, receive, send)
            return

        sub = jwt_claims.get("sub")
        role: str | None = None
        fuente = "legacy_env"

        if use_postgres() and self.conn_factory is not None and sub:
            conn = await self.conn_factory()
            row = await conn.fetchrow(
                """
                SELECT r.codigo AS role_codigo, u.is_active
                FROM users u JOIN roles r ON r.id = u.role_id
                WHERE u.id::text = $1 OR u.legacy_username = $1
                """,
                sub,
            )
            if row is not None and row["is_active"]:
                role = row["role_codigo"]
                fuente = "postgres"
            else:
                await _registrar_legacy_fallback(conn, username=sub, motivo_postgres="jwt_sub_no_resuelto")

        if role is None:
            role = self.resolve_role_legacy(sub) if sub else None
            fuente = "legacy_env"

        scope.setdefault("state", {})["auth_source"] = fuente
        scope["state"]["auth_role"] = role

        await self.app(scope, receive, send)
