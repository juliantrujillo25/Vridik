# Handoff para Claude Code — Plan 30-60-90 (post-auditoría Fable 5)

Fecha de corte: 20-jul-2026. Contexto completo en `vridik_audit.md` /
`vridik_audit.json` (auditoría) e `Instrucciones - CLAUDE.md` (reglas del
proyecto, historia, estado real por sprint). Leé los tres ANTES de tocar
código. Este archivo es la lista de trabajo delegada, en orden.

## Reglas no negociables (heredadas, no las relajes)

- Nunca llamadas reales a Anthropic ni a PostgreSQL de producción sin
  autorización explícita del dev lead POR TAREA. Las tareas de abajo que
  la requieren están marcadas [REQUIERE AUTORIZACIÓN]; pedila antes de
  ejecutar, no después.
- Modelo: `claude-sonnet-5`. Naming: Vridik / JuliX.
- Migraciones idempotentes. Ningún fallo como éxito silencioso.
- Limpiar `__pycache__` antes de confiar en pytest/py_compile.
- Cada tarea = un commit, suite local en verde antes de deploy.
- Deploy de `vridik-api`: `railway up --service vridik-api --detach` desde
  la raíz del repo (correcto, el backend vive ahí). Deploy de
  `vridik-frontend`: **NUNCA** el mismo patrón -- `railway up` no respeta
  el directorio de trabajo del shell en este monorepo. Usar siempre
  `railway up frontend --path-as-root --service vridik-frontend --detach`
  desde la raíz del repo. Ver el incidente real documentado en "Ya hecho"
  (21-jul) si hace falta el porqué.

## Ya hecho el 20-jul (no repetir)

- `Instrucciones - CLAUDE.md`: sección S5-GAP-01 corregida al estado real
  (GATE corrido y reprobado 15%→35%).
- `eval/evaluador.py::contrastar_flag_con_norma_clave()` + 
  `tests/test_evaluador_juez.py` (9 tests): regresión UGPP-07 fijada.
  Suite completa local: 372 passed, 123 skipped.
- **T1 CERRADO** (verificado con el dev lead en esta sesión, 20-jul):
  password de Postgres de producción rotada en Railway. Confirmado
  antes de seguir tocando la base.
- **T2 parcialmente arrancado, en paralelo, por otra sesión**: se
  construyó `core/corpus_curation.py` + `api/corpus_endpoint.py` (mini-
  herramienta de curaduría de 3 pasos, `/plataforma/corpus`, exclusiva
  admin de plataforma) y se cargaron **9 chunks reales** en `rag_chunks`
  (arrancaba en 0, no en 85 -- **corrección real: `vridik_audit.md` dice
  "85 de 400+ chunks", ese número describe un sistema legacy pre-Vridik,
  no la tabla Postgres actual; confirmado por consulta directa a
  producción**): 2 sentencias del Consejo de Estado (rad. 26571 y SU
  2022CE-SUJ-4-001/24724, texto real extraído de PDF oficial) + 4 normas
  (Ley 1151/2007 art. 156, Ley 1607/2012 arts. 178/180, Ley 1393/2010
  art. 30, CST art. 64 -- todas con texto verbatim verificado contra
  fuente oficial). Verificado de punta a punta con una consulta real a
  JuliX que recuperó y citó correctamente el contenido cargado.
  **Falta explícitamente**: cruzar esto contra las ~30 referencias de
  `norma_clave` en `eval/banco_casos_vridik.xlsx` (T2 lo pide
  específicamente) -- lo cargado hasta ahora se eligió por tener texto
  ya verificado a mano, no por cobertura sistemática del banco. Limitación
  real encontrada: WebFetch trunca documentos legales grandes (DUR,
  códigos completos, leyes de +100 artículos) antes de llegar a
  artículos lejos del principio -- para el resto del CST y normas
  similares, la vía que funcionó fue descargar el PDF oficial y
  extraerlo con PyMuPDF localmente (mismo método ya usado con las
  sentencias), no depender de un fetch en vivo.
