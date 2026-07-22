# Instrucciones — Project Vridik

Este archivo no existía en el repositorio antes de esta auditoría (búsqueda
en todas las carpetas conectadas sin resultados) — se crea ahora como punto
de partida para Claude Code, con lo que la auditoría de `vridik_roadmap.md`
S1-S7 dejó confirmado. Actualízalo cuando cierres cada gap de
`AUDITORIA_PARA_CLAUDE.md`.

## Qué es este repositorio, en dos frases

Vridik es un despacho de abogados aumentado por IA (JuliX = asistente de
redacción legal con RAG sobre normativa colombiana, Claude Sonnet 5). El
roadmap real vive en `vridik_roadmap.md`/`vridik_roadmap.json` — esa es la
única fuente de verdad de fase/sprint; si algo en `backlog_fase1_vridik.md`
contradice al roadmap, manda el roadmap.

## Hallazgo crítico de esta auditoría — dos ramas coexistiendo

El repo contiene dos implementaciones de "S1-S7" que NO son la misma cosa:

1. **La rama del roadmap** (`vridik_roadmap.md`): auth con roles/refresh
   tokens (`schema_semana1_vridik.sql`), banco de evaluación GATE
   (`eval/`), RAG legal (`rag/`, `julix/`). Bien construida en código pero
   con gaps reales de cierre (ver `AUDITORIA_PARA_CLAUDE.md`).
2. **La rama realmente montada en `app/main.py` y desplegada en Railway**:
   `api/auth_endpoint.py` + `core/auth.py`, `api/admin_endpoint.py`,
   `api/products_endpoint.py`, `api/orders_endpoint.py`,
   `api/seller_endpoint.py`, `api/payments_endpoint.py` (Wompi),
   `api/case_documents_endpoint.py`. Esta rama reutiliza los mismos
   números de sprint (S1-S7) pero para requisitos distintos a los del
   roadmap — es la que corre en producción. Actualización: ya NO le
   faltan roles/refresh tokens — ver "Progreso contra
   AUDITORIA_PARA_CLAUDE.md" más abajo (S1-GAP-01, Fases A y B cerradas).

**DECISIÓN TOMADA (dev lead, ver "Consolidación de producto" más abajo):
el copiloto legal es el producto real.** El marketplace se desmantela
activamente (no solo se congela) en lo que no sea esencial. Antes de
seguir desmantelando, confirmar con el dev lead qué cuenta como esencial
en cada caso puntual (ver el punto sobre `case_documents`/`orders` más
abajo) -- no asumir.

## Reglas no negociables (todo el proyecto)

- Modelo: `claude-sonnet-5` (CORREGIDO — ver Progreso más abajo: la versión
  original de esta regla, `claude-sonnet-5-20250624`, nunca existió como
  model ID válido en la API de Anthropic; se escribió sin verificación real
  contra la API, cosa que esta auditoría explícitamente prohibía hacer).
  Nunca cambiar sin instrucción explícita del dev lead.
- Nunca ejecutar llamadas reales contra la API de Anthropic ni contra
  PostgreSQL de producción sin autorización explícita — todo el código se
  verifica con mocks/fakes salvo que el backlog documente lo contrario.
  Excepción ya autorizada por el dev lead en esta sesión: verificación
  puntual de S1-GAP-01 (Fases A y B) y del pipeline JuliX contra Claude
  real, ambas con autorización explícita caso por caso.
- Naming: siempre "Vridik" / "JuliX", nunca otro nombre de producto.
- Ningún fallo se presenta como éxito silencioso — timeouts, truncados,
  contexto insuficiente se comunican explícitamente.
- Toda migración SQL es idempotente (`CREATE TABLE IF NOT EXISTS`,
  `ALTER ... ADD COLUMN IF NOT EXISTS`).
- Antes de confiar en `pytest`/`py_compile`, limpiar `__pycache__` — este
  entorno ha mostrado bytecode cacheado enmascarando archivos corregidos.

## Cómo correr las pruebas

```bash
pip install -r requirements-test.txt
pytest -q
```

Ningún test llama a Anthropic ni a PostgreSQL reales por defecto.

## Dónde está cada cosa

Ver la tabla de estructura en `README.md`. Para el estado sprint-por-sprint
de la rama del roadmap, ver `backlog_fase1_vridik.md` y
`data/roadmap_status.md`. Para los gaps pendientes contra
`vridik_roadmap.md` S1-S7, ver `AUDITORIA_PARA_CLAUDE.md` (generado en esta
auditoría).

## Progreso contra AUDITORIA_PARA_CLAUDE.md

- **S1-GAP-01 (bloqueante) — EN PROGRESO, decisión tomada: migrar de
  verdad, no solo documentar.** El dev lead decidió llevar la auth
  realmente montada al esquema completo del roadmap (`roles`,
  `user_credentials`, `refresh_tokens`, `auth_events`), en vez de
  actualizar el roadmap para reflejar el diseño simple.
  - **Fase A (schema, aditiva) — CERRADA.** `migrations/005_auth_roles_refresh_tokens.sql`
    aplicada y verificada contra Railway real: 4 tablas nuevas, `role_id`
    backfilleado en los 16 usuarios existentes, `email` migrado a `CITEXT`.
    `users.role`/`users.hashed_password` NO se tocaron — cero regresiones.
  - **Fase B (código) — CERRADA.** `core/refresh_tokens.py` (rotación +
    detección de reuso con family_id, gracia de 10s) + `core/auth_events.py`
    + `POST /auth/refresh` + `POST /auth/logout`, y `register`/`login`/
    `2fa/login` ahora emiten `refresh_token` además de `access_token`
    (15 min, antes 60). `tests/test_auth_refresh.py` (9 tests). Verificado
    end-to-end contra producción real (register → refresh → logout →
    refresh rechazado). 147 tests locales en verde.
  - **Fase C (cleanup: soltar `users.hashed_password` en favor de
    `user_credentials`, evaluar soltar `role` en favor de `role_id`) —
    PENDIENTE**, deliberadamente pospuesta hasta validar Fase B en
    producción por un tiempo. Nada de código depende de esto todavía.
  - Endpoints `/auth/refresh`/`/auth/logout` aún no tienen wiring en
    ningún frontend (no hay frontend en este repo) — son API-only por
    ahora, listos para que un cliente los use.
