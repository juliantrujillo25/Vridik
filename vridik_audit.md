# Vridik - Auditoría Fable 5

Fecha: 20-jul-2026. Modo: solo lectura, 0 ejecución de código, 0 llamadas a producción.

**Nota previa obligatoria sobre el contexto que me diste.** El "estado al 05/07/2026" de tu prompt está desactualizado contra la evidencia del repo al 20/07: no hay "0 tests" (hay 51 archivos de test con 428 funciones `test_`), no hay "usuarios en ENV" (users/user_credentials en Postgres), no falta 2FA (TOTP + backup codes + must_enroll en producción), no falta SSE (S11 completo, 4 fases). El stack tampoco es Next.js: el frontend real es **React + Vite + TypeScript** (`frontend/package.json`) sobre backend **FastAPI + asyncpg**; lo de Next.js parece memoria de la era JURIS IA (carpeta legacy separada, con su propio `juris_ia.db` SQLite). Audito contra lo que hay, no contra el contexto declarado. Advertencia estándar: varias afirmaciones del repo sobre operaciones reales en Railway (migraciones aplicadas, DROP TABLE, enrolamiento admin) están documentadas pero no las verifiqué operativamente — solo el código resultante.

## Resumen Ejecutivo (3 bullets que duelen)

- **El corazón del producto no pasa su propio control de calidad.** El GATE de evaluación (≥80% de aprobación) corrió dos veces (15-16 jul) y dio **15% y 35%**. JuliX, la razón por la que alguien pagaría, hoy no cumple el estándar que vos mismo definiste. Todo lo demás — auth impecable, SSE, cobro — es carrocería sobre un motor que todavía no arranca. Y `Instrucciones - CLAUDE.md` sigue diciendo que S5 está "bloqueado esperando datos": estado desactualizado que esconde el problema real.
- **El corpus RAG es 1/5 de lo necesario y es la causa probable del gate fallido.** 85 de 400+ chunks, `corpus_manifest.csv` con ~20 filas, fuerte solo en Laboral/UGPP. El diagnóstico de PROMPTS.md ya lo dice: `norma_clave` guarda la cita pero no el texto del artículo — el modelo no puede citar verbatim lo que no tiene. Esto no se arregla con más prompts (v3 está escrito y sin correr); se arregla con corpus.
- **Cero staging, un solo admin, secretos quemados.** No hay entorno de staging (documentado honestamente en ROLLBACK.md/SECURITY.md), producción tiene 1 cuenta admin, y la password real de Postgres se pegó dos veces en un chat esta misma semana (rotala HOY). Con 1 despacho es incómodo; con 100 despachos es negligencia.

## Semáforo por eje

| # | Eje | Semáforo | Score |
|---|-----|----------|-------|
| 1 | Arquitectura y escalabilidad | 🟡 Amarillo | 60 |
| 2 | Seguridad y compliance Colombia | 🟡 Amarillo | 65 |
| 3 | RAG y JuliX | 🔴 Rojo | 35 |
| 4 | Deuda técnica | 🟢 Verde | 80 |
| 5 | Producto y UX | 🟡 Amarillo | 60 |
| 6 | Roadmap | 🟡 Amarillo | 65 |
| 7 | Riesgo de caída (Radar Judicial) | 🔴 Rojo | 40 |

**Score global: 58/100.** Comprable como equipo/código, no comprable como producto hasta que el eje 3 pase a verde.

### Eje 1 — Arquitectura y escalabilidad 🟡

Lo bueno: multi-tenancy real por `despachos` (backfill idempotente en arranque), **RLS de Postgres como segunda capa** en las 4 tablas con `despacho_id` directo (`core/rls.py`) — esto está por encima del 95% de SaaS legales de la región. Migraciones aditivas disciplinadas, pool asyncpg con `max_size` dimensionado tras un incidente real (12-jul).

Lo malo para 100 despachos: **todo corre en un proceso** (alertas de términos como loop in-process, SSE reservando conexiones dedicadas del pool con techo manual), no hay colas reales (ni BullMQ ni Celery ni nada — el pdf_worker es un proceso aparte, no una cola), RLS cubre solo 4 de ~9 tablas tenant (las indirectas quedaron para después, documentado), storage de PDFs **local y efímero** (se pierden en cada redeploy, bug documentado en el propio endpoint), sin staging, sin réplicas, sin backups evidenciados. Versión de Postgres: no evidenciada (no pude conectarme a la base — mi sandbox no tiene red hacia Railway).

