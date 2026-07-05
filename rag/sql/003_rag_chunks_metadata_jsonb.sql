-- =====================================================================
-- Vridik / JuliX — rag/sql/003_rag_chunks_metadata_jsonb.sql
-- Sprint S11: columna metadata JSONB en rag_chunks, requerida por
-- rag/ingest_desktop.py para el dedup nivel-archivo:
--   SELECT 1 FROM rag_chunks WHERE metadata->>'sha256' = $1
--
-- Distinta de las columnas anio/tribunal/tipo_fuente/prioridad agregadas
-- en 002_rag_chunks_metadata.sql (S7, corpus normativo): esta columna
-- guarda metadata específica de documentos de CLIENTES (sha256 del
-- archivo completo, fuente = carpeta de origen del despacho), que no
-- aplica al corpus normativo (leyes/decretos/jurisprudencia) y por eso
-- se modela aparte como JSONB en vez de columnas TEXT adicionales.
--
-- Migración idempotente: segura de correr aunque la columna ya exista.
-- =====================================================================

BEGIN;

ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Índice GIN para acelerar filtros por clave JSONB (metadata->>'sha256',
-- metadata->>'fuente') usados por ingest_desktop.py y por el boost de
-- rag/context_builder.py (S11: filtro por fuente de cliente).
CREATE INDEX IF NOT EXISTS ix_rag_chunks_metadata_gin ON rag_chunks USING GIN (metadata);

-- Índice de expresión específico para el chequeo de dedup por sha256
-- (más selectivo que el GIN genérico para esta consulta puntual).
CREATE INDEX IF NOT EXISTS ix_rag_chunks_metadata_sha256
    ON rag_chunks ((metadata ->> 'sha256'));

COMMIT;

-- Rollback de referencia:
-- DROP INDEX IF EXISTS ix_rag_chunks_metadata_sha256;
-- DROP INDEX IF EXISTS ix_rag_chunks_metadata_gin;
-- ALTER TABLE rag_chunks DROP COLUMN IF EXISTS metadata;
