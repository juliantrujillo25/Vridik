# Vridik

Vridik es el sistema de gestión legal en desarrollo para el despacho, con **JuliX** como asistente de IA para redacción de documentos jurídicos (Sonnet 5, vía Anthropic). Este repositorio es el backend de Fase 1: autenticación, JuliX con RAG legal, evaluación de calidad, exportación a PDF, mensajería en tiempo real y despliegue en Railway.

> Estado del proyecto: ver [`backlog_fase1_vridik.md`](./backlog_fase1_vridik.md) para el detalle sprint por sprint (qué está listo para producción, qué sigue en progreso y qué requiere datos/infraestructura real antes de continuar).

## Qué es JuliX

JuliX es el motor de generación de documentos legales de Vridik: recibe una pregunta o un expediente, recupera contexto normativo real vía RAG (búsqueda semántica sobre leyes, decretos y jurisprudencia colombiana) y genera una respuesta con Claude Sonnet 5, citando únicamente las fuentes recuperadas — nunca completa con normas de memoria. Si el RAG no encuentra contexto suficiente, JuliX responde explícitamente "No tengo fuente suficiente" en vez de inventar una cita.

## Estructura del repositorio

```
api/                  Endpoints HTTP (FastAPI)
  julix_endpoint.py      POST /julix/query, GET /julix/stream (SSE), /health
  admin_users_endpoint.py CRUD de usuarios (solo rol admin)
app/
  main.py                Punto de entrada ASGI (uvicorn app.main:app)
core/                  Lógica de negocio transversal
  feature_flag_legacy.py  Autenticación con doble lectura (ENV legacy -> PostgreSQL)
  admin_users.py           CRUD de usuarios, revocación de sesiones, auditoría
  totp_2fa.py              2FA (TOTP) opcional para roles admin/abogado
julix/                 Motor de JuliX
  client.py               Cliente de Anthropic (retry, timeout, streaming, ledger)
  service.py              Orquestador: contexto RAG + prompt + streaming + cache
  context_builder.py       Presupuesto de tokens y prioridad normativa del prompt final
  ledger.py                Costos por llamada, límite blando mensual
  pdf_export.py            Exportación de respuestas a PDF con citas
  router.py                Heurística de selección de tarea/prompt por área legal
  prompts/                  Prompts versionados por tarea (nunca hardcodeados en código)
rag/                   Recuperación semántica (pgvector)
  context_builder.py       Embeddings + búsqueda + re-ranking por tipo de fuente y recencia
  cache.py                 Cache de respuestas (SQLite) para preguntas repetidas
  ingest_ugpp.py / ingest_corpus.py / ingest_desktop.py  Pipelines de ingesta de corpus
  quality_gate.py           Valida que cada chunk tenga cita reconocible antes de aceptarlo
  anonymizer.py             Anonimización obligatoria antes de embeber documentos de cliente
workers/
  pdf_worker.py             Worker asíncrono: cola `pdf_jobs` en PostgreSQL -> PDF -> object storage
storage/
  object_storage.py         Abstracción de almacenamiento (local por defecto, S3 opcional)
migrations/            Migraciones SQL versionadas (idempotentes)
eval/                  Banco de evaluación de calidad de JuliX (gate de fase)
tests/                 Suite pytest (ver "Tests" más abajo)
```

## Cómo correr las pruebas

```bash
pip install -r requirements-test.txt
pytest -q
```

Ningún test llama a Anthropic ni a PostgreSQL reales por defecto: el SDK de Anthropic se mockea (`tests/support/fakes.py`), y los tests que sí requieren PostgreSQL real (`db` fixture, rollback transaccional) se saltan automáticamente si `TEST_DATABASE_URL` no está configurado.

## Despliegue (Railway)

Ver [`railway.json`](./railway.json): 3 servicios (`vridik-api`, `vridik-postgres` managed, `vridik-pdf-worker`). Variables clave que deben configurarse como secretos reales antes de desplegar:

- `ANTHROPIC_API_KEY` — nunca en texto plano en el repositorio.
- `JWT_SECRET` — nunca vacío en producción (el servicio loguea `CRITICAL` al arrancar si lo está).
- `DATABASE_URL` — se resuelve automáticamente vía referencia al servicio `vridik-postgres`.
- `VRIDIK_ALLOWED_ORIGINS` — orígenes CORS del frontend, separados por comas; vacío por defecto (falla cerrado).

`scripts/railway_setup_rag.sh` aplica las migraciones SQL (`rag/sql/rag_chunks_schema.sql`, `migrations/003_pdf_jobs.sql`, `migrations/004_totp_2fa.sql`) al arrancar el servicio API — de forma idempotente, seguro de correr en cada redeploy.

## Principios de diseño (no negociables)

- **Ningún fallo se presenta como éxito silencioso** — timeouts, errores de formato, respuestas truncadas y contexto insuficiente se comunican explícitamente, nunca se ocultan.
- **JuliX solo cita lo que está en el contexto recuperado** — la directiva de fuente obligatoria se agrega a todo prompt de tarea, sin excepción.
- **Ninguna contraseña o secreto se persiste en claro** — hashes bcrypt para contraseñas, SHA-256 para tokens de refresco y códigos de respaldo de 2FA.
- **Nada se ejecuta contra Anthropic, PostgreSQL o AWS reales sin autorización explícita** — todo el código de este repositorio está verificado con mocks/fakes salvo que el backlog documente lo contrario.
