# Vridik - Auditoría Forja vs Cuida tus mascotas

Fecha: 21-jul-2026. Referencia de oro: "Cuida tus mascotas" (Next.js 16 + Supabase + RLS + PWA). Metodología: las 11 etapas de La Forja aplicadas a Vridik.

## Corrección de premisa (esto es parte de la auditoría, no un tecnicismo)

El contexto que me pasaste describe un Vridik que ya no existe. Contra el repo real al 21-jul:

| Deuda declarada | Realidad verificada en el repo |
|---|---|
| "0 tests" | **437 funciones de test** en `tests/` |
| "usuarios en ENV" | Users en Postgres (`users` + `user_credentials`, login lee de ahí) |
| "sin 2FA real" | TOTP completo + backup codes + `must_enroll` admin, en producción |
| "sin SSE" | S11 completo: canal SSE `/api/events/stream`, NOTIFY/LISTEN, reconexión |
| "sin RLS real" | `core/rls.py` con RLS de Postgres en 4 tablas (users, casos, julix_calls, matriz_riesgo) — **incompleto, no inexistente** |
| "Stack Next.js" | Backend **FastAPI + asyncpg**; frontend **React + Vite + TS** (no Next.js) |

Esto cambia la naturaleza de la auditoría: Vridik **no** necesita "llegar a RLS", necesita **completar** el RLS que ya empezó (5 tablas más) y decidir si migra su Postgres autogestionado a Supabase. Audito contra eso.

**Sobre migrar a Supabase:** mascotas usó Supabase porque partió de cero en un día. Vridik ya tiene RLS nativo de Postgres funcionando, 437 tests, refresh tokens con rotación, y despliegue en Railway. Migrar a Supabase te daría Auth+Storage+RLS gestionados y Edge Functions, pero **botarías** un stack de auth que ya está en percentil alto y reescribirías 437 tests contra otra plataforma. Mi recomendación honesta: **adoptar el patrón Supabase (RLS por fila desde el diseño, Storage gestionado, PWA) SIN migrar el motor** — completar RLS sobre tu Postgres actual, mover Storage a R2/S3 (ya abstraído en `storage/object_storage.py`), y sumar PWA al frontend React. Abajo doy el SQL RLS igual, ejecutable, porque la sintaxis de `CREATE POLICY` es idéntica en Postgres puro y en Supabase (Supabase ES Postgres). Donde mascotas usa `auth.uid()`, Vridik usa `current_setting('vridik.current_user_id')` que ya setea su middleware.

## Score Forja (etapas cumplidas antes de codificar)

Cuánto de las 11 etapas de La Forja Vridik puede documentar hoy:

| Etapa | Estado Vridik | Nota |
|---|---|---|
| 1. Modelo de negocio | 🟡 Parcial | Roadmap menciona Radar/Cobro/Bóveda como features, no como planes con precio |
| 2. PDR | 🟡 Parcial | `vridik_roadmap.md` es más blueprint que PDR de problema |
| 3. Spec técnica | 🟢 Sí | Stack documentado, migraciones idempotentes, `Instrucciones - CLAUDE.md` |
| 4. UX personas | 🔴 No | No existe documento de personas |
| 5. Journey maps | 🔴 No | El "loop de término" está en código (alertas) pero no mapeado como journey |
| 6. User stories | 🔴 No | Roadmap en tareas técnicas, no en historias de usuario |
| 7. Diseño de pantallas | 🟡 Parcial | Frontend existe, sin documento de diseño |
| 8. Auditoría de seguridad | 🟢 Sí | `vridik_audit.md`, `SECURITY.md`, RLS parcial |
| 9. Pre-mortem | 🔴 No | Riesgos dispersos en roadmap, sin pre-mortem formal |
| 10. Blueprint por fases | 🟢 Sí | Plan 30-60-90 + `HANDOFF_CLAUDE_CODE.md` |
| 11. Verificación contra DB real | 🟢 Sí | Corridas reales del GATE, verificación en producción documentada |

