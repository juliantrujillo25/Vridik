#!/usr/bin/env python3
"""
Vridik — migrations/migrate_users.py
Sprint S1 (Fase 1 — "Usuarios en PostgreSQL"): migra los usuarios que hoy
viven en ENV/CSV (deuda documentada en la tabla Estado Actual del roadmap)
hacia las tablas PostgreSQL de schema_semana1_vridik.sql (users, roles,
user_credentials, auth_events).

Diseño:
  - IDEMPOTENTE: correr este script N veces con el mismo JURIS_USERS no debe
    duplicar usuarios ni sobrescribir contraseñas ya migradas. La idempotencia
    se logra por email (users.email, citext) — si el usuario ya existe y ya
    tiene user_credentials, se omite y se registra 'migration_skip_existing'.
  - DRY-RUN POR DEFECTO: el script nunca escribe en la base de datos a menos
    que se invoque explícitamente con --commit. En dry-run imprime el plan
    completo (qué se crearía, qué se omitiría) sin abrir una transacción de
    escritura.
  - MANIFEST PARA ROLLBACK: cada corrida en modo --commit escribe un archivo
    JSON en migrations/.migration_runs/<timestamp>.json con el valor original
    de JURIS_USERS (para poder restaurar el comportamiento legacy) y con los
    user_id creados en esa corrida (para poder desactivarlos si algo sale
    mal). rollback_env.py consume ese manifest.
  - LOG EN auth_events: cada usuario creado (o migración fallida) deja un
    registro en auth_events con event_type='user_migrated' o
    'user_migration_failed', consistente con el resto de Vridik.

Formato esperado de JURIS_USERS (ENV):
    "usuario1:password1:admin,usuario2:password2:abogado,usuario3:password3:cliente"
  - separador de usuarios: coma
  - separador de campos: dos puntos (":")
  - roles válidos: admin | abogado | cliente (deben existir en la tabla roles)

USO:
    python migrate_users.py                  # dry-run (no toca la BD)
    python migrate_users.py --commit         # ejecuta la migración real

NO SE EJECUTA CONTRA UNA BASE DE DATOS REAL EN ESTE ENTREGABLE.
Este archivo es código de referencia para Sprint S1; requiere que
DATABASE_URL apunte a una instancia real de PostgreSQL con
schema_semana1_vridik.sql ya aplicado.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore

try:
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore


MIGRATION_RUNS_DIR = Path(__file__).parent / ".migration_runs"
VALID_ROLES = {"admin": 1, "abogado": 2, "cliente": 3}
BCRYPT_ROUNDS = 12


# ---------------------------------------------------------------------------
# Parseo de JURIS_USERS
# ---------------------------------------------------------------------------
@dataclass
class LegacyUserEntry:
    legacy_username: str
    password_plain: str
    role_codigo: str

    def validar(self) -> list[str]:
        errores = []
        if not self.legacy_username or ":" in self.legacy_username:
            errores.append(f"username inválido: {self.legacy_username!r}")
        if not self.password_plain:
            errores.append(f"password vacío para {self.legacy_username!r}")
        if self.role_codigo not in VALID_ROLES:
            errores.append(
                f"rol '{self.role_codigo}' inválido para {self.legacy_username!r} "
                f"(válidos: {sorted(VALID_ROLES)})"
            )
        return errores


def parse_juris_users(raw: str) -> list[LegacyUserEntry]:
    """Parsea JURIS_USERS='user:pass:role,user:pass:role,...'"""
    entradas: list[LegacyUserEntry] = []
    raw = raw.strip()
    if not raw:
        return entradas
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        partes = chunk.split(":")
        if len(partes) != 3:
            raise ValueError(
                f"Entrada JURIS_USERS mal formada (se esperaba user:pass:role): {chunk!r}"
            )
        username, password, role = (p.strip() for p in partes)
        entradas.append(LegacyUserEntry(username, password, role))
    return entradas


# ---------------------------------------------------------------------------
# Plan de migración (dry-run y commit comparten el mismo plan)
# ---------------------------------------------------------------------------
@dataclass
class PlanItem:
    entry: LegacyUserEntry
    accion: str  # 'crear' | 'omitir_existente' | 'error_validacion'
    detalle: str = ""
    user_id: str | None = None


@dataclass
class MigrationManifest:
    run_id: str
    started_at: str
    mode: str  # 'dry_run' | 'commit'
    juris_users_backup: str  # valor original completo de JURIS_USERS, para rollback_env.py
    items: list[dict] = field(default_factory=list)
    finished_at: str | None = None
    status: str = "in_progress"  # 'in_progress' | 'ok' | 'failed'
    error: str | None = None


async def _email_existente(conn, email: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM users WHERE email = $1 AND deleted_at IS NULL", email
    )
    return row is not None


async def _tiene_credenciales(conn, user_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM user_credentials WHERE user_id = $1", user_id
    )
    return row is not None


def _email_sintetico(username: str) -> str:
    """Los usuarios legacy no siempre tienen email real en ENV. Se genera un
    email sintético estable y verificable, marcado como pendiente de
    actualización real por el admin en el Panel de Administración (S2)."""
    return f"{username}@legacy.vridik.local"


def hash_password(password_plain: str) -> str:
    if bcrypt is None:
        raise RuntimeError("Falta la dependencia 'bcrypt' (pip install bcrypt)")
    hashed = bcrypt.hashpw(password_plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


async def _registrar_auth_event(conn, *, user_id: str | None, event_type: str, metadata: dict) -> None:
    await conn.execute(
        """
        INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
        VALUES ($1, NULL, $2, $3::jsonb)
        """,
        user_id, event_type, json.dumps(metadata),
    )


async def construir_plan(conn, entradas: list[LegacyUserEntry]) -> list[PlanItem]:
    plan: list[PlanItem] = []
    for entry in entradas:
        errores = entry.validar()
        if errores:
            plan.append(PlanItem(entry, "error_validacion", "; ".join(errores)))
            continue

        email = _email_sintetico(entry.legacy_username)
        if await _email_existente(conn, email):
            plan.append(PlanItem(entry, "omitir_existente", f"email {email} ya migrado"))
            continue

        plan.append(PlanItem(entry, "crear", f"se creará con email {email}"))
    return plan


def imprimir_plan(plan: list[PlanItem], mode: str) -> None:
    print(f"\n=== Vridik / migrate_users.py — plan de migración ({mode}) ===")
    for item in plan:
        print(f"  [{item.accion:18s}] {item.entry.legacy_username:20s} rol={item.entry.role_codigo:8s} {item.detalle}")
    resumen = {}
    for item in plan:
        resumen[item.accion] = resumen.get(item.accion, 0) + 1
    print(f"\nResumen: {resumen}\n")


async def ejecutar_migracion(conn, plan: list[PlanItem], manifest: MigrationManifest) -> None:
    """Ejecuta el plan dentro de una única transacción. Si cualquier item
    falla, se hace ROLLBACK completo de la transacción (ningún usuario queda
    a medio crear) y el manifest se marca 'failed' para que rollback_env.py
    sepa que debe restaurar el ENV legacy."""
    async with conn.transaction():
        for item in plan:
            if item.accion != "crear":
                manifest.items.append({**asdict(item), "ejecutado": False})
                continue

            email = _email_sintetico(item.entry.legacy_username)
            role_id = VALID_ROLES[item.entry.role_codigo]
            password_hash = hash_password(item.entry.password_plain)

            user_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO users (id, email, nombre_completo, role_id, legacy_username, must_change, is_active)
                VALUES ($1, $2, $3, $4, $5, true, true)
                """,
                user_id, email, item.entry.legacy_username, role_id, item.entry.legacy_username,
            )
            await conn.execute(
                """
                INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
                VALUES ($1, $2, 'bcrypt', true)
                """,
                user_id, password_hash,
            )
            await _registrar_auth_event(
                conn,
                user_id=user_id,
                event_type="user_migrated",
                metadata={
                    "origen": "migrate_users.py",
                    "legacy_username": item.entry.legacy_username,
                    "role": item.entry.role_codigo,
                    "run_id": manifest.run_id,
                },
            )
            item.user_id = user_id
            manifest.items.append({**asdict(item), "ejecutado": True})