- **T2, segunda pasada (mismo día)**: 15 chunks reales en total (9→15).
  Se cruzó por primera vez contra `norma_clave` del banco: **Ley
  1010/2006 arts. 2, 7, 9, 10, 11** (cierra LAB-08 completo) y **Decreto
  379/2026 art. 3.2.7.5** (cierra UGPP-07 Y de paso el Decreto 780/2016
  que había quedado pendiente). **Hallazgo metodológico serio, confirmado
  DOS VECES de forma independiente**: pedirle a WebFetch/WebSearch "el
  texto literal completo" de un artículo mediano/largo devuelve con
  total confianza (comillas, formato de cita) un extracto RECORTADO que
  se presenta como si fuera el artículo entero -- en Ley 1010/2006 art.
  10 la segunda verificación reveló que faltaba un numeral completo
  incluso DESPUÉS de "confirmar" la primera extracción; en Ley 100/1993
  art. 18 la respuesta fue literalmente la primera frase de un artículo
  con varios párrafos más (topes de 25 SMLMV, aportes progresivos). **No
  se cargó Ley 100/1993 (arts. 18/19/23) por esto** -- queda pendiente,
  NO uses lo que ya se extrajo de esos tres artículos en esta sesión, es
  incompleto. El único método que dio texto genuinamente completo y
  verificable fue descargar el PDF oficial (aunque WebFetch diga "no
  puedo parsear este PDF", el binario queda guardado localmente igual,
  ver ruta en la respuesta de la herramienta) y extraerlo con PyMuPDF --
  ahí se ven los límites reales de cada artículo (dónde empieza el
  siguiente). Úsalo SIEMPRE para artículos de más de un par de frases,
  no solo para códigos grandes.
  **Pendiente real de `norma_clave` del banco, todavía sin cargar**: E.T.
  arts. 114-1/635/817/818/823/826/828/831 y CPACA art. 138 (códigos
  grandes, mismo riesgo de truncamiento que el CST -- usar PDF+PyMuPDF);
  Decreto 1072/2015 arts. 2.2.4.2.2.1 y ss. (DUR, ídem); Ley 100/1993
  arts. 18/19/23 (ver hallazgo arriba); Ley 2277/2022 art. 89; Decreto
  1601/2022; Ley 1739/2014 (resto, ya se cargó el art. 50); Ley 1562/2012
  art. 2; Ley 361/1997 art. 26; Ley 995/2005; Ley 52/1975 art. 1 (nunca
  se encontró en Ola 6 tampoco); CST arts. 46/159/160/168/179/186/189/
  192/239/240/249/253 (el 64 ya está cargado); sentencias SU-049/2017 y
  SU-213/2024 (ya leídas en fuente oficial en la Ola 8 del corpus, pero
  nunca cargadas a `rag_chunks` -- son un caso fácil, solo falta
  re-fetchear y cargar, no requieren investigación nueva).
- **T2, tercera pasada (mismo día)**: 20 chunks reales en total (15→20).
  Se cargó **Ley 2277/2022 art. 89** (IBC independientes, PDF+PyMuPDF --
  el artículo de una ley de reforma tributaria de 47 páginas, confirmado
  completo por límites naturales del artículo siguiente), **Ley 361/1997
  art. 26** (estabilidad laboral reforzada, PDF+PyMuPDF), **SU-049/2017 y
  SU-213/2024** (regla de unificación citada textualmente entre
  comillas, confirmada la de SU-213 con una segunda fuente independiente
  -- se descartó el resto de cada respuesta de WebFetch por venir sin
  comillas, es decir resumen del modelo, no cita) y **Ley 995/2005 arts.
  1-2 completos** (ley corta de 2 artículos, PDF+PyMuPDF confirmó que no
  faltaba nada). Con esto, del banco de 20 casos: **LAB-03, LAB-07 y
  LAB-08 quedan con TODA su `norma_clave` cargada**; UGPP-04/05/07/10 y
  LAB-01/05 con cobertura parcial. Sesión de prueba limpiada.
  **Pendiente real, actualizado**: E.T. (UGPP-04/08/09/11), CPACA art.
  138 (UGPP-10), Decreto 1072/2015 (UGPP-12) -- los tres son códigos/DUR
  grandes, usar PDF+PyMuPDF, no fetch en vivo. Ley 100/1993 arts. 18/19/23
  (UGPP-06/08, ver hallazgo de fiabilidad -- lo ya extraído en la sesión
  anterior NO sirve, hay que re-extraer del PDF). Decreto 1601/2022
  (UGPP-07). Ley 1562/2012 art. 2 (UGPP-12). Ley 52/1975 art. 1 (LAB-06,
  nunca encontrado en ninguna pasada, ni en Ola 6 del corpus ni acá --
  puede que solo exista en el Diario Oficial escaneado, no en gestores
  normativos). CST arts. 46/159/160/168/179/186/189/192/239/240/249/253
  (LAB-02/04/06/07, el 64 ya está) -- el PDF de la Rama Judicial que se
  probó antes es un OCR malo del texto de 1950 sin las reformas, no
  sirve; probar el PDF de Función Pública (`norma_pdf.php?i=199983`,
  el mismo que se usó para leer el art. 64 en vivo, pero descargado
  entero y extraído local en vez de fetcheado en vivo).
