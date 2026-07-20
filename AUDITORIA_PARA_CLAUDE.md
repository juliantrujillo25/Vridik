# AUDITORIA VRIDIK S1-S7 PARA CLAUDE CODE

## Resumen Ejecutivo

`vridik_roadmap.md`/`.json` (fuente de verdad) define S1-S7 como: auth con roles/refresh tokens/rotación, panel admin con bitácora, suite de tests con cobertura real, JuliX con Claude y 5 fallos domados, banco de evaluación GATE, iteración de prompts documentada, y pipeline de ingesta de corpus con validador de citas. El código realmente montado en `app/main.py` y desplegado en Railway (`api/auth_endpoint.py`, `core/auth.py`, `api/admin_endpoint.py`) es una implementación paralela y más simple que NO usa `schema_semana1_vridik.sql` (roles/user_credentials/refresh_tokens) ni cumple varios criterios de salida del roadmap. S4 (JuliX/Claude) y S9 (re-ranking, fuera de alcance aquí) son los más sólidos. El GATE de S5 nunca se ejecutó (Ana Luisa no llenó `respuesta_esperada`), por lo que Fase 1 no está formalmente certificada contra el roadmap pese al 86/86 del backlog operativo.

## Gaps Bloqueantes

- ID: S1-GAP-01
- Sprint Roadmap: "Esquema: users (UUID, citext, soft delete, legacy_username), roles (tabla), user_credentials (argon2id, must_change), refresh_tokens (hash, rotación, revocables), auth_events" + "access JWT 15min + refresh rotativo con detección de reuso"
- Estado actual: Bug prod - Evidencia: `schema_semana1_vridik.sql:21-138` define el esquema completo del roadmap, pero `core/auth.py:44-58` (`ensure_users_table`) crea una tabla `users` distinta (id, email, is_active, created_at, hashed_password) sin `roles`, `user_credentials`, `refresh_tokens` ni `citext`. `api/auth_endpoint.py` no tiene endpoints `/auth/refresh` ni `/auth/logout` (grep de `refresh_token|family_id|token_hash` en ese archivo: sin resultados). El JWT vive 60 min (`JWT_EXPIRE_MINUTES`), no 15, y no hay revocación de sesión posible.
- Instrucción atómica para Claude Code: Modifica `core/auth.py` para que `ensure_users_table()` aplique el esquema real de `schema_semana1_vridik.sql` (tablas `roles`, `user_credentials`, `refresh_tokens`) y agrega en `api/auth_endpoint.py` los endpoints `POST /auth/refresh` (rota el refresh token, detecta reuso vía `family_id`) y `POST /auth/logout` (revoca el refresh token activo).
- Criterio de Aceptación: `pytest tests/test_auth.py tests/test_refresh_tokens.py -q` (crear el segundo archivo) debe pasar, incluyendo un test que reutiliza un refresh token ya usado y espera 401 con revocación de toda la familia.
- Prioridad: Bloqueante

- ID: S5-GAP-01
- Sprint Roadmap: "GATE: ≥60% en global 3-4 para continuar; si no se cumple, S6 se redefine como diagnóstico exclusivo"
- Estado actual: No existe - Evidencia: `backlog_fase1_vridik.md:26` y `data/roadmap_status.md:13,35` documentan que `eval/banco_casos_vridik.xlsx` tiene la columna `respuesta_esperada` vacía — nunca la llenó Ana Luisa. `eval/evaluador.py --commit` (mencionado en `backlog_fase1_vridik.md:97`) no tiene nada que evaluar sin esos datos. El GATE nunca se ejecutó.
- Instrucción atómica para Claude Code: No modifiques código: bloquea cualquier trabajo nuevo sobre JuliX/prompts hasta recibir `eval/banco_casos_vridik.xlsx` con `respuesta_esperada` completo, y entonces corre `python eval/evaluador.py --commit`.
- Criterio de Aceptación: `python eval/evaluador.py --commit` debe terminar imprimiendo el porcentaje de casos con `score>=4` y sin `hallucination_flag`; el gate pasa si es ≥60%.
- Prioridad: Bloqueante

## Gaps Alta y Media

- ID: S2-GAP-01
- Sprint Roadmap: "Sección Actividad por usuario leyendo auth_events" + "reset contraseña" (CRUD admin)
- Estado actual: Parcial - Evidencia: `api/admin_endpoint.py:194-387` (router real, montado en `app/main.py`) solo expone `GET/POST /users`, `PATCH /users/{id}/role` y rutas de productos/órdenes/imágenes — no hay `GET /users/{id}/actividad` ni ningún endpoint de reset de contraseña. Esas rutas sí existen en `api/admin_users_endpoint.py` (`/actividad`, `/reset`) pero ese router está desmontado (`app/main.py` comentario: "ya no se montan aquí").
- Instrucción atómica para Claude Code: Modifica `api/admin_endpoint.py` para agregar `GET /users/{user_id}/actividad` (lee `auth_events` filtrado por `user_id`) y `POST /users/{user_id}/reset-password` (genera password temporal, fuerza cambio en próximo login).
- Criterio de Aceptación: `curl -s -o /dev/null -w "%{http_code}" -X GET $BASE_URL/admin/users/USER_ID/actividad -H "Authorization: Bearer $ADMIN_TOKEN"` debe devolver `200`.
- Prioridad: Alta