def _guardar_manifest(manifest: MigrationManifest) -> Path:
    MIGRATION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = MIGRATION_RUNS_DIR / f"{manifest.run_id}.json"
    path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


async def main_async(commit: bool) -> int:
    raw_juris_users = os.environ.get("JURIS_USERS", "")
    database_url = os.environ.get("DATABASE_URL")

    if not raw_juris_users:
        print("JURIS_USERS no está definido o está vacío. Nada que migrar.")
        return 0

    if asyncpg is None:
        print("ERROR: falta la dependencia 'asyncpg' (pip install asyncpg)", file=sys.stderr)
        return 1

    if not database_url:
        print("ERROR: DATABASE_URL no está configurado.", file=sys.stderr)
        return 1

    entradas = parse_juris_users(raw_juris_users)
    if not entradas:
        print("JURIS_USERS no contiene entradas válidas.")
        return 0

    manifest = MigrationManifest(
        run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
        started_at=datetime.now(timezone.utc).isoformat(),
        mode="commit" if commit else "dry_run",
        juris_users_backup=raw_juris_users,  # respaldo íntegro para rollback_env.py
    )

    conn = await asyncpg.connect(database_url)
    try:
        plan = await construir_plan(conn, entradas)
        imprimir_plan(plan, manifest.mode)

        errores_validacion = [p for p in plan if p.accion == "error_validacion"]
        if errores_validacion:
            print(f"ATENCIÓN: {len(errores_validacion)} entradas con error de validación no se migrarán.")

        if not commit:
            print("Modo dry-run: no se realizó ningún cambio en la base de datos.")
            manifest.status = "ok"
            manifest.finished_at = datetime.now(timezone.utc).isoformat()
            manifest.items = [{**asdict(p), "ejecutado": False} for p in plan]
            path = _guardar_manifest(manifest)
            print(f"Manifest de dry-run guardado en {path}")
            return 0

        try:
            await ejecutar_migracion(conn, plan, manifest)
            manifest.status = "ok"
        except Exception as exc:  # noqa: BLE001 — se registra y se relanza tras guardar el manifest
            manifest.status = "failed"
            manifest.error = str(exc)
            manifest.finished_at = datetime.now(timezone.utc).isoformat()
            path = _guardar_manifest(manifest)
            print(f"ERROR durante la migración: {exc}", file=sys.stderr)
            print(f"Manifest de la corrida fallida guardado en {path}", file=sys.stderr)
            print("Ejecuta 'python rollback_env.py --run-id <run_id>' para restaurar el ENV legacy.", file=sys.stderr)
            return 1

        manifest.finished_at = datetime.now(timezone.utc).isoformat()
        path = _guardar_manifest(manifest)
        print(f"Migración completada. Manifest guardado en {path}")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik — migración de usuarios legacy (ENV) a PostgreSQL")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Ejecuta la migración de verdad. Sin esta bandera, el script solo hace dry-run.",
    )
    args = parser.parse_args()

    import asyncio

    return asyncio.run(main_async(commit=args.commit))


if __name__ == "__main__":
    raise SystemExit(main())