- **T2, cuarta pasada (21-jul)**: 32 chunks reales en total (20→32). Se
  resolvieron los 3 códigos/DUR grandes pendientes, todos con PDF+PyMuPDF
  desde el arranque (nunca se intentó fetch en vivo primero, para no
  perder tiempo con el patrón ya conocido de truncamiento): **Estatuto
  Tributario** (358 páginas, PDF de Función Pública `i=6533` -- arts.
  114-1/635/817/818/823/826/828/831, cierra UGPP-04/08/09/11), **CPACA**
  (128 páginas, `i=41249` -- art. 138, cierra UGPP-10), **Decreto
  1072/2015 DUR Sector Trabajo** (335 páginas, `i=72173` -- Sección 2
  completa, arts. 2.2.4.2.2.1 a 2.2.4.2.2.4, ARL de contratistas
  independientes en alto riesgo, cierra UGPP-12). Los 8 artículos del
  E.T. se ubicaron por regex sobre el texto extraído completo (mucho más
  rápido y confiable que pedirle a un LLM que busque uno por uno dentro
  de un documento de 1.7M caracteres) y se verificaron por límite natural
  real (dónde empieza el artículo siguiente en el propio texto, no
  "aparenta estar completo"). Sesión de prueba limpiada.
  **Con esto, del banco de 20 casos: LAB-03/07/08 completos; UGPP-04/05/
  07/09/10/11 y LAB-01/05 con al menos una norma real cargada.**
  **Pendiente real, acotado**: Ley 100/1993 arts. 18/19/23 (UGPP-06/08 --
  re-extraer del PDF, sigue sin hacerse); Decreto 1601/2022 (UGPP-07);
  Ley 1562/2012 art. 2 (UGPP-12, aunque ya referenciado indirectamente
  dentro del extracto de Decreto 1072/2015 cargado); Ley 52/1975 art. 1
  (LAB-06, nunca encontrado en 2 pasadas distintas ni en la Ola 6 del
  corpus -- candidato a "no existe en gestores normativos digitales,
  buscar en el Diario Oficial escaneado o marcar pendiente para Ana
  Luisa"); resto del CST (LAB-02/04/06/07, el art. 64 ya está -- usar
  PDF de Función Pública `i=199983` descargado ENTERO con PyMuPDF, igual
  que el resto de esta pasada, no el de la Rama Judicial que es OCR del
  texto de 1950 sin reformas).
- **T2 CERRADO -- quinta pasada (21-jul)**: 52 chunks reales en total
  (32→52). Se resolvió TODO lo que quedaba pendiente: **Ley 100/1993
  arts. 18/19/23** (re-extraídos del PDF -- confirmado que el art. 18
  tiene 3 parágrafos más allá de la primera frase, tal como anticipaba
  el hallazgo de la pasada anterior), **Decreto 1601/2022** (Título 7
  completo, 6 artículos, con nota de vigencia explícita de que el art.
  3.2.7.5 quedó superado por Decreto 379/2026 ya cargado), **Ley
  1562/2012 art. 2** (afiliados al Sistema de Riesgos Laborales),
  **Ley 52/1975 art. 1** (encontrado por fin al tercer intento --
  alcaldiabogota.gov.co/sisjur, confirmado por una segunda fuente
  independiente con contenido idéntico) y **los 12 artículos restantes
  del CST** (46/159/160/168/179/186/189/192/239/240/249/253 -- el PDF
  de Función Pública `i=199983` SÍ tiene el texto completo y vigente,
  con reformas incluidas hasta 2021; contradice el miedo de la pasada
  anterior de que hiciera falta buscar en otro lado). Todos verificados
  por límite natural real (dónde empieza el artículo siguiente).
  **Con esto, prácticamente TODAS las referencias de `norma_clave` de
  los 20 casos del banco (`eval/banco_casos_vridik.xlsx`) tienen texto
  verbatim real cargado en `rag_chunks`.** T2 queda cerrado -- el
  siguiente paso lógico es T3 (correr el GATE de nuevo con esto ya
  cargado). Sesión de prueba limpiada.
