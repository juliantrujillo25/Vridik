"""
Vridik — tests/conftest.py
Sprint S3: fixtures centrales de la suite de 45 tests.

Diseño (ver backlog_fase1_vridik.md, S3):
  - PostgreSQL real en tests (nunca SQLite) — citext y UUID exigen fidelidad,
    especialmente para el test de email duplicado case-insensitive.
  - `db`: conexión con rollback transaccional — cada test corre dentro de una
    transacción que se revierte al final, así los tests son idempotentes y
    nunca dejan basura en la base de datos (ni siquiera en un TEST_DATABASE_URL
    apuntando a staging).
  - `seed_roles`: garantiza que existen los 3 roles del schema.
  - `seeded_users`: aplica el mismo seed de db/seed_railway.sql (julian, ana,
    cliente1, soporte) dentro de la transacción de cada test.
  - `make_user`: factory para usuarios ad hoc.
  - `backend`: fixture parametrizada ['legacy', 'postgres'] que activa
    USE_POSTGRES acorde (ver core/feature_flag_legacy.py) — todo test que la
    reciba corre dos veces, una por cada fuente de autenticación.
  - `auth_client(role)`: helper con token de acceso emitido igual que en
    producción (JWT HMAC 15 min).

Si TEST_DATABASE_URL no está configurado (por ejemplo, corriendo localmente
sin PostgreSQL), los tests que dependen de `db` se saltan explícitamente con
un mensaje claro — nunca caen en silencio ni usan SQLite como sustituto.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

try:
    import pytest_asyncio
except ImportError:  # pragma: no cover
    pytest_asyncio = None  # type: ignore

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore

try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None  # type: ignore

try:
    import jwt as pyjwt  # PyJWT
except ImportError:  # pragma: no cover
    pyjwt = None  # type: ignore


# Repo layout: migrations/, core/, julix/, tests/ son hermanos en la raíz.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

JWT_SECRET_TEST = os.environ.get("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")
ACCESS_TOKEN_TTL_SECONDS = 15 * 60  # 15 min, igual que producción (ver roadmap S1)

# Credenciales del seed (deben coincidir con db/seed_railway.sql)
SEED_USERS = [
    {"legacy_username": "julian",   "email": "julian@vridik.local",   "role": "admin",   "password": "Vridik#Admin2026!",   "id": "cbe8915d-ff96-406d-a2a6-cef125711cfc"},
    {"legacy_username": "ana",      "email": "ana@vridik.local",      "role": "abogado",  "password": "Vridik#Abogada2026!", "id": "d0d8da54-0e77-4c9d-bd4d-32f54cf28e00"},
    {"legacy_username": "cliente1", "email": "cliente1@vridik.local", "role": "cliente",  "password": "Vridik#Cliente2026!", "id": "43622ec2-e3d3-405b-abc5-ef4babb586cc"},
    {"legacy_username": "soporte",  "email": "soporte@vridik.local",  "role": "abogado",  "password": "Vridik#Soporte2026!", "id": "e9ed5322-3977-4cc5-91b7-153577dd975c"},
]
ROLE_IDS = {"admin": 1, "abogado": 2, "cliente": 3}


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_db: requiere TEST_DATABASE_URL con PostgreSQL real")


@pytest.fixture(scope="session")
def juris_users_env() -> str:
    """Construye el valor de JURIS_USERS legacy a partir del mismo seed que
    db/seed_railway.sql, para que los tests de camino legacy y camino
    PostgreSQL verifiquen exactamente las mismas credenciales."""
    return ",".join(f"{u['legacy_username']}:{u['password']}:{u['role']}" for u in SEED_USERS)


@pytest.fixture(autouse=True)
def _env_base(monkeypatch, juris_users_env):
    """Variables de entorno base para todos los tests. autouse=True para que
    ningún test dependa accidentalmente del ENV real de quien corre pytest."""
    monkeypatch.setenv("JURIS_USERS", juris_users_env)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET_TEST)
    monkeypatch.setenv("ANTHROPIC_API_KEY_STAGING", "test-key-staging-no-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY_PROD", "test-key-prod-no-real")
    # Mock genérico pedido en S4 (semana 4-6): julix/client.py acepta ANTHROPIC_API_KEY
    # como fallback si no hay key específica de entorno — nunca se llama a Anthropic real.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-generic-no-real")
    monkeypatch.setenv("JULIX_RATE_LIMIT_ENABLED", "true")
    yield


@pytest.fixture(autouse=True)
def _cache_aislada_por_test(monkeypatch, tmp_path):
    """S11-extra: julix/service.py ahora instancia `RAGCache()` (rag/cache.py)
    con el path SQLite por defecto (data/rag_cache.db) antes de llamar al
    modelo. Sin este fixture, dos corridas de la suite compartirían ese
    archivo real — la segunda corrida trataría la pregunta de un test
    anterior como cache HIT (saltándose el SDK mockeado por completo) en vez
    de miss, rompiendo tests/test_julix.py (`factory.llamadas` quedaba
    vacío). Se parchea el nombre `RAGCache` tal como quedó importado dentro
    de julix.service (no la clase original en rag.cache) para que cada test
    use su propio archivo temporal — aislado, descartado al terminar, nunca
    comparte estado con otro test ni con data/rag_cache.db real."""
    import julix.service as julix_service_module
    from rag.cache import RAGCache as _RAGCacheReal

    ruta_test = tmp_path / "rag_cache_test.db"
    monkeypatch.setattr(julix_service_module, "RAGCache", lambda *a, **kw: _RAGCacheReal(db_path=ruta_test))
    yield


@pytest.fixture(params=["legacy", "postgres"], ids=["backend=legacy", "backend=postgres"])
def backend(request, monkeypatch) -> str:
    """Parametriza USE_POSTGRES. Todo test que reciba este fixture corre
    dos veces: una contra JURIS_USERS (legacy), otra contra PostgreSQL."""
    valor = "true" if request.param == "postgres" else "false"
    monkeypatch.setenv("USE_POSTGRES", valor)
    return request.param


@pytest.fixture(scope="session")
def test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session", autouse=True)
def _backfill_de_sesion(test_database_url):
    """Hardening RLS (core/rls.py): `ensure_rls_policies()` se salta
    `FORCE ROW LEVEL SECURITY` en cualquier tabla con filas
    `despacho_id IS NULL` pendientes (red de seguridad real para
    producción -- ver ese módulo). Los 4 usuarios de
    `db/seed_railway.sql` (julian/ana/cliente1/soporte) predatan el
    concepto de despacho y NUNCA pasan por el backfill real, que solo
    corre al arrancar `app/main.py::_conectar_db` -- la suite nunca
    levanta ese proceso. Sin este fixture, esas filas quedarían con
    `despacho_id NULL` para siempre en la base de test, y
    `ensure_rls_policies()` nunca aplicaría `FORCE` en users/casos/
    julix_calls durante NINGÚN test -- exactamente lo que pasó la
    primera vez que corrió tests/test_rls.py contra CI real.

    Corre UNA vez por sesión, con su PROPIA conexión que sí comitea
    (nunca la fixture `db`, que hace rollback) -- mismo trabajo que hace
    app/main.py al arrancar en producción real, para que el estado de la
    base de test represente "producción ya migrada", no "producción
    recién instalada".

    Fixture SÍNCRONA con `asyncio.run()` propio (no `pytest_asyncio.
    fixture`) a propósito: un fixture async de alcance "session" corre en
    un event loop distinto al que pytest-asyncio arma por test (modo
    `auto`, alcance de loop por función) -- `asyncio.run()` evita
    depender de ese manejo de loop por completo.

    También asegura acá (no dentro de la transacción con rollback de `db`)
    las tablas/columnas que varios tests dan por sentado que ya existen sin
    pasar ellos mismos por el ensure_*() correspondiente (`actuaciones`,
    `terminos`, `users.role`, `users.es_superadmin`) -- antes, cualquier
    ensure_*() corrido dentro de la transacción de un test se perdía en el
    rollback de ese mismo test, así que el resultado dependía de qué otro
    test hubiera corrido antes en la misma sesión y alcanzado a dejarlas
    creadas (nunca ocurre, todos hacen rollback). Corriendo una sola vez acá,
    con la conexión que sí comitea, quedan disponibles para toda la sesión
    sin importar el orden de los tests."""
    if asyncpg is None or not test_database_url:
        return

    import asyncio

    async def _correr() -> None:
        from core.actuaciones import ensure_actuaciones_table
        from core.admin import ensure_role_column, ensure_superadmin_column
        from core.case import ensure_casos_despacho_backfill
        from core.despachos import ensure_despachos_backfill
        from core.terminos import ensure_terminos_table
        from julix.ledger import ensure_julix_calls_despacho_backfill

        conn = await asyncpg.connect(test_database_url)
        try:
            await ensure_despachos_backfill(conn)
            await ensure_casos_despacho_backfill(conn)
            await ensure_julix_calls_despacho_backfill(conn)
            await ensure_role_column(conn)
            await ensure_superadmin_column(conn)
            await ensure_actuaciones_table(conn)
            await ensure_terminos_table(conn)
        finally:
            await conn.close()

    asyncio.run(_correr())


@pytest_asyncio.fixture if pytest_asyncio else pytest.fixture
async def db(test_database_url, backend):
    """Conexión con rollback transaccional. Se salta explícitamente si no hay
    PostgreSQL real disponible (nunca usa SQLite de reemplazo)."""
    if asyncpg is None:
        pytest.skip("asyncpg no instalado — ver requirements-test.txt")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL no configurado: se requiere PostgreSQL real (ver S3, service container en CI)")

    conn = await asyncpg.connect(test_database_url)
    tx = conn.transaction()
    await tx.start()
    # Hardening RLS (core/rls.py): estos ~300 tests testean funciones core
    # directo (create_caso(), etc.), no el camino HTTP + middleware de
    # conexión-por-request -- sin este bypass, cualquier SELECT/INSERT
    # contra users/casos/julix_calls/matriz_riesgo devolvería 0 filas
    # apenas esas tablas tengan FORCE ROW LEVEL SECURITY. El enforcement
    # real de RLS se prueba en tests/test_rls.py, revocando este bypass
    # explícitamente dentro de esos tests.
    await conn.execute("SELECT set_config('app.bypass_rls', 'true', false)")
    try:
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


@pytest_asyncio.fixture if pytest_asyncio else pytest.fixture
async def make_despacho(db):
    """Factory: crea un despacho ad hoc dentro de la transacción del test
    (Fase 4, multi-tenancy). Uso: despacho = await make_despacho(nombre="Despacho X").
    `despachos`/`users.despacho_id` no vienen en schema_semana1_vridik.sql
    (aplicado por CI antes de la suite) -- se asegura acá, igual que otros
    tests reales de Postgres aseguran su propia tabla antes de usarla."""
    from core.despachos import ensure_despachos_table

    await ensure_despachos_table(db)

    async def _make(*, nombre: str | None = None) -> str:
        despacho_id = str(uuid.uuid4())
        nombre = nombre or f"Despacho de prueba {despacho_id[:8]}"
        await db.execute(
            "INSERT INTO despachos (id, nombre) VALUES ($1, $2)",
            despacho_id, nombre,
        )
        return despacho_id

    return _make


@pytest_asyncio.fixture if pytest_asyncio else pytest.fixture
async def seed_roles(db):
    for codigo, role_id in ROLE_IDS.items():
        await db.execute(
            """
            INSERT INTO roles (id, codigo, nombre)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
            """,
            role_id, codigo, codigo.capitalize(),
        )
    return ROLE_IDS


@pytest_asyncio.fixture if pytest_asyncio else pytest.fixture
async def seeded_users(db, seed_roles, make_despacho):
    """Aplica el mismo contenido de db/seed_railway.sql dentro de la
    transacción del test actual. Fase 4: los 4 usuarios seed comparten UN
    despacho (representan el despacho único que Vridik tenía antes de
    multi-tenancy -- necesitan poder interactuar entre sí, p.ej. julian
    como admin gestionando casos de cliente1)."""
    if bcrypt is None:
        pytest.skip("bcrypt no instalado — ver requirements-test.txt")

    despacho_id = await make_despacho(nombre="Despacho seed")

    creados = []
    for u in SEED_USERS:
        # ON CONFLICT DO UPDATE (no DO NOTHING) para despacho_id -- estos 4
        # usuarios ya existen en la base ANTES de que corra la suite (CI
        # aplica db/seed_railway.sql una sola vez, fuera de la transacción
        # por-test), con despacho_id todavía NULL (ese seed no conocía la
        # columna). Sin el UPDATE, quedarían sin despacho dentro de la
        # transacción rollback de este test.
        await db.execute(
            """
            INSERT INTO users (id, email, nombre_completo, role_id, despacho_id, legacy_username, must_change, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, true, true)
            ON CONFLICT (id) DO UPDATE SET despacho_id = EXCLUDED.despacho_id
            """,
            u["id"], u["email"], u["legacy_username"].capitalize(), ROLE_IDS[u["role"]], despacho_id, u["legacy_username"],
        )
        password_hash = bcrypt.hashpw(u["password"].encode(), bcrypt.gensalt(rounds=4)).decode()  # rounds bajos: velocidad en tests
        await db.execute(
            """
            INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
            VALUES ($1, $2, 'bcrypt', true)
            ON CONFLICT (user_id) DO NOTHING
            """,
            u["id"], password_hash,
        )
        creados.append({**u, "despacho_id": despacho_id})
    return creados


@pytest_asyncio.fixture if pytest_asyncio else pytest.fixture
async def make_user(db, seed_roles, make_despacho):
    """Factory: crea un usuario ad hoc dentro de la transacción del test.
    Uso: user = await make_user(role='cliente', password='Clave#Test1').

    Fase 4: `despacho_id` es opcional -- si no se pasa, el usuario recibe
    un despacho propio nuevo. Dos usuarios que necesiten interactuar en el
    mismo caso (cliente + abogado asignado, p.ej.) DEBEN pasar el MISMO
    despacho_id explícito, o la validación cross-despacho de
    `core.case.asignar_abogado` los va a rechazar."""

    async def _make(
        *, role: str = "cliente", password: str = "Clave#Test123!",
        email: str | None = None, despacho_id: str | None = None,
    ):
        if bcrypt is None:
            pytest.skip("bcrypt no instalado — ver requirements-test.txt")
        if despacho_id is None:
            despacho_id = await make_despacho()
        user_id = str(uuid.uuid4())
        email = email or f"user-{user_id[:8]}@vridik.local"
        # `role` TEXT (no `role_id`) es la fuente real que lee toda la app
        # (core/admin.py::ensure_role_column, api/admin_endpoint.py::_resolver_
        # usuario) -- `role_id` es una capa secundaria de la migración 005 que
        # nunca se sincroniza sola. Sin setearla acá, cualquier usuario creado
        # por este factory con un rol distinto de 'cliente' quedaba con
        # role='cliente' (el DEFAULT) para cualquier chequeo real de
        # autorización, un gap que nunca se notó porque ningún test real de
        # Postgres había dependido del texto del rol hasta ahora.
        await db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'cliente'")
        await db.execute(
            """
            INSERT INTO users (id, email, nombre_completo, role_id, role, despacho_id, must_change, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, false, true)
            """,
            user_id, email, "Usuario de prueba", ROLE_IDS[role], role, despacho_id,
        )
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
        await db.execute(
            """
            INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
            VALUES ($1, $2, 'bcrypt', false)
            """,
            user_id, password_hash,
        )
        return {"id": user_id, "email": email, "role": role, "password": password, "despacho_id": despacho_id}

    return _make


def issue_access_token(*, sub: str, role: str, ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS) -> str:
    """Emite un access JWT HMAC igual que en producción (S1): 15 min de vida."""
    if pyjwt is None:
        pytest.skip("PyJWT no instalado — ver requirements-test.txt")
    now = int(time.time())
    claims = {"sub": sub, "role": role, "iat": now, "exp": now + ttl_seconds}
    return pyjwt.encode(claims, JWT_SECRET_TEST, algorithm="HS256")


@pytest.fixture
def token_factory():
    return issue_access_token


@pytest.fixture
def auth_client_factory(token_factory):
    """Retorna un callable auth_client(role, sub) -> dict con el token emitido
    y los claims, listo para pasarse a un cliente HTTP de pruebas (httpx) o
    para alimentar directamente core.feature_flag_legacy.DualAuthJWTMiddleware
    en los tests de S1/S2."""

    def _factory(role: str, sub: str = "test-user"):
        token = token_factory(sub=sub, role=role)
        return {"token": token, "role": role, "sub": sub, "headers": {"Authorization": f"Bearer {token}"}}

    return _factory