Veredicto: aguanta 10-20 despachos con dolor operativo. Para 100 necesita: cola real para Radar Judicial y PDFs, S3/R2 para storage, RLS completo, staging.

### Eje 2 — Seguridad y compliance Colombia 🟡

Código de seguridad: **sorprendentemente bueno.** 2FA TOTP con backup codes de un solo uso y `must_enroll` para admin, refresh tokens con rotación + detección de reuso por familia, rate limiting de login/TOTP contando sobre `auth_events` (sobrevive redeploys), bitácora con **hash encadenado** (`core/auth_events.py`), soporte de rotación de JWT con doble clave (`SECURITY.md`), clave TOTP desacoplada de JWT_SECRET, HSTS + CSP. Esto es percentil alto.

Compliance Ley 1581 / SIC: **acá está el hueco.** No evidencié: endpoints ARCO (acceso/rectificación/supresión de datos del titular), política de retención/borrado de datos, aviso de privacidad versionado, registro RNBD (trámite operativo, no código — pero no hay ni rastro documental), cifrado en reposo de documentos legales (los PDFs viven en filesystem local plano). Ley 527 (firma/mensaje de datos): nada evidenciado — la bitácora hash-chain es un buen cimiento probatorio pero no es firma electrónica. **Lo que te multa la SIC primero:** no poder atender una solicitud de supresión de un titular en términos, y tratar datos sin RNBD si aplica el umbral. Punto positivo real: `core/analitica.py` explícitamente NO perfila jueces (advertencia SAMAI respetada en el esquema mismo).

Riesgo inmediato no-código: la `DATABASE_URL` con password real quedó en el historial de este chat. **Rotar credenciales de Postgres en Railway hoy.**

### Eje 3 — RAG y JuliX 🔴

- Banco de 20 casos: completo con `respuesta_esperada` (ya no bloqueado en datos — CLAUDE.md desactualizado).
- GATE ≥80%: **corrido y reprobado dos veces: 15% → 35%** (runs del 15-16 jul). La mejora vino de prompts v2; v3 está redactado y sin correr.
- ¿Alucina JuliX? El validador post-generación (`validar_citas_post_generacion()`) existe y marca `[revisar]` — bien. Pero el análisis del 16-jul muestra el problema inverso también: UGPP-07 se reclasificó de "alucinación" a "sobre-cautela" (el juez de evaluación se equivocó). Es decir: **también el evaluador necesita calibración.**
- Prompts versionados: sí (`julix/prompts/*_v1/v2/v3.md`, PROMPTS.md honesto). Ledger de costos: sí (`julix_calls` con despacho_id).
- Corpus: 85/400+ chunks. La herramienta de curaduría (`core/corpus_curation.py`, ingesta <10 min sin código) existe — lo que falta son los documentos.

**Arreglo concreto (por ser rojo):** el diagnóstico ya está en PROMPTS.md — `norma_clave` guarda solo la cita, nunca el texto del artículo. Secuencia: (1) enriquecer el corpus con el texto verbatim de los ~30 artículos más citados por el banco (usar `core/corpus_curation.py`, no CSV a mano); (2) correr v3 contra el banco; (3) recalibrar el juez del evaluador con UGPP-07 como caso de regresión (un fallo conocido del juez debe quedar como test del evaluador). Solo después de eso tiene sentido tocar prompts otra vez.

### Eje 4 — Deuda técnica 🟢

Tu lista de deudas está casi toda saldada: tests **428 funciones** (meta de 45 pulverizada), coverage gate 60% en CI (medido 71-72%), usuarios en Postgres con `user_credentials` (login ya lee de ahí), términos CPACA/CPT con vencimiento **siempre calculado** por `procesal/calendario_judicial.py` (nunca a mano — decisión correcta), clasificador de actuaciones sobre Haiku listo (`procesal/clasificador_actuaciones.py`, reusa prompt versionado). PDF: se eligió ReportLab, no LibreOffice headless — decisión razonable, generación nativa en vez de conversión; si el requisito real es .docx editable por el abogado, eso sí sigue abierto.

