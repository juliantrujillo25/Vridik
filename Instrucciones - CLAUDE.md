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

**No fusiones automáticas.** Antes de tocar auth, confirma con el dev lead
cuál de las dos rutas es la que se quiere llevar a producción de verdad:
migrar la rama montada al esquema de `schema_semana1_vridik.sql`, o
actualizar `vridik_roadmap.md` para reflejar que el diseño cambió.

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
- Resto de gaps (S2 a S7 del backlog) — sin empezar todavía.
