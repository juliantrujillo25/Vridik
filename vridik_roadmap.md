# Roadmap Vridik

## Resumen

Vridik evoluciona de sistema de gestión con IA adjunta a **despacho aumentado por IA** en 4 fases de 90 días (Q3-2026 a Q2-2027). La tesis: el monitoreo de procesos ya está resuelto en Colombia (Monolegal, Expedientes.co); la diferenciación real está en lo que pasa **después** de la notificación — interpretación IA de la actuación, cálculo automático del término, y generación del borrador de respuesta. Nadie compite ahí.

Tres módulos diferenciadores construidos sobre lo existente:

1. **Copiloto Procesal** — pipeline evento judicial → clasificación IA → término calculado → borrador JuliX. Reutiliza RAG, JuliX, Generador y Dashboard.
2. **Cobro Inteligente** — valor en disputa por caso, liquidación automática de cuota litis sobre éxito medible (glosa levantada), panel "ahorro generado" para el cliente.
3. **Bóveda de Cumplimiento** — bitácora probatoria inmutable, SAGRILAFT lite, firma electrónica integrada (Ley 527/1999). Convierte el software del despacho en requisito del cliente corporativo.

Foso defensivo a 12 meses: (a) el **corpus propietario** de pares actuación→respuesta→resultado validados por el despacho, (b) el **flujo cerrado** evento→término→borrador que exige ser desarrollador y litigante a la vez, (c) la **confianza vendible** (bitácora + compliance + ahorro medible).

Advertencia regulatoria transversal: SAMAI advierte que la disponibilidad pública de datos judiciales no autoriza tratamiento masivo para análisis (Ley 1581). El monitoreo se limita a radicados propios del despacho; la analítica se reformula como **línea decisional por tipo de resolución UGPP**, no perfilamiento de jueces.

## Tabla Estado Actual

| Componente | Avance | Estado / deuda |
|---|---|---|
| Panel Vridik Pro | 90% | KPIs, vencimientos manuales (no calculados) |
| Portal Cliente Vridik | 55% | Mi Caso básico, vinculación manual |
| Mensajes | 85% | Chat interno con adjuntos, sin polling/tiempo real |
| Generador Word | 75% | Plantillas UGPP, fuente configurable, sin PDF |
| RAG | 65% | 85 chunks, fuerte en Laboral/UGPP, vacío en el resto, sin metadatos |
| JuliX | 70% | Redactor con prioridad normativa, **nunca probado con Claude real** |
| Roles / Auth | 90% / 85% | JWT (HMAC-SHA256), sin 2FA, usuarios en ENV/CSV |
| Tests | 0% | Deuda crítica: cero tests, sin CI |

## Fases

### Fase 1 — Consolidación (Q3-2026, semanas 1-13)

**Objetivo:** base vendible y estable; despejar la incógnita de JuliX con números.

**Bloques:** A. Cimientos (S1-3) · B. JuliX real (S4-6) · C. Corpus (S7-9) · D. Entregables (S10-11) · E. Cierre (S12-13, con colchón).

#### Semana 1 — Usuarios en PostgreSQL
- Esquema: `users` (UUID, citext email, soft delete, `legacy_username` puente), `roles` (tabla, no enum), `user_credentials` (argon2id/bcrypt, `must_change`), `refresh_tokens` (hash, rotación, revocables), `auth_events` (embrión de bitácora probatoria).
- Flujo de tokens: access JWT 15 min (HMAC actual para firma) + refresh 7 días en BD con rotación y detección de reuso (gracia 10s para carrera de dos pestañas; mutex de refresh en frontend).
- Migración sin downtime en 4 etapas: preparación → doble lectura con BD primaria y evento `legacy_fallback` como detector → corte tras 48h sin fallbacks → `ROLLBACK.md` ensayado en staging.
- Unificar la clave de localStorage del token entre frontend legacy y Vridik (`vridik.auth.refresh`); access token en memoria.
- **Salida:** 3 roles login contra PostgreSQL con la misma respuesta JSON; desactivar usuario surte efecto en ≤15 min; rollback probado.

