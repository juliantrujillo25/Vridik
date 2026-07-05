#!/usr/bin/env python3
"""
Vridik — migrations/rollback_env.py
Contraparte de migrate_users.py (Sprint S1, ROLLBACK.md). Si una corrida de
migración falla a mitad de camino, o si tras el corte a PostgreSQL aparece un
problema en producción, este script permite volver al comportamiento legacy
basado en ENV sin perder rastro de lo que pasó.

Qué hace, en orden:
  1. Lee el manifest JSON de la corrida (migrations/.migration_runs/<run_id>.json)
     escrito por migrate_users.py.
  2. Imprime el valor ORIGINAL de JURIS_USERS (respaldado antes de migrar) en
     forma de comando `export` listo para pegar, y opcionalmente lo escribe a
     un archivo .env.rollback — esto es la "restauración del ENV".
  3. Si la corrida llegó a crear usuarios en PostgreSQL (mode='commit') antes
     de fallar o antes de decidirse el rollback, desactiva esos usuarios
     (soft-delete vía is_active=false / deactivated_at) en vez de borrarlos
     físicamente — coherente con la política de soft-delete del schema.
  4. Deja registro en auth_events de tipo 'migration_rollback' por cada
     usuario desactivado, y de tipo 'legacy_fallback_restored' a nivel global.

USO:
    python rollback_env.py --run-id 20260713T090000Z-ab12cd34            # solo mostrar
    python rollback_env.py --run-id 20260713T090000Z-ab12cd34 --write-env # escribe .env.rollback
    python rollback_env.py --run-id 20260713T090000Z-ab12cd34 --deactivate-db  # además desactiva en Postgres

NO SE EJECUTA CONTRA UNA BASE DE DATOS REAL EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore

MIGRATION_RUNS_DIR = Path(__file__).parent / ".migration_runs"
ENV_ROLLBACK_FILE = Path(__file__).parent / ".env.rollback"


def cargar_manifest(run_id: str) -> dict:
    path = MIGRATION_RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No existe manifest para run_id={run_id!r} en {MIGRATION_RUNS_DIR}. "
            "Verifica que migrate_users.py se haya corrido con --commit o dry-run antes."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def restaurar_env(manifest: dict, *, escribir_archivo: bool) -> None:
    juris_users_original = manifest["juris_users_backup"]
    print("\n=== Vridik — restauración de ENV legacy (S1 ROLLBACK.md) ===")
    print(f"run_id: {manifest['run_id']}  modo original: {manifest['mode']}  estado: {manifest['status']}")
    print("\nPara restaurar el comportamiento legacy, exporta esta variable en Railway "
          "(o en el shell de despliegue) y activa USE_POSTGRES=false "
          "(ver core/feature_flag_legacy.py):\n")
    print(f'export JURIS_USERS="{juris_users_original}"')
    print('export USE_POSTGRES=false\n')

    if escribir_archivo:
        contenido = (
            f'# Vridik — ENV de rollback generado por rollback_env.py\n'
            f'# run_id: {manifest["run_id"]}\n'
            f'# generado: {datetime.now(timezone.utc).isoformat()}\n'
            f'JURIS_USERS="{juris_users_original}"\n'
            f'USE_POSTGRES=false\n'
        )
        ENV_ROLLBACK_FILE.write_text(contenido, encoding="utf-8")
        print(f"Escrito en {ENV_ROLLBACK_FILE} — cargar con 'source' o subir como variables de Railway.")


async def desactivar_usuarios_migrados(manifest: dict, database_url: str) -> None:
    """Soft-delete de los usuarios creados en esta corrida (no se borran
    físicamente — política del schema). Deja auth_event 'migration_rollback'
    por cada uno y uno global 'legacy_fallback_restored'."""
    if asyncpg is None:
        raise RuntimeError("Falta la dependencia 'asyncpg' (pip install asyncpg)")

    user_ids = [item["user_id"] for item in manifest["items"] if item.get("user_id")]
    if not user_ids:
        print("Esta corrida no llegó a crear usuarios en PostgreSQL. Nada que desactivar.")
        return

    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            for user_id in user_ids:
                await conn.execute(
                    """
                    UPDATE users
                    SET is_active = false, deactivated_at = now()
                    WHERE id = $1
                    """,
                    user_id,
                )
                # Revocar cualquier refresh token vivo del usuario desactivado
                await conn.execute(
                    """
                    UPDATE refresh_tokens
                    SET revoked_at = now(), revoked_reason = 'migration_rollback'
                    WHERE user_id = $1 AND revoked_at IS NULL
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
                    VALUES ($1, NULL, 'migration_rollback', $2::jsonb)
                    """,
                    user_id,
                    json.dumps({"run_id": manifest["run_id"], "motivo": "rollback_env.py"}),
                )
            await conn.execute(
                """
                INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
                VALUES (NULL, NULL, 'legacy_fallback_restored', $1::jsonb)
                """,
                json.dumps({"run_id": manifest["run_id"], "usuarios_desactivados": len(user_ids)}),
            )
        print(f"{len(user_ids)} usuario(s) desactivados en PostgreSQL y auth_events registrado.")
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik — rollback de migración de usuarios (S1)")
    parser.add_argument("--run-id", required=True, help="run_id del manifest generado por migrate_users.py")
    parser.add_argument("--write-env", action="store_true", help="Escribe migrations/.env.rollback")
    parser.add_argument(
        "--deactivate-db",
        action="store_true",
        help="Además de restaurar el ENV, desactiva en PostgreSQL los usuarios creados en esa corrida",
    )
    args = parser.parse_args()

    try:
        manifest = cargar_manifest(args.run_id)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    restaurar_env(manifest, escribir_archivo=args.write_env)

    if args.deactivate_db:
        import asyncio
        import os

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("ERROR: DATABASE_URL no configurado; no se puede desactivar en PostgreSQL.", file=sys.stderr)
            return 1
        asyncio.run(desactivar_usuarios_migrados(manifest, database_url))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