**Score Forja: 5.5 / 11.** Vridik es fuerte en lo técnico (spec, seguridad, blueprint, verificación) y débil exactamente donde mascotas brilla: **producto** (personas, journeys, historias, pre-mortem). Ese es el gap real, no el stack.

## Lo que mascotas hace perfecto y Vridik no tiene

1. **Producto antes que código.** Mascotas hizo 11 etapas de definición ANTES de la primera migración. Vridik construyó primero y documenta después. Se nota: tiene 437 tests pero cero personas escritas.
2. **Un "loop" con gancho emocional.** El loop de comida predictivo ("te avisa antes de que se acabe la bolsa") es un motivo para volver cada día. Vridik tiene alertas de términos en código, pero no las trata como el corazón del producto.
3. **Gamificación con propósito.** XP, racha 🔥, care-score: convierten una tarea aburrida en hábito. Vridik no tiene ni un solo elemento de esto.
4. **Modo Perdido / QR público.** Una ficha compartible sin login. Vridik obliga a login para todo; no tiene forma de compartir un caso con un cliente sin crearle cuenta.
5. **PWA instalable + animaciones.** Se siente app nativa. El frontend de Vridik es un SPA React sin PWA ni motion.
6. **RLS desde la migración 1.** Mascotas nunca tuvo un momento sin aislamiento por fila. Vridik lo agregó tarde y a medias (4 de 9 tablas).

## Adaptaciones concretas (mascotas → Vridik)

| Feature mascotas | Adaptación Vridik | Viabilidad |
|---|---|---|
| Loop de comida predictivo | **Loop de término**: JuliX avisa T-5 / T-3 / T-1 días antes del vencimiento CPACA/CPT | Alta — `procesal/alertas_terminos.py` ya corre cada 6h; falta escalonar y notificar por SSE |
| care-score por mascota | **health-score por proceso** (0-100, ver fórmula abajo) | Alta — todos los inputs ya existen en `terminos`/`actuaciones` |
| Racha 🔥 de cuidado | **Racha de cumplimiento**: días consecutivos sin término vencido | Alta — se calcula sobre `terminos` |
| XP + nivel del dueño | **XP por término cumplido a tiempo**, nivel del abogado/despacho | Media — tabla nueva `gamificacion` |
| Logros ("primera vacuna") | **Logros** ("10 tutelas ganadas", "100 términos sin vencer") | Media — tabla `logros` |
| Modo Perdido + QR | **Modo Urgente**: ficha pública de caso (estado + próximo término) por QR, token firmado, sin login | Media — endpoint público read-only con token de un solo caso |
| PWA instalable | **PWA Vridik** (manifest + service worker en el frontend Vite) | Alta — `vite-plugin-pwa` |
| canvas-confetti al completar | Confetti al **cerrar un caso ganado** o cumplir una racha | Baja/estética |
| Storage Supabase | **R2/S3** para PDFs (ya abstraído en `storage/object_storage.py`) | Alta — es T5 del handoff |
| Edge Functions | **Workers FastAPI** ya existentes (`workers/pdf_worker.py`) | N/A — ya cubierto |

## RLS Supabase propuesto (SQL real, ejecutable)

Vridik ya tiene RLS en `core/rls.py` para 4 tablas con `despacho_id` directo. Faltan las 5 tablas que hoy dependen de un `WHERE` manual vía join con `casos`. Esta es la migración que las cierra. Sintaxis válida tanto en tu Postgres de Railway como en Supabase (donde reemplazarías `current_setting('vridik.current_user_id')` por `auth.uid()` y `current_setting('vridik.current_despacho_id')` por un claim del JWT).