#### Semana 2 — Panel de administración de usuarios
- CRUD admin: crear (temporal mostrada una vez, copiable), listar (tabla densa: rol badge, estado, último acceso relativo), editar, desactivar (revoca refresh), reset contraseña.
- UI: drawer lateral con foco atrapado, radio de roles con descripción, confirmaciones proporcionales, estados vacíos con voz, operable 100% teclado, contraste AA.
- Sección "Actividad" por usuario leyendo `auth_events` (semilla visible de bitácora Fase 3).
- **Salida:** Ana Luisa crea un usuario en <2 min sin ayuda; `must_change` bloquea todo salvo el cambio; cada acción deja `auth_event`.

#### Semana 3 — Suite de tests + CI
- Stack: pytest + httpx + **PostgreSQL real** en tests (citext y UUID exigen fidelidad; SQLite falsearía el test de email duplicado case-insensitive).
- 3 capas: ~15 unitarias, ~25 integración, ~5 de contrato (snapshots JSON que protegen ambos frontends). Catálogo de ~45 tests: login (8), tokens (12), autorización por rol (10), CRUD (10), contrato (5).
- 5 fixtures centrales: `db` con rollback transaccional, `seed_roles`, usuarios por rol, `auth_client(role)`; factory `make_user()`.
- CI GitHub Actions: postgres service container, ruff, `cov-fail-under=50` (sube a 60 al cierre), <3 min, branch protection. Romperlo a propósito una vez.
- 3 reglas en CONTRIBUTING.md: bug en producción gana test antes del fix; flaky se arregla o borra esa semana; contratos solo cambian con anuncio.
- **Salida:** ≥40 tests verdes; merge bloqueado sin CI; test nuevo autenticado en <10 líneas.

#### Semana 4 — JuliX con Claude real
- Módulo con frontera limpia: `service` / `prompts/` (archivos versionados con encabezado `v:`) / `client` (reintentos, timeouts, streaming) / `context_builder` (presupuesto de tokens por parte, truncado con criterio) / `ledger`.
- Streaming SSE hacia el frontend desde el día uno, con cancelar visible.
- Selección de modelo por tarea: documento de fondo → evaluar Sonnet primero, escalar solo si el banco lo exige; comunicaciones/clasificación → Haiku.
- Ledger `julix_calls`: modelo, prompt_version, tokens, costo USD, latencia, estado. Límite blando mensual (80% aviso, 100% confirmación por documento — nunca bloqueo duro) y techo de tokens por petición. Widget de costos en Panel Vridik Pro.
- 5 modos de fallo domados: timeout/red (backoff, sin reintento silencioso si ya hubo streaming), 429 (`retry-after`), 529 (borrador parcial recuperable), truncado por `max_tokens` (marcado, nunca presentado como completo), formato inválido (marcado, no corregido en silencio).
- API keys separadas staging/producción; prompts y respuestas guardados en tabla restringida (futuro dataset propietario).
- **Salida:** documento de punta a punta con streaming; corrida de humo de 3 casos con 2 modelos y costos comparados.

#### Semana 5 — Banco de evaluación (GATE de fase)
- 20 casos reales resueltos con **patrón oro** (lo que el despacho presentó): 8 UGPP núcleo (2×RQI/RCD/RDO/RDC), 4 UGPP borde, 4 laboral no-UGPP, **2 trampa** (no responder de fondo por procedibilidad; norma derogada en la entrada), 2 documento cliente.
- Ficha estándar por caso: entrada anonimizada + `contexto.md` (instrucción como se la daría a un junior) + patrón oro + rúbrica vacía. Banco congelado antes de la corrida 1.
- Anonimización por reemplazo consistente (Ley 1581 + secreto profesional): placeholders con formato verosímil; cifras y fechas se conservan (son la sustancia jurídica); la hace el despacho, ~15 h, arranca en paralelo desde la semana 1 de calendario.
- Rúbrica: 4 dimensiones (corrección jurídica, estrategia, completitud, forma) + global 1-4 ("¿cuánto trabajo me ahorra?") + 2 flags (🚩 alucinación → global 1 automático; 🚩 omisión peligrosa) + campo libre "¿qué corregirías primero?".
- Logística: script reproducible (hash de prompt + versión), calificación a ciegas en 3 sesiones de ≤7 casos, sin el constructor presente.
- **GATE:** ≥60% en global 3-4 para continuar; si no, la semana 6 es diagnóstico.

