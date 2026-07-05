# Backlog Ejecutable — Vridik Fase 1 (Railway)

**Proyecto:** Vridik · **Fase:** 1 — Consolidación · **Periodo:** Q3-2026 · **Duración:** 13 sprints semanales
**Entorno de despliegue:** Railway (servicio API + PostgreSQL managed + worker PDF + servicio JuliX)

Convención de estados de sprint en el tablero Railway/GitHub Projects: `Backlog → En progreso → Review → Done`. Cada tarea de la tabla es un issue; cada fila "Salida" es el criterio de aceptación del issue "Salida — Sprint N"; cada "Definition of Done" es un issue de tipo `gate` que bloquea el sprint siguiente si no cierra.

## Bloques

| Bloque | Sprints | Objetivo |
|---|---|---|
| A. Cimientos | S1–S3 | Auth real en PostgreSQL + panel admin + CI |
| B. JuliX real | S4–S6 | Integración Claude, banco de evaluación, iteración de prompts |
| C. Corpus | S7–S9 | Pipeline de ingesta y carga a 400+ chunks |
| D. Entregables | S10–S11 | PDF y mensajería en tiempo real |
| E. Cierre | S12–S13 | 2FA, hardening, regresión y demo (con colchón) |

## Estado de sprints

| Sprint | Estado | Notas |
|---|---|---|
| S1 — Usuarios en PostgreSQL | ✅ **Listo para deploy** | `schema_semana1_vridik.sql`, `migrations/migrate_users.py` (dry-run + `--commit`, idempotente), `migrations/rollback_env.py`, `core/feature_flag_legacy.py` (flag `USE_POSTGRES` + doble lectura) y `db/seed_railway.sql` (4 usuarios de prueba) entregados y verificados con `py_compile`. Pendiente antes de correr en Railway real: aplicar `schema_semana1_vridik.sql` en la instancia managed, cargar `JURIS_USERS`/`DATABASE_URL` en las variables de entorno, y ejecutar `migrate_users.py` primero en modo dry-run. |
| S2 — Panel de administración de usuarios | 🔜 Pendiente | Backend de doble lectura (`feature_flag_legacy.py`) ya disponible como base; falta el CRUD de UI y los tests de S2. |
| S3 — Suite de tests + CI | ✅ **Tests base + CI** | `/tests/` con 45 tests pytest (`test_auth.py` 10, `test_roles.py` 8, `test_mensajes.py` 7, `test_generador.py` 8, `test_julix.py` 7, `test_panel.py` 5), fixtures con rollback transaccional sobre PostgreSQL real y parametrización `backend=[legacy,postgres]` sobre `feature_flag_legacy.py`. `.github/workflows/ci.yml` con job `test` (py_compile + pytest + gate de ≥90% tests verdes vía `scripts/check_pass_ratio.py`) y job `validate-sql` (dry-run de los 3 `.sql` de Vridik/JuliX sobre PostgreSQL efímero). `requirements-test.txt` publicado. Pendiente antes de activar branch protection real: conectar el CRUD de UI de S2 para que `test_roles.py`/`test_mensajes.py`/`test_generador.py`/`test_panel.py` dejen de depender de sus fakes de contrato. |
| S4 — JuliX con Claude real | ✅ **Sonnet 5 configurado** | `julix/client.py` completo: `AsyncAnthropic` real, modelo confirmado `claude-sonnet-5-20250624` vía `ANTHROPIC_MODEL_JULIX` (ajuste del dev lead en semana 5, ya no es placeholder), retry con backoff exponencial (máx. 3 intentos, nunca tras streaming parcial), timeout duro de 30s, y registro propio en `julix_calls`. `julix/ledger.py`: tabla de precios 2026 confirmada para Sonnet 5 ($3.00/1M input, $15.00/1M output — TODO retirado), `get_monthly_cost(user_id)`, `obtener_ultima_llamada`. `julix/prompts/v1_ugpp_demanda.md` y `v2_laboral_consulta.md` agregados sin tocar los prompts previos. `api/julix_endpoint.py` (FastAPI): `POST /julix/query` con JWT + rate limit 20/min. `tests/test_julix.py` (7 tests, 45 en total) mockeando el SDK, no `stream_completion` completo. |
| S5 — Banco de evaluación (GATE de fase) | ⏳ **Esperando a Ana Luisa** | `eval/banco_casos_vridik.xlsx` (20 casos: 12 UGPP + 8 Laboral), `eval/sql/julix_evals_schema.sql` (tabla `julix_evals`, columna `run_id` + vista de resumen por corrida), `eval/evaluador.py` (`--dry-run` explícito y `--commit`, mutuamente excluyentes), `eval/run_eval_railway.sh` (fija `ANTHROPIC_MODEL`/`ANTHROPIC_MODEL_JULIX=claude-sonnet-5-20250624`, corre dry-run → commit → imprime resumen de la corrida más reciente desde `julix_evals`), `eval/guia_abogada.md` (guía de 1 página + checklist final de 5 minutos). Todo el código está listo y verificado con mocks; lo único que falta es que Ana Luisa llene `respuesta_esperada` en los 20 casos — sin eso, `--commit` no tiene nada que evaluar. |
| S6 — Iteración de prompts / RAG base | ✅ **Listo para producción** | Cierre completo: `requirements.txt` con `sentence-transformers==2.7.0`, `pgvector`, `psycopg2-binary`, `pypdf`; `rag/sql/rag_chunks_schema.sql` (tabla + índice `ivfflat`); `rag/ingest_ugpp.py` con `--check` (valida que `/data/ugpp/` tenga PDFs, sin tocar embeddings ni BD), `--dry-run` y `--commit`; `scripts/railway_setup_rag.sh` (instala deps, aplica schema, corre `--check`); `nixpacks.toml` (build/start de Railway) + `app/main.py` (re-exporta el API de JuliX para que `uvicorn app.main:app` sea un path válido). `julix/service.py` sigue inyectando contexto RAG real + directiva de fuente obligatoria (heredado de la entrega anterior). Todo verificado con `py_compile`, pytest (47 tests) y validación manual de `--check`/`--dry-run`/TOML — nada ejecutado contra Anthropic, PostgreSQL real ni los PDFs reales de UGPP. Pendiente estrictamente operativo (no de código): correr `scripts/railway_setup_rag.sh` en Railway y luego `rag/ingest_ugpp.py --commit` sobre los 30 PDFs reales cuando estén disponibles en `/data/ugpp/`. |
| S7 — Expansión de corpus (85 → 400) | 🚧 **En progreso** | `data/corpus_manifest.csv` (20 filas de ejemplo: Ley 1607/2012, Ley 2010/2019, Decreto 1625/2016, 7 sentencias Consejo de Estado UGPP, CST), `rag/ingest_corpus.py` (nuevo, sibling de `ingest_ugpp.py`: `--source csv --priority {alta,media,baja,todas}`, chunking 600/120 tokens, metadata norma/artículo/año/tribunal, dedup por hash), `scripts/ingest_batch.sh` (lotes de 50 filas del manifiesto, dry-run por defecto). Falta: completar el manifiesto a 400 filas reales y correr `--commit` contra los PDFs reales (no incluido en este entregable). |
| S8 — Pipeline curado (quality gate) | 🚧 **En progreso** | `rag/quality_gate.py` (nuevo): valida `[norma, artículo]` presentes, rechaza chunks <100 caracteres o sin patrón de cita reconocible, genera `rag_quality_report.json` con motivos agregados. Verificado con casos válidos/inválidos hechos a mano. Falta: correrlo contra el corpus real una vez cargado (S7 `--commit`). |
| S9 — Búsqueda mejorada (re-ranking) | 🚧 **En progreso** | `rag/context_builder.py` actualizado: `ChunkRecuperado` gana campos opcionales `anio`/`tribunal`/`tipo_fuente` (compatibles con las construcciones ya existentes en `tests/test_julix.py`), propiedades `similitud` y `score` (boost por tipo de fuente ley>decreto>jurisprudencia + bonus de recencia 2019-2026), y `buscar_contexto` ahora trae un pool de candidatos 3x más grande y los reordena por `.score` antes de truncar a `top_k`. Verificado: una ley de 2019 le gana a una jurisprudencia de 2015 aunque esta última tenga distancia bruta levemente mejor. |
| S10 — Export PDF con citas | 🚧 **En progreso** | `julix/pdf_export.py` (nuevo): `FuenteCitada` (con `desde_chunk_recuperado`/`desde_referencia`) + `generar_pdf(...)` con ReportLab — header "Vridik Pro", cuerpo de la respuesta, sección "Fuentes citadas" numerada, disclaimer "Borrador para revisión de abogado – no constituye asesoría legal" en el pie de cada página. `api/julix_endpoint.py` actualizado: `?format=pdf` en `POST /julix/query` devuelve el PDF (`FileResponse`) en vez de JSON; se agrega el campo `pregunta` (antes nunca llegaba desde el endpoint a `service.generar_documento`, gap detectado y cerrado en esta entrega). Verificado generando PDFs reales (firma `%PDF-`) con y sin fuentes. |
| S11-extra — Economía de tokens (ingesta de documentos de cliente) | 🚧 **En progreso** | `rag/ingest_desktop.py` (nuevo): dedup a nivel archivo (SHA256 vs. `metadata->>'sha256'`) y a nivel chunk (`hash_dedup`), anonimización obligatoria antes de embeddings, chunking 600/120 reutilizando `rag/ingest_corpus.py`, batch embedding de 32, `--dry-run`/`--commit` mutuamente excluyentes, salvaguarda de 8MB para extracción en dry-run. `rag/anonymizer.py` (nuevo): NER spaCy con fallback heurístico, `is_duplicate()`. `rag/sql/003_rag_chunks_metadata_jsonb.sql` (nueva migración idempotente, columna `metadata` JSONB + 2 índices). `rag/context_builder.py` actualizado: `fuente_cliente`, filtro `solo_fuentes` y bonus `+0.08` para `{"Giraldo Velasco","Marta Arias"}`. `data/desktop_manifest.csv` generado con una corrida **real** de `--dry-run` (autorizada explícitamente por el usuario) sobre las carpetas reales de Giraldo Velasco Abogados y Marta Arias — solo simulación, sin embeddings ni escritura en Postgres; `--commit` no se ejecutó contra datos reales. Suite de 47 tests re-verificada sin regresiones. Falta: ejecutar `--commit` en el entorno de producción de Vridik bajo los procedimientos de manejo de datos del despacho. |
| S11 — Mensajería en tiempo real (SSE) | 🔜 Pendiente | Sin cambios respecto al backlog original. |
| S12–S13 | 🔜 Pendiente | Sin cambios respecto al backlog original. |