- ID: S3-GAP-01
- Sprint Roadmap: "GitHub Actions: cov-fail-under=50 (sube a 60 al cierre)" + "CONTRIBUTING.md con 3 reglas"
- Estado actual: No existe - Evidencia: `.github/workflows/ci.yml:88` solo aplica `scripts/check_pass_ratio.py --threshold 0.90` (ratio de tests verdes, no cobertura de código); no hay `cov-fail-under` ni `pytest --cov` en el workflow. `CONTRIBUTING.md` no existe en el repo (glob sin resultados).
- Instrucción atómica para Claude Code: Modifica `.github/workflows/ci.yml` para agregar `pytest --cov=. --cov-fail-under=60` en el job `test`, y crea `CONTRIBUTING.md` con las 3 reglas del roadmap (bug en prod gana test antes del fix; flaky se arregla o se borra esa semana; contratos solo cambian con anuncio).
- Criterio de Aceptación: `pytest --cov=. --cov-fail-under=60 -q` debe correr sin el flag `--no-cov-on-fail` y fallar el job si la cobertura real cae debajo de 60%.
- Prioridad: Media

- ID: S4-GAP-01
- Sprint Roadmap: "API keys separadas staging/producción" + "corrida de humo: 3 casos x 2 modelos con costos comparados"
- Estado actual: Implementado (parcial) - Evidencia: `julix/client.py` resuelve `ANTHROPIC_API_KEY_STAGING`/`ANTHROPIC_API_KEY_PROD` con fallback a `ANTHROPIC_API_KEY` (líneas 117-125), tamed 5 modos de fallo (timeout/429/529/truncado/formato, líneas 196-271), `MODEL_BY_TASK` selecciona modelo por tarea (línea 91). No evidenciado: si las variables de entorno separadas están realmente configuradas en Railway (no hay archivo de variables reales en las carpetas de trabajo), y la corrida de humo de 3 casos x 2 modelos con costos comparados no tiene artefacto de salida en el repo.
- Instrucción atómica para Claude Code: No modifiques código: corre `python eval/evaluador.py --dry-run` seguido de una corrida real de 3 casos contra Sonnet y Haiku, y guarda el reporte de costos en `eval/corrida_humo_s4.json`.
- Criterio de Aceptación: `test -f eval/corrida_humo_s4.json && echo OK` debe imprimir `OK` con al menos 6 registros (3 casos x 2 modelos).
- Prioridad: Media

- ID: S6-GAP-01
- Sprint Roadmap: "Publicar PROMPTS.md (versiones, patrones de fallo, reglas de oro heredables)"
- Estado actual: No existe - Evidencia: glob de `PROMPTS.md` en la raíz del repo sin resultados. Existen prompts versionados (`julix/prompts/v1_ugpp_demanda.md`, `v2_laboral_consulta.md`, `v3_litigio_colombia.md`, `v3_laboral_colombia.md`) pero ninguna bitácora consolidada de iteración con hipótesis por versión.
- Instrucción atómica para Claude Code: Crea `PROMPTS.md` en la raíz documentando cada versión de `julix/prompts/*.md` con su hipótesis de cambio, patrón de fallo que la motivó y resultado de la corrida de prueba correspondiente.
- Criterio de Aceptación: `test -f PROMPTS.md && grep -c "^## v" PROMPTS.md` debe devolver un número ≥4 (una sección por versión de prompt existente).
- Prioridad: Media

- ID: S7-GAP-01
- Sprint Roadmap: "Esquema corpus_documents (jerarquia, vigencia, fuente_url, hash) + corpus_chunks (referencia citable)" + "Validador de citas post-generación en JuliX (cita ↔ referencia en contexto)"
- Estado actual: Parcial - Evidencia: `rag/sql/rag_chunks_schema.sql:9-13` documenta explícitamente que `rag_chunks` es "una versión más ligera que corpus_documents/corpus_chunks... del roadmap original" — no existen esas tablas. Grep de `validador|valida.*cita|cita.*referencia` en `julix/service.py` sin resultados: no hay validación post-generación de que cada cita corresponda a una referencia presente en el contexto, solo una directiva en el system prompt (`DIRECTIVA_FUENTE_OBLIGATORIA`) que depende de que el modelo la respete.
- Instrucción atómica para Claude Code: Modifica `julix/service.py` para agregar una función `validar_citas_post_generacion(respuesta, chunks_usados)` que verifique con regex que cada norma/artículo citado en la respuesta aparece en al menos un chunk del contexto, y marque `[revisar]` si no.
- Criterio de Aceptación: `pytest tests/test_validador_citas.py -q` (crear el archivo) debe pasar con un caso donde la respuesta cita una norma ausente del contexto y el resultado queda marcado `[revisar]`.
- Prioridad: Alta

## Checklist Verificación Final Prod S6+S7

```bash
curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/products"

curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/products?category=penal"

curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/seller/products" -H "Authorization: Bearer $CUSTOMER_TOKEN"

curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE_URL/orders/$ORDER_ID/pay" -H "Authorization: Bearer $BUYER_TOKEN"

curl -s -o /dev/null -w "%{http_code}\n" -X POST "$BASE_URL/webhooks/wompi" -H "Content-Type: application/json" -d '{"event":"transaction.updated","data":{"transaction":{"id":"x","status":"APPROVED","reference":"r1"}},"signature":{"properties":["transaction.id"],"checksum":"firma-invalida"},"timestamp":1234567890}'
```

Resultados esperados: 200, 200, 403, 201, 401.