#### Semana 6 — Iteración de prompts con método
- Triage por causa raíz, no síntoma: contexto insuficiente (→ context_builder), recuperación fallida (→ RAG), instrucción ambigua (→ prompt), conocimiento ausente (→ backlog ingesta S8-9), juicio deficiente (→ prompt razonado o modelo).
- Flags primero: ¿alucinó sin fuente en corpus (→ ingesta) o con fuente en contexto (→ gravedad máxima, instrucción anti-alucinación)?
- Reglas: 1 cambio por experimento con probe de 3-5 casos; máximo 4 versiones de prompt, cada una con hipótesis escrita; jerarquía de intervención (reordenar contexto → instrucciones negativas → razonamiento por etapas con procedibilidad obligatoria → ejemplos del patrón oro → cambio de modelo); vigilar regresión cruzada entre tipos de documento.
- Corrida 2: mismos 20, orden re-aleatorizado, misma rúbrica. Salidas: ≥80% → congelar línea base; 60-79% → gate parcial, corrida 3 tras corpus (S9) con predicción explícita; <60% → freno y revisión de roadmap.
- Fijar costo promedio por documento (margen unitario para Fase 3). Publicar `PROMPTS.md` (versiones, patrones de fallo, reglas de oro heredables).

#### Semana 7 — Pipeline de ingesta del corpus
- Metadatos jurídicos: `corpus_documents` (tipo_fuente, **jerarquia** kelseniana operativa, area, **vigencia** + nota, fuente_url oficial, hash dedup) y `corpus_chunks` (orden, **referencia** citable "Art. 33", embedding, tokens).
- `jerarquia`+`vigencia` hacen mecánica la prioridad normativa (el context_builder ordena y filtra); `referencia` habilita el **validador de citas post-generación** (toda cita debe corresponder a una referencia presente en el contexto) — detector de alucinaciones en producción.
- Chunking por estructura jurídica, no por tamaño: leyes por artículo, sentencias por sección (hechos/problema/considerandos/decisión), conceptos por pregunta-respuesta. Prefijo de contexto autocontenido en cada chunk.
- Pipeline: extracción → normalización → detección de estructura semiautomática (regex + revisión humana) → chunking → prefijo → dedup por hash → metadatos → embedding batch con ledger → test de recuperación en cada ingesta.
- Versionado normativo: lo derogado se marca, nunca se borra (relevancia retroactiva); filtro de vigencia como parámetro del caso (refinamiento Fase 2, modelo lo soporta ya).
- Mini-herramienta de 3 pasos en una vista: carga con texto extraído siempre visible → chunks propuestos editables (unir/dividir/renombrar, atajos de teclado) → metadatos con selects preseleccionados por heurística. Borradores persistentes, modo oscuro.
- **Salida:** ingesta <10 min sin código; 85 chunks re-ingestados sin degradación (humo de 3 casos); dedup demostrada; validador de citas activo.

