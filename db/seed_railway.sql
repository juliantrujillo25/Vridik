-- =====================================================================
-- Vridik — db/seed_railway.sql
-- Sprint S1/S2: 4 usuarios de prueba para el entorno de staging en Railway,
-- sobre el esquema de schema_semana1_vridik.sql (roles, users, user_credentials).
--
-- IMPORTANTE:
--   - Este seed es SOLO para staging/demo. Nunca correr contra producción.
--   - Los password hashes son bcrypt reales (12 rounds), precomputados en
--     este entregable (no se ejecutó nada contra una BD real). Las
--     contraseñas en claro se documentan abajo únicamente para que el
--     equipo pueda hacer login de prueba en staging; deben rotarse antes
--     de cualquier demo pública.
--   - must_change=true en los 4: el primer login exige cambio de clave,
--     igual que en el flujo real de S2 (Panel admin de usuarios).
--   - 'soporte' usa el rol 'abogado' como placeholder: el schema de S1 solo
--     define admin/abogado/cliente; si Vridik necesita un rol de soporte
--     interno diferenciado, se agrega en una migración futura (Fase 2+) sin
--     tocar este seed.
--
-- Credenciales de staging (rotar antes de cualquier demo pública):
--   julian    / Vridik#Admin2026!    (admin)
--   ana       / Vridik#Abogada2026!  (abogado)
--   cliente1  / Vridik#Cliente2026!  (cliente)
--   soporte   / Vridik#Soporte2026!  (abogado, placeholder de soporte interno)
-- =====================================================================

BEGIN;

-- Los roles ya deben existir (insertados por schema_semana1_vridik.sql).
-- Este INSERT es idempotente por si el seed se corre en una BD nueva
-- antes que el script de esquema haya poblado roles.
INSERT INTO roles (id, codigo, nombre, descripcion) VALUES
    (1, 'admin',   'Administrador', 'Acceso total: gestión de usuarios, configuración, bitácora completa'),
    (2, 'abogado',  'Abogado/a',     'Gestión de casos, generador de documentos, JuliX, mensajería'),
    (3, 'cliente',  'Cliente',       'Portal Cliente Vridik: Mi Caso, mensajes, panel de ahorro (Fase 3)')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- julian — admin
-- ---------------------------------------------------------------------
INSERT INTO users (id, email, nombre_completo, role_id, legacy_username, must_change, is_active)
VALUES (
    'cbe8915d-ff96-406d-a2a6-cef125711cfc',
    'julian@vridik.local',
    'Julián (dev lead / admin de staging)',
    1,
    'julian',
    true,
    true
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
VALUES (
    'cbe8915d-ff96-406d-a2a6-cef125711cfc',
    '$2b$12$5jG.UZxupEVls1fEFUH1H.ATm0BXCbjha5yj5y70M6d/WUh/2f/HC',  -- bcrypt('Vridik#Admin2026!')
    'bcrypt',
    true
)
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- ana — abogada (Ana Luisa, usuaria de referencia del roadmap)
-- ---------------------------------------------------------------------
INSERT INTO users (id, email, nombre_completo, role_id, legacy_username, must_change, is_active)
VALUES (
    'd0d8da54-0e77-4c9d-bd4d-32f54cf28e00',
    'ana@vridik.local',
    'Ana Luisa (abogada)',
    2,
    'ana',
    true,
    true
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
VALUES (
    'd0d8da54-0e77-4c9d-bd4d-32f54cf28e00',
    '$2b$12$vS/TCdAO2e6yhZo992G1cOZct2tud1KdcA1Ec85iGURwusV8RR/hm',  -- bcrypt('Vridik#Abogada2026!')
    'bcrypt',
    true
)
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- cliente1 — cliente (Portal Cliente Vridik)
-- ---------------------------------------------------------------------
INSERT INTO users (id, email, nombre_completo, role_id, legacy_username, must_change, is_active)
VALUES (
    '43622ec2-e3d3-405b-abc5-ef4babb586cc',
    'cliente1@vridik.local',
    'Cliente de prueba 1',
    3,
    'cliente1',
    true,
    true
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
VALUES (
    '43622ec2-e3d3-405b-abc5-ef4babb586cc',
    '$2b$12$OOkXf6.Kr3XQd/kVK1FcOOBCoM9T49gsV6OyD.LCjf8n.GO7kLYea',  -- bcrypt('Vridik#Cliente2026!')
    'bcrypt',
    true
)
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- soporte — rol 'abogado' como placeholder de soporte interno (ver nota arriba)
-- ---------------------------------------------------------------------
INSERT INTO users (id, email, nombre_completo, role_id, legacy_username, must_change, is_active)
VALUES (
    'e9ed5322-3977-4cc5-91b7-153577dd975c',
    'soporte@vridik.local',
    'Soporte interno (staging)',
    2,
    'soporte',
    true,
    true
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_credentials (user_id, password_hash, hash_algorithm, is_temporary)
VALUES (
    'e9ed5322-3977-4cc5-91b7-153577dd975c',
    '$2b$12$mVGjDtvkd7CrSyQNs/ucqOhg0Xlb3KtkLG1D.X05yBZaTKKNiBaTG',  -- bcrypt('Vridik#Soporte2026!')
    'bcrypt',
    true
)
ON CONFLICT (user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- auth_events: deja rastro de que estos 4 usuarios nacieron del seed de
-- staging, no de un registro real ni de la migración legacy (migrate_users.py)
-- ---------------------------------------------------------------------
INSERT INTO auth_events (user_id, actor_id, event_type, metadata)
SELECT id, NULL, 'user_created', jsonb_build_object('origen', 'seed_railway.sql', 'entorno', 'staging')
FROM users
WHERE id IN (
    'cbe8915d-ff96-406d-a2a6-cef125711cfc',
    'd0d8da54-0e77-4c9d-bd4d-32f54cf28e00',
    '43622ec2-e3d3-405b-abc5-ef4babb586cc',
    'e9ed5322-3977-4cc5-91b7-153577dd975c'
);

COMMIT;

-- Rollback de referencia (deshacer solo el seed, no el esquema):
-- DELETE FROM auth_events WHERE metadata->>'origen' = 'seed_railway.sql';
-- DELETE FROM user_credentials WHERE user_id IN (
--     'cbe8915d-ff96-406d-a2a6-cef125711cfc', 'd0d8da54-0e77-4c9d-bd4d-32f54cf28e00',
--     '43622ec2-e3d3-405b-abc5-ef4babb586cc', 'e9ed5322-3977-4cc5-91b7-153577dd975c'
-- );
-- DELETE FROM users WHERE id IN (
--     'cbe8915d-ff96-406d-a2a6-cef125711cfc', 'd0d8da54-0e77-4c9d-bd4d-32f54cf28e00',
--     '43622ec2-e3d3-405b-abc5-ef4babb586cc', 'e9ed5322-3977-4cc5-91b7-153577dd975c'
-- );
