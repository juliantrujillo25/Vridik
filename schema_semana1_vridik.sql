-- =====================================================================
-- Vridik — Esquema PostgreSQL Semana 1 (Sprint S1: Usuarios en PostgreSQL)
-- Tablas: roles, users, user_credentials, refresh_tokens, auth_events
-- Motor objetivo: PostgreSQL 15+ (Railway managed Postgres)
-- Convención: no downtime — este script es la migración "preparación"
-- del plan de 4 etapas (preparación → doble lectura → corte 48h → rollback)
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Extensiones requeridas
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";    -- email case-insensitive

-- ---------------------------------------------------------------------
-- Tabla: roles
-- Tabla, no enum: permite agregar roles (Fase 2+) sin migración de tipo.
-- ---------------------------------------------------------------------
CREATE TABLE roles (
    id          SMALLINT PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,          -- 'admin' | 'abogado' | 'cliente'
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO roles (id, codigo, nombre, descripcion) VALUES
    (1, 'admin',   'Administrador', 'Acceso total: gestión de usuarios, configuración, bitácora completa'),
    (2, 'abogado',  'Abogado/a',     'Gestión de casos, generador de documentos, JuliX, mensajería'),
    (3, 'cliente',  'Cliente',       'Portal Cliente Vridik: Mi Caso, mensajes, panel de ahorro (Fase 3)')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------
-- Tabla: users
-- UUID como PK, citext para email (unicidad case-insensitive real),
-- soft delete vía deactivated_at, legacy_username como puente de migración.
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email            CITEXT NOT NULL,
    nombre_completo  TEXT NOT NULL,
    role_id          SMALLINT NOT NULL REFERENCES roles(id),
    legacy_username  TEXT,                     -- puente con el sistema legacy durante la migración
    must_change      BOOLEAN NOT NULL DEFAULT true,  -- fuerza cambio de contraseña temporal
    is_active        BOOLEAN NOT NULL DEFAULT true,
    last_login_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_at   TIMESTAMPTZ,               -- soft delete: NULL = activo
    deleted_at       TIMESTAMPTZ                -- soft delete definitivo (borrado lógico)
);

-- Unicidad de email solo entre usuarios no borrados lógicamente
CREATE UNIQUE INDEX ux_users_email_active
    ON users (email)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX ux_users_legacy_username
    ON users (legacy_username)
    WHERE legacy_username IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX ix_users_role_id ON users (role_id);
CREATE INDEX ix_users_is_active ON users (is_active) WHERE is_active = true;

-- ---------------------------------------------------------------------
-- Tabla: user_credentials
-- Separada de users por higiene de seguridad (nunca se hace SELECT *
-- sobre credenciales por accidente). argon2id preferido, bcrypt como
-- fallback documentado para el algoritmo legacy durante la migración.
-- ---------------------------------------------------------------------
CREATE TABLE user_credentials (
    user_id        UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash  TEXT NOT NULL,               -- argon2id (preferido) o bcrypt (legacy)
    hash_algorithm TEXT NOT NULL DEFAULT 'argon2id'
                   CHECK (hash_algorithm IN ('argon2id', 'bcrypt')),
    is_temporary   BOOLEAN NOT NULL DEFAULT false, -- true mientras must_change=true
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by     UUID REFERENCES users(id)     -- admin que ejecutó el reset, NULL si fue el propio usuario
);

-- ---------------------------------------------------------------------
-- Tabla: refresh_tokens
-- Nunca se guarda el token en claro: solo su hash (SHA-256).
-- Rotación + detección de reuso: al usar un refresh token se marca
-- used_at y se crea uno nuevo enlazado por replaced_by_id. Si un token
-- ya usado (used_at IS NOT NULL) se presenta de nuevo → reuso detectado
-- → revocar toda la familia (revoked_at en todos los tokens con mismo
-- family_id) y disparar auth_event 'refresh_reuse_detected'.
-- ---------------------------------------------------------------------
CREATE TABLE refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL UNIQUE,        -- SHA-256 del refresh token real
    family_id       UUID NOT NULL,               -- agrupa la cadena de rotación de una sesión
    replaced_by_id  UUID REFERENCES refresh_tokens(id),
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,        -- issued_at + 7 días
    used_at         TIMESTAMPTZ,                 -- se marca al rotar (con gracia de 10s para carrera de pestañas)
    revoked_at      TIMESTAMPTZ,                 -- revocación manual (logout, desactivación, reuso detectado)
    revoked_reason  TEXT,                        -- 'logout' | 'user_deactivated' | 'reuse_detected' | 'admin_reset'
    user_agent      TEXT,
    ip_address      INET
);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
CREATE INDEX ix_refresh_tokens_expires_at ON refresh_tokens (expires_at)
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------
-- Tabla: auth_events
-- Embrión de la bitácora probatoria (Fase 3: bitácora sellada con hash
-- encadenado). Append-only por convención de aplicación: nunca se hace
-- UPDATE/DELETE sobre filas existentes desde el código de negocio.
-- ---------------------------------------------------------------------
CREATE TABLE auth_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_id    UUID REFERENCES users(id) ON DELETE SET NULL, -- quién ejecutó la acción (admin en CRUD, o el propio user_id)
    event_type  TEXT NOT NULL,
    -- 'login_success' | 'login_failed' | 'logout' | 'token_refresh'
    -- | 'refresh_reuse_detected' | 'user_created' | 'user_updated'
    -- | 'user_deactivated' | 'password_reset' | 'legacy_fallback'
    -- | 'totp_enrolled' | 'totp_verified' | 'totp_failed' (Fase 1 S12)
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- detalle libre por tipo de evento
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_auth_events_user_id_created_at ON auth_events (user_id, created_at DESC);
CREATE INDEX ix_auth_events_event_type ON auth_events (event_type);
CREATE INDEX ix_auth_events_created_at ON auth_events (created_at DESC);
-- Índice específico para el detector de legacy_fallback (corte a las 48h limpias)
CREATE INDEX ix_auth_events_legacy_fallback ON auth_events (created_at)
    WHERE event_type = 'legacy_fallback';

COMMIT;

-- =====================================================================
-- Notas de migración sin downtime (plan de 4 etapas, ver ROLLBACK.md)
-- 1. Preparación: correr este script en staging y producción (tablas
--    nuevas, no toca el sistema legacy).
-- 2. Doble lectura: la app intenta users/PostgreSQL primero; si falla,
--    cae a la fuente legacy y escribe auth_events(event_type='legacy_fallback').
-- 3. Corte: tras 48h sin filas legacy_fallback nuevas, se desactiva la
--    ruta de fallback en el código (feature flag, no borra tablas legacy).
-- 4. Rollback ensayado: ROLLBACK.md documenta cómo reactivar el fallback
--    legacy y cómo revertir este script (DROP en orden inverso de FKs).
-- =====================================================================

-- Rollback de referencia (ejecutar solo desde ROLLBACK.md, en ese orden):
-- DROP TABLE IF EXISTS auth_events;
-- DROP TABLE IF EXISTS refresh_tokens;
-- DROP TABLE IF EXISTS user_credentials;
-- DROP TABLE IF EXISTS users;
-- DROP TABLE IF EXISTS roles;
