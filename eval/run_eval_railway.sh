#!/bin/bash
# Vridik / JuliX — eval/run_eval_railway.sh
# Sprint S5 (banco de evaluación) — corrida en Railway/staging.
#
# Qué hace, en orden:
#   1. Fija el modelo de la corrida a claude-sonnet-5-20250624.
#   2. Corre evaluador.py --dry-run: valida el banco (cuenta cuántos de los
#      20 casos ya tienen 'respuesta_esperada' llenada por Ana Luisa) sin
#      llamar a Claude ni escribir en julix_evals.
#   3. Corre evaluador.py --commit: la corrida real — genera la respuesta
#      de JuliX con el prompt de producción, la califica con el "Claude
#      juez" y persiste cada caso en julix_evals.
#   4. Imprime el resumen de la corrida más reciente (score promedio y
#      conteo de alucinaciones) directamente desde julix_evals.
#
# Precondición: la columna 'respuesta_esperada' de eval/banco_casos_vridik.xlsx
# debe estar llena (ver eval/guia_abogada.md) — si no lo está, el paso 3 no
# tiene nada que evaluar y el resumen del paso 4 saldrá vacío.
#
# NO SE EJECUTA EN ESTE ENTREGABLE.

set -e

echo "=== Vridik/JuliX — corrida del banco de evaluación (S5) ==="

# ANTHROPIC_MODEL: nombre pedido explícitamente para esta corrida.
# julix/client.py lee ANTHROPIC_MODEL_JULIX como su variable canónica
# (ver julix/client.py, MODELO_DOCUMENTOS_POR_DEFECTO) — se exportan ambas
# para que la corrida quede fijada a Sonnet 5 sin depender de cuál de los
# dos nombres termine leyendo el código en cada punto.
export ANTHROPIC_MODEL=claude-sonnet-5-20250624
export ANTHROPIC_MODEL_JULIX=claude-sonnet-5-20250624

echo "--- Paso 1/3: dry-run (validación del banco) ---"
python eval/evaluador.py --dry-run

echo "--- Paso 2/3: corrida real (--commit) ---"
python eval/evaluador.py --commit

if [ -z "$DATABASE_URL" ]; then
  echo "AVISO: DATABASE_URL no configurado, no se puede imprimir el resumen de julix_evals." >&2
  exit 0
fi

echo "--- Paso 3/3: resumen de la corrida más reciente ---"
psql "$DATABASE_URL" -c "
SELECT
    run_id,
    AVG(score) AS avg_score,
    SUM(CASE WHEN hallucination_flag THEN 1 ELSE 0 END) AS casos_con_alucinacion
FROM julix_evals
GROUP BY run_id
ORDER BY run_id DESC
LIMIT 1;
"