Deuda real restante: docstrings/estado desactualizados (CLAUDE.md sobre S5, docstring de pdf_worker), Fase C de auth pospuesta (columna `hashed_password` legacy), archivos `.diff` sueltos en la raíz del repo (`context_builder.diff`, `pdf_worker.diff`, etc. — o se aplican o se borran), RLS incompleto.

### Eje 5 — Producto y UX 🟡

Frontend real existe (React+Vite+TS, consume auth 2FA/casos/JuliX), pero no evidencié la separación "Panel Vridik Pro" vs "Portal Cliente Vridik" como productos distintos — hay un solo frontend en el repo. **Cobro Inteligente sí diferencia:** `honorarios_liquidados` siempre calculado por backend (fijo/cuota litis/mixto), liquidación de una sola vez — eso es disciplina financiera que el 95% de despachos lleva en Excel. **Bóveda de Cumplimiento: a medias.** `core/cumplimiento.py` tiene la matriz de riesgo (heurística transparente, con disclaimer correcto de "no sustituye al oficial de cumplimiento"), pero listas restrictivas ONU/OFAC/PEP están en esquema sin datos ni cruce — hoy no podés venderla como bóveda. La diferenciación real del producto sigue siendo JuliX, y JuliX está en rojo (eje 3).

### Eje 6 — Roadmap 🟡

Fase 1: cerrada en código, abierta en calidad (gate). Fases 2/3/4: **arrancadas en paralelo antes de cerrar el gate** — actuaciones, términos, cobro, bitácora, matriz de riesgo, analítica, RLS. Es amplitud real y bien construida, pero es amplitud sobre un core reprobado. Qué movería: congelar features nuevas de Fase 2-4 hasta que el gate pase; lo único de Fase 2 que no congelaría es el calendario de términos (ya genera valor sin depender de JuliX). Para que 3 despachos paguen en Q2-2027 falta, en orden: (1) gate ≥80%, (2) corpus 400+, (3) ingesta de actuaciones resuelta (eje 7), (4) storage S3 para que los PDFs no se evaporen, (5) compliance mínimo Ley 1581 (ARCO). Con eso, Q2-2027 es realista; sin el (1), no hay fecha.

### Eje 7 — Riesgo de caída (Radar Judicial) 🔴

Estado actual honesto: **no hay scraper, y eso es correcto.** La ingesta está bloqueada en la decisión build-vs-integrate (documentado en `procesal/__init__.py`), las actuaciones se registran a mano y el clasificador IA ya funciona sobre texto pegado — la arquitectura está lista para enchufar cualquier fuente.

Decisión (por ser rojo, la recomendación exacta): **integrar proveedor, no scraper propio.** Rama Judicial sin API oficial + CAPTCHA + TYBA con ViewState = un scraper propio es un empleado de tiempo completo con esperanza de vida de semanas por cada cambio de portal, más exposición legal por evasión de controles de acceso. Contratá TusDatos.co o AliadoJudicial (o Monolegal como benchmark de precio) con contrato que incluya SLA de frescura de datos y cláusula de licitud de la fuente; el clasificador y `terminos` ya consumen texto, así que la integración es un adaptador delgado (`procesal/ingesta_<proveedor>.py`) + un webhook. Scraper propio solo como plan C, y jamás para clientes pagos sin fallback. El riesgo de bloqueo pasa a ser del proveedor — ese es exactamente el riesgo que estás pagando por transferir.

## Top 10 deudas que matan el proyecto

