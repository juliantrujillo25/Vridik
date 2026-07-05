# Vridik — Estado del Roadmap (Fase 1)

Generado a partir de una revisión de los archivos ya entregados en Project Vridik (sin ejecutar código). Límite semanal usado: **75%**.

## Completado

| Tarea | Estado | Bloqueador | Próximo paso |
|---|---|---|---|
| S1 — Usuarios en PostgreSQL | [x] En repo | Ninguno | Aplicar `schema_semana1_vridik.sql` y correr `migrate_users.py` en Railway real |
| S2 — Panel de administración | [ ] No iniciado | Depende de S1 en Railway | Construir CRUD de UI sobre `feature_flag_legacy.py` |
| S3 — Suite de tests + CI | [x] En repo | Ninguno | Conectar CRUD real de S2 para que los fakes de contrato dejen de ser necesarios |
| S4 — JuliX con Claude real | [x] En repo | Ninguno | Ninguno — listo para producción |
| S5 — Banco de evaluación (Gate Fase 1) | [ ] Código listo, sin correr | Falta que Ana Luisa llene `respuesta_esperada` en `banco_casos_vridik.xlsx` | Enviar el Excel a Ana Luisa (ver `eval/guia_abogada.md`) |
| S6 — Iteración de prompts / RAG base | [x] En repo | Ninguno | Ninguno — listo para producción |
| S7 — Expansión de corpus (85→400) | [x] En repo (manifiesto de ejemplo, 20 filas) | Falta completar el manifiesto a 400 filas reales | Completar `data/corpus_manifest.csv` y correr `--commit` |
| S8 — Pipeline curado (quality gate) | [x] En repo | Depende de S7 con datos reales | Correr `rag/quality_gate.py` contra el corpus real una vez cargado |
| S9 — Búsqueda mejorada (re-ranking) | [x] En repo | Ninguno | Ninguno — verificado con casos de prueba |
| S10 — Export PDF con citas | [x] En repo | Ninguno | Ninguno — verificado generando PDFs reales |
| Estilo Ana Luisa (`julix/prompt_v3.txt`) | [x] En repo | Ninguno | Integrar la inyección condicional en `julix/service.py` cuando `user_id == "ana_luisa"` |
| Boost personalización (`julix/context_builder.py`) | [x] En repo | Ninguno | Ninguno — verificado con casos de prueba |
| `rag/eval_ana_luisa.py` | [x] En repo | Ninguno | Integrar `CRITERIO_JUEZ_SUENA_COMO_ANA_LUISA` en `eval/evaluador.py` si se quiere en el mismo gate |
| `rag/cache.py` + integración de cache | [x] En repo | Ninguno | Conectar `obtener_respuesta_con_cache()` en `julix/service.py` antes de la llamada real a Claude |

## En progreso

| Tarea | Estado | Bloqueador | Próximo paso |
|---|---|---|---|
| Migración Desktop (Giraldo Velasco / Marta Arias) | Código listo (`rag/ingest_desktop.py`), dry-run real ya ejecutado | `--commit` nunca se ha corrido contra datos reales (decisión deliberada de esta sesión) | Revisar `data/desktop_manifest.csv` y decidir si se ejecuta `--commit` en el entorno de producción |
| Perfil real de Ana Luisa | No iniciado | Falta `scripts/build_ana_profile.py` (no construido todavía) | Construir el script y correrlo offline sobre una muestra de 200 conversaciones (filtro UGPP/Ana/pensión) |

## Falta Fase 1

| Tarea | Estado | Bloqueador | Próximo paso |
|---|---|---|---|
| S5 — Evaluación con Excel de Ana Luisa | Bloqueado | Esperando que Ana Luisa llene `respuesta_esperada` (20 casos) | Seguimiento con Ana Luisa; sin esto, `--commit` de `eval/evaluador.py` no tiene nada que evaluar |
| S11 — Cache | Recién pedido, código entregado hoy | Ninguno a nivel de código; falta wiring en `service.py` | Conectar `obtener_respuesta_con_cache()` al flujo real de `julix/service.py` |
| S12 — Telemetría y métricas | No iniciado | Ninguno | Definir qué métricas más allá de `cache_hits`/`cache_misses` se necesitan (latencia, costo por consulta, errores) |
| Deploy Railway con S7-S10 | No iniciado | Ninguno de código; operativo | Correr `scripts/railway_setup_rag.sh` y `rag/ingest_ugpp.py --commit` en Railway real |
| Pruebas de carga (50 consultas simultáneas) | No iniciado | Depende de deploy en Railway | Diseñar el script de carga una vez el servicio esté desplegado |

## Riesgos

| Riesgo | Estado | Bloqueador | Próximo paso |
|---|---|---|---|
| Límite semanal 75% usado | Activo | Ninguno | Priorizar S11 (cache, ya entregado) y S5 (desbloquear con Ana Luisa) antes de abrir trabajo nuevo |
| `juris_ia.db` vacío | Confirmado, no migrar | Las 3 tablas (`analisis`, `procesos`, `generaciones`) tienen 0 filas y ninguna columna de embeddings | Revisar cuando `juris_ia.db` tenga datos reales que migrar |
| 80MB de ChatGPT sin procesar | Pendiente, dato sensible | Decisión explícita de no analizar el export completo todavía | Construir `scripts/build_ana_profile.py` con muestreo acotado (200 conversaciones) en vez de procesar el export completo |