- **S2-GAP-01 (alta) — CERRADO.** `GET /admin/users/{id}/actividad` y
  `POST /admin/users/{id}/reset-password` montados en `api/admin_endpoint.py`
  (la lógica ya existía en `core/admin_users.py`, solo faltaba conectarla).
  Fix necesario: `resetear_password()` ahora también escribe
  `users.hashed_password` (dual-write) -- antes solo tocaba
  `user_credentials`, que `/auth/login` no lee todavía. Verificado en
  producción (ruta montada, exige auth). 6 tests nuevos.
- **S3-GAP-01 (media) — CERRADO.** `.github/workflows/ci.yml` agrega
  `coverage report --fail-under=60` (medido: 71-72% real, sin excluir
  nada). `CONTRIBUTING.md` con las 3 reglas del roadmap.
- **S4-GAP-01 (media) — CERRADO.** `eval/corrida_humo_s4.json`: 3 casos
  reales del banco (UGPP-01/02/03) x 2 modelos (Sonnet vía
  `ugpp_demanda`, Haiku vía `clasificacion_documento`) = 6 registros,
  todos `status=ok`, costo total real **$0.045962 USD**. No usa
  `eval/evaluador.py --commit` (ese filtra a solo casos CON
  `respuesta_esperada`, que hoy son cero -- sigue bloqueado en S5) --
  es un smoke test directo de `julix/client.py` vía
  `client._abrir_stream_sdk()`, con autorización explícita del dev lead
  para gastar dinero real en esta corrida puntual.