1. GATE de evaluación en 35% vs meta 80% — el producto no cumple su promesa central.
2. Corpus RAG 85/400+ chunks, sin texto verbatim de normas — causa raíz probable del #1.
3. Credenciales de Postgres de producción expuestas en chat — rotar ya.
4. Sin staging: todo se verifica directo en producción (documentado en ROLLBACK.md).
5. Storage de PDFs local y efímero — documentos legales que desaparecen en cada redeploy.
6. Sin endpoints ARCO ni política de retención (Ley 1581) — riesgo SIC directo al primer cliente real.
7. Ingesta de actuaciones sin resolver (build-vs-integrate) — el Copiloto Procesal depende de datos manuales.
8. 1 sola cuenta admin de producción — bus factor 1, y `must_enroll` ya demostró que puede dejarla afuera.
9. RLS incompleto (4 de ~9 tablas tenant) — el aislamiento entre despachos depende de que nadie olvide un WHERE.
10. Estado documental desactualizado (CLAUDE.md dice S5 "bloqueado en datos" cuando ya reprobó el gate dos veces) — la documentación miente por omisión.

## Qué mantener / Qué rehacer / Qué borrar

**Mantener (no tocar):** todo el stack de auth (2FA/refresh/rate-limit/bitácora hash-chain/rotación JWT), disciplina de migraciones aditivas + ROLLBACK.md/SECURITY.md, calendario de términos siempre-calculado, cobro siempre-calculado, validador de citas, herramienta de curaduría de corpus, la decisión de NO scrapear, la decisión de NO perfilar jueces, los 428 tests.

**Rehacer / completar:** corpus (85→400+ con texto verbatim de normas), evaluador (recalibrar el juez con UGPP-07 como regresión), storage local→S3/R2, RLS a las 5 tablas restantes, listas restrictivas de cumplimiento (datos reales o quitarla del pitch), separación real Panel Pro vs Portal Cliente si es promesa comercial.

**Borrar:** archivos `.diff` sueltos de la raíz, sección desactualizada de S5 en `Instrucciones - CLAUDE.md` (reescribir con el estado real), carpeta legacy JURIS IA fuera del ámbito del producto (archivarla, no mezclarla con Vridik).

## Plan de 30-60-90 días para pasar a producción real

**Días 1-30 — el motor.** Rotar credenciales Postgres (día 1). Actualizar CLAUDE.md con estado real de S5 (día 1). Cargar texto verbatim de los ~30 artículos más citados vía curaduría. Correr prompts v3 contra el banco. Recalibrar juez del evaluador. Meta de salida: gate ≥60% (intermedia honesta, no 80 de golpe). Crear segunda cuenta admin + staging mínimo (un servicio Railway clon con DB propia).

**Días 31-60 — que no se caiga ni multe.** Storage S3/R2 para PDFs (adaptador ya existe en `storage/object_storage.py`). Endpoints ARCO + política de retención + aviso de privacidad versionado; evaluar obligación RNBD con abogado (tenés dos despachos aliados). RLS a tablas indirectas. Firmar contrato con proveedor de datos judiciales (TusDatos/AliadoJudicial) y construir el adaptador de ingesta. Meta de salida: gate ≥80% (el de verdad).

**Días 61-90 — que se venda.** Piloto con 1 despacho real (no de prueba) con Radar Judicial vía proveedor + alertas de términos activas. Completar listas restrictivas o retirar "Bóveda" del pitch. Carga de corpus a 400+ chunks con Ana Luisa usando la herramienta de curaduría (ya no hay excusa de tooling). Definir pricing contra el costo real por caso que ya mide el ledger.

## Mejoras para ser top 5% en Colombia

1. **Citación verificable como feature visible:** el `[revisar]` del validador convertido en UI donde cada cita de JuliX enlaza al chunk fuente — nadie más en el mercado colombiano muestra la prueba de cada afirmación.
2. **Términos como producto de entrada:** el calendario CPACA/CPT con alertas es vendible solo, sin IA, a despachos que jamás pagarían por un copiloto — puerta de entrada barata que financia el resto.
3. **Bitácora hash-chain como argumento probatorio:** documentarla formalmente (qué garantiza, qué no) y ofrecerla como evidencia de notificación con acuse — con revisión de abogado sobre valor probatorio Ley 527, es un diferenciador que casi nadie tiene.
4. **Analítica UGPP sobre casos propios** (ya construida, sin perfilar jueces): con 50+ casos reales se vuelve el dashboard que un socio de despacho muestra a sus clientes.
5. **Publicar el score del gate:** cuando pase de 80%, hacer del banco de evaluación un asset comercial ("JuliX aprueba X% en un banco de 20 casos reales auditado") — la honestidad medible como marca.