- **TF1 CERRADO (21-jul)**: `core/rls.py::ensure_rls_policies_indirectas()`
  -- RLS real de Postgres (`FORCE ROW LEVEL SECURITY`) en las 5+2 tablas
  que solo tenían aislamiento de aplicación: `actuaciones`, `terminos`,
  `cobro_caso`, `case_documents` (join directo por `caso_id`) y
  `mensajes`/`conversaciones`/`conversation_reads` (join indirecto vía
  `conversacion_id` -- `mensajes` NO tiene `caso_id` propio, hallazgo real
  de esquema). **No se aplicó el SQL de `vridik_forja_audit.md` tal
  cual**: usaba nombres de GUC (`vridik.current_despacho_id`) que no
  coinciden con los reales del proyecto (`app.despacho_id`/
  `app.bypass_rls`, ya usados en el `ensure_rls_policies()` original) --
  se reimplementó con los nombres reales y el mismo patrón idempotente
  `DO $$ ... EXCEPTION WHEN duplicate_object`. Tampoco se implementó la
  política bonus `casos_por_rol` del audit (fuera del alcance pedido,
  interacción con la política existente sin analizar). `tests/
  test_rls_indirectas.py` (6 tests, Postgres real): sin-contexto-no-ve-
  nada, con-despacho-correcto, bypass-ve-todo, IDOR en INSERT cruzado
  (WITH CHECK), y el test específico del join de dos saltos de
  `mensajes`. Suite local en verde, CI verde contra Postgres real (run
  `29827642734`). Commit `1c6da1c`, desplegado y pendiente de verificar
  en producción junto con TF2 (mismo release).
- **TF2 CERRADO (21-jul)**: `core/health_score.py` -- score de riesgo
  0-100 por caso, fórmula exacta de
  `vridik_architecture_v2.json::gamificacion_vridik.health_score_formula`,
  calculado siempre en backend (nunca input del cliente/abogado, mismo
  principio que `honorarios_liquidados`). Columna `casos.health_score`/
  `health_score_actualizado_en` vive en `core/case.py::
  ensure_casos_table()` (no en `core/health_score.py`) porque
  `COLUMNAS_CASO` necesita la columna creada de forma confiable antes de
  leerla. Recalculo inmediato al crear/cambiar un término o una actuación
  (`api/terminos_endpoint.py`, `api/actuaciones_endpoint.py`) + recalculo
  de todos los casos abiertos en el mismo job de `procesal/
  alertas_terminos.py` que ya corre cada 6h (sin bucle de fondo nuevo).
  Expuesto en frontend: `HealthScorePill` (ui.tsx) junto al `EstadoPill`
  en `CasoDetailPage.tsx`, badge silencioso-en-verde (solo aparece si
  score > 30) en `CasosListPage.tsx`, mismos umbrales de semáforo que el
  backend (0-30/31-70/71-100). `tests/test_health_score.py` (9 puras +
  4 Postgres real). `tsc --noEmit` limpio; verificado en navegador que la
  app carga sin errores de consola (verificación visual del pill con
  datos reales de riesgo queda pendiente del deploy, el backend en
  producción hoy todavía no tiene la columna). Commits `b37a38a`
  (backend) y `045e036` (frontend).
