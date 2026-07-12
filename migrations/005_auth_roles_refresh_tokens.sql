-- =====================================================================
-- Vridik — migrations/005_auth_roles_refresh_tokens.sql
-- Fase A del plan de migración de auth (aprobado por el dev lead,
-- AUDITORIA_PARA_CLAUDE.md S1-GAP-01) — agrega el esquema de
-- schema_semana1_vridik.sql (roles/user_credentials/refresh_tokens/
-- auth_events) sobre la tabla `users` real y simple que ya corre en
-- producción (core/auth.py::ensure_users_table + core/admin.py::
-- ensure_role_column).
--
-- Principio: aditivo puro. Ninguna columna/tabla existente se renombra
-- ni se suelta -- `users.role` (TEXT) y `users.hashed_password` se
-- quedan intactos y siguen siendo la fuente real que usa el código hoy;
-- role_id/user_credentials son una capa nueva en paralelo hasta que el
-- código de Fase B se valide en producción (ver Fase C del plan).
--
-- Roles reales del marketplace (admin/seller/customer, confirmado contra
-- producción: SELECT DISTINCT role FROM users), NO el vocabulario legal
-- del roadmap original (admin/abogado/cliente) -- ese roadmap asumía un
-- despacho legal; este proyecto pivotó a un marketplace de servicios
-- legales con otro modelo de roles.
--
-- Migración idempotente: segura de correr aunque ya se haya aplicado.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------
-- 1. roles
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id          SMALLINT PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO roles (id, codigo, nombre, descripcion) VALUES
    (1, 'admin',    'Administrador', 'Acceso total: gestión de usuarios, productos, órdenes, pagos'),
    (2, 'seller',   'Vendedor',      'Gestión de sus propios productos y pedidos'),
    (3, 'customer', 'Cliente',       'Compra servicios, ve sus pedidos')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 2. Columnas nuevas en users -- todas nullable o con default, nunca
-- rompen filas existentes. role_id se backfillea desde la columna role
-- TEXT ya existente (que NO se toca).
-- ---------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id SMALLINT REFERENCES roles(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS nombre_completo TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

UPDATE users SET role_id = (SELECT id FROM roles WHERE codigo = users.role)
WHERE role_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_users_role_id ON users (role_id);

-- ---------------------------------------------------------------------
-- 3. email -> CITEXT (case-insensitive real). Bajo riesgo: preserva el
-- UNIQUE existente, solo cambia la semántica de comparación.
-- ---------------------------------------------------------------------
ALTER TABLE users ALTER COLUMN email TYPE CITEXT;

-- ---------------------------------------------------------------------
-- 4. user_credentials -- backfill copiando hashed_password. La columna
-- users.hashed_password se queda intacta (Fase B sigue leyéndola hasta
-- que se valide el nuevo flujo; ver Fase C del plan para el cleanup).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_credentials (
    user_id        UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash  TEXT NOT NULL,
    hash_algorithm TEXT NOT NULL DEFAULT 'bcrypt'
                   CHECK (hash_algorithm IN ('argon2id', 'bcrypt')),
    is_temporary   BOOLEAN NOT NULL DEFAULT false,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by     UUID REFERENCES users(id)
);

INSERT INTO user_credentials (user_id, password_hash, hash_algorithm)
SELECT id, hashed_password, 'bcrypt' FROM users
WHERE hashed_password IS NOT NULL
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 5. refresh_tokens -- nunca se guarda el token en claro, solo su hash.
-- Rotación + detección de reuso vía family_id (ver Fase B).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,
    family_id       UUID NOT NULL,
    replaced_by_id  UUID REFERENCES refresh_tokens(id),
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    user_agent      TEXT,
    ip_address      INET
);

CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_family_id ON refresh_tokens (family_id);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_expires_at ON refresh_tokens (expires_at)
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------
-- 6. auth_events -- embrión de bitácora probatoria (Fase 3 del roadmap).
-- Append-only por convención de aplicación: nunca UPDATE/DELETE desde
-- código de negocio.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type  TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_auth_events_user_id_created_at ON auth_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_auth_events_event_type ON auth_events (event_type);
CREATE INDEX IF NOT EXISTS ix_auth_events_created_at ON auth_events (created_at DESC);

COMMIT;

-- ROLLBACK: el DROP TABLE que estaba acá comentado quedó OBSOLETO -- se
-- escribió cuando la Fase A era puramente aditiva y nada más dependía de
-- estas tablas. Ya no es así: user_credentials es la fuente REAL de
-- password_hash (Fase C, S1-GAP-01), auth_events es load-bearing para
-- rate limiting de login (core/rate_limit.py) y reset de 2FA, y
-- refresh_tokens sostiene toda sesión activa. Correr un DROP TABLE
-- ciego contra esto ROMPE producción. Ver ROLLBACK.md (raíz del repo)
-- para el procedimiento real -- hoy, el rollback recomendado es de
-- código (redeploy de un commit anterior contra el esquema actual, que
-- sigue siendo un superset aditivo compatible), no de esquema.
