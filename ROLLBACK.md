# Vridik — Rollback de la migración de auth (roadmap S1, Fase A)

Pedido por el roadmap (`vridik_roadmap.md`, Semana 1): *"Migración sin
downtime en 4 etapas: preparación → doble lectura con evento
`legacy_fallback` como detector → corte tras 48h sin fallbacks →
`ROLLBACK.md` ensayado en staging."*

## Contexto

`migrations/005_auth_roles_refresh_tokens.sql` (Fase A, aditiva) agregó
`roles`, `user_credentials`, `refresh_tokens`, `auth_events` sobre el
esquema real de `users` que ya corría en producción — sin tocar
`users.role`/`users.hashed_password`. Se aplicó contra la Postgres real
de Railway; verificado en su momento: 4 tablas nuevas, cero regresiones.

## Por qué el rollback original (SQL comentado al final de la migración)
## ya NO es seguro

El comentario `-- Rollback de referencia` al final de
`migrations/005_auth_roles_refresh_tokens.sql` decía *"Fase A es
puramente aditiva -- revertirla no afecta el código actual"*. Eso era
cierto **en el momento en que se escribió**, pero dejó de serlo: sesiones
posteriores (Fase B, Fase C, y el hardening S12-13) construyeron
funcionalidad real sobre esas tablas. Hoy, correr ese `DROP TABLE` a
ciegas rompería producción de verdad:

| Tabla | Quién depende de ella hoy | Qué se rompe si se dropea |
|---|---|---|
| `user_credentials` | `core/admin.py`, `core/admin_users.py`, `core/feature_flag_legacy.py`, `api/admin_endpoint.py`, `api/auth_endpoint.py` | **`POST /auth/login` deja de poder autenticar a nadie** -- desde la Fase C (S1-GAP-01) esta tabla es la fuente REAL de `password_hash`, no una copia aditiva en paralelo. `users.hashed_password` ya no se lee en el login real. |
| `refresh_tokens` | `core/admin_users.py`, `core/auth.py`, `core/refresh_tokens.py`, `core/totp_2fa.py`, `api/auth_endpoint.py` | `POST /auth/refresh`/`/auth/logout` 500 en cada llamada; ninguna sesión puede renovarse sin volver a loguear. |
| `auth_events` | `core/admin_users.py`, `core/auth_events.py`, `core/feature_flag_legacy.py`, `core/rate_limit.py`, `core/totp_2fa.py`, `api/admin_endpoint.py`, `api/auth_endpoint.py` | **`POST /auth/login` deja de funcionar directamente** -- `core/rate_limit.py::excede_limite_login()` consulta esta tabla ANTES de verificar la contraseña; sin la tabla, esa query lanza un error de Postgres y el login entero cae con 500. También rompe el reset de 2FA (`totp_reset`) y toda la sección "Actividad" del panel. |
| `roles` | Herencia del schema del roadmap (`schema_semana1_vridik.sql`) -- no se usa desde la rama realmente montada en producción (que usa `users.role` TEXT, no `role_id`) | Bajo riesgo real hoy, pero dropearla sin revisar podría romper la suite de tests del roadmap track (`tests/test_auth.py`, `db`/`seed_roles` fixture) si alguna vez se corre contra esa tabla en un entorno real. |
| Columnas de `users` (`role_id`, `must_change`, `deactivated_at`, `deleted_at`, etc.) | `core/admin_users.py::resetear_password()` usa `must_change`; varios endpoints filtran por `deleted_at IS NULL` | `must_change` es justo lo que fuerza a un usuario con password temporal (reset admin, ver `POST /admin/users/{id}/reset-password`) a cambiarla -- perder la columna no rompe el login, pero silencia esa protección. |

**Conclusión: un rollback de esquema (DROP TABLE/DROP COLUMN) sobre
producción HOY es de alto riesgo y probablemente indeseable.** El
esquema es un superset aditivo estable -- no hay ninguna razón real para
revertirlo salvo un bug específico introducido por una migración
posterior, y en ese caso el rollback correcto casi siempre es de
**código**, no de base de datos.

## Procedimiento de rollback real recomendado (código, no esquema)

Porque toda migración de este proyecto es aditiva (`CREATE TABLE IF NOT
EXISTS`, `ADD COLUMN IF NOT EXISTS` -- regla no negociable, ver
`Instrucciones - CLAUDE.md`), el código de una versión **anterior**
siempre puede correr contra el esquema **actual** (más nuevo) sin
romperse: las columnas/tablas que ese código viejo no conoce
simplemente no las toca. Esto significa que el camino seguro para
deshacer un despliegue problemático es:

1. **Identificar el último deployment bueno conocido:**
   ```bash
   railway deployment list --service vridik-api
   ```
2. **Redesplegar ese commit específico** (no hace falta revertir nada en
   la base de datos):
   ```bash
   git checkout <commit-bueno>
   railway up --service vridik-api --detach
   ```
   o, si el problema es reciente y el deploy anterior sigue disponible en
   Railway, usar el rollback nativo de Railway sobre el deployment
   anterior en vez de re-subir código.
3. **Verificar** con los mismos chequeos de siempre (`/health`, un
   `POST /auth/register` + `login` de prueba, revisar
   `railway logs --service vridik-api` por errores nuevos).
4. **Nunca** correr un `DROP TABLE`/`DROP COLUMN` como parte de este
   proceso salvo que el problema sea específicamente de esquema (p.ej.
   una migración con un `CREATE TABLE` mal escrito que hay que rehacer)
   -- y en ese caso, mapear las dependencias reales primero (la tabla de
   arriba es el punto de partida, pero hay que re-verificarla porque
   sigue cambiando con cada sesión).

## Staging real (T6 del roadmap, 21-jul-2026)

Ya existe un entorno de staging persistente en Railway (`staging-vridik`
-- servicios `vridik-api`/`vridik-frontend`/`Postgres` propios, separados
de producción, creado como clon estructural de producción con
`railway environment new <nombre> --duplicate production`, **nunca**
con los datos reales -- el volumen de Postgres nace vacío). Ver
`SECURITY.md` para el mismo update.

Al levantarlo se encontró (y arregló, commit `55ae2da`) un bug real que
solo se manifiesta con una base de Postgres genuinamente vacía:
`ensure_auth_migration_005`/`ensure_despachos_backfill`/etc. asumían que
`users` ya existía (cierto en producción desde hace meses, nunca antes
puesto a prueba) -- exactamente el tipo de cosa que "ensayado en
staging" está pensado para atrapar.

**Todavía no se ensayó un rollback real** (deploy de un commit viejo
contra el esquema de staging ya migrado) -- este entorno recién se armó,
el ensayo en sí queda como siguiente paso antes de confiar ciegamente en
este documento contra producción.

Lo que sí se verificó, sin tocar producción, antes de que staging
existiera:
- El mapeo de dependencias de la tabla de arriba (grep real contra el
  código actual, no una suposición).
- Que el principio "código viejo corre seguro contra esquema nuevo" se
  cumple por diseño en todas las migraciones de este proyecto (regla no
  negociable de aditividad, nunca violada hasta la fecha).