- **TF3 CERRADO (21-jul)**: `core/terminos.py::DIAS_ESCALONES=(5,3,1)` +
  `escalon_aplicable()` -- tres avisos por término (T-5/T-3/T-1) en vez
  del aviso único de Fase 2. Columna nueva `ultimo_escalon_notificado`
  (SMALLINT, la vieja `ultima_alerta_enviada` queda sin usar, no se
  borró). `listar_terminos_para_alertar()` reescrito con CASE en SQL
  para traer el escalón de cada fila y filtrar solo los que alcanzaron
  un escalón MÁS urgente que el último notificado -- un término
  notificado en T-5 reaparece al llegar a T-3, uno en T-1 (el más
  urgente) no vuelve a aparecer nunca. Evento SSE nuevo
  `termino.por_vencer` (reemplaza `termino.alerta`, actualizado en
  `ActuacionesYTerminos.tsx`/`CasosListPage.tsx`, mismo consumidor de
  siempre). Gancho de gamificación en `api/terminos_endpoint.py`:
  marcar un término 'cumplido' ANTES del vencimiento dispara
  `termino.cumplido` a cliente/abogado del caso; ya vencido no dispara
  nada (no es un logro) -- solo el evento SSE, las tablas
  `gamificacion`/`logros` (migs 12/13) siguen siendo fase 2. Tests:
  `escalon_aplicable` en las 5 fronteras (pura), fake de orquestación
  (4 tests), 3 tests contra Postgres real incluido el caso central de
  re-escalar T-5→T-3, y 2 tests del gancho de gamificación (a tiempo
  dispara, vencido no). Suite local 384 passed/143 skipped, CI verde
  contra Postgres real (run `29829681978`). `tsc --noEmit` limpio.
  Commit `4e302ea`. **Con esto, Track Forja (TF1/TF2/TF3) queda
  completo en el repo** -- falta el deploy a producción de los tres +
  verificación en vivo, requiere autorización explícita antes de tocar
  Postgres de producción.
- **Deploy de TF1/TF2/TF3 a producción (21-jul), autorizado explícitamente
  por el dev lead**: `railway up --service vridik-api --detach`, deploy
  `8eca5855` SUCCESS, sin errores en logs.
  **Hallazgo real #1 -- TF1 es deuda técnica, no protección real
  todavía**: las 7 tablas indirectas SÍ tienen `ENABLE`+`FORCE ROW LEVEL
  SECURITY` con las políticas correctas (confirmado con `pg_class`/
  `pg_policies` contra producción), pero el rol de Postgres que usa
  `vridik-api` (`DATABASE_URL`, mismo usuario que `DATABASE_PUBLIC_URL`)
  es `postgres` y es **superusuario** (`rolsuper=true`,
  `rolbypassrls=true`, confirmado con `SELECT rolsuper, rolbypassrls
  FROM pg_roles`). Un superusuario de Postgres SIEMPRE se salta RLS --
  ni `FORCE ROW LEVEL SECURITY` lo puede anular (`FORCE` solo afecta al
  dueño de la tabla cuando NO es superusuario). Railway aprovisiona un
  único rol `postgres` para toda la base, sin un rol de aplicación
  separado sin privilegios -- así que hoy TF1 es inerte en producción:
  el único aislamiento real sigue siendo el `WHERE despacho_id = $1` de
  aplicación, igual que antes de TF1. CI sí prueba el enforcement real
  porque tiene un paso explícito que le quita `SUPERUSER`/`BYPASSRLS`
  al rol de test antes de correr `pytest` -- producción nunca tuvo esa
  separación. **Decisión del dev lead: dejarlo documentado como deuda
  técnica por ahora** (las políticas quedan listas para cuando exista
  un rol de aplicación separado), no tratarlo como una migración
  fallida ni revertirla.
  **Hallazgo real #2 -- bug real de producción, encontrado y arreglado
  en el momento**: `POST /casos/{id}/terminos`, `PATCH .../estado`,
  `POST /casos/{id}/actuaciones` y `PATCH .../resultado` devolvían 500
  en producción. Causa: `core/health_score.py::recalcular_health_score`
  tenía `fecha_vencimiento >= $2 - $3` sin casts explícitos --
  PostgreSQL 18 (la versión REAL de producción, confirmado con `SELECT
  version()`) infiere el tipo de esa resta distinto que PostgreSQL 15
  (la versión que usa CI, `postgres:15` en `.github/workflows/ci.yml`),
  resolviéndola como `integer` en vez de `date` y tirando "operator
  does not exist: date >= integer". CI nunca lo detectó porque corre
  contra una versión de Postgres distinta a la real. Fix: `$2::date` y
  `$3::int` explícitos. Verificado directo contra Postgres de
  producción antes (falla) y después (pasa) del fix, además de
  auditadas TODAS las demás queries nuevas de TF2/TF3 contra el schema
  real de producción para descartar el mismo patrón en otro lado (no
  apareció en ninguna otra). Commit `b3d6214`, redeploy `933def13`
  SUCCESS. **Riesgo real pendiente**: CI sigue en `postgres:15` --
  cualquier SQL nuevo con inferencia de tipos ambigua puede repetir
  esta clase de bug sin que CI lo vea. Convendría subir CI a `postgres:18`
  (o al menos agregar el hábito de castear explícitamente cualquier
  aritmética entre parámetros, no solo entre parámetro y columna).
  **Verificación funcional en vivo (post-hotfix), con cuenta throwaway
  limpiada después**: TF2 -- crear un término vencido recalculó
  `health_score` sincrónicamente (score=75, confirmado vía `GET /casos/
  {id}`). TF3 -- la query de `listar_terminos_para_alertar` evaluó
  escalón=1 correctamente contra el schema real; marcar un término
  futuro como cumplido disparó el evento `termino.cumplido` real (fila
  en `user_events`). TF1 -- no se pudo verificar aislamiento real por
  el hallazgo #1 de arriba (queda como deuda técnica, no como
  verificado).