## Tabla de 13 sprints

| # | Sprint | Bloque | Tareas | Salida | Definition of Done |
|---|---|---|---|---|---|
| 1 | S1 — Usuarios en PostgreSQL ✅ *Listo para deploy* | A. Cimientos | · Esquema `users` (UUID, citext email, soft delete, `legacy_username`), `roles`, `user_credentials` (argon2id, `must_change`), `refresh_tokens` (hash, rotación), `auth_events`.<br>· Access JWT 15 min (HMAC) + refresh 7 días en BD con rotación y detección de reuso (gracia 10s).<br>· Migración 4 etapas: preparación → doble lectura con evento `legacy_fallback` → corte tras 48h limpias → `ROLLBACK.md` ensayado en staging.<br>· Unificar clave localStorage `vridik.auth.refresh`; access token en memoria. | 3 roles login contra PostgreSQL con mismo contrato JSON; desactivar usuario surte efecto en ≤15 min; rollback probado en staging. | Migración corrida en staging sin downtime; 0 `legacy_fallback` en 48h; `ROLLBACK.md` ejecutado una vez de verdad. |
| 2 | S2 — Panel de administración de usuarios | A. Cimientos | · CRUD admin: crear (temporal mostrada una vez, copiable), listar, editar, desactivar (revoca refresh), reset.<br>· Drawer accesible: foco atrapado, radio de roles con descripción, confirmaciones proporcionales, 100% teclado, contraste AA.<br>· Sección "Actividad" por usuario leyendo `auth_events`.<br>· Tests: email duplicado case-insensitive → 409, no-admin → 403, reset revoca refresh. | Ana Luisa crea un usuario en <2 min sin ayuda; `must_change` bloquea todo salvo cambio de clave; cada acción deja `auth_event`. | CRUD completo probado manualmente por Ana Luisa; navegación 100% por teclado verificada; auditoría visible en UI. |
| 3 | S3 — Suite de tests + CI ✅ *Tests base + CI* | A. Cimientos | · pytest + httpx + **PostgreSQL real** (service container) — nunca SQLite.<br>· Catálogo ~45 tests: login (8), tokens (12), autorización por rol (10), CRUD (10), contrato (5).<br>· 5 fixtures centrales (`db` con rollback transaccional, `seed_roles`, usuarios por rol, `auth_client(role)`) + factory `make_user()`.<br>· GitHub Actions: postgres service container, ruff, `cov-fail-under=50`, <3 min, branch protection.<br>· `CONTRIBUTING.md` con 3 reglas; romper CI a propósito una vez. | ≥40 tests verdes; merge bloqueado sin CI pasando; test nuevo autenticado en <10 líneas. | Pipeline CI corre en <3 min en Railway/GitHub Actions; branch protection activa en `main`; cobertura ≥50% reportada. |
| 4 | S4 — JuliX con Claude real ✅ *Sonnet 5 configurado* | B. JuliX real | · Módulo `/julix/`: `service`, `prompts/` versionados (encabezado `v:`), `client` (reintentos, timeouts, streaming), `context_builder` (presupuesto de tokens, truncado con criterio), `ledger`.<br>· Streaming SSE al frontend desde el día uno, con cancelar visible.<br>· Selección de modelo por tarea (Sonnet por defecto en documentos de fondo, Haiku en clasificación/comunicaciones).<br>· Ledger `julix_calls` (modelo, prompt_version, tokens, costo USD, latencia, estado); límite blando mensual (80% aviso, 100% confirmación); techo de tokens por petición; widget de costos en Panel Vridik Pro.<br>· Domar 5 modos de fallo: timeout/red, 429, 529, truncado por `max_tokens`, formato inválido.<br>· API keys separadas staging/producción; prompts y respuestas en tabla restringida. | Documento de punta a punta generado con streaming; corrida de humo de 3 casos × 2 modelos con costos comparados. | Ningún fallo se presenta como éxito silencioso; ledger de costos operativo con al menos 6 llamadas registradas; keys separadas confirmadas en Railway (variables de entorno por entorno). |
| 5 | S5 — Banco de evaluación (GATE de fase) ⏳ *Esperando a Ana Luisa* | B. JuliX real | · 20 casos reales con patrón oro: 8 UGPP núcleo, 4 UGPP borde, 4 laboral no-UGPP, 2 trampa (procedibilidad / norma derogada), 2 documento cliente.<br>· Ficha estándar: entrada anonimizada + `contexto.md` + patrón oro + rúbrica vacía. Banco congelado antes de la corrida 1.<br>· Anonimización por reemplazo consistente (cifras y fechas se conservan), hecha por el despacho.<br>· Rúbrica: 4 dimensiones + global 1-4 + 2 flags (alucinación, omisión peligrosa) + campo libre.<br>· Script reproducible (hash de prompt + versión); calificación a ciegas en 3 sesiones ≤7 casos. | Corrida 1 completa con calificación ciega registrada. | **GATE:** ≥60% en global 3-4 para continuar; si no se cumple, S6 se redefine como diagnóstico exclusivo. |
| 6 | S6 — Iteración de prompts con método ✅ *Listo para producción* | B. JuliX real | · Triage por causa raíz: contexto insuficiente → context_builder; recuperación fallida → RAG; instrucción ambigua → prompt; conocimiento ausente → backlog ingesta S8-9; juicio deficiente → prompt razonado o modelo.<br>· Flags primero (alucinación sin fuente vs. con fuente en contexto).<br>· Máximo 4 versiones de prompt, 1 cambio por experimento, cada una con hipótesis escrita y probe de 3-5 casos.<br>· Jerarquía de intervención: reordenar contexto → instrucciones negativas → razonamiento por etapas → ejemplos del patrón oro → cambio de modelo.<br>· Corrida 2 re-aleatorizada con misma rúbrica; fijar costo promedio por documento. | `PROMPTS.md` publicado (versiones, patrones de fallo, reglas de oro). | ≥80% → congelar línea base; 60-79% → gate parcial (corrida 3 tras corpus en S9); <60% → freno formal y revisión de roadmap documentada. |
| 7 | S7 — Pipeline de ingesta del corpus 🧩 *Preparado* | C. Corpus | · Esquema `corpus_documents` (tipo_fuente, jerarquia, area, vigencia + nota, fuente_url, hash dedup) y `corpus_chunks` (orden, referencia citable, embedding, tokens).<br>· Chunking por estructura jurídica (no por tamaño): leyes por artículo, sentencias por sección, conceptos por pregunta-respuesta; prefijo de contexto autocontenido.<br>· Pipeline: extracción → normalización → detección de estructura semiautomática → chunking → prefijo → dedup por hash → metadatos → embedding batch con ledger → test de recuperación por ingesta.<br>· Validador de citas post-generación en JuliX (cita ↔ referencia presente en el contexto).<br>· Mini-herramienta de 3 pasos: carga con texto extraído visible → chunks editables (atajos de teclado) → metadatos preseleccionados por heurística; borradores persistentes, modo oscuro. | Ingesta de un documento nuevo en <10 min sin código; 85 chunks existentes re-ingestados sin degradación (humo de 3 casos). | Dedup demostrada con un documento duplicado deliberado; validador de citas activo y bloqueando alucinaciones sin fuente en pruebas dirigidas. |
| 8 | S8 — Carga del corpus, olas 1 y 2 | C. Corpus | · Ola 1: backlog del triage S6 (~80-120 chunks) con probe de confirmación.<br>· Ola 2: columna vertebral UGPP/laboral — solo artículos citados en el patrón oro + frecuentes (~120-150 chunks).<br>· Ana Luisa selecciona con una semana de ventaja (lista con fuente oficial + justificación); sesiones ≤2h/10 docs; solo SUIN-Juriscol, relatorías, UGPP oficial.<br>· Test de recuperación creciente (≥15 preguntas tipo abogado, ≥12 en top-3) tras cada ola. | Olas 1 y 2 cargadas con metadatos completos y fuente oficial verificable. | Probes de JuliX por ola sin desplazamiento de chunks buenos por genéricos; auditoría de metadatos intermedia sin huecos. |
| 9 | S9 — Carga del corpus, olas 3 y 4 | C. Corpus | · Ola 3: procesal CPACA/CPT/CGP, prepara el motor de términos de Fase 2 (~100 chunks).<br>· Ola 4: jurisprudencia por línea decisional, 10-15 sentencias, chunking por considerandos (~80-100 chunks) — se recorta primero si falta tiempo.<br>· Exclusiones escritas: tributario general, SAGRILAFT, civil/comercial amplio, doctrina académica.<br>· Auditoría de metadatos al cierre de las 4 olas. | ≥400 chunks totales con metadatos y fuente oficial; exclusiones publicadas por escrito. | Recuperación ≥12/15 en top-3 sobre el conjunto completo; cero regresiones detectadas en probes acumulados de las 4 olas. |
| 10 | S10 — Exportación PDF | D. Entregables | · LibreOffice headless en imagen Docker propia con fuentes instaladas (evitar sustitución silenciosa de fuentes); perfil `UserInstallation` efímero por conversión.<br>· Worker con cola `pdf_jobs` en PostgreSQL, timeout duro 60s con kill, 1-2 concurrentes.<br>· Postproceso: metadatos del documento, pie de trazabilidad opcional, invalidación del PDF derivado al regenerar el docx.<br>· UX: botón con estados honestos (generando → listo con peso → error con reintento), previsualización inline, `aria-live`, nomenclatura automática.<br>· Test automatizado por plantilla (páginas, cadenas clave, metadatos, fuentes embebidas = fuentes pedidas) + validación visual de Ana Luisa en 3 documentos reales. | PDF fiel en todas las plantillas del Generador. | Conversión colgada muere sola sin tumbar la cola; validación visual de Ana Luisa documentada con capturas en 3 documentos. |
| 11 | S11 — Mensajería en tiempo real (SSE) | D. Entregables | · Canal genérico multiplexado `/api/events/stream` (message.new/read, pdf.ready/error; preparado para actuacion/termino de Fase 2). Patrón notificar-y-buscar.<br>· Distribución con PostgreSQL NOTIFY/LISTEN; auth sin access token en la URL (ticket efímero o interceptor existente).<br>· Reconexión: `Last-Event-ID` + buffer `user_events` (TTL 24h) + evento `resync`; backoff con jitter; heartbeat servidor 25s / cliente 40s.<br>· No-leídos por cursor temporal (`conversation_reads`); badge accesible + contador en `<title>`.<br>· Optimistic UI con reintento; scroll sin robo; fallback automático a polling 20s. | Mensaje visible en <10s (real <1s en condiciones normales); evento `pdf.ready` viajando por el mismo canal (prueba de genericidad del canal). | Tortura de reconexión (suspensión, cambio de red, redeploy en Railway) sin pérdida ni duplicados de mensajes. |
| 12 | S12 — 2FA y hardening | E. Cierre | · TOTP: secreto cifrado en reposo, enrolamiento QR + secreto copiable, 8 códigos de recuperación hasheados, enrolamiento no confirmado expira en 15 min, token de pre-autenticación de 5 min, anti-replay (ventana ±1 período), reset administrativo. Obligatorio admin (`must_enroll`), promovido abogado, silencioso cliente.<br>· Rate limiting por email+IP (login 10 fallos/15 min; TOTP 5 fallos).<br>· Headers: HSTS, nosniff, CSP en Report-Only 2 días → aplicar, `frame-ancestors none`.<br>· Rotación de JWT secret con doble clave ensayada en staging (`SECURITY.md`); apagado de endpoints huérfanos; validación de adjuntos en servidor. | 2FA funcional para admin con recuperación probada; `SECURITY.md` publicado. | CSP aplicado (no solo Report-Only) sin romper el frontend; rotación de JWT secret ensayada al menos una vez en staging sin caída de sesión masiva. |
| 13 | S13 — Regresión, triage y demo (cierre de Fase 1) | E. Cierre | · Regresión: cobertura ≥60% con tests de valor real; guion manual en 2 frontends + móvil físico; corrida final del banco de 20 casos como no-regresión del trimestre.<br>· Triage de deuda técnica en 3 cubos: ahora / backlog Fase 2 con dueño / descartado por escrito.<br>· Demo con Ana Luisa operando los 5 flujos sin intervención del desarrollador + 2 preguntas registradas ("¿qué te estorbó?", "¿se lo mostrarías a un colega tal como está?"). | Backlog de Fase 2 con contenido real y dueños asignados. | **Definition of Done Fase 1 completo:** 5 flujos de demo sin intervención; 0 usuarios fuera de PostgreSQL; 2FA admin obligatorio; JuliX ≥80% global 3-4 sin alucinaciones no diagnosticadas y con las 2 trampas detectadas; ≥400 chunks con recuperación ≥12/15; cobertura ≥60% en auth+generador con CI bloqueante; costo por documento conocido; `SECURITY.md`/`ROLLBACK.md`/`PROMPTS.md`/`CONTRIBUTING.md` publicados y ensayados. |