```sql
-- migration: 007_rls_tablas_indirectas.sql (idempotente)
-- Cierra RLS en las 5 tablas tenant que hoy solo tienen filtro de aplicación.
-- Patrón: una fila es visible si su caso pertenece al despacho activo.
-- fail-open con narrowing (mismo criterio que core/rls.py): sin GUC seteado,
-- current_setting(..., true) devuelve NULL y NINGUNA fila pasa el USING.

DO $$
DECLARE
  t text;
  tablas text[] := ARRAY['actuaciones','terminos','cobro_caso','case_documents','mensajes'];
BEGIN
  FOREACH t IN ARRAY tablas LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- actuaciones: visible si su caso es del despacho activo
DROP POLICY IF EXISTS actuaciones_aislamiento_despacho ON actuaciones;
CREATE POLICY actuaciones_aislamiento_despacho ON actuaciones
  USING (
    EXISTS (
      SELECT 1 FROM casos c
      WHERE c.id = actuaciones.caso_id
        AND c.despacho_id = current_setting('vridik.current_despacho_id', true)::uuid
    )
  );

-- terminos: idéntico criterio (el motor de vencimientos vive acá)
DROP POLICY IF EXISTS terminos_aislamiento_despacho ON terminos;
CREATE POLICY terminos_aislamiento_despacho ON terminos
  USING (
    EXISTS (
      SELECT 1 FROM casos c
      WHERE c.id = terminos.caso_id
        AND c.despacho_id = current_setting('vridik.current_despacho_id', true)::uuid
    )
  );

-- cobro_caso: el cobro cuelga de un caso
DROP POLICY IF EXISTS cobro_aislamiento_despacho ON cobro_caso;
CREATE POLICY cobro_aislamiento_despacho ON cobro_caso
  USING (
    EXISTS (
      SELECT 1 FROM casos c
      WHERE c.id = cobro_caso.caso_id
        AND c.despacho_id = current_setting('vridik.current_despacho_id', true)::uuid
    )
  );

-- case_documents: documento generado por JuliX sobre un caso
DROP POLICY IF EXISTS case_documents_aislamiento_despacho ON case_documents;
CREATE POLICY case_documents_aislamiento_despacho ON case_documents
  USING (
    EXISTS (
      SELECT 1 FROM casos c
      WHERE c.id = case_documents.caso_id
        AND c.despacho_id = current_setting('vridik.current_despacho_id', true)::uuid
    )
  );

-- mensajes: la conversación cuelga de un caso
DROP POLICY IF EXISTS mensajes_aislamiento_despacho ON mensajes;
CREATE POLICY mensajes_aislamiento_despacho ON mensajes
  USING (
    EXISTS (
      SELECT 1 FROM casos c
      WHERE c.id = mensajes.caso_id
        AND c.despacho_id = current_setting('vridik.current_despacho_id', true)::uuid
    )
  );
```

Ejemplo de política **por rol** (mascotas separa dueño de cuidador; Vridik separa abogado de cliente) — un cliente solo ve su propio caso aunque sea del mismo despacho:

```sql
-- Refuerzo por rol sobre casos: cliente ve solo los suyos; abogado/admin ven los del despacho.
DROP POLICY IF EXISTS casos_por_rol ON casos;
CREATE POLICY casos_por_rol ON casos
  USING (
    -- admin/abogado del despacho
    (current_setting('vridik.current_role', true) IN ('admin','abogado')
      AND despacho_id = current_setting('vridik.current_despacho_id', true)::uuid)
    OR
    -- cliente: solo su propio caso
    (current_setting('vridik.current_role', true) = 'cliente'
      AND cliente_id = current_setting('vridik.current_user_id', true)::uuid)
  );
```

**Verificación obligatoria (regla del proyecto: RLS se prueba contra Postgres real, no fakes):** un test que setea `vridik.current_despacho_id` al despacho A e intenta leer un `termino` del despacho B debe devolver 0 filas. Sin ese test, la política es teoría.

## Top 5 quick wins en 48h para blindar Vridik