- **Incidente real -- deploy de `vridik-frontend` por `railway up` sin
  `--path-as-root` rompió el sitio en producción (21-jul, mismo release)**:
  al desplegar el frontend con `railway up --service vridik-frontend
  --detach` (mismo patrón que siempre funcionó para `vridik-api`, que SÍ
  vive en la raíz del repo), Railway ignoró por completo el subdirectorio
  `frontend/` -- `railway up` **no** escala al directorio de trabajo del
  shell; usa la raíz del proyecto vinculado sin importar desde dónde se
  invoque (confirmado corriéndolo también parado adentro de `frontend/`:
  mismo resultado). El build resultante instaló `requirements.txt` del
  backend y sirvió la API de FastAPI en la URL del frontend --
  `GET https://vridik-frontend-production.up.railway.app/` devolvía
  `{"detail":"Not Found"}` en vez del SPA. Diagnosticado con `railway
  status --json` (`serviceManifest.build.nixpacksConfigPath` mostraba
  `/nixpacks.toml`, es decir el de la raíz del repo, no
  `frontend/nixpacks.toml`) y confirmado con `railway logs --build`.
  **Fix real, la única forma correcta de desplegar `vridik-frontend`
  desde la CLI en este monorepo**:
  ```
  railway up frontend --path-as-root --service vridik-frontend --detach
  ```
  (`--path-as-root` es justo el mecanismo documentado por la propia CLI
  para monorepos: `railway up ./apps/api --path-as-root --service api`).
  Sin el flag, cualquier futuro deploy manual del frontend por CLI va a
  repetir este mismo apagón. Restaurado y verificado (200 OK, SPA real,
  sin errores de consola) en minutos -- ningún dato de usuario se vio
  afectado, fue solo el contenido servido en esa URL. **Anotalo en
  cualquier script/alias de deploy que se agregue a futuro** -- ver
  también la nota en `frontend/nixpacks.toml`, que asumía (mal) que el
  Root Directory ya estaba resuelto del lado de Railway.

## Cola de trabajo, en orden

### T1 — ~~Rotación de credenciales Postgres~~ CERRADO (20-jul-2026)
Confirmado con el dev lead: password rotada en Railway.

### T2 — ~~Corpus verbatim para el banco~~ CERRADO (21-jul-2026), ver "Ya hecho"
Diagnóstico en `PROMPTS.md`: `norma_clave` del banco guarda solo la CITA
(p.ej. "Ley 1607 de 2012, Art. 179"), nunca el texto del artículo. JuliX
no puede citar verbatim lo que no tiene.
1. Extraer de `eval/banco_casos_vridik.xlsx` la lista de normas/artículos
   referenciados en `norma_clave` de los 20 casos (~30 artículos únicos).
2. Conseguir el texto oficial de cada artículo (fuentes oficiales
   únicamente: SUIN-Juriscol, Función Pública, DIAN — regla de S8-9).
   Si un texto no se consigue de fuente oficial, marcarlo pendiente para
   Ana Luisa, NO usar fuentes secundarias.
3. Cargarlos vía la herramienta existente `core/corpus_curation.py`
   (borrador → chunks → publicar), NO por CSV a mano. [REQUIERE
   AUTORIZACIÓN: la publicación embebe con la API real y escribe en
   `rag_chunks` de producción.]
4. Además, evaluar (propuesta, discutir con dev lead antes): enriquecer la
   columna `norma_clave` del banco con el texto verbatim, para que el
   ejercicio S5 (fuente única permitida) también lo tenga. Eso cambia el
   banco — dejar el xlsx original respaldado y versionar el cambio.

