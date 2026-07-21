"""
Vridik — scripts/seed_staging.py
Roadmap T6 (Staging mínimo): siembra un despacho + 3 usuarios sintéticos +
1 caso de ejemplo en el entorno de STAGING, contra el esquema REAL actual
(vía las mismas funciones core/*.py que usa la app en producción, no SQL
a mano contra un esquema que puede estar desactualizado -- ver el
problema real que tenía db/seed_railway.sql: apuntaba a
schema_semana1_vridik.sql, de antes de la migración a despachos de
Fase 4, con columnas como role_id/nombre_completo que ya no existen).

USO:
    STAGING_DB_URL="postgresql://..." python scripts/seed_staging.py

NUNCA correr esto contra producción -- valida explícitamente que la URL
no apunte a un host conocido de producción antes de escribir nada.

Credenciales (SOLO para staging/demo, mismo criterio que
db/seed_railway.sql -- rotar antes de cualquier demo pública):
    admin@staging.vridik.local     / Staging#Admin2026!
    abogado@staging.vridik.local   / Staging#Abogado2026!
    cliente@staging.vridik.local   / Staging#Cliente2026!

Idempotente: si el despacho de staging ya existe (por nombre), no
duplica nada -- seguro de correr de nuevo tras cada redeploy de staging.
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.auth import ensure_role_column, ensure_users_table, hash_password
from core.case import create_caso, ensure_casos_table
from core.despachos import ensure_despachos_table

NOMBRE_DESPACHO = "Despacho de Prueba (Staging)"

USUARIOS = [
    ("admin@staging.vridik.local", "Staging#Admin2026!", "admin"),
    ("abogado@staging.vridik.local", "Staging#Abogado2026!", "abogado"),
    ("cliente@staging.vridik.local", "Staging#Cliente2026!", "cliente"),
]

# Nunca corras este seed contra un host que suene a producción -- guarda
# de seguridad barata pero real (evita el típico "copié mal la variable
# de entorno y ahora hay despachos de prueba en la base real").
_FRAGMENTOS_PROHIBIDOS = ("hayabusa",)


async def main() -> None:
    db_url = os.environ.get("STAGING_DB_URL")
    if not db_url:
        raise SystemExit("Falta STAGING_DB_URL -- nunca se adivina ni se usa un default.")
    if any(frag in db_url for frag in _FRAGMENTOS_PROHIBIDOS):
        raise SystemExit(
            "STAGING_DB_URL parece apuntar a producción (host prohibido encontrado) -- abortado."
        )

    conn = await asyncpg.connect(db_url)
    try:
        await ensure_users_table(conn)
        await ensure_role_column(conn)
        await ensure_despachos_table(conn)
        await ensure_casos_table(conn)

        existente = await conn.fetchval("SELECT id FROM despachos WHERE nombre = $1", NOMBRE_DESPACHO)
        if existente:
            print(f"Ya existe '{NOMBRE_DESPACHO}' (id={existente}) -- no se duplica nada.")
            return

        despacho_id = await conn.fetchval(
            "INSERT INTO despachos (nombre) VALUES ($1) RETURNING id", NOMBRE_DESPACHO,
        )
        print(f"Despacho creado: {despacho_id}")

        ids_por_rol: dict[str, str] = {}
        for email, password, role in USUARIOS:
            password_hash = hash_password(password)
            user_id = await conn.fetchval(
                """
                INSERT INTO users (email, hashed_password, role, despacho_id, is_active)
                VALUES ($1, $2, $3, $4, true)
                RETURNING id
                """,
                email, password_hash, role, despacho_id,
            )
            await conn.execute(
                "INSERT INTO user_credentials (user_id, password_hash) VALUES ($1, $2) "
                "ON CONFLICT (user_id) DO NOTHING",
                user_id, password_hash,
            )
            ids_por_rol[role] = str(user_id)
            print(f"  usuario {role}: {email} ({user_id})")

        caso = await create_caso(
            conn,
            cliente_id=ids_por_rol["cliente"],
            despacho_id=despacho_id,
            titulo="Caso de ejemplo (staging)",
            descripcion="Caso sintético para probar el copiloto en staging -- no es un caso real.",
            abogado_id=ids_por_rol["abogado"],
        )
        print(f"Caso de ejemplo creado: {caso['id']}")

        print("\nListo. Credenciales de staging (rotar antes de cualquier demo pública):")
        for email, password, role in USUARIOS:
            print(f"  {role:8s} {email}  /  {password}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
