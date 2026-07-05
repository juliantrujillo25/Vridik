-- =====================================================================
-- Vridik / JuliX — eval/sql/julix_evals_schema.sql
-- Sprint S5: banco de evaluación (Gate de Fase 1).
-- Tabla: julix_evals — una fila por caso evaluado del banco.
-- =====================================================================

BEGIN;

CREATE TABLE julix_evals (
    id                    BIGSERIAL PRIMARY KEY,
    caso_id               TEXT NOT NULL,            -- 'UGPP-01' .. 'UGPP-12', 'LAB-01' .. 'LAB-08'
    area                  TEXT NOT NULL CHECK (area IN ('UGPP', 'Laboral')),
    dificultad            SMALLINT NOT NULL CHECK (dificultad BETWEEN 1 AND 3),
    model                 TEXT NOT NULL,             -- modelo usado para generar la respuesta de JuliX
    score                 SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 5),
    precision_normativa   SMALLINT CHECK (precision_normativa BETWEEN 0 AND 5),
    cita_correcta         BOOLEAN NOT NULL DEFAULT false,
    hallucination_flag    BOOLEAN NOT NULL DEFAULT false,
    comentario_juez       TEXT,
    respuesta_julix       TEXT NOT NULL,
    costo_usd_generacion  NUMERIC(10, 6),
    costo_usd_juez        NUMERIC(10, 6),
    costo_usd_total       NUMERIC(10, 6) GENERATED ALWAYS AS (
        COALESCE(costo_usd_generacion, 0) + COALESCE(costo_usd_juez, 0)
    ) STORED,
    run_id            TEXT NOT NULL,             -- agrupa todas las filas de una misma corrida del banco
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_julix_evals_run_id ON julix_evals (run_id);
CREATE INDEX ix_julix_evals_caso_id ON julix_evals (caso_id);
CREATE INDEX ix_julix_evals_hallucination ON julix_evals (hallucination_flag) WHERE hallucination_flag = true;

-- Vista de apoyo: % de aprobación por corrida (Gate de Fase 1, >=80%)
CREATE VIEW julix_evals_resumen_por_corrida AS
SELECT
    run_id,
    COUNT(*) AS total_casos,
    COUNT(*) FILTER (WHERE score >= 4 AND NOT hallucination_flag) AS casos_aprobados,
    COUNT(*) FILTER (WHERE hallucination_flag) AS casos_con_alucinacion,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE score >= 4 AND NOT hallucination_flag) / NULLIF(COUNT(*), 0),
        1
    ) AS porcentaje_aprobacion,
    SUM(costo_usd_total) AS costo_total_usd,
    MIN(created_at) AS iniciado_en,
    MAX(created_at) AS finalizado_en
FROM julix_evals
GROUP BY run_id;

COMMIT;

-- Rollback de referencia:
-- DROP VIEW IF EXISTS julix_evals_resumen_por_corrida;
-- DROP TABLE IF EXISTS julix_evals;