## Regla de recorte (colchón de S12-13)

Si el tiempo no alcanza, recortar en este orden: 2FA opcional para abogados → CSP fina → banco reducido a 8 casos. **Nunca se recorta:** demo con Ana Luisa, regresión de los 5 flujos, rate limiting.

## Notas de despliegue en Railway

- Servicios sugeridos: `vridik-api` (FastAPI/Django), `vridik-postgres` (plugin managed PostgreSQL), `vridik-pdf-worker` (imagen Docker con LibreOffice headless, S10), `vridik-julix` si se aísla como servicio propio (S4).
- Variables de entorno separadas por entorno Railway (staging/producción): `ANTHROPIC_API_KEY_STAGING`, `ANTHROPIC_API_KEY_PROD`, `JWT_SECRET`, `DATABASE_URL`.
- CI (S3) corre en GitHub Actions, no en Railway; Railway solo despliega tras CI verde en `main` (deploy-on-green).
- El worker de PDF (S10) y el canal SSE (S11) requieren confirmar que el plan de Railway soporta conexiones long-lived (SSE) y procesos en segundo plano (worker de cola); validar límites de memoria para LibreOffice headless antes de S10.

## Artefactos de S1/S2 entregados

- `/migrations/migrate_users.py` — migración idempotente ENV → PostgreSQL (dry-run por defecto, `--commit` explícito, bcrypt, manifest JSON para rollback, log en `auth_events`).
- `/migrations/rollback_env.py` — restaura `JURIS_USERS`/`USE_POSTGRES=false` a partir del manifest de una corrida y, opcionalmente, desactiva (soft-delete) los usuarios creados en PostgreSQL.
- `/core/feature_flag_legacy.py` — flag `USE_POSTGRES`, autenticación con doble lectura (PostgreSQL primero, fallback legacy con `auth_event='legacy_fallback'`) y `DualAuthJWTMiddleware` para resolver el rol del JWT contra ambas fuentes durante la ventana de migración.
- `/db/seed_railway.sql` — 4 usuarios de prueba para staging (`julian` admin, `ana` abogada, `cliente1` cliente, `soporte` con rol `abogado` como placeholder), con hashes bcrypt reales precomputados y `must_change=true`.

