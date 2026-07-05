#!/bin/bash
# Vridik / JuliX — scripts/railway_setup_rag.sh
# Sprint S6 (cierre de RAG): script de arranque en Railway.
#
# Qué hace, en orden:
#   1. Instala dependencias de requirements.txt (incluye sentence-transformers,
#      pgvector, psycopg2-binary agregados en el cierre de S6).
#   2. Aplica rag/sql/rag_chunks_schema.sql sobre $DATABASE_URL (idempotente:
#      CREATE TABLE/EXTENSION usan IF NOT EXISTS donde aplica; si la tabla ya
#      existe, psql devuelve el error de Postgres pero el script no debe
#      tumbar el arranque por eso — ver `|| true` más abajo).
#   3. Aplica migrations/003_pdf_jobs.sql (S10/S11-extra: tabla `pdf_jobs`
#      que consume workers/pdf_worker.py) — DESPUÉS de rag_chunks_schema.sql,
#      mismo manejo idempotente/no-fatal que el paso anterior.
#   4. Corre rag/ingest_ugpp.py --check: valida que /data/ugpp/ tiene PDFs,
#      SIN cargar el modelo de embeddings ni tocar la base de datos.
#   5. Imprime el mensaje de que el RAG queda listo para --commit (la
#      ingesta real de los 30 PDFs se dispara aparte, manualmente, nunca
#      como parte automática del arranque del servicio).
#
# Este script NO ejecuta la ingesta real (--commit) — ese paso queda
# deliberadamente manual, fuera del ciclo de arranque de Railway, para que
# alguien decida conscientemente cuándo cargar el corpus (y no cada vez que
# el servicio reinicia o se redespliega).
#
# NO SE EJECUTA EN ESTE ENTREGABLE.

set -e

echo "=== Vridik/JuliX — setup de RAG en Railway (S6) ==="

pip install --no-cache-dir -r requirements.txt

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL no está configurado. Abortando setup de RAG." >&2
  exit 1
fi

echo "--- Aplicando rag/sql/rag_chunks_schema.sql ---"
psql "$DATABASE_URL" -f rag/sql/rag_chunks_schema.sql || {
  echo "AVISO: rag_chunks_schema.sql devolvió un error (probablemente ya estaba aplicado). Continuando." >&2
}

echo "--- Aplicando migrations/003_pdf_jobs.sql (tabla pdf_jobs) ---"
psql "$DATABASE_URL" -f migrations/003_pdf_jobs.sql || {
  echo "AVISO: 003_pdf_jobs.sql devolvió un error (probablemente ya estaba aplicado). Continuando." >&2
}

echo "--- Validando /data/ugpp/ (rag/ingest_ugpp.py --check) ---"
python rag/ingest_ugpp.py --check

echo "RAG listo para --commit"
