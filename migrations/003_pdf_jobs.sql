-- =====================================================================
-- Vridik / JuliX — migrations/003_pdf_jobs.sql
-- Sprint S10/S11-extra: tabla `pdf_jobs`, la cola de trabajos que consume
-- workers/pdf_worker.py (SELECT ... WHERE status='pending' ... FOR UPDATE
-- SKIP LOCKED) para generar PDFs con julix/pdf_export.py y actualizar
-- status='done' + pdf_url al terminar.
--
-- Migración idempotente: segura de correr aunque la tabla ya exista.
--
-- Nota de consistencia (RESUELTA): workers/pdf_worker.py se alineó a este
-- esquema (columna `query`, sin `tarea`/`caso_id`/`respuesta`/`fuentes` de
-- una versión anterior del worker) -- ver el encabezado de ese archivo
-- para el detalle. `pdf_jobs` ya aplicada y verificada contra Railway real
-- (S1-GAP-01, Fase A de la auditoría de auth arrastró esta también).
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS pdf_jobs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query      TEXT NOT NULL,
    user_id    TEXT,
    status     TEXT DEFAULT 'pending',
    pdf_url    TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_pdf_jobs_status ON pdf_jobs (status);

COMMIT;

-- Rollback de referencia:
-- DROP INDEX IF EXISTS ix_pdf_jobs_status;
-- DROP TABLE IF EXISTS pdf_jobs;