- **S5-GAP-01 (bloqueante) — ESTADO REAL ACTUALIZADO (20-jul-2026,
  auditoría Fable 5): el GATE YA CORRIÓ y REPROBÓ.** La versión anterior
  de esta sección ("sigue bloqueado, falta que Ana Luisa llene
  respuesta_esperada") quedó desactualizada: el banco está completo y
  `eval/evaluador.py --commit` corrió dos veces con datos reales
  (15-jul y 16-jul-2026, runs `s5-...-4f201beb` y `s5-...-46812ab1`,
  ver PROMPTS.md y git log): **15% y luego 35% de aprobación, ambas por
  debajo del GATE >=80%**. El bloqueo hoy es de RESULTADO, no de datos.
  Además: (a) UGPP-07 se reclasificó el 16-jul (`e1db508`) de
  "alucinación real" a "abstención/sobre-cautela" — el Decreto 379/2026
  que citaba SÍ existe; el juez del evaluador lo marcó mal, o sea el
  evaluador también necesita calibración; (b) el diagnóstico de
  PROMPTS.md apunta a un límite estructural del banco (`norma_clave`
  guarda solo la cita, nunca el texto verbatim del artículo) — **T2
  (21-jul, quinta pasada, + sexta pasada 22-jul) cargó texto verbatim
  real para 19 de los 20 casos del banco.** La sexta pasada cerró 5 de
  los 6 huecos reales encontrados el 22-jul: Ley 1607/2012 art. 179
  (UGPP-01/02/03 -- ojo, se cargó la versión vigente mod. Ley 1819/2016
  art. 314, NO la original de 2012, que da un texto distinto), CST arts.
  127/128 (UGPP-06), Ley 2466/2025 arts. 10/14 (LAB-02 -- estos artículos
  además SUPERAN los chunks viejos de CST 160/179 ya cargados, pendiente
  de reemplazarlos o anotarlos), Resolución 3461/2025 arts. 1/2/6
  (LAB-08). Solo LAB-04 (jurisprudencia sin sentencia puntual citada en
  el banco) queda sin cargar a propósito. Ver detalle completo en
  `HANDOFF_CLAUDE_CODE.md` ("Corrección de T2"). Regla del propio
  roadmap ignorada hasta la corrida de 16-jul: "<60% → freno y
  revisión" — las Fases 2-4 se construyeron igual.
  **T3 (corrida con prompts v3), intentada por primera vez el 21-jul
  contra Anthropic + Postgres reales -- NO completó una corrida oficial
  todavía:**
  1. Primer bug real encontrado en el primer intento: `eval/
     evaluador.py --commit` corre como "sistema" (sin `despacho_id`
     propio) y el INSERT al ledger de `julix_calls` crasheaba con
     `InsufficientPrivilegeError` bajo RLS de tenant isolation. Fix:
     `bypass_rls` explícito en la conexión dedicada del script (`d200c30`,
     caso legítimo de herramienta administrativa, no un agujero).
  2. Continuando la corrida, 3/20 casos (UGPP-03/06/07) cayeron al
     fallback punitivo (score=0) por ruido de parseo del juez, no por
     mala calidad real de la respuesta (confirmado reenviando el mismo
     input al juez fuera de la corrida: dio JSON válido con score=3).
     Fix: reintento hasta 2 veces antes del fallback punitivo, sigue
     fail-closed si el ruido persiste (`f6f5533`).
  3. Con ambos bugs ya arreglados, la corrida OFICIAL completa (20
     casos, `--commit` persistido como la corrida real de T3) quedó
     **bloqueada por saldo insuficiente en la cuenta de Anthropic** —
     hallazgo real del 21-jul, nunca antes documentado en detalle en
     ningún archivo (solo sobrevivía en el título de un commit de docs).
     **No hay todavía ningún resultado (%) de una corrida v3 oficial** --
     el último número medido y persistido sigue siendo el 35% de la
     corrida de 16-jul (v2). Antes de reintentar T3: confirmar con el
     dev lead que la cuenta de Anthropic tiene saldo, y que se autoriza
     explícitamente el gasto real de esa corrida puntual (regla no
     negociable del proyecto).
- **S6-GAP-01 (media) — CERRADO.** `PROMPTS.md` consolidado, honesto
  sobre que ningún prompt tiene corrida de evaluación medida todavía
  (bloqueado en S5).
- **S7-GAP-01 (alta) — CERRADO.** `julix/service.py::validar_citas_post_generacion()`
  -- regex extrae citas de norma/artículo del texto ya generado, compara
  por clave normalizada (no substring crudo) contra
  `BuiltContext.chunks_incluidos`, marca `[revisar]` como chunk extra al
  final del stream si hay cita sin respaldo. 7 tests nuevos. Desplegado
  y verificado en producción.

**Balance final de la auditoría:** de los 7 gaps, 6 cerrados (S1 Fases
A/B, S2, S3, S4, S6, S7). Solo **S5** sigue abierto — y desde el
20-jul-2026 su naturaleza cambió: ya NO depende de datos de Ana Luisa
(el banco está completo y el GATE corrió), sino de subir el resultado
de 35% a >=80% — eso SÍ es trabajo de código+corpus (ver la entrada
S5-GAP-01 actualizada arriba y vridik_audit.md).

## Continuación del roadmap (post-desmantelamiento del marketplace)

Con el marketplace fuera (ver "Consolidación de producto" abajo), se
retomó `vridik_roadmap.md` (única fuente de verdad de fase/sprint) más
allá de los gaps S1-S7 de la auditoría. Estado real relevado antes de
elegir por dónde seguir:

- **S8-9 (corpus 85→400+ chunks)** — pipeline listo (`rag/ingest_ugpp.py`,
  `rag/quality_gate.py`), pero `data/corpus_manifest.csv` solo tiene ~20
  filas. Bloqueado en selección de documentos por Ana Luisa, igual que S5
  -- no es trabajo de código puro.
- **S10 (export PDF)** — cerrado (ver nota de `pdf_jobs` en
  "Consolidación de producto").
- **S11 (mensajería en tiempo real, SSE)** — solo existe un contrato fake
  (`tests/test_mensajes.py` contra `FakeMensajesService`,
  `tests/support/fakes.py`) -- no hay `api/mensajes_endpoint.py` ni
  `core/mensajes.py` reales, ni canal de eventos `/api/events/stream`.
  Feature grande y nueva, no arrancada.
- **S12-13 (2FA + hardening + cierre)** — 2FA TOTP completo y en
  producción (`/auth/2fa/setup`, `/auth/2fa/verify`, `/auth/2fa/login`);
  headers de seguridad + CORS fail-closed ya testeados
  (`tests/test_api_hardening.py`). Faltaba rate limiting de login por
  email+IP -- gap chico y acotado, elegido para cerrar primero.

**Rate limiting de login (S12-13) — CERRADO.** `core/rate_limit.py`
(nuevo): `excede_limite_login()` (10 fallos de contraseña/15 min por
email+IP) y `excede_limite_totp()` (5 códigos TOTP inválidos/15 min por
user_id) -- ambas cuentan directo sobre `auth_events`, sin tabla de
contadores nueva ni caché en memoria (se hubiera perdido en cada
redeploy). `core/auth_events.py::registrar_evento()` ahora escribe
`ip_address`/`user_agent` (las columnas ya existían en el schema desde
Fase A, nunca se llenaban). `api/auth_endpoint.py::login()`/`login_2fa()`
chequean el límite ANTES de verificar contraseña/código -- un intento
bloqueado ni gasta bcrypt ni revela si el email existe. IP leída de
`X-Forwarded-For` (Railway detrás de proxy) con fallback a
`request.client.host`.

Verificación en dos capas: `tests/test_rate_limit.py` (nuevo) prueba las
queries SQL directo contra PostgreSQL real (fixture `db`, real en CI
-- INET/JSONB/`IS NOT DISTINCT FROM` no se pueden confiar a un fake);
`tests/test_auth_refresh.py` prueba el wiring HTTP del 429 sobre el fake
existente. El placeholder de S12 en `tests/test_auth.py`
(`test_rate_limit_placeholder_contrato_login`) se actualizó para
verificar las constantes reales de `core/rate_limit.py` en vez de
constantes locales sueltas.

**S11 (mensajería + SSE) — Fase A CERRADA: backend real de mensajes.**
Plan en 4 fases (mismo patrón que el desmantelamiento del marketplace):
A. backend real de mensajes (esta) · B. canal SSE genérico
`/api/events/stream` con NOTIFY/LISTEN · C. reconexión (Last-Event-ID +
buffer 24h + resync) · D. no-leídos ya cerrado en la Fase A (ver abajo) +
enganchar `pdf.ready` de `case_documents` al canal.

`core/mensajes.py` (nuevo) reemplaza a
`tests/support/fakes.py::FakeMensajesService` como capa de datos real,
misma firma de funciones (crear/marcar_leido/no_leidos_para/borrar) para
que las fases B-D (SSE encima) no tengan que tocarla.
`api/mensajes_endpoint.py` (nuevo): rutas sobre un `caso` (core/case.py)
-- una conversación cuelga siempre de un caso, mismo criterio de
ownership que `case_documents` (cliente del caso, abogado asignado, o
admin).

Decisión de diseño: no-leídos por **cursor temporal**
(`conversation_reads`: conversacion_id, user_id, last_read_at) en vez de
una fila de lectura por mensaje -- es lo que pide el roadmap S11 de
entrada ("cursor temporal... marcado solo con conversación abierta y
pestaña visible"), así que se implementó así desde la Fase A en vez de
construir algo más simple ahora y migrar el schema después.
`marcar_leido(mensaje_id, user_id)` avanza el cursor hasta el
`created_at` de ese mensaje (GREATEST, nunca lo retrocede).

`tests/test_mensajes_endpoint.py` (nuevo, 9 tests) prueba la
implementación real end-to-end -- no reemplaza a
`tests/test_mensajes.py` (Sprint S3, contrato de `FakeMensajesService`),
que sigue documentando el contrato de datos original y queda intacto.

**S11 Fase B — CERRADA: canal SSE genérico.** `core/events.py` (nuevo):
`notificar_evento()` sobre `pg_notify()` (Postgres NOTIFY/LISTEN, cero
infra nueva) -- un canal por usuario (`vridik_events_<user_id>`, no uno
global filtrado por conexión) para que Postgres entregue el evento solo a
quien le importa. Patrón "notificar-y-buscar" del roadmap: el evento
lleva solo IDs, nunca el contenido -- quien lo recibe hace un fetch
normal contra la API REST, que ya aplica permisos.

`api/events_endpoint.py` (nuevo): `GET /api/events/stream`, canal SSE
único y multiplexado por usuario (no por caso), auth con el mismo
Bearer JWT de siempre -- el roadmap pide "nunca el access token en la
URL" y recomienda fetch+ReadableStream (no `EventSource` nativo, que no
puede mandar headers). `api/mensajes_endpoint.py::crear_mensaje_endpoint`
ya lo usa: al crear un mensaje notifica `message.new` al otro
participante del caso (nunca al propio autor; sin abogado asignado
todavía, no notifica a nadie).

Heartbeat cada 25s (`: keep-alive\n\n`) incluido desde esta fase, no
diferido a la C -- es plomería necesaria para que el generador note
`request.is_disconnected()` sin bloquearse para siempre en la cola, así
que no tenía sentido esperar. Lo que sí queda para la **Fase C**:
reconexión real (`Last-Event-ID` + buffer `user_events` de 24h + evento
`resync`) -- esta versión reenvía cada NOTIFY tal cual apenas llega, sin
recuperar lo que pasó mientras el cliente estuvo desconectado (el REST
normal sigue siendo la fuente de verdad).

Verificación en dos capas, mismo patrón que `core/rate_limit.py`:
`tests/test_events.py` prueba `notificar_evento()` contra un fake (arma
la query/payload correctos) Y contra PostgreSQL real con dos conexiones
propias (`asyncpg.connect()`, nunca la fixture `db` transaccional de
`conftest.py` -- un NOTIFY solo se entrega al hacer COMMIT, y `db`
siempre hace ROLLBACK, así que ese fixture no puede probar la entrega
real). `tests/test_mensajes_endpoint.py` prueba que `crear_mensaje_endpoint`
notifica al destinatario correcto (fake).

**S11 Fase C — CERRADA: reconexión real.** `user_events` (nuevo,
`core/events.py::ensure_events_table`): buffer con TTL de 24h, purgado
oportunista en cada `notificar_evento()` (sin cron nuevo -- "cero infra
nueva" sigue aplicando). `notificar_evento()` ahora persiste el evento
(`INSERT ... RETURNING id`) ANTES de mandar el NOTIFY, y ese mismo `id`
viaja en el payload y en el campo `id:` de SSE -- es el valor que el
cliente devuelve como `Last-Event-ID` al reconectar.

`api/events_endpoint.py`: si el cliente manda `Last-Event-ID` (header
estándar de SSE, o `?last_event_id=` para debug manual con curl) y ese id
todavía está en el buffer (`core.events.existe_evento`), se reproducen
en orden los eventos posteriores ANTES de seguir con el stream en vivo.
Si no está (TTL vencido, o nunca existió para este usuario), se manda un
único evento `event: resync` -- el cliente debe asumir que su estado
puede estar desactualizado y volver a pedir todo por REST.

Orden importante documentado en el propio archivo: `add_listener()` se
activa ANTES de leer el buffer, así que un evento que llegue justo en ese
momento no se pierde -- puede aparecer duplicado (una vez en el replay,
otra vez en vivo); el cliente real es quien debe descartar por `id`
cualquier evento ya visto, esto es responsabilidad del futuro frontend,
no de este backend.

`tests/test_events.py` suma: purga del buffer (fake) y, contra
PostgreSQL real, un test de replay (`listar_eventos_desde` trae solo lo
posterior a un id dado) y uno de resync (`existe_evento` da `False` para
un id que nunca existió). No se escribió un test HTTP-level de streaming
indefinido contra un fake (TestClient no maneja bien generators SSE que
nunca terminan de forma confiable) -- la lógica de negocio que importa ya
está probada contra Postgres real; el endpoint es una capa fina de
formateo encima.

**S11 Fase D — CERRADA: no-leídos (ya resuelto en la Fase A, cursor
temporal) + `pdf.ready`/`pdf.error` enganchados al canal.**
`workers/pdf_worker.py::_notificar_pdf()` (nuevo) llama al mismo
`core.events.notificar_evento()` que usa `api/mensajes_endpoint.py`, pero
desde un **proceso completamente distinto** (el worker de PDF corre
aparte del servidor web) -- es la prueba de genericidad que pide el
roadmap para el canal SSE: no es algo atado a mensajes, es infraestructura
reusable. Se llama tras `_marcar_done()`/`_marcar_error()` en
`_procesar_trabajo()`, nunca antes -- la fila de `pdf_jobs` ya es la
fuente de verdad antes de intentar notificar.

Cuidado real encontrado: `pdf_jobs.user_id` es `TEXT`, no siempre un UUID
válido de `users.id` (puede ser `None` o un valor legacy) -- pero
`user_events.user_id` es `UUID`. `_notificar_pdf()` es deliberadamente
best-effort (try/except propio, solo logea si falla) para que un
`user_id` raro nunca deje un trabajo de PDF a medias; el job ya quedó
`done`/`error` en `pdf_jobs` antes de intentar la notificación, que es
pura optimización de latencia, no la fuente de verdad.

`tests/test_pdf_worker_events.py` (nuevo, 4 tests) prueba
`_notificar_pdf()` -- no existían tests previos de `pdf_worker.py`
(el docstring del archivo afirmaba lo contrario; quedó desactualizado,
no se corrigió esa parte por estar fuera del alcance de esta fase).

**Con esto, S11 (mensajería en tiempo real) queda completo: las 4 fases
del roadmap cerradas.** Del roadmap de Fase 1 completo, solo sigue
bloqueado **S5** (banco de evaluación, depende de Ana Luisa) y **S8-9**
(corpus 85→400+, depende de selección de documentos por Ana Luisa) --
ninguno de los dos es trabajo de código pendiente.

## S12-13 (hardening) — gaps cerrados post-S11

Revisión completa del roadmap Semana 12-13 contra lo que ya estaba en
código (2FA TOTP, headers básicos, rate limiting de login) encontró 4
gaps reales, elegidos por el dev lead para cerrar en esta sesión:

- **Endpoint huérfano — CERRADO.** `api/admin_users_endpoint.py` se borró
  entero: nunca se montaba en `app/main.py` (su chequeo de rol esperaba
  `role` DENTRO del JWT, que S1 nunca emite -- incompatible desde
  siempre con los JWT reales, `api/admin_endpoint.py` es el panel admin
  real). `core/admin_users.py` queda intacto -- `actividad_usuario()`/
  `resetear_password()` de ahí siguen en uso real vía
  `api/admin_endpoint.py`. Las pruebas HTTP del endpoint huérfano se
  quitaron de `tests/test_admin_users.py`; las pruebas de
  `core/admin_users.py` (que sí se usa) quedaron intactas.
- **Headers HSTS + CSP — CERRADO.** `api/julix_endpoint.py`:
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  (seguro sin condicionar nada, Railway sirve siempre HTTPS) y
  `Content-Security-Policy-Report-Only: default-src 'none';
  frame-ancestors 'none'` (Report-Only, no el header que aplica de
  verdad, siguiendo la secuencia del roadmap -- aunque este backend hoy
  es solo API JSON sin HTML/JS/CSS propios, así que aplicar directo
  hubiera sido seguro igual). Sin `report-uri`/`report-to` todavía --
  agregar un colector de reportes es un paso aparte si hace falta.
- **Códigos de respaldo TOTP + reset admin — CERRADO.**
  `generar_codigos_respaldo()` ya existía pero nadie los guardaba ni
  los podía usar. `core/totp_2fa.py::confirmar_activacion()` ahora
  genera y persiste los hashes (columna `totp_backup_codes`, JSONB) al
  activar el 2FA y devuelve los códigos en claro UNA vez (`POST
  /auth/2fa/verify` los suma a la respuesta). `verificar_login_totp()`
  acepta un código de respaldo como alternativa al TOTP normal -- de un
  solo uso, el hash se borra al validarlo. Nuevo `POST
  /admin/users/{id}/reset-2fa` ("perdí el teléfono"): un admin
  desactiva el 2FA de otro usuario, deja un `auth_event` `totp_reset`
  con el admin como actor (`desactivar_totp()` ahora acepta `actor_id`
  opcional).
- **2FA obligatorio para admin (`must_enroll`) — CERRADO, PENDIENTE DE
  ENROLAMIENTO REAL.** `get_current_admin()` (`api/admin_endpoint.py`)
  ahora rechaza con 403 a cualquier admin sin `totp_enabled` -- query
  separada de `_resolver_usuario()` (que comparte `get_current_user`,
  sin este requisito) para no tocar el contrato de ningún otro caller.
  Un admin sin 2FA SÍ puede seguir usando `POST /auth/2fa/setup` +
  `POST /auth/2fa/verify` (dependen de `get_current_user`, no de
  `get_current_admin`) para autoenrolarse con su mismo token -- nunca
  queda completamente afuera de su cuenta, pero sí pierde acceso al
  panel `/admin/*` hasta que lo haga.

  **Verificado antes de tocar código:** producción tiene exactamente 1
  admin real y `totp_enabled=false` -- confirmado con una lectura
  (`railway run --service Postgres`, `SELECT id, role, totp_enabled
  FROM users WHERE role='admin'`), nunca se escribió nada. El dev lead
  confirmó explícitamente seguir con el bloqueo real (no un flag suave)
  sabiendo que iba a perder acceso al panel hasta enrolarse. **Acción
  pendiente fuera de este código: correr `POST /auth/2fa/setup` +
  `POST /auth/2fa/verify` con la cuenta admin real apenas esto se
  despliegue** -- hasta entonces, el panel admin de producción queda
  inaccesible para esa cuenta.

  **Enrolamiento real completado.** La única cuenta admin de
  producción no tenía email/password conocidos por el dev lead (era de
  una sesión anterior) -- se le reseteó la password vía
  `core.admin_users.resetear_password()` (mismo mecanismo tested que
  `POST /admin/users/{id}/reset-password`, corrido como script directo
  contra Postgres porque hacía falta ya-ser-admin para llamarlo por
  HTTP, circular). La password temporal se entregó al dev lead vía un
  archivo local (nunca impresa en la salida de una herramienta --
  bloqueado una vez por el classifier de auto-mode por intentar
  imprimirla, correctamente). El dev lead hizo login, generó el
  secreto TOTP, lo cargó a mano en su autenticador (el QR salió
  corrupto por un problema de encoding en PowerShell -- se usó el
  `secret` crudo de la `otpauth_uri` en vez del PNG) y confirmó la
  activación. Verificado end-to-end: login con 2FA real, canje de
  `temp_token`, y `GET /admin/users` responde 20 usuarios con la
  cuenta real y 2FA activo. `must_enroll` queda cerrado de punta a
  punta, no solo desplegado.

## Rollback de la migración de auth (roadmap S1) — CERRADO

`ROLLBACK.md` (nuevo, raíz del repo): el rollback de referencia que
tenía comentado `migrations/005_auth_roles_refresh_tokens.sql` decía
"Fase A es puramente aditiva, revertirla no afecta el código actual" --
eso dejó de ser cierto en algún punto de esta sesión. Mapeo real de
dependencias hecho con grep contra el código actual (no supuesto):
`user_credentials` es la fuente REAL de `password_hash` desde la Fase C
(ya no una copia aditiva en paralelo), `auth_events` es load-bearing
para `core/rate_limit.py::excede_limite_login()` (el login entero
tira 500 sin esa tabla) y para el reset de 2FA, `refresh_tokens`
sostiene toda sesión activa. Un `DROP TABLE` a ciegas hoy rompe
producción.

Procedimiento real documentado: como toda migración de este proyecto es
aditiva (regla no negociable), código de una versión anterior siempre
corre seguro contra el esquema actual (más nuevo) -- el rollback
correcto es de **código** (redeploy de un commit anterior / rollback
nativo de Railway a un deployment previo), no de esquema. Limitación
declarada explícitamente en el propio documento: este proyecto no tiene
un entorno de staging real (solo Railway producción + el service
container efímero de CI), así que "ensayado en staging" no se pudo
hacer de forma literal -- se documentó qué SÍ se verificó en su lugar
(el mapeo de dependencias real, y que el principio de aditividad nunca
se violó) en vez de afirmar un ensayo que no ocurrió.

También se corrigió el comentario de rollback desactualizado en
`migrations/005_auth_roles_refresh_tokens.sql` (apunta a `ROLLBACK.md`
ahora) y se anotó `schema_semana1_vridik.sql` (el schema de CI del
roadmap-track, nunca aplicado contra Railway real) para que no se
confunda con lo que hay que revertir en producción.

## Rotación de JWT_SECRET — paso 1: desacoplar la clave de cifrado TOTP

Al arrancar la rotación de `JWT_SECRET` (último ítem puro de código de
la Fase 1 del roadmap) se encontró un problema serio ANTES de escribir
código de rotación: `core/totp_2fa.py::_fernet()` derivaba la clave de
cifrado de `totp_secret` directo de `JWT_SECRET` (SHA-256). Rotar
`JWT_SECRET` habría dejado **indescifrable para siempre** cualquier
`totp_secret` ya guardado -- incluida la cuenta admin real recién
enrolada en esta misma sesión. Como `must_enroll` (S12-13) bloquea el
panel admin sin 2FA funcional, el escenario era: rotar JWT_SECRET →
2FA del admin roto → admin no puede entrar al panel → admin no puede
resetear su propio 2FA (esa acción también requiere panel) → bloqueo
circular, solo recuperable con otro script directo a la base de datos.

**CERRADO antes de tocar la rotación en sí.** `TOTP_ENCRYPTION_KEY`
(variable de entorno nueva, independiente): `core/totp_2fa.py::_fernet()`
la usa si está configurada; si no, cae a `_fernet_legacy()` (la
derivación vieja de JWT_SECRET, comportamiento idéntico al de antes —
compatible con cualquier entorno que todavía no configuró la variable
nueva, incluida la suite de tests). `_desencriptar_secreto()` intenta
con la clave actual primero y, si falla y hay `TOTP_ENCRYPTION_KEY`
configurada, reintenta con la legacy -- así un `totp_secret` cifrado
ANTES de que la variable existiera sigue funcionando sin ninguna
migración coordinada ni ventana de corte. Confirmado con test real
(`test_rotar_jwt_secret_no_rompe_un_secreto_cifrado_con_totp_encryption_key`):
cifrar con `TOTP_ENCRYPTION_KEY` configurada, rotar `JWT_SECRET` por
completo, y descifrar sigue funcionando.

**Paso 1 desplegado y verificado.** `TOTP_ENCRYPTION_KEY` generada
(Fernet) y configurada en Railway vía `railway variable set --stdin`
(la clave nunca tocó la salida de ninguna herramienta). El redeploy la
cargó; verificado end-to-end en producción real con un usuario de
prueba: enrolar 2FA (cifra con la clave nueva) + login con 2FA
(descifra con la clave nueva) funciona. La cuenta admin real sigue
usando el fallback legacy (su secreto se cifró antes de que la variable
existiera) -- sin romperse.

## Rotación de JWT_SECRET — paso 2: soporte de doble clave + SECURITY.md — CERRADO

`core/auth.py`: las claves de firma/verificación se leen de `os.environ`
en CADA llamada (antes eran constante de módulo leída al importar) --
por dos motivos: que una rotación vía variable + redeploy tome efecto
sin reimportar, y que los tests puedan monkeypatchear. Firmar
(`create_jwt`/`create_temp_2fa_token`) usa siempre la clave ACTUAL
(`_jwt_secret_actual()`); verificar (`decode_jwt`/`decode_temp_2fa_token`)
acepta la actual Y la anterior (`JWT_SECRET_PREVIOUS`, si está
configurada, vía `jwt_secrets_para_verificar()`). Un token expirado se
corta como resultado definitivo (no se prueba la otra clave -- la firma
ya era válida con la primera). `api/julix_endpoint.py::_decodificar_jwt`
reutiliza la misma `jwt_secrets_para_verificar()` (no duplica la lista
de claves de la ventana de rotación).

`SECURITY.md` (nuevo): procedimiento de rotación de 5 pasos (guardar la
actual como PREVIOUS → poner la nueva → verificar la ventana → esperar
~15 min a que caduquen los access tokens viejos → borrar PREVIOUS),
tabla de qué depende de `JWT_SECRET` y qué NO (refresh tokens son
opacos, no JWT; contraseñas bcrypt; totp_secret ya desacoplado), y la
limitación honesta de "ensayado en staging" (no hay staging real -- se
documentó qué SÍ se verificó: los tests de doble clave y el desacople
TOTP end-to-end en producción).

`tests/test_jwt_rotation.py` (nuevo, 12 tests): token viejo valida
durante la ventana y deja de valer al cerrarla, token nuevo valida,
clave desconocida se rechaza, expirado se rechaza, temp token de 2FA
emitido antes de rotar se canjea durante la ventana, un access token
normal nunca sirve como temp token de 2FA. Efecto colateral del cambio
import-time → call-time: `tests/test_julix_stream.py` parcheaba el
atributo de módulo `JWT_SECRET` (ya no surte efecto) -- se cambió a
`monkeypatch.setenv`, mismo resultado.

Análisis que respaldó el diseño: el impacto real de rotar `JWT_SECRET`
es acotado porque los refresh tokens NO son JWT (tokens opacos
hasheados, no dependen de la clave) -- una sesión con refresh válido se
recupera sola en ≤15 min vía `POST /auth/refresh`. La doble clave cubre
la ventana de esos 15 min (access tokens) y los 5 min del temp token de
2FA, para que nadie con una sesión activa vea un 401 durante la
rotación.

**Pendiente: la rotación en sí NO se ejecutó** -- solo el soporte está
desplegado. `JWT_SECRET_PREVIOUS` no está configurada (no hay rotación
en curso), así que el comportamiento es idéntico al de antes.
Ejecutarla es un procedimiento operativo (ver SECURITY.md), a correr
solo si hace falta (sospecha de filtración, o rotación preventiva) --
no es trabajo de código pendiente.

## Consolidación de producto (post-auditoría)

Decisión del dev lead: **el copiloto legal (JuliX/RAG) es el producto
real**, no el marketplace. Trabajo ya cerrado en esta dirección:

- **Fase C de auth (parcial) — CERRADA.** `POST /auth/login` ahora lee
  `password_hash` de `user_credentials` (LEFT JOIN), no de
  `users.hashed_password` (esa columna se queda, nunca se soltó -- sin
  DDL destructivo). Fix encontrado y necesario antes del cutover:
  `core/admin.py::create_user()` (POST /admin/users) nunca escribía en
  `user_credentials` -- solo `/auth/register` y `resetear_password()` lo
  hacían -- se corrigió con el mismo dual-write. Deliberadamente NO se
  tocó `role`→`role_id` (RBAC funciona perfecto con la columna TEXT,
  cero beneficio real, alto riesgo). Verificado end-to-end en producción.
- **`pdf_jobs` — el desajuste de schema documentado en
  `migrations/003_pdf_jobs.sql` ya estaba resuelto** (alguien ajustó
  `workers/pdf_worker.py` para usar el schema real en algún punto
  anterior a esta sesión) -- el comentario de la migración solo estaba
  desactualizado, se corrigió.
- **`case_documents` commiteado.** `api/case_documents_endpoint.py` +
  `core/case_documents.py` llevaban sin commitear desde antes de esta
  sesión (se subían en cada `railway up` porque ese comando sube el
  directorio de trabajo, no el estado de git) -- riesgo real de
  desaparecer si algún día Railway despliega desde git en vez del CLI.
  Ya en el historial. Conecta las dos rutas: una orden del marketplace
  ES el caso legal, JuliX genera el documento sobre esa orden.
- **`.gitignore` agregado** + 69 `.pyc` destrackeados (nunca debieron
  estar en git).
- **Migración de vocabulario de roles — CERRADA.** `admin/seller/
  customer` → `admin/abogado/cliente` en `roles.codigo` y `users.role`
  (`migrations/006_roles_vocabulario_legal.sql`), y en todo el código
  que compara contra esos valores (`core/permissions.py`,
  `api/admin_endpoint.py`, `core/admin.py`). Alcance deliberadamente
  acotado: `seller_id` (columna FK), `get_current_seller()` (nombre de
  función), y el prefix `/seller` del router NO se tocaron -- son
  conceptos de dominio del marketplace (quién es dueño de un producto),
  no valores de rol; se revisan en la fase de desmantelamiento, no en
  esta migración de vocabulario. Verificado end-to-end en producción:
  19 usuarios reales migrados (7 abogado, 1 admin, 11 cliente), 0 con
  vocabulario viejo.

- **Rediseño `casos` — CERRADO.** `core/case.py`/`api/casos_endpoint.py`:
  entidad `casos` (cliente_id, abogado_id, estado) independiente del
  marketplace. `case_documents` ahora ancla a `caso_id` **o** `order_id`
  (uno de los dos; `order_id` pasó a nullable). Rutas nuevas
  `POST/GET /casos/{id}/documents`; `/orders/{id}/documents` se
  mantiene por compatibilidad hasta desmantelar `orders` de verdad.
  Verificado en producción real (`POST/GET /casos` end-to-end). Esto
  desbloquea poder desmantelar `orders` sin romper la generación de
  documentos de JuliX.

**Desmantelamiento del marketplace — alcance confirmado por el dev
lead: completo** (`seller_endpoint.py` + `products` + `orders`,
incluye decidir qué pasa con Wompi). Se verificó antes de tocar nada
que los datos de producción en esas tablas (2 products, 3 orders, 1
payment) son datos de prueba de S1-S7, no clientes reales -- confirmado
por el dev lead, se pueden descartar sin migración.

Progreso, fase por fase (cada fase = un commit, probado local, CI
verde, desplegado y verificado en producción antes de pasar a la
siguiente):

- **Fase 1 — CERRADA.** `api/seller_endpoint.py` (la pieza más
  aislada: nadie más lo importaba salvo `app/main.py` y su propio test
  file `tests/test_permissions.py`, ambos removidos) +
  `core/order.py::list_orders_for_seller` (código muerto, solo lo
  llamaba `seller_endpoint.py`).
- **Fase 2 — CERRADA.** Gestión admin de productos/órdenes/imágenes
  quitada de `api/admin_endpoint.py`: `post_products`/`patch_product`/
  `delete_product`/`post_product_image`/`delete_product_image`/
  `post_product_image_primary`/`get_orders`/`patch_order_status`, sus
  Pydantic models, y `get_current_seller()` (ya sin llamadores tras la
  fase 1). `core/product.py` quedó solo de lectura (se quitaron
  `create_product`/`update_product`/`soft_delete`/`add_image`/
  `get_image`/`delete_image`/`set_primary`) -- el catálogo público
  (`api/products_endpoint.py`) sigue intacto, no depende de esas
  funciones. `core/order.py::list_all_orders` también se quitó (código
  muerto); `update_status()` sigue viva porque
  `api/payments_endpoint.py` la llama al confirmar un pago Wompi (el
  branch de "cancelled + restaurar stock" quedó sin ninguna ruta HTTP
  que lo dispare, pero se conservó con un test directo contra la
  función en `tests/test_orders.py` en vez de borrarlo -- es lógica
  real, no muerta, solo sin exponer todavía).
- **Fase 3 — CERRADA.** `api/payments_endpoint.py`, `core/payment.py`,
  `core/wompi.py` y `tests/test_payments.py` se borraron enteros:
  decisión tomada (no dejarlos dormidos) porque dependían por completo
  de `orders` (una tabla también en desmantelamiento) y no había
  ninguna transacción real en producción -- queda todo en el
  historial de git si hace falta resucitarlos más adelante sobre
  `casos`, con un modelo de cobro nuevo a diseñar, no una resurrección
  literal. Efecto colateral encontrado y limpiado: `python-multipart`
  (`requirements.txt`/`requirements-test.txt`) había quedado huérfano
  desde la fase 2 (solo lo usaba la ruta de upload de imágenes ya
  removida) -- se quitó en el mismo commit.
  `core.order.update_status()` (con el branch de restaurar stock al
  cancelar) queda sin ningún caller HTTP tras esto -- se revisa en la
  fase 4, no se tocó acá.
- **Fase 4 — código cerrado, falta el drop de tablas.** Se borraron
  enteros `api/orders_endpoint.py`, `core/order.py`,
  `api/products_endpoint.py`, `core/product.py`. Efecto colateral
  encontrado y limpiado en el mismo commit: `core/permissions.py`
  (`check_owner`/`PERMISSIONS`/`has_permission`) y `core/storage.py`
  (`save_file`/`delete_file`/`ensure_storage`, exclusivo de imágenes
  de producto) quedaron sin ningún llamador tras sacar
  products/orders -- se borraron también, junto con el mount
  `/uploads` en `app/main.py`. La ruta legacy
  `/orders/{id}/documents` se quitó de `case_documents_endpoint.py` y
  `core/case_documents.py` volvió a ser solo `caso_id` (la tabla
  `case_documents` nunca había llegado a crearse en producción --
  verificado antes de tocar código -- así que no había ningún
  documento real que preservar). `core.order.update_status()` se fue
  con el resto de `core/order.py` (ya no tenía caller HTTP desde la
  fase 3).

  **DROP TABLE ejecutado y verificado — FASE 4 CERRADA, DESMANTELAMIENTO
  COMPLETO.** Con el código ya desplegado y verificado en verde (404 en
  todas las rutas removidas, `casos`/`admin`/auth intactos), se corrió
  `DROP TABLE IF EXISTS payments, order_items, product_images, orders,
  products CASCADE` contra la Postgres de producción real (vía
  `railway run --service Postgres`). Conteo justo antes del drop: 1
  payment, 3 order_items, 1 product_image, 3 orders, 2 products (los
  mismos datos de prueba confirmados descartables). Las 5 tablas
  verificadas como no existentes después. Producción re-verificada
  sana post-drop: health 200, `casos` 200, `admin/users` 403 (rol
  correcto). El marketplace (Vridik Abogados, sprints S1-S7 originales)
  ya no existe en código ni en base de datos — el copiloto legal
  (`casos`/`case_documents`/JuliX) es el único producto.
