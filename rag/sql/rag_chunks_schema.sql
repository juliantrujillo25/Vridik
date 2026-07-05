-- =====================================================================
-- Vridik / JuliX — rag/sql/rag_chunks_schema.sql
-- Sprint S6: RAG base sobre pgvector. Ampliada en S7 (expansión del corpus
-- 85 -> 400) con metadata de año/tribunal/tipo_fuente/prioridad, poblada
-- desde data/corpus_manifest.csv por rag/ingest_corpus.py.
-- Tabla: rag_chunks — chunks embebidos (sentence-transformers/all-MiniLM-L6-v2,
-- 384 dimensiones) para recuperación semántica en rag/context_builder.py.
--
-- Relación con el roadmap: esta sigue siendo una versión más ligera que
-- corpus_documents/corpus_chunks (pipeline curado completo de S7-S9 del
-- roadmap original, con revisión humana de 3 pasos) — rag_chunks prioriza
-- desbloquear la inyección de contexto real en JuliX rápido, con metadata
-- suficiente para filtrar por vigencia aproximada (año) y tipo de fuente.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE rag_chunks (
    id           BIGSERIAL PRIMARY KEY,
    norma        TEXT NOT NULL,             -- p.ej. 'Ley 1607 de 2012'
    articulo     TEXT NOT NULL,             -- p.ej. 'Art. 179'
    parrafo      TEXT,                       -- p.ej. 'Parágrafo 1' o NULL si no aplica
    texto        TEXT NOT NULL,               -- contenido del chunk (~600-800 tokens según pipeline)
    tokens       INTEGER NOT NULL,
    fuente_pdf   TEXT NOT NULL,               -- nombre/ruta del PDF de origen
    chunk_index  INTEGER NOT NULL,            -- posición del chunk dentro del PDF de origen
    hash_dedup   TEXT NOT NULL UNIQUE,        -- sha256 del texto, evita reingestar el mismo chunk
    embedding    VECTOR(384) NOT NULL,         -- sentence-transformers/all-MiniLM-L6-v2
    -- Metadata agregada en S7 (expansión de corpus 85 -> 400, rag/ingest_corpus.py):
    anio         SMALLINT,                     -- año de la norma o de la sentencia (p.ej. 2012, 2019, 2024)
    tribunal     TEXT,                         -- solo jurisprudencia: 'Consejo de Estado', 'Corte Suprema de Justicia', etc. NULL en ley/decreto
    tipo_fuente  TEXT CHECK (tipo_fuente IN ('ley', 'decreto', 'jurisprudencia')),
    prioridad    TEXT CHECK (prioridad IN ('alta', 'media', 'baja')),  -- heredada de data/corpus_manifest.csv
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índice aproximado de vecinos más cercanos (coseno) para la búsqueda del
-- top-5 en rag/context_builder.py. 'lists=100' es razonable para un corpus
-- de hasta ~decenas de miles de chunks (30 PDFs base de UGPP); recalibrar
-- si el corpus crece mucho más (ver S7-S9, carga a 400+ chunks del RAG legal).
CREATE INDEX ix_rag_chunks_embedding ON rag_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX ix_rag_chunks_norma ON rag_chunks (norma);
CREATE INDEX ix_rag_chunks_fuente_pdf ON rag_chunks (fuente_pdf);
CREATE INDEX ix_rag_chunks_tipo_fuente ON rag_chunks (tipo_fuente);
CREATE INDEX ix_rag_chunks_anio ON rag_chunks (anio);
CREATE INDEX ix_rag_chunks_prioridad ON rag_chunks (prioridad);

COMMIT;

-- Rollback de referencia:
-- DROP TABLE IF EXISTS rag_chunks;
-- DROP EXTENSION IF EXISTS "vector";
