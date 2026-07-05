-- =====================================================================
-- Vridik / JuliX — rag/sql/002_rag_chunks_metadata.sql
-- Sprint S7: migración idempotente que agrega la metadata de expansión de
-- corpus (año, tribunal, tipo_fuente, prioridad) a una tabla rag_chunks que
-- ya existiera con el esquema original de S6.
--
-- Si se parte de un rag_chunks_schema.sql recién aplicado (ya incluye estas
-- columnas), este script no hace nada gracias a IF NOT EXISTS — es seguro
-- correrlo siempre, sin necesidad de saber si S6 ya se actualizó o no.
-- =====================================================================

BEGIN;

ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS anio SMALLINT;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tribunal TEXT;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tipo_fuente TEXT;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS prioridad TEXT;

-- Los CHECK constraints no admiten IF NOT EXISTS directamente; se agregan
-- solo si no existen ya (por nombre), para que la migración sea repetible.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'rag_chunks_tipo_fuente_check'
    ) THEN
        ALTER TABLE rag_chunks
            ADD CONSTRAINT rag_chunks_tipo_fuente_check
            CHECK (tipo_fuente IN ('ley', 'decreto', 'jurisprudencia'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'rag_chunks_prioridad_check'
    ) THEN
        ALTER TABLE rag_chunks
            ADD CONSTRAINT rag_chunks_prioridad_check
            CHECK (prioridad IN ('alta', 'media', 'baja'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_rag_chunks_tipo_fuente ON rag_chunks (tipo_fuente);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_anio ON rag_chunks (anio);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_prioridad ON rag_chunks (prioridad);

COMMIT;

-- Rollback de referencia:
-- ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_tipo_fuente_check;
-- ALTER TABLE rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_prioridad_check;
-- ALTER TABLE rag_chunks DROP COLUMN IF EXISTS anio, DROP COLUMN IF EXISTS tribunal,
--     DROP COLUMN IF EXISTS tipo_fuente, DROP COLUMN IF EXISTS prioridad;
