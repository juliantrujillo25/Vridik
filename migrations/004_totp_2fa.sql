-- =====================================================================
-- Vridik / JuliX — migrations/004_totp_2fa.sql
-- Sprint S12: 2FA (TOTP, RFC 6238) opcional para roles admin/abogado.
--
-- Diseño (ver core/totp_2fa.py, S12):
--   - `totp_secret`: secreto base32 generado por el propio backend
--     (pyotp.random_base32()) — NUNCA se genera ni se acepta desde el
--     cliente, para que un cliente comprometido no pueda fijar un secreto
--     conocido y saltarse el 2FA.
--   - `totp_enabled`: false hasta que el usuario confirme un código válido
--     durante el setup (ver core/totp_2fa.py:confirmar_activacion) — un
--     secreto generado pero nunca confirmado no debe habilitar el login
--     con 2FA (evita quedar bloqueado por un QR nunca escaneado).
--   - `totp_activado_en`: auditoría de cuándo se confirmó la activación.
--
-- Migración idempotente: segura de correr aunque las columnas ya existan.
-- =====================================================================

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS totp_secret TEXT,
    ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS totp_activado_en TIMESTAMPTZ;

-- Nunca se expone totp_secret en consultas de listado (SELECT * FROM users
-- en el panel admin, por ejemplo) — queda como responsabilidad de la capa
-- de aplicación (core/totp_2fa.py, api/*) seleccionar columnas explícitas
-- y nunca incluir totp_secret en una respuesta HTTP.

COMMIT;

-- Rollback de referencia:
-- ALTER TABLE users
--     DROP COLUMN IF EXISTS totp_secret,
--     DROP COLUMN IF EXISTS totp_enabled,
--     DROP COLUMN IF EXISTS totp_activado_en;
