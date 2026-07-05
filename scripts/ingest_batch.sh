#!/bin/bash
# Vridik / JuliX — scripts/ingest_batch.sh
# Sprint S7: corre rag/ingest_corpus.py en lotes de 50 filas del manifiesto
# data/corpus_manifest.csv, para la expansión del corpus (85 -> 400 chunks)
# sin cargar todo en una sola corrida larga y poder reanudar si algo falla
# a mitad de camino (basta con volver a correr desde el offset del último
# lote impreso en la salida).
#
# USO:
#   ./scripts/ingest_batch.sh [manifest] [prioridad] [modo]
#     manifest   ruta al CSV (default: data/corpus_manifest.csv)
#     prioridad  alta|media|baja|todas / high|medium|low|all (default: alta)
#     modo       dry-run|commit (default: dry-run)
#
# Ejemplos:
#   ./scripts/ingest_batch.sh                                   # dry-run, prioridad alta
#   ./scripts/ingest_batch.sh data/corpus_manifest.csv alta commit
#
# NO SE EJECUTA EN ESTE ENTREGABLE.

set -e

BATCH_SIZE=50
MANIFEST="${1:-data/corpus_manifest.csv}"
PRIORIDAD="${2:-alta}"
MODO="${3:-dry-run}"

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: no existe el manifiesto '$MANIFEST'" >&2
  exit 1
fi

if [ "$MODO" != "dry-run" ] && [ "$MODO" != "commit" ]; then
  echo "ERROR: modo '$MODO' inválido (usa 'dry-run' o 'commit')" >&2
  exit 1
fi

TOTAL=$(python3 -c "
import csv
with open('$MANIFEST', encoding='utf-8') as f:
    print(sum(1 for _ in csv.DictReader(f)))
")

echo "=== Vridik/RAG — ingesta por lotes ==="
echo "Manifiesto: $MANIFEST ($TOTAL filas totales) | prioridad=$PRIORIDAD | modo=$MODO | tamaño de lote=$BATCH_SIZE"

if [ "$TOTAL" -eq 0 ]; then
  echo "AVISO: el manifiesto no tiene filas. Nada que hacer."
  exit 0
fi

OFFSET=0
LOTE_NUM=1
while [ "$OFFSET" -lt "$TOTAL" ]; do
  echo ""
  echo "--- Lote #$LOTE_NUM (offset=$OFFSET, limit=$BATCH_SIZE) ---"

  if [ "$MODO" = "commit" ]; then
    python rag/ingest_corpus.py --source csv --manifest "$MANIFEST" --priority "$PRIORIDAD" \
      --offset "$OFFSET" --limit "$BATCH_SIZE" --commit
  else
    python rag/ingest_corpus.py --source csv --manifest "$MANIFEST" --priority "$PRIORIDAD" \
      --offset "$OFFSET" --limit "$BATCH_SIZE"
  fi

  OFFSET=$((OFFSET + BATCH_SIZE))
  LOTE_NUM=$((LOTE_NUM + 1))
done

echo ""
echo "Ingesta por lotes completa ($((LOTE_NUM - 1)) lote(s) procesados)."
