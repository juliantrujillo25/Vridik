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
- **S5-GAP-01 (bloqueante) — SIGUE BLOQUEADO.** No es código: falta que
  Ana Luisa llene `respuesta_esperada` en `eval/banco_casos_vridik.xlsx`
  (20 casos). Sin esto, `eval/evaluador.py --commit` no tiene nada que
  evaluar y el GATE de Fase 1 (>=80% aprobación) nunca puede correr.
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
A/B, S2, S3, S4, S6, S7). Solo **S5** sigue abierto, y depende
enteramente de Ana Luisa, no de más trabajo de código.

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
- **Fase 3 — pendiente.** Pagos (`api/payments_endpoint.py`,
  `core/payment.py`, `core/wompi.py`) -- depende de `orders`, real
  integración de dinero (aunque sin transacciones reales en
  producción); decidir si se borra del todo o se deja dormida.
- **Fase 4 — pendiente.** `orders_endpoint.py`/`core/order.py`
  restante, quitar la ruta legacy `/orders/{id}/documents` de
  `case_documents`, y el drop de las tablas
  (`products`/`orders`/`order_items`/`product_images`/`payments`) vía
  migración.