1. **Migración 007 RLS (arriba)** — cierra el hueco de aislamiento entre despachos, que es el riesgo #1 de un multi-tenant legal (un cliente viendo datos de otro despacho es multa SIC directa). Ya está el SQL; falta aplicarla + test contra Postgres real.
2. **health-score por proceso** — una columna calculada + endpoint. Convierte "una lista de casos" en "un tablero de riesgo" de un día para otro. Fórmula abajo, todos los inputs existen.
3. **Loop de término escalonado (T-5/T-3/T-1) por SSE** — `procesal/alertas_terminos.py` ya corre; falta escalonar los avisos y empujarlos por el canal SSE que ya existe. Es el gancho diario de mascotas, aplicado.
4. **PWA en el frontend** — `vite-plugin-pwa`, manifest + service worker. Instalable en el móvil del abogado en el juzgado. Medio día.
5. **Modo Urgente (ficha pública por QR)** — endpoint read-only con token firmado por caso, sin login. El abogado comparte estado con su cliente sin crearle cuenta. Es el "Modo Perdido" traducido, y es diferenciador comercial.

### Fórmula del health-score por proceso (viable, todos los inputs existen)

Score de **riesgo** 0-100 (0 = sano, 100 = crítico), por caso, calculado siempre en backend (nunca input del cliente, mismo principio que `honorarios_liquidados`):

```
health_score = min(100, round(
    40 * urgencia_termino      # término más próximo del caso
  + 25 * silencio_judicial     # días sin actuación / umbral
  + 20 * terminos_vencidos     # proporción de términos ya vencidos del caso
  + 15 * incumplimiento_previo # racha rota en este caso
))

donde:
  urgencia_termino =
      1.0  si hay término venciendo en <=1 día
      0.7  si <=3 días
      0.4  si <=5 días
      0.1  si <=15 días
      0.0  si no hay término abierto
  silencio_judicial = min(1.0, dias_sin_actuacion / 90)
  terminos_vencidos = terminos_vencidos_abiertos / max(1, terminos_totales_del_caso)
  incumplimiento_previo = 1.0 si el caso rompió una racha en los últimos 30 días, si no 0.0
```

Semáforo para la UI: 0-30 verde, 31-70 amarillo, 71-100 rojo. El care-score de mascotas te dice qué mascota descuidaste; el health-score de Vridik te dice **qué caso te va a estallar** — el mismo mecanismo, aplicado a algo por lo que un abogado paga.

## Blueprint corregido (metodología Forja, cada fase con las 11 etapas)

**Fase 0 — Definición de producto (la que falta, 1 semana, sin código).** Cerrar las 4 etapas Forja que Vridik no tiene: personas (las 3 de abajo), journey maps (loop de término), user stories (las 20 de `vridik_architecture_v2.json`), pre-mortem formal. Entregable: `PDR_VRIDIK.md`. Sin esto, seguís construyendo features sin norte de producto.

**Fase 1 — Blindaje + gancho (30 días).** RLS completo (mig. 007) + health-score + loop de término escalonado por SSE + PWA. Cada uno con su test contra DB real y verificación en producción. Meta: Vridik deja de ser "un gestor" y pasa a "el tablero que te avisa antes de que estalle un caso".

**Fase 2 — Diferenciadores vendibles (60 días).** Modo Urgente (QR público) + gamificación (health-score ya sienta la base de datos) + Storage R2. En paralelo, el bloqueo real de producto: subir el GATE de JuliX de 35% a ≥80% (ver `HANDOFF_CLAUDE_CODE.md` T2/T3) — sin esto, ningún diferenciador salva un copiloto que reprueba su propio banco.

**Fase 3 — Cobro y compliance (90 días).** Cobro Inteligente (% sobre glosa recuperada, ya en `core/cobro.py`) como plan pago + Bóveda de Cumplimiento (matriz de riesgo ya existe, faltan listas restrictivas) + ARCO/Ley 1581. Meta: 3 despachos pagando.

**Fase 4 — Radar Judicial (escalamiento).** Integrar proveedor (TusDatos/AliadoJudicial), nunca scraper propio (ver pre-mortem). El clasificador de actuaciones ya consume texto; es un adaptador delgado.

Las 3 personas, las 20 user stories, el journey del loop de término, el pre-mortem completo y las 14 migraciones están en `vridik_architecture_v2.json`.