#### Semanas 8-9 — Carga del corpus (85 → 400+)
- Principio editorial: biblioteca curada, no scraping. Cada documento entra por respaldar un tipo de documento de JuliX o un fallo del triage — nunca "por si acaso".
- 4 olas: (1) backlog del triage S6 (~80-120 chunks, con probe de confirmación); (2) columna vertebral UGPP/laboral — solo artículos citados en el patrón oro + frecuentes (~120-150); (3) procesal CPACA/CPT/CGP que prepara el motor de términos de Fase 2 (~100); (4) jurisprudencia por línea decisional, 10-15 sentencias, chunking por considerandos (~80-100). Si falta tiempo, se recorta la ola 4 primero.
- División: Ana Luisa selecciona con una semana de ventaja (lista con fuente oficial + "por qué entra"); tú procesas en sesiones de ≤2h/10 docs. Solo SUIN-Juriscol, relatorías, UGPP oficial.
- 3 mallas: test de recuperación creciente (≥15 preguntas redactadas como pregunta de abogado, ≥12 en top-3); probes de JuliX por ola vigilando desplazamiento de chunks buenos por genéricos; auditoría de metadatos al cierre.
- Exclusiones escritas: tributario general (Fase 2+), SAGRILAFT (Fase 4), civil/comercial amplio (Fase 4), doctrina académica (probablemente nunca).