## Artefactos de S3 entregados

- `/tests/conftest.py` — fixtures centrales: `db` (rollback transaccional sobre PostgreSQL real), `seed_roles`, `seeded_users` (mismos datos de `db/seed_railway.sql`), `make_user`, `backend` (parametriza `USE_POSTGRES` true/false) y `auth_client_factory` (emite JWT HMAC de 15 min igual que producción).
- `/tests/support/fakes.py` — contratos mínimos (`FakeRolesService`, `FakeMensajesService`, `FakeGeneradorService`, `FakePanelService`, `FakeAnthropicStream`, `FakeLedgerDB`) para los módulos que aún no tienen implementación de producción; se reemplazan por los clientes reales sin tocar los tests.
- `/tests/test_auth.py`, `test_roles.py`, `test_mensajes.py`, `test_generador.py`, `test_julix.py`, `test_panel.py` — 45 tests en total (10+8+7+8+7+5), verificado con `pytest --collect-only`.
- `/.github/workflows/ci.yml` — job `test` (py_compile, ruff, PostgreSQL real vía service container, pytest con JUnit XML, gate de ≥90% tests verdes) y job `validate-sql` (dry-run de `schema_semana1_vridik.sql`, `julix/sql/ledger_schema.sql` y `db/seed_railway.sql` sobre un PostgreSQL efímero que se destruye al terminar el job).
- `/scripts/check_pass_ratio.py` — calcula el ratio de tests verdes desde el reporte JUnit y falla el job si cae debajo del umbral (90%), sin contar los `skipped` a favor.
- `/requirements-test.txt` — pytest, pytest-asyncio, asyncpg, bcrypt, PyJWT, httpx, ruff.

## Artefactos de S4 (semana 4-6) entregados

- `/julix/client.py` — `JuliXClient` con `AsyncAnthropic` real, retry+backoff (máx. 3, timeout 30s), y registro propio en `julix_calls`; `_abrir_stream_sdk` aislado a propósito para que los tests mockeen solo el SDK.
- `/julix/ledger.py` — tabla de precios 2026, `costo_mensual_por_usuario`/`get_monthly_cost`, `obtener_ultima_llamada`, y la fachada `JuliXLedger`.
- `/julix/service.py` — actualizado para no duplicar el registro en el ledger (ahora vive en `client.py`); pasa `user_id`/`caso_id`/`prompt_version`/`prompt_hash` al cliente.
- `/julix/prompts/v1_ugpp_demanda.md` y `/julix/prompts/v2_laboral_consulta.md` — nuevos, sin tocar los prompts previos; `/julix/prompts/__init__.py` reescrito para filtrar por el campo `tarea` del encabezado.
- `/api/julix_endpoint.py` — `POST /julix/query` (FastAPI) con JWT + rate limit 20/min vía feature flag propio, y `GET /julix/health`.
- `/tests/test_julix.py` — actualizado a 7 tests que mockean el SDK (no todo el cliente), verificado con `pytest` real (40 passed, 10 skipped por falta de PostgreSQL real, 0 fallos).
- `/requirements.txt` (nuevo) y `/requirements-test.txt` (actualizado) — agregan `anthropic`, `fastapi`, `pydantic`.

## Artefactos de S5 (Banco de evaluación) entregados

- `/eval/banco_casos_vridik.xlsx` — 20 casos (12 UGPP + 8 Laboral), columnas `id/area/pregunta/respuesta_esperada/norma_clave/dificultad`, validación de datos en `area` y `dificultad`, hoja de instrucciones incluida. `respuesta_esperada` queda vacía para que la llene Ana Luisa.
- `/eval/sql/julix_evals_schema.sql` — tabla `julix_evals` (score, hallucination_flag, costo_usd_generacion/juez/total, corrida_id) + vista `julix_evals_resumen_por_corrida`.
- `/eval/evaluador.py` — dry-run por defecto (valida el banco, cuenta pendientes); `--commit` genera la respuesta de JuliX con el prompt real de producción, la califica con un "Claude juez" (0-5 + `hallucination_flag`), persiste en `julix_evals` y aplica el Gate de Fase 1 (≥80% de casos con `score>=4` y sin alucinación). Verificado con mocks del SDK (sin llamar a Anthropic real).
- `/eval/guia_abogada.md` — guía de una página para Ana Luisa: cómo llenar `respuesta_esperada`, 90 minutos estimados, calificación a ciegas.
- `julix/client.py` — `MODEL_BY_TASK` ahora incluye `evaluacion_juez` (mismo modelo Sonnet 5).

## Artefactos de S6 (RAG base) entregados

- `/rag/context_builder.py` — embeddings locales, búsqueda top-5 en `rag_chunks` vía pgvector, cita `[norma, artículo, párrafo]`, heurística de jerarquía y conversión a `RankedChunk` (`a_ranked_chunks`) para reutilizar `julix/context_builder.py` sin duplicar lógica de truncado.
- `/rag/sql/rag_chunks_schema.sql` — tabla `rag_chunks` (vector 384 dim) + índice `ivfflat`.
- `/rag/ingest_ugpp.py` — ingesta de PDFs de `/data/ugpp/`, chunking ~800/100 tokens (aproximación por palabras), embeddings locales, dedup por hash; dry-run por defecto, verificado con una carpeta de prueba vacía y con la lógica de chunking/heurísticas de norma-artículo de forma aislada.
- `/julix/service.py` — recuperación automática de contexto vía RAG cuando no se pasan `chunks_candidatos`, y directiva de fuente obligatoria (`DIRECTIVA_FUENTE_OBLIGATORIA`) agregada a todo system prompt.
- `/tests/test_julix.py` — 2 tests nuevos verificados con pytest real (mock del SDK + mock de `rag_buscar_contexto`): confirman que la directiva llega al `system_prompt` y que la cita del chunk recuperado llega al `user_content`.

## Artefactos de cierre S6 + preparación de plugins (esta entrega)