### T3 — Corrida 3 del GATE con prompts v3 (P0) [REQUIERE AUTORIZACIÓN]
`julix/prompts/v3_laboral_colombia.md` y `v3_litigio_colombia.md` están
redactados y sin corrida real. Tras T2:
1. `python eval/evaluador.py --excel eval/banco_casos_vridik.xlsx --commit`
   contra Anthropic real + Postgres real (mismo procedimiento que las
   corridas del 15/16-jul; costo esperado <1 USD por corrida, techo en el
   ledger).
2. Meta intermedia honesta: >=60%. Si <60%: FRENO Y REVISIÓN (regla del
   roadmap S6) — diagnóstico por causa raíz antes de otra iteración, no
   prompt v4 a ciegas.
3. Revisar cualquier `flag_cuestionado` en los resultados (contraste
   mecánico nuevo) antes de aceptar el % final.
4. Actualizar `PROMPTS.md` e `Instrucciones - CLAUDE.md` con el resultado
   real, sea cual sea.

### T4 — Segunda cuenta admin de producción (P1) [REQUIERE AUTORIZACIÓN]
Bus factor 1 hoy. Crear un segundo admin real vía `POST /admin/users`
(con la cuenta admin existente), enrolarlo en 2FA (`must_enroll` lo va a
exigir), y verificar login end-to-end. La password temporal NUNCA se
imprime en salida de herramientas (precedente del 16-jul: archivo local).

### T5 — Storage S3/R2 para PDFs (P0)
`storage/object_storage.py` ya abstrae local vs S3; producción corre en
local efímero (los PDFs mueren en cada redeploy — bug documentado en
`api/case_documents_endpoint.py`).
1. Crear bucket (R2 de Cloudflare o S3) — decisión de proveedor con el
   dev lead (costo ~0 a este volumen).
2. Configurar `OBJECT_STORAGE_BACKEND=s3` + credenciales en Railway
   (vía `railway variable set --stdin`, nunca en salida de herramientas).
3. Verificar end-to-end: generar documento con `generar_pdf=true`,
   confirmar que `pdf_url` es URL http(s) y que
   `GET /casos/{id}/documents/{id}/pdf` redirige. [REQUIERE AUTORIZACIÓN]
4. Los PDFs viejos con rutas de filesystem quedan 404 con el mensaje de
   "almacenamiento efímero" ya existente — aceptable, documentarlo.

### T6 — Staging mínimo (P1)
Un servicio Railway clon (API + Postgres propio, seed mínimo) para que
"verificado en staging" deje de ser una limitación declarada en
ROLLBACK.md/SECURITY.md. Sin datos reales de producción en staging
(Ley 1581): usuarios sintéticos.

### T7 — Endpoints ARCO + retención (P1, Ley 1581)
Nuevo `api/datos_personales_endpoint.py` (o nombre que prefieras
consistente con el repo): acceso (export JSON de datos propios),
rectificación (delegable a los endpoints existentes), supresión
(soft-delete + anonimización de `users` respetando FKs y la bitácora
inmutable — diseño a discutir: qué se anonimiza vs qué se conserva por
deber legal). Documento corto `PRIVACIDAD.md` con política de retención.
El registro RNBD es trámite del dev lead, no código — solo dejarlo
apuntado.

### T8 — ~~RLS a las 5 tablas restantes~~ CERRADO (21-jul-2026) == TF1
Misma tarea que TF1 de Track Forja (ver abajo) -- se cerró ahí.

## Track Forja — producto vendible (ref: auditoría "Cuida tus mascotas")

Contexto en `vridik_forja_audit.md` + `vridik_architecture_v2.json`.
Objetivo: que Vridik deje de ser "un gestor más". Estas tareas NO dependen
del GATE de JuliX (venden aunque JuliX siga en 35%), así que pueden correr
en paralelo al track T2/T3. Orden sugerido: TF1 → TF2 → TF3.

### TF1 — RLS completo en las 5 tablas indirectas -- CERRADO EN EL REPO, DEUDA TÉCNICA EN PRODUCCIÓN (21-jul-2026) == T8
`core/rls.py::ensure_rls_policies_indirectas()`, commit `1c6da1c`,
desplegado en producción (`ENABLE`+`FORCE ROW LEVEL SECURITY` + políticas
confirmadas contra `pg_class`/`pg_policies` reales). **Pero no protege
nada todavía**: `vridik-api` se conecta a Postgres con el rol `postgres`,
que es superusuario (`rolbypassrls=true`) -- un superusuario SIEMPRE se
salta RLS, `FORCE` no lo puede anular. Railway no da un rol de aplicación
separado por defecto. Decisión del dev lead (21-jul): dejarlo como deuda
técnica documentada, no revertir ni tratarlo como si protegiera de
verdad. Detalle completo en "Ya hecho". **Para cerrarlo de verdad**: crear
un rol Postgres sin `SUPERUSER`/`BYPASSRLS` con privilegios suficientes
para las migraciones idempotentes existentes, y migrar `DATABASE_URL` de
`vridik-api` a ese rol -- cambio de infraestructura real, no solo código.