#### Semana 10 — Exportación PDF
- Ruta: **LibreOffice headless** en imagen Docker propia con fuentes instaladas (la sustitución silenciosa de fuentes es la causa #1 de PDFs deformes). Descartados: servicio externo (confidencialidad) y generación directa (plantillas duplicadas).
- Worker con cola en PostgreSQL (`pdf_jobs`), timeout duro 60s con kill, 1-2 concurrentes, perfil `UserInstallation` efímero por conversión.
- Postproceso: metadatos del documento, pie de trazabilidad opcional por plantilla (enlace visible con la bitácora de Fase 3), PDF/A como parámetro futuro. El PDF es derivado: se invalida al regenerar el docx.
- UX: botón con estados honestos (generando → listo con peso → error con reintento), previsualización inline nativa antes de descargar (última defensa de fidelidad), `aria-live` en cambios de estado, nomenclatura automática significativa del archivo.
- Verificación: test automatizado por plantilla (páginas, cadenas clave, metadatos, **fuentes embebidas = fuentes pedidas**) + validación visual de Ana Luisa en 3 documentos reales, documentada con capturas.

#### Semana 11 — Mensajería en tiempo real (SSE)
- Canal de eventos **genérico y multiplexado** (`/api/events/stream`): message.new/read, pdf.ready/error; en Fase 2: actuacion.nueva, termino.alerta. Patrón notificar-y-buscar (el evento lleva IDs, el fetch trae contenido y aplica permisos).
- Distribución interna con PostgreSQL NOTIFY/LISTEN (cero infra nueva). Auth del stream: fetch+ReadableStream con el interceptor existente (recomendado) o ticket efímero de 30s; nunca el access token en la URL.
- Reconexión: `Last-Event-ID` + buffer `user_events` (TTL 24h) + evento `resync` → reconciliación completa (el fetch es la verdad, el stream es optimización). Backoff con jitter, heartbeat servidor 25s / detección cliente 40s, verificación en `visibilitychange`.
- No-leídos por cursor temporal (`conversation_reads`), marcado solo con conversación abierta y pestaña visible; badge en sidebar con aria-label + contador en `<title>`. "Visto" al cliente: decisión de producto con la abogada.
- UX: optimistic UI con estado y reintento (el texto nunca se pierde), scroll sin robo con píldora "↓ N nuevos", `aria-live` solo en entrantes, agrupación temporal.
- Degradación: fallback automático a polling 20s reutilizando el endpoint de reconciliación.
- **Salida:** tortura de reconexión (suspensión, cambio de red, redeploy) sin pérdida ni duplicados; evento pdf.ready viajando por el canal (prueba de genericidad).

#### Semanas 12-13 — 2FA, hardening y cierre
- TOTP: secreto cifrado en reposo, enrolamiento con QR + secreto copiable, confirmación antes de generar 8 códigos de recuperación hasheados, enrolamiento no confirmado expira en 15 min. Login en dos pasos con token de pre-autenticación de 5 min. Anti-replay, ventana ±1 período, reset administrativo desde el panel ("perdí el teléfono"). Obligatorio admin (`must_enroll`), promovido abogado, silencioso cliente.
- Hardening: rate limiting por email+IP (login 10 fallos/15 min; TOTP 5 fallos), headers (HSTS, nosniff, CSP en Report-Only 2 días → aplicar, frame-ancestors none), rotación de JWT secret con doble clave ensayada en staging (`SECURITY.md`), apagado de endpoints huérfanos, validación de adjuntos en servidor.
- Semana 13: regresión (cov ≥60 con tests de valor real, guion manual en 2 frontends + móvil físico, corrida final del banco como no-regresión del trimestre); triage de deuda en 3 cubos (ahora / backlog F2 con dueño / descartado por escrito); **demo con Ana Luisa operando** los 5 flujos sin intervención + 2 preguntas registradas ("¿qué te estorbó?", "¿se lo mostrarías a un colega tal como está?").
- Regla de recorte si el colchón no alcanza: 2FA opcional de abogados → CSP fina → banco reducido a 8 casos. Nunca se recorta: demo, regresión de 5 flujos, rate limiting.

**Definition of Done Fase 1:** 5 flujos de demo sin intervención; 0 usuarios fuera de BD; 2FA admin obligatorio; JuliX ≥80% global 3-4 con cero alucinaciones sin diagnóstico y trampas detectadas; ≥400 chunks con recuperación ≥12/15; cobertura ≥60% auth+generador con CI bloqueante; costo por documento conocido; SECURITY/ROLLBACK/PROMPTS/CONTRIBUTING publicados y ensayados.

### Fase 2 — Copiloto Procesal (Q4-2026)

**Objetivo:** IA que actúa sobre eventos judiciales, no que espera preguntas.

- Ingesta de actuaciones de radicados propios del despacho (decisión temprana build-vs-integrate: empezar integrando proveedor de monitoreo, construir scraping propio solo si el volumen lo justifica; límite legal: solo procesos propios).
- Clasificador IA de actuaciones (auto admisorio, requerimiento, fallo, traslado) sobre Haiku + el canal de eventos de la S11.
- Motor de términos CPACA/CPT/CGP con calendario judicial y festivos 2026-27 (corpus de la ola 3 como base normativa citable).
- Borrador automático vía JuliX con el expediente del caso; semáforo de vencimientos calculados (no manuales) en el dashboard.
- **Métricas:** 100% de actuaciones clasificadas en <24h; 0 términos vencidos sin alerta en 90 días; ≥50% de borradores usados como punto de partida.
- **Riesgo Colombia:** cambios sin aviso en portales de la Rama; advertencia SAMAI → radicados propios únicamente.

### Fase 3 — Cobro Inteligente + trazabilidad (Q1-2027)

**Objetivo:** monetización visible; el cliente ve cuánto le ahorra el despacho.

- Valor en disputa por caso (glosa, sanciones, intereses); esquemas de honorarios (fijo/cuota litis/mixto) con liquidación automática del éxito al cierre de etapa.
- Cuenta de cobro / factura vía proveedor tecnológico DIAN autorizado (integrar, no construir).
- Panel "ahorro generado" en Portal Cliente Vridik (55% → 90%); bitácora sellada de notificaciones con acuse (crece sobre `auth_events` + hash encadenado).
- **Métricas:** Portal Cliente Vridik al 90%; 100% de casos activos con valor en disputa; primera cuenta de cobro sin Excel.
- **Riesgo Colombia:** facturación electrónica es terreno regulado (proveedor autorizado); gestión de expectativas del cliente al ver cifras.

### Fase 4 — Escalamiento (Q2-2027)

**Objetivo:** de herramienta interna a producto multi-despacho.

- Multi-tenancy real con aislamiento estricto (Ley 1581 entre tenants); onboarding self-service <1 semana.
- Bóveda de Cumplimiento: bitácora inmutable, SAGRILAFT lite (listas restrictivas, matriz de riesgo, reportes Supersociedades), firma electrónica integrada vía API de proveedor certificado colombiano.
- Analítica de línea decisional UGPP sobre corpus propio (no perfilamiento de jueces individuales).
- Pricing por despacho; piloto externo desde F3.
- **Métricas:** 3 despachos pagando; churn 0 del piloto; onboarding <1 semana.
- **Riesgo Colombia:** aislamiento de datos entre tenants; la competencia copia features superficiales, no el corpus.

## Roadmap.json

```json
{
  "fase1": {
    "nombre": "Consolidación",
    "periodo": "Q3-2026",
    "semanas": {
      "s1": {
        "titulo": "Usuarios en PostgreSQL",
        "tareas": [
          "Crear esquema: users (UUID, citext), roles, user_credentials (argon2id), refresh_tokens, auth_events",
          "Implementar access JWT 15min + refresh rotativo con detección de reuso y gracia 10s",
          "Migración doble lectura con evento legacy_fallback y corte tras 48h limpias",
          "Unificar clave localStorage entre legacy y Vridik; access token en memoria",
          "Escribir y ensayar ROLLBACK.md en staging"
        ],
        "salida": ["3 roles login contra BD con mismo contrato JSON", "desactivación efectiva ≤15min", "cero legacy_fallback 48h"]
      },
      "s2": {
        "titulo": "Panel admin de usuarios",
        "tareas": [
          "CRUD: crear con temporal única copiable, listar, editar, desactivar (revoca refresh), reset",
          "Drawer accesible: foco atrapado, teclado completo, confirmaciones proporcionales",
          "Sección Actividad por usuario desde auth_events",
          "Tests: email duplicado case-insensitive 409, 403 no-admin, reset revoca refresh"
        ],
        "salida": ["Ana Luisa crea usuario <2min sin ayuda", "must_change bloquea todo salvo cambio", "toda acción deja auth_event"]
      },
      "s3": {
        "titulo": "Suite de tests + CI",
        "tareas": [
          "pytest + httpx + PostgreSQL real (service container)",
          "45 tests: login 8, tokens 12, roles 10, CRUD 10, contrato 5",
          "5 fixtures centrales + factory make_user",
          "GitHub Actions <3min, ruff, cov-fail-under=50, branch protection",
          "CONTRIBUTING.md con 3 reglas; romper CI a propósito una vez"
        ],
        "salida": ["≥40 tests verdes", "merge bloqueado sin CI", "test autenticado nuevo en <10 líneas"]
      },
      "s4": {
        "titulo": "JuliX con Claude real",
        "tareas": [
          "Módulo julix/: service, prompts versionados en archivos, client con reintentos, context_builder con presupuesto de tokens, ledger",
          "Streaming SSE al frontend con cancelar",
          "Ledger julix_calls con costo USD, prompt_version, estado; límite blando mensual y techo por petición",
          "Domar 5 modos de fallo: timeout, 429, 529, truncado, formato inválido",
          "Widget de costos en dashboard; keys separadas staging/prod",
          "Corrida de humo: 3 casos x 2 modelos con costos"
        ],
        "salida": ["documento punta a punta con streaming", "todo fallo es ruidoso, ningún parcial parece completo"]
      },
      "s5": {
        "titulo": "Banco de evaluación (GATE)",
        "tareas": [
          "20 casos reales con patrón oro: 8 UGPP núcleo, 4 borde, 4 laboral, 2 trampa, 2 cliente",
          "Anonimización por reemplazo (cifras y fechas se conservan), hecha por el despacho",
          "Rúbrica 4 dimensiones + global 1-4 + flags alucinación/omisión + campo qué-corregirías",
          "Corrida 1 con script reproducible; calificación a ciegas en 3 sesiones sin el constructor",
          "Sesión de cierre: peores 5 + flags → lista priorizada"
        ],
        "salida": ["GATE: ≥60% global 3-4 para continuar; alucinación = global 1 automático"]
      },
      "s6": {
        "titulo": "Iteración de prompts",
        "tareas": [
          "Triage por causa raíz: contexto / recuperación / instrucción / corpus ausente / juicio",
          "Máximo 4 versiones de prompt, cada una con hipótesis escrita y probe de 3-5 casos",
          "Jerarquía: reordenar contexto → instrucciones negativas → razonamiento por etapas → ejemplos → modelo",
          "Corrida 2 re-aleatorizada; fijar costo promedio por documento",
          "Publicar PROMPTS.md"
        ],
        "salida": ["≥80% → congelar línea base; 60-79% → corrida 3 tras corpus; <60% → freno y revisión"]
      },
      "s7": {
        "titulo": "Pipeline de ingesta",
        "tareas": [
          "Esquema corpus_documents (jerarquia, vigencia, fuente_url, hash) + corpus_chunks (referencia citable)",
          "Chunking por estructura jurídica con prefijo de contexto autocontenido",
          "Pipeline con dedup, embedding batch con ledger, test de recuperación por ingesta",
          "Validador de citas post-generación en JuliX (cita ↔ referencia en contexto)",
          "Mini-herramienta de 3 pasos con edición de chunks por teclado"
        ],
        "salida": ["ingesta <10min sin código", "85 chunks re-ingestados sin degradación", "dedup demostrada"]
      },
      "s8_9": {
        "titulo": "Carga del corpus 85→400+",
        "tareas": [
          "Ola 1: backlog del triage S6 con probe de confirmación",
          "Ola 2: UGPP/laboral solo artículos del patrón oro + frecuentes",
          "Ola 3: CPACA/CPT/CGP (prepara motor de términos F2)",
          "Ola 4: 10-15 sentencias por línea decisional (se recorta primero si falta tiempo)",
          "Ana Luisa selecciona con 1 semana de ventaja; solo fuentes oficiales; sesiones ≤2h",
          "3 mallas: recuperación ≥12/15, probes por ola, auditoría de metadatos"
        ],
        "salida": ["≥400 chunks con metadatos y fuente oficial", "cero regresiones en probes", "exclusiones publicadas"]
      },
      "s10": {
        "titulo": "Exportación PDF",
        "tareas": [
          "LibreOffice headless en Docker con fuentes instaladas; perfil efímero por conversión",
          "Worker con cola pdf_jobs en PostgreSQL, timeout 60s con kill, 1-2 concurrentes",
          "Postproceso: metadatos, pie de trazabilidad opcional, invalidación del derivado al regenerar docx",
          "UX: estados honestos del botón, previsualización inline, aria-live, nomenclatura automática",
          "Test de fuentes embebidas en CI + validación visual de Ana Luisa en 3 documentos"
        ],
        "salida": ["PDF fiel en todas las plantillas", "conversión colgada muere sin tumbar la cola"]
      },
      "s11": {
        "titulo": "Mensajería SSE",
        "tareas": [
          "Canal genérico /api/events/stream multiplexado (message, pdf, futuro actuacion/termino)",
          "Patrón notificar-y-buscar; NOTIFY/LISTEN de PostgreSQL; auth sin token en URL",
          "Last-Event-ID + buffer 24h + resync → reconciliación; backoff con jitter; heartbeat 25s",
          "No-leídos por cursor temporal; badge accesible + título de pestaña",
          "Optimistic UI con reintento; scroll sin robo; fallback a polling"
        ],
        "salida": ["mensaje visible <10s (real <1s)", "tortura de reconexión sin pérdida ni duplicados", "pdf.ready por el mismo canal"]
      },
      "s12_13": {
        "titulo": "2FA, hardening y cierre",
        "tareas": [
          "TOTP: enrolamiento QR+secreto, códigos de recuperación hasheados, pre-auth token 5min, anti-replay, reset administrativo; obligatorio admin",
          "Rate limiting email+IP (login 10/15min, TOTP 5), headers HSTS/nosniff/CSP report-only→aplicar, rotación JWT secret ensayada",
          "Regresión: cov ≥60, guion manual en 2 frontends + móvil físico, corrida final del banco",
          "Triage de deuda en 3 cubos con destino escrito",
          "Demo: Ana Luisa opera 5 flujos sin intervención + 2 preguntas registradas"
        ],
        "salida": ["Definition of Done completo verificado", "backlog F2 con contenido real"]
      }
    },
    "metricas": [
      "JuliX ≥80% global 3-4 en banco de 20 casos, cero alucinaciones sin diagnóstico, 2 trampas detectadas",
      "0 usuarios fuera de PostgreSQL; 2FA obligatorio en admin",
      "≥400 chunks con metadatos completos; recuperación ≥12/15 en top-3",
      "Cobertura ≥60% en auth y generador; CI bloqueante <3min",
      "Costo promedio por documento conocido y bajo techo comercial",
      "5 flujos de demo operados por la abogada sin intervención del desarrollador"
    ],
    "riesgo_colombia": "Costo de tokens vs tarifa del despacho; calidad del corpus depende del tiempo de la abogada (recurso escaso: agendar S5, S8-9, S13 desde el inicio)"
  },
  "fase2": {
    "nombre": "Copiloto Procesal",
    "periodo": "Q4-2026",
    "tareas": [
      "Ingesta de actuaciones de radicados propios (integrar proveedor primero; scraping propio solo si el volumen lo justifica)",
      "Clasificador IA de actuaciones (auto admisorio, requerimiento, fallo, traslado) con Haiku",
      "Motor de términos CPACA/CPT/CGP con calendario judicial y festivos 2026-27",
      "Borrador automático de respuesta vía JuliX con contexto del expediente",
      "Semáforo de vencimientos calculados en dashboard, alertas por el canal de eventos de S11"
    ],
    "metricas": [
      "100% de actuaciones de radicados activos clasificadas en <24h",
      "0 términos vencidos sin alerta en 90 días",
      "≥50% de borradores usados como punto de partida por los abogados"
    ],
    "riesgo_colombia": "Cambios sin aviso en portales de la Rama Judicial; advertencia de uso de datos de SAMAI → limitarse a radicados propios del despacho"
  },
  "fase3": {
    "nombre": "Cobro Inteligente + trazabilidad",
    "periodo": "Q1-2027",
    "tareas": [
      "Valor en disputa por caso (glosa, sanciones, intereses) y esquemas de honorarios (fijo, cuota litis, mixto)",
      "Liquidación automática del éxito al cierre de etapa (glosa levantada = base de cuota litis)",
      "Cuenta de cobro / factura vía proveedor tecnológico autorizado DIAN (integrar, no construir)",
      "Panel de ahorro generado en Portal Cliente Vridik (55% → 90%)",
      "Bitácora sellada de notificaciones con acuse (hash encadenado sobre auth_events)"
    ],
    "metricas": [
      "Portal Cliente Vridik al 90%",
      "100% de casos activos con valor en disputa registrado",
      "Primera cuenta de cobro generada sin Excel"
    ],
    "riesgo_colombia": "Facturación electrónica es terreno regulado DIAN; sensibilidad del cliente al ver cifras (gestión de expectativas)"
  },
  "fase4": {
    "nombre": "Escalamiento",
    "periodo": "Q2-2027",
    "tareas": [
      "Multi-tenancy real con aislamiento estricto entre despachos",
      "Onboarding self-service en menos de 1 semana",
      "Bóveda de Cumplimiento: bitácora inmutable + SAGRILAFT lite + firma electrónica integrada (proveedor certificado, Ley 527/1999)",
      "Analítica de línea decisional UGPP sobre corpus propio (no perfilamiento de jueces)",
      "Pricing por despacho y conversión del piloto externo iniciado en F3"
    ],
    "metricas": [
      "3 despachos pagando",
      "Churn 0 del piloto",
      "Tiempo de onboarding <1 semana"
    ],
    "riesgo_colombia": "Ley 1581 entre tenants (aislamiento de datos de terceros); la competencia copia features superficiales pero no el corpus propietario"
  }
}
```
