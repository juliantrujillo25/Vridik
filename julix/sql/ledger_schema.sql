-- =====================================================================
-- Vridik / JuliX — Ledger de costos (Sprint S4: JuliX con Claude real)
-- Tabla: julix_calls
-- =====================================================================

BEGIN;

CREATE TABLE julix_calls (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    caso_id         UUID,                        -- referencia al caso/expediente (Vridik core)
    tarea           TEXT NOT NULL,                 -- 'redaccion_ugpp' | 'clasificacion_documento' | ...
    model           TEXT NOT NULL,                  -- 'claude-sonnet-5' | 'claude-haiku-4-5-20251001' | ...
    prompt_version  INTEGER NOT NULL,
    prompt_hash     TEXT NOT NULL,                    -- sha256[:16] del contenido del prompt (reproducibilidad)
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    costo_usd       NUMERIC(10, 6) NOT NULL,
    latency_ms      INTEGER NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN (
                        'ok', 'timeout', 'rate_limited',
                        'overloaded_partial', 'truncated', 'invalid_format'
                    )),
    environment     TEXT NOT NULL CHECK (environment IN ('staging', 'production')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_julix_calls_user_id ON julix_calls (user_id);
CREATE INDEX ix_julix_calls_caso_id ON julix_calls (caso_id);
CREATE INDEX ix_julix_calls_created_at ON julix_calls (created_at DESC);
CREATE INDEX ix_julix_calls_status ON julix_calls (status) WHERE status <> 'ok';

-- Vista de apoyo para el widget de costos del Panel Vridik Pro:
-- gasto del mes en curso por entorno.
CREATE VIEW julix_gasto_mensual AS
SELECT
    environment,
    date_trunc('month', created_at) AS mes,
    SUM(costo_usd) AS costo_total_usd,
    COUNT(*) AS llamadas,
    COUNT(*) FILTER (WHERE status <> 'ok') AS llamadas_con_fallo
FROM julix_calls
GROUP BY environment, date_trunc('month', created_at);

COMMIT;

-- Rollback de referencia:
-- DROP VIEW IF EXISTS julix_gasto_mensual;
-- DROP TABLE IF EXISTS julix_calls;