### TF2 — ~~health-score por proceso~~ CERRADO Y VERIFICADO EN PRODUCCIÓN (21-jul-2026)
`core/health_score.py`, commits `b37a38a` (backend), `045e036` (frontend),
`b3d6214` (hotfix de un 500 real en producción, ver "Ya hecho" -- cast de
tipos faltante que solo se manifestaba en PostgreSQL 18, la versión real
de producción, no en el PostgreSQL 15 de CI). Verificado en vivo post-fix:
crear un término vencido recalcula `health_score` sincrónicamente
(confirmado con cuenta throwaway, score=75, limpiada después).

### TF3 — ~~Loop de término escalonado T-5/T-3/T-1 por SSE~~ CERRADO Y VERIFICADO EN PRODUCCIÓN (21-jul-2026)
`core/terminos.py::DIAS_ESCALONES=(5,3,1)` + `escalon_aplicable()` (pura) +
`listar_terminos_para_alertar()` reescrito con CASE en SQL, columna nueva
`ultimo_escalon_notificado` (la vieja `ultima_alerta_enviada` queda sin
usar, no se borró). Evento SSE nuevo `termino.por_vencer` (reemplaza
`termino.alerta`), frontend actualizado (`ActuacionesYTerminos.tsx`,
`CasosListPage.tsx`). Gancho de gamificación: `api/terminos_endpoint.py`
dispara `termino.cumplido` cuando se marca un término cumplido ANTES del
vencimiento (no dispara si ya estaba vencido). Tests: `escalon_aplicable`
en las 5 fronteras (pura), fake de orquestación, y 3 tests contra
Postgres real -- incluido el caso central de TF3 (un término notificado
en T-5 vuelve a aparecer al llegar a T-3; uno notificado en T-1 nunca
vuelve a aparecer). Commit `4e302ea`, CI verde contra Postgres real (run
`29829681978`). Verificado en vivo post-hotfix: la query de escalones
evalúa bien contra el schema real de producción (escalón=1 para un
término vencido), y el gancho de gamificación disparó `termino.cumplido`
de verdad (fila real en `user_events`, limpiada después).

**Con esto, Track Forja (TF1/TF2/TF3) está desplegado en producción.**
TF2/TF3 verificados funcionalmente en vivo. TF1 queda desplegado pero
como deuda técnica explícita (ver arriba) -- las políticas están listas,
falta el rol de aplicación separado para que empiecen a proteger de
verdad. Pendiente separado y real, encontrado en esta misma pasada: subir
la versión de Postgres de CI (`postgres:15`) para que deje de divergir de
la versión real de producción (18) -- fue la causa raíz del 500 de TF2.

### TF0 — Definición de producto (sin código, 1 semana, dev lead + Ana Luisa)
Las 4 etapas Forja que Vridik no tiene, ya redactadas en
`vridik_architecture_v2.json` (personas, journey del loop de término,
20 user stories, pre-mortem). Consolidar en un `PDR_VRIDIK.md`. No es
trabajo de Claude Code — es decisión de producto; queda apuntado para que
las fases siguientes tengan norte.

### Congelado hasta GATE >=80% (no trabajar sin instrucción explícita)
Features nuevas de Fases 2-4 (excepto lo listado arriba). Listas
restrictivas ONU/OFAC/PEP. Firma electrónica Ley 527. Radar Judicial
(la decisión de proveedor TusDatos/AliadoJudicial es del dev lead;
cuando esté, el adaptador es `procesal/ingesta_<proveedor>.py` + webhook).

## Definición de terminado (por tarea)

Suite local verde con pycache limpio → commit → CI verde → deploy →
verificación en producción documentada en `Instrucciones - CLAUDE.md`
(sección de progreso, con fecha y evidencia). Si algo no se pudo
verificar, se escribe "no verificado" — nunca se reporta como hecho.