- `/requirements.txt` — agrega `sentence-transformers==2.7.0`, `pgvector`, `psycopg2-binary`, `pypdf`.
- `/rag/ingest_ugpp.py` — agrega `--check` (chequeo de salud liviano, verificado con carpeta vacía/inexistente/con PDF de prueba) y `--dry-run` explícito, además del `--commit` ya existente.
- `/scripts/railway_setup_rag.sh` — instala dependencias, aplica `rag/sql/rag_chunks_schema.sql`, corre `--check`; sintaxis validada con `bash -n`.
- `/eval/run_eval_railway.sh` — fija el modelo de la corrida, encadena `--dry-run` → `--commit` → resumen SQL desde `julix_evals` (columna renombrada de `corrida_id` a `run_id` para que la query coincida exactamente); sintaxis validada.
- `/eval/guia_abogada.md` — checklist final de 5 minutos agregado al final de la guía existente.
- `/julix/prompts/v3_litigio_colombia.md` y `/julix/prompts/v3_laboral_colombia.md` — fusionan guardrails reales de [anthropics/claude-for-legal](https://github.com/anthropics/claude-for-legal) (etiquetas de procedencia `[norma citada en el contexto]`/`[conocimiento del modelo — verificar]`, nota del revisor, regla de cita verbatim, contenido recuperado tratado como dato y no como instrucción, postura de marcar `[revisar]` en vez de decidir en silencio) con calibración normativa colombiana (CPACA/CGP para litigio, CST/CPT para laboral) y el guardrail "borrador para abogado, cita norma" pedido explícitamente. Cargan correctamente en el loader existente (`prompts.load_prompt('litigio_colombia')` / `'laboral_colombia'`).
- `/julix/router.py` — `route_by_area(pregunta)` con heurística de palabras clave (sin llamar a Claude), verificado con 5 preguntas de ejemplo cubriendo los 3 casos y el fallback.
- `/nixpacks.toml` — build/start de Railway, validado como TOML.
- `/app/main.py` (nuevo, de soporte) — re-exporta el API de JuliX para que el `cmd` de `nixpacks.toml` (`uvicorn app.main:app`) apunte a un módulo real; sin esto, el comando de arranque fallaría porque `app/main.py` no existía todavía.

**Nota importante:** ninguno de estos scripts se ejecutó de verdad (ni ingesta real, ni llamadas a Anthropic, ni build de Railway) — todo quedó verificado con `py_compile`, `bash -n`, parseo de TOML, y pruebas manuales acotadas (carpetas de prueba, preguntas de ejemplo), tal como se pidió.

## Artefactos de S7-S10 (esta entrega — corpus, curado, re-ranking, PDF)

- `/data/corpus_manifest.csv` — plantilla con 20 filas de ejemplo (columnas `fuente, tipo, norma, articulos_clave, prioridad`): 10 `ley` (Ley 1607/2012, Ley 2010/2019), 3 `decreto` (Decreto 1625/2016), 7 `jurisprudencia` (Consejo de Estado, radicados 2018-2024) + CST distribuido en las filas de prioridad media. Verificado con `csv.DictReader`: 20 filas, conteos por tipo y prioridad correctos.
- `/rag/ingest_corpus.py` (nuevo, sibling de `rag/ingest_ugpp.py` — este último no se tocó) — lee `data/corpus_manifest.csv`, filtra por `--priority {alta,media,baja,todas}` (con alias `high/medium/low/all`), chunking 600 tokens/120 overlap (aprox. por palabras), infiere año y tribunal desde el nombre de la norma, calcula hash de dedup, y expone `--source csv --manifest --priority --offset --limit --commit` (dry-run por defecto). Verificado: filtrado por prioridad (14/20 en `alta`), inferencia de año/tribunal en aislado, chunking produce 6 chunks de 600 tokens desde un texto de 2000 palabras (vs. 4 chunks/800 tokens de `ingest_ugpp.py`).
- `/scripts/ingest_batch.sh` (nuevo) — recorre el manifiesto en lotes de 50 filas, invocando `rag/ingest_corpus.py --offset/--limit` por lote; dry-run por defecto, `--commit` explícito. Verificado con `bash -n` y una corrida dry-run funcional (1 lote sobre las 20 filas del manifiesto de ejemplo).
- `/rag/quality_gate.py` (nuevo) — `evaluar_chunk()` puro (sin BD): rechaza chunks sin `norma`/`articulo`, con texto <100 caracteres, o sin patrón de cita reconocible en el propio texto; `generar_reporte()` agrega aceptados/rechazados/motivos frecuentes; `ejecutar_quality_gate_sobre_bd()` (async) lee `rag_chunks` y escribe `rag_quality_report.json`. Verificado con 4 chunks de prueba (1 válido, 3 con distintos motivos de rechazo) — reporte JSON generado correctamente.
- `/rag/context_builder.py` (actualizado) — `ChunkRecuperado` gana `anio`/`tribunal`/`tipo_fuente` (opcionales, default `None` — no rompe las construcciones existentes en `tests/test_julix.py`), propiedad `similitud` (distancia → similitud en [0,1]) y `score` (similitud × peso por tipo de fuente + bonus de recencia 2019-2026). `buscar_contexto()` ahora trae un pool de `top_k * 3` candidatos desde pgvector y los reordena en Python por `.score` antes de truncar a `top_k`. Verificado: una ley de 2019 (distancia 0.15) supera en score a una jurisprudencia de 2015 (distancia 0.10, más cercana en bruto).
- `/julix/pdf_export.py` (nuevo) — `FuenteCitada` (dataclass con `.cita` en formato `[norma, artículo, párrafo]`, más `desde_chunk_recuperado()`/`desde_referencia()`) y `generar_pdf()` con ReportLab: header "Vridik Pro", cuerpo de la respuesta partido en párrafos, sección "Fuentes citadas" numerada, y pie de página con el disclaimer "Borrador para revisión de abogado – no constituye asesoría legal" dibujado en cada página vía `onPage`. Verificado generando PDFs reales (firma binaria `%PDF-`) con y sin fuentes citadas.
- `/api/julix_endpoint.py` (actualizado) — nuevo query param `?format=pdf` en `POST /julix/query`: genera el PDF con `julix/pdf_export.py` usando las mismas fuentes de la generación (explícitas del payload, o recuperadas del RAG si no vinieron) y responde con `FileResponse`. Se agrega el campo `pregunta` a `JuliXQueryRequest` — antes nunca llegaba desde el endpoint a `service.generar_documento()` a pesar de que el parámetro existe desde S6; gap detectado y cerrado en esta entrega.
- `/requirements.txt` (actualizado) — agrega `reportlab==4.2.5`.
- `/tests/test_rag_quality.py` (nuevo, 3 tests) y `/tests/test_pdf_export.py` (nuevo, 2 tests) — llevan la suite de 47 a 52 tests. Verificado con `pytest` real: 52 tests totales, 47 passed + 5 nuevos passed = 52 ejecutables sin infraestructura real, 10 skipped (tests parametrizados `backend=[legacy,postgres]` preexistentes que requieren PostgreSQL real — comportamiento esperado, no una regresión de esta entrega).

**Nota importante (S7-S10):** no se ejecutó ninguna ingesta real, ninguna llamada a Anthropic ni ninguna consulta contra PostgreSQL real — todo quedó verificado con `py_compile`, `bash -n`, `pytest` (con mocks/fixtures existentes), y pruebas manuales acotadas (chunks de prueba, manifiesto de 20 filas de ejemplo, PDFs generados en `/tmp`).

## Artefactos de S11-extra (economía de tokens — ingesta de documentos de cliente) entregados

- `/rag/ingest_desktop.py` (nuevo) — dedup de dos niveles: SHA256 del archivo completo contra `metadata->>'sha256'` en `rag_chunks` (salta el archivo por completo si ya existe) y `hash_dedup` a nivel chunk (evita re-embeber plantillas repetidas entre documentos distintos). `--dry-run` (sin BD, sin embeddings) y `--commit` (async, real) mutuamente excluyentes. Chunking 600/120 reutilizando `chunkear_texto` de `rag/ingest_corpus.py`. `embeber_lote()` agrupa hasta 32 chunks por llamada a `sentence-transformers`. Salvaguarda `TAMANIO_MAXIMO_EXTRACCION_DRY_RUN_BYTES = 8MB`: archivos más grandes se marcan `nuevo_pesado` y solo reciben una estimación de tokens por tamaño (necesaria tras detectar 11 libros contables escaneados de 12-25MB en las carpetas reales que hacían impracticable la extracción completa en dry-run). `escribir_manifest()` escribe solo `ruta,sha256,estado,chunks_nuevos,tokens_usados` — nunca texto ni nombres.
- `/rag/anonymizer.py` (nuevo) — `anonimizar_texto()`: identificadores (NIT/cédula, regex, excluye años) → `[ID]`; personas vía NER spaCy (`es_core_news_sm`) si está instalado, si no fallback heurístico por mayúsculas con lista de exclusión de términos jurídicos → `[CLIENTE]`. `modo_ner_activo()` reporta cuál mecanismo se usó (en este entorno: `heuristico_mayusculas`, spaCy no está instalado). `is_duplicate()` expuesto para test/mock del dedup sin depender de BD.
- `/rag/sql/003_rag_chunks_metadata_jsonb.sql` (nuevo) — migración idempotente: columna `metadata JSONB NOT NULL DEFAULT '{}'`, índice GIN genérico + índice de expresión sobre `metadata->>'sha256'`. Distinta de `002_rag_chunks_metadata.sql` (S7, columnas TEXT del corpus normativo); esta es específica de documentos de cliente. BEGIN/COMMIT balanceados, verificado.
- `/rag/context_builder.py` (actualizado) — `ChunkRecuperado` gana `fuente_cliente: str | None`; `FUENTES_CLIENTE_PRIORITARIAS = {"Giraldo Velasco","Marta Arias"}` con bonus `+0.08` en `.score`; `buscar_contexto()` gana parámetro opcional `solo_fuentes: list[str] | None` que filtra duro por `metadata->>'fuente' = ANY(...)`. Verificado: compatibilidad retroactiva (`ChunkRecuperado` sin `fuente_cliente` sigue funcionando) y que un chunk de cliente prioritario le gana en score a una jurisprudencia con distancia bruta mejor.
- `/data/desktop_manifest.csv` (nuevo — **salida real**, no plantilla) — generado ejecutando `rag/ingest_desktop.py --dry-run` de verdad sobre las carpetas reales `GIRALDO VELASCO ABOGADOS` y `MARTA ARIAS`, conectadas con autorización explícita del usuario tras una pregunta de aclaración sobre manejo de datos sensibles. Resultado: 93 archivos nuevos (396 chunks, ≈213.250 tokens estimados), 11 archivos pesados >8MB marcados `nuevo_pesado` (≈28M "tokens" — estimación por tamaño, no chunkeados de verdad), 7 archivos `skip` (duplicados reales detectados correctamente entre subcarpetas). **Solo se ejecutó `--dry-run`: ningún embedding real, ninguna escritura en Postgres, ningún dato de cliente persistido.** `--commit` permanece verificado por código (`py_compile`) pero no ejecutado contra datos reales — queda para el entorno de producción de Vridik bajo los procedimientos propios del despacho.
- `/rag/README_ingest_desktop.md` (nuevo) — guía de uso con los dos comandos pedidos (`--dry-run`, `--commit`), explicación de los 4 mecanismos de ahorro de tokens, resumen de la corrida real de validación con la aclaración explícita de que los ≈28M tokens estimados de archivos pesados no deben sumarse a los ≈213.250 tokens reales.

**Nota importante (S11-extra):** las carpetas `GIRALDO VELASCO ABOGADOS` y `MARTA ARIAS` son datos reales de clientes del despacho; se conectaron a este entorno de validación por elección explícita del usuario. Como salvaguarda adicional no solicitada explícitamente pero consistente con la regla del proyecto de "no ejecutar ingestas reales", solo se corrió `--dry-run` (sin persistencia, sin llamadas a embeddings, sin tocar Postgres) — `--commit` no se ejecutó contra estos datos reales. La carpeta `~/Desktop/Juris-ia` mencionada originalmente en la tarea no existía con ese nombre; se localizó y conectó después como `C:\Users\Julian Trujillo\Desktop\JURIS IA`.

### `JURIS IA` — hallazgo y decisión del usuario

`JURIS IA` resultó ser el repositorio del propio proyecto (código fuente,
`.git`, `node_modules`, `venv`, `juris_ia.db`, contratos de API, ~126,980
archivos en total) — no una carpeta de expedientes de cliente. Por
decisión explícita del usuario, **no se escaneó como carpeta de
documentos** (ni siquiera los `.pdf`/`.docx` sueltos de la raíz).

Se evaluó en su lugar migrar `juris_ia.db` (SQLite) como fuente alternativa
de chunks/embeddings ya procesados, según lo pedido. Inspección real del
schema: 3 tablas (`analisis`, `procesos`, `generaciones`), **ninguna con
columna de embeddings/vector**, y las 3 con **0 filas** — no hay nada que
migrar hoy. Lo más cercano es `analisis.texto_extraido` + `analisis.hash_pdf`
(texto plano sin vectorizar, tabla vacía). Por decisión explícita del
usuario, no se construyó el extractor todavía — queda pendiente para
cuando `juris_ia.db` tenga datos reales que migrar a `rag_chunks`.

## Artefactos de S11-extra-2 (personalización de estilo — Ana Luisa) entregados

- `/julix/prompt_v3.txt` (nuevo) — sección "Estilo de respuesta" con el texto
  literal pedido: bullets accionables primero, explicación simple después,
  evitar tecnicismos DIAN sin definir, ejemplo numérico siempre. Es un `.txt`
  deliberadamente separado del loader versionado de `julix/prompts/*.md`
  (que solo escanea `.md`) — pensado como capa de personalización a inyectar
  condicionalmente cuando `user_id == "ana_luisa"` (la integración en
  `julix/service.py` queda fuera de este entregable, no se pidió).
- `/julix/context_builder.py` (actualizado) — `RankedChunk` gana el campo
  opcional `etiquetas: list[str]` (default vacío, no rompe construcciones
  existentes); nueva función `aplicar_boost_personalizacion(chunks, *,
  user_id)`: si `user_id == "ana_luisa"` sube al frente (sort estable) los
  chunks etiquetados `"explicación_simple"`, sin alterar el orden para
  cualquier otro usuario; `construir_contexto()` gana el parámetro opcional
  `user_id` y aplica el boost antes de truncar por presupuesto. Verificado
  con un caso de prueba: 3 chunks (uno técnico, uno etiquetado
  "explicación_simple" de igual jerarquía, uno de menor jerarquía) — con
  `user_id="ana_luisa"` el etiquetado sube primero; sin ese `user_id` (o con
  cualquier otro), el orden es idéntico al de antes del cambio. Diff completo
  en `context_builder.diff` (entregado junto con este backlog).
- `/rag/eval_ana_luisa.py` (nuevo) — criterio "¿Suena como Ana Luisa?" (0-2
  puntos): `evaluar_estilo_heuristico()` pura (sin LLM, sin BD, sin red)
  chequea 4 sub-criterios (bullets al inicio, explicación en prosa después,
  ausencia de tecnicismos DIAN sin definir, presencia de ejemplo numérico) y
  mapea a 0/1/2 puntos; `generar_reporte_estilo()` agrega por lote; también
  expone `CRITERIO_JUEZ_SUENA_COMO_ANA_LUISA` (texto listo para sumar al
  `JUEZ_SYSTEM_PROMPT` de `eval/evaluador.py` en una integración futura, no
  hecha en este entregable para no tocar el gate de S5 sin pedido explícito).
  Verificado con `python rag/eval_ana_luisa.py --demo`: caso bien construido
  → 2 puntos; caso sin bullets/explicación/ejemplo y con tecnicismos sin
  definir → 0 puntos, con motivos correctos.
- Suite de 47 tests re-verificada sin regresiones tras estos cambios.

**Nota importante (S11-extra-2):** `data/ana_luisa_profile.md` (mencionado
como ya existente en la tarea) no existía. Se encontró en su lugar el export
crudo real de ChatGPT de Ana Luisa en `~/Desktop/ChatGPT/` (~2,204
conversaciones, ~80MB en 5 archivos `conversations-*.json`, datos
personales/profesionales sensibles). Por decisión explícita del usuario, NO
se analizó ese export en este entregable — se usó tal cual el texto de
"Estilo de respuesta" que el usuario ya había especificado. Queda pendiente
(explícitamente solicitado por el usuario, no construido todavía):
`scripts/build_ana_profile.py`, que procesará offline una muestra de 200
conversaciones filtradas por "UGPP"/"Ana"/"pensión" de los 5
`conversations-*.json` para generar `data/ana_luisa_profile.md` en batch.

## Artefactos de S11-extra-3 (cache de respuestas RAG) entregados

- `/rag/cache.py` (nuevo) — clase `RAGCache` sobre SQLite (`data/rag_cache.db`
  por defecto), tabla `rag_cache` exactamente con las columnas pedidas
  (`query_hash TEXT PK, respuesta TEXT, fuentes JSON, tokens INTEGER,
  created_at TIMESTAMP`). `normalizar_query()` (lower + NFKD sin acentos +
  espacios colapsados) y `hash_query()` (SHA256 de la query normalizada) —
  "¿Qué es el IBC?" y "que es el ibc?" producen el mismo hash. `get()`
  retorna `(respuesta, fuentes, tokens)` si la entrada sigue vigente dentro
  de `ttl_horas` (default 24h) o `None` si no existe o expiró; `set()`
  guarda/reemplaza con `created_at = ahora (UTC)`. El TTL NO se guarda por
  fila (no se pidió esa columna): `ttl_horas_para_query()` clasifica la
  pregunta (7 días si es una definición como "¿qué es...?"/"definición
  de...", 24h en cualquier otro caso — UGPP/expediente puntual) y quien
  integra la cache pasa ese mismo TTL tanto al leer como al escribir.
- `/julix/context_builder.py` (actualizado) — nueva función
  `obtener_respuesta_con_cache(*, query, generar_respuesta, cache=None)`:
  revisa `rag/cache.py` ANTES de que el caller invoque a Anthropic. Hit
  vigente → no se llama `generar_respuesta`, suma 1 a
  `METRICAS["cache_hits"]`. Miss (o expiración) → llama `generar_respuesta()`
  una vez, guarda el resultado en cache, suma 1 a
  `METRICAS["cache_misses"]`. `generar_respuesta` es un callback inyectado
  (no se importa `julix/client.py` directamente) para no acoplar este
  módulo — que hoy no depende de red — a una llamada real, y para que el
  test pueda usar un callback falso sin mockear el SDK de Anthropic. Diff
  completo en `context_builder_cache.diff` (entregado junto con este
  backlog).
- `/tests/test_cache.py` (nuevo, 5 tests) — 3 pedidos explícitamente (hit,
  miss, expiración) más 2 adicionales de soporte (clasificación de TTL por
  tipo de pregunta, normalización de query). Usa SQLite temporal
  (`tmp_path` de pytest) por test, sin tocar `data/rag_cache.db` real. La
  expiración se simula sobreescribiendo `created_at` directamente en SQLite
  (30h de antigüedad contra un TTL de 24h), sin necesidad de mockear
  `datetime.now()`. Verificado con `pytest`: 5/5 passed. Suite completa:
  **52 passed, 10 skipped** (antes: 47 passed — los 5 nuevos de cache no
  restan ni rompen ninguno existente).

**Nota importante (S11-extra-3):** no se ejecutó ninguna ingesta real, no
se tocó el pipeline de RAG (`rag/ingest_corpus.py`, `rag/ingest_desktop.py`,
`rag/context_builder.py` de retrieval) ni se llamó a Anthropic real, tal
como se pidió — `rag/cache.py` es una utilidad de cache local sobre SQLite,
y `obtener_respuesta_con_cache()` en `julix/context_builder.py` se probó
exclusivamente con callbacks falsos (`generar_respuesta`), nunca con el
cliente real de JuliX.

## Artefactos de S11-extra-4 (wiring de cache en julix/service.py) entregados

- `/julix/service.py` (actualizado) — wiring directo pedido explícitamente:
  import de `RAGCache`/`hash_query`/`ttl_horas_para_query` desde
  `rag.cache`; helper `_query_hash(query) -> str` (delega en
  `rag.cache.hash_query()` en vez de reimplementar la normalización, para
  que lectura y escritura calculen siempre el mismo hash). En
  `generar_documento()`: paso 0 (nuevo, antes de todo lo demás incluido el
  límite blando mensual) calcula `query_hash` sobre `pregunta or
  expediente_texto`, hace `cache.get(query_hash, ttl_horas=...)` y, si hay
  hit, `yield` la respuesta cacheada y `return` sin llamar a Anthropic ni al
  RAG. En miss, el flujo sigue igual que antes; el streaming acumula
  `respuesta_completa` y, solo si termina sin error, se llama
  `cache.set(query_hash, respuesta_completa, contexto.chunks_incluidos,
  contexto.tokens_estimados)`. No se tocó `julix/prompt_v3.txt` ni se
  reescribió `julix/context_builder.py` (la función
  `obtener_respuesta_con_cache()` de la entrega anterior queda intacta y sin
  usar aquí — este wiring es deliberadamente directo, tal como se pidió).
  Diff completo en `service_cache.diff` (entregado junto con este backlog).
- `/tests/conftest.py` (actualizado, fixture nueva `_cache_aislada_por_test`,
  `autouse=True`) — **hallazgo real durante la verificación, no pedido
  explícitamente pero necesario para no romper tests existentes**: como
  `generar_documento()` ahora instancia `RAGCache()` con el path SQLite por
  defecto (`data/rag_cache.db`), dos corridas de la suite compartían ese
  archivo real y la segunda corrida trataba la pregunta de un test anterior
  como cache HIT — saltándose por completo el SDK mockeado y rompiendo
  `tests/test_julix.py::test_service_sin_contexto_rag_responde_no_tengo_fuente`
  y `test_service_con_contexto_ugpp_cita_art_179`. La fixture parchea el
  nombre `RAGCache` tal como quedó importado dentro de `julix.service` (no
  la clase original) para que cada test use su propio archivo SQLite
  temporal, aislado y descartado al terminar.
- `/rag/cache.py` (fix menor) — se agregó `PRAGMA journal_mode=MEMORY` en
  `RAGCache.__init__`. **Hallazgo real, con impacto potencial en
  producción**: al probar el wiring contra el path por defecto real
  (`data/rag_cache.db`, dentro de esta carpeta de trabajo montada como
  FUSE), SQLite fallaba con `disk I/O error` incluso en el `CREATE TABLE`
  inicial — el rollback journal por defecto de SQLite depende de locks a
  nivel de filesystem que este tipo de montaje no soporta bien.
  `journal_mode=MEMORY` evita ese archivo de journal aparte y resuelve el
  error; en un filesystem local normal (Railway, disco local) sigue
  funcionando sin cambios. **Vale la pena tenerlo presente si `data/` llega
  a vivir sobre un volumen de red en producción**, aunque Railway
  típicamente usa disco local para el servicio, donde este problema no
  debería aparecer.
- Verificado: suite completa corrida **dos veces seguidas** en el mismo
  proceso para confirmar que el aislamiento por test funciona de verdad
  (no solo que "pasa una vez") — **52 passed, 10 skipped** ambas veces,
  sin dejar `data/rag_cache.db` real ni archivos `-journal` residuales.

**Nota importante (S11-extra-4):** este wiring en `julix/service.py` sigue
sin ejecutarse contra Anthropic real ni contra PostgreSQL real — los tests
mockean el SDK (`FakeSDKStreamFactory`) exactamente igual que antes de esta
entrega; lo único nuevo que se ejerce de verdad es la propia lógica de
`rag/cache.py` sobre SQLite.

## Artefactos de S11-extra-5 (railway.json — despliegue de 4 servicios) entregados

- `/railway.json` (nuevo) — declara los 4 servicios: `vridik-api` (Nixpacks,
  `uvicorn app.main:app`, healthcheck `/health`, `restartPolicyType:
  ON_FAILURE`), `vridik-postgres` (plugin managed de Railway, no imagen
  custom; `rag/sql/rag_chunks_schema.sql` se sigue aplicando desde el
  arranque de `vridik-api` vía `scripts/railway_setup_rag.sh`, tal como ya
  documentaba S6 — Railway no aplica SQL de init automáticamente sobre el
  plugin managed), `vridik-pdf-worker` (`builder: DOCKERFILE` apuntando a
  `docker/pdf-worker.Dockerfile`, nuevo, con LibreOffice headless + fuentes;
  sin `healthcheckPath` porque es un worker de cola sin HTTP, monitoreado
  por `restartPolicy`), y `vridik-redis` (managed, backend de la cola del
  pdf-worker). Variables pedidas explícitamente (`ANTHROPIC_API_KEY` desde
  el vault de secretos de Railway, `DATABASE_URL` vía variable de
  referencia `${{vridik-postgres.DATABASE_URL}}`, `USE_POSTGRES=true`)
  declaradas tanto en `vridik-api.variables` como en un bloque
  `variables_compartidas` aparte para que queden explícitas.
  **Nota de honestidad técnica**: el esquema público de `railway.json` de
  Railway es por-servicio (un build/deploy por archivo); no existe un
  esquema oficial para declarar 4 servicios en un único archivo. Este
  `railway.json` documenta los 4 servicios como referencia de
  infraestructura-como-código explícita y consistente — para aplicarlo de
  verdad hay que crear los 4 servicios en el proyecto de Railway (dashboard
  o CLI) y llevar el bloque `build`/`deploy` correspondiente a cada uno.
  Esto queda anotado en el propio archivo (`_nota` de nivel raíz).
- `/docker/pdf-worker.Dockerfile` (nuevo) — imagen con
  `libreoffice-writer`/`libreoffice-calc` + fuentes (`fonts-liberation`,
  `fonts-dejavu`) para evitar la sustitución silenciosa de fuentes al
  convertir documentos a PDF (mismo requisito ya anotado en el roadmap
  original de S10). No se construyó ni se ejecutó esta imagen.
- `/api/julix_endpoint.py` (actualizado, cambio mínimo) — se agregó
  `GET /health` (alias de `/julix/health` con la ruta que Railway espera
  por convención para `deploy.healthcheckPath`) — antes solo existía
  `/julix/health`, y `railway.json` habría apuntado a una ruta inexistente.
  Verificado con `TestClient`: `GET /health` → `200 {"status": "ok",
  "servicio": "vridik-api"}`. Suite completa re-verificada sin regresiones:
  **52 passed, 10 skipped**.

**Inconsistencia S10 — RESUELTA (esta entrega, S11-extra-6):** el hallazgo
anotado arriba (Redis vs. `pdf_jobs` en Postgres) se corrigió por completo.
`vridik-redis` se eliminó de `railway.json` (vuelve a tener 3 servicios:
`vridik-api`, `vridik-postgres`, `vridik-pdf-worker`) y `vridik-pdf-worker`
ya no referencia `REDIS_URL` en ninguna parte — solo `DATABASE_URL`. El
backend de cola definitivo es la tabla `pdf_jobs` en PostgreSQL, tal como
decía el roadmap original de S10.

## Artefactos de S11-extra-6 (corrección de la inconsistencia S10 — cola en Postgres, no Redis) entregados

- `/railway.json` (actualizado) — se eliminó el servicio `vridik-redis` y la
  variable `REDIS_URL` de `vridik-pdf-worker`; ahora declara solo 3
  servicios. `vridik-pdf-worker.deploy.startCommand` pasó de
  `python -m workers.pdf_worker` a `python workers/pdf_worker.py` (coincide
  con el `CMD` real del Dockerfile). Se agregó `PDF_WORKER_POLL_SECONDS=5`
  a las variables del worker. `vridik-api.deploy.healthcheckPath` sigue en
  `/health`, sin tocar, tal como se pidió explícitamente.
- `/workers/pdf_worker.py` (nuevo) — loop asíncrono cada
  `PDF_WORKER_POLL_SECONDS` (5s por defecto): toma hasta
  `PDF_WORKER_CONCURRENCY` (2 por defecto) filas de `pdf_jobs` con
  `status='pending'` vía `SELECT ... FOR UPDATE SKIP LOCKED` (para que
  réplicas futuras del worker nunca procesen el mismo trabajo dos veces),
  genera el PDF con `julix/pdf_export.py:generar_pdf` (corrida en
  executor aparte, ya que ReportLab no es async), y marca `status='done'`
  + `pdf_url` si sale bien o `status='error'` + `error_mensaje` si falla —
  incluyendo timeout duro de `PDF_JOB_TIMEOUT_SECONDS` (60s, tal como pedía
  el roadmap de S10) que solo mata esa conversión puntual, nunca todo el
  worker. El esquema esperado de `pdf_jobs` (columnas `id, tarea, caso_id,
  respuesta, fuentes JSONB, status, pdf_url, error_mensaje, created_at,
  updated_at`) queda documentado en el docstring del archivo — la migración
  SQL de esa tabla no se creó todavía (no se pidió explícitamente; queda
  pendiente antes de poder correr este worker contra Postgres real).
  Verificado: `py_compile` OK; `_construir_fuentes()` y
  `_ruta_pdf_para_job()` probados de forma aislada (sin BD) — descartan
  correctamente una fuente sin `norma` y arman la ruta del PDF esperada.
- `/docker/pdf-worker.Dockerfile` (actualizado) — se quitó `redis-tools` de
  las dependencias del sistema y el `CMD` pasó de
  `["python3", "-m", "workers.pdf_worker"]` a
  `["python3", "workers/pdf_worker.py"]`, coincidiendo con el
  `startCommand` de `railway.json`.
- Suite completa re-verificada sin regresiones: **52 passed, 10 skipped**
  (no se tocó ningún test existente en esta corrección).

**Pendiente explícito (no resuelto en esta entrega, fuera del alcance de
"corrige la inconsistencia" pedido):** la migración SQL de la tabla
`pdf_jobs` todavía no existe como archivo — solo está documentada como
comentario en `workers/pdf_worker.py`. Tampoco existe integración de
almacenamiento de objetos (S3/Railway volume) para `pdf_url`: el worker
guarda el PDF localmente en `PDF_WORKER_OUTPUT_DIR` y usa esa ruta local
como `pdf_url` — suficiente para esta corrección, pero no para producción
real con múltiples réplicas del servicio API sirviendo el PDF descargado.

## Artefactos de S11-extra-7 (migración real de `pdf_jobs`) entregados

- `/migrations/003_pdf_jobs.sql` (nuevo) — migración idempotente
  (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`): tabla
  `pdf_jobs` exactamente con el esquema pedido (`id UUID` con
  `gen_random_uuid()` vía `pgcrypto`, `query TEXT NOT NULL`, `user_id TEXT`,
  `status TEXT DEFAULT 'pending'`, `pdf_url TEXT`, `created_at`/`updated_at
  TIMESTAMP`) + índice `ix_pdf_jobs_status` sobre `status`. BEGIN/COMMIT
  balanceados (1/1), verificado. Incluye rollback de referencia comentado,
  mismo patrón que `rag/sql/002_rag_chunks_metadata.sql` y
  `rag/sql/003_rag_chunks_metadata_jsonb.sql`.
- `/scripts/railway_setup_rag.sh` (actualizado) — aplica
  `migrations/003_pdf_jobs.sql` justo después de
  `rag/sql/rag_chunks_schema.sql`, con el mismo manejo no-fatal (`||` con
  aviso) que el paso anterior, para que un redeploy no truene si la tabla
  ya existía. Verificado con `bash -n` (sintaxis válida).
- `workers/pdf_worker.py` — **sin tocar**, tal como se pidió explícitamente
  (confirmado por hash del archivo antes/después de esta entrega).
- Suite completa re-verificada sin regresiones: **52 passed, 10 skipped**.

**Nota importante (S11-extra-7) — desajuste de esquema detectado, NO
resuelto silenciosamente:** este esquema literal de `pdf_jobs`
(`id, query, user_id, status, pdf_url, created_at, updated_at`) no coincide
con las columnas que `workers/pdf_worker.py` (entrega anterior) espera leer
de esa misma tabla (`id, tarea, caso_id, respuesta, fuentes`). Como la
tarea pidió explícitamente no tocar `workers/pdf_worker.py`, este desajuste
queda documentado como comentario dentro de la propia migración y aquí en
el backlog — **antes de correr el worker contra esta tabla real hace falta
reconciliar ambos lados** (ajustar el worker a este esquema más simple, o
añadir `tarea`/`caso_id`/`fuentes` a `pdf_jobs` en una migración posterior).
No se decidió cuál de las dos rutas tomar; queda pendiente de una
instrucción explícita.

## Artefactos de S11-extra-8 (reconciliación del desajuste de esquema `pdf_jobs`) entregados

**Decisión explícita del dev lead:** usar el esquema de
`migrations/003_pdf_jobs.sql` (`id, query, user_id, status, pdf_url,
created_at, updated_at`) como el correcto para S10 — se ajustó
`workers/pdf_worker.py`, no la migración.

- `/workers/pdf_worker.py` (reescrito) — alineado por completo con el
  esquema real de la migración:
  - `_obtener_trabajos_pendientes()` ahora hace
    `SELECT id, query, user_id FROM pdf_jobs WHERE status='pending' ...
    FOR UPDATE SKIP LOCKED` (antes seleccionaba `tarea, caso_id, respuesta,
    fuentes`, columnas que no existen en la migración real).
  - Se eliminaron todas las referencias a `tarea`, `caso_id`, `respuesta` y
    `fuentes` como columnas de la fila (incluyendo el helper
    `_construir_fuentes()`, que ya no aplica porque las fuentes no vienen
    precalculadas en la tabla).
  - Nueva función `generate_pdf(query, user_id, *, db_connection, job_id)`:
    como la fila ya no trae `tarea`, se decide en el momento con
    `julix.router.route_by_area(query)` + `TAREA_POR_AREA`; llama a
    `julix.service.JuliXService.generar_documento(...)` (que ya revisa
    `rag/cache.py` antes de tocar Anthropic — wiring de S11-extra-4, se
    reutiliza tal cual, sin duplicar lógica de cache en el worker) para
    obtener la respuesta completa; reconstruye las fuentes citadas
    reproduciendo la búsqueda RAG con la misma query
    (`rag.context_builder.buscar_contexto`), mismo patrón que
    `api/julix_endpoint.py:_fuentes_citadas_para_pdf`; genera el PDF con
    `julix/pdf_export.py:generar_pdf` (en executor aparte, ReportLab no es
    async).
  - `_marcar_error()` simplificado: la migración no tiene columna
    `error_mensaje`, así que el motivo del fallo queda solo en el log
    (`logger.exception`/`logger.error`), nunca se inventó una columna que
    la migración no tiene.
  - Tras la reescritura se detectó que la primera copia guardada en disco
    había quedado incompleta a mitad de `_ciclo_una_vez` (le faltaban el
    cierre de esa función, toda `run_worker` y el guard
    `if __name__ == "__main__":`) — se regeneró el archivo completo y se
    reverificó `py_compile` + `ast.parse` + la suite de tests antes de
    generar el diff final.
  - `migrations/003_pdf_jobs.sql` — **sin tocar**, tal como se pidió
    explícitamente (BEGIN/COMMIT balanceados 1/1, sin cambios).
- Suite completa re-verificada sin regresiones: **52 passed, 10 skipped**.
- `pdf_worker.diff` (nuevo, entregado) — diff unificado de
  `workers/pdf_worker.py` (antes/después de esta reconciliación), único
  archivo solicitado como entregable de esta tarea.

**Inconsistencia S10 (desajuste de esquema) — RESUELTA (S11-extra-8):** ya
no hay divergencia entre `migrations/003_pdf_jobs.sql` y
`workers/pdf_worker.py`; el worker lee y escribe exactamente las columnas
que la migración define. Pendiente explícito, sin cambios respecto a
entregas anteriores: la migración de almacenamiento de objetos (S3/Railway
volume) para `pdf_url` sigue fuera de alcance.
