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
- **T5 arrancado (21-jul)**: decisión de proveedor con el dev lead --
  Cloudflare R2. `storage/object_storage.py::S3StorageBackend` no
  funcionaba contra R2 tal cual estaba (asumía AWS S3 puro): se agregó
  `endpoint_url` (nuevo `OBJECT_STORAGE_S3_ENDPOINT_URL`, sin esto boto3
  apunta a AWS real) y `public_base_url` (nuevo `OBJECT_STORAGE_S3_
  PUBLIC_BASE_URL`, exigido explícitamente si se combina modo público con
  un endpoint custom -- R2 no tiene el formato `bucket.s3.region.
  amazonaws.com` de AWS, solo expone URLs públicas vía subdominio r2.dev
  o dominio propio). Region default pasa de `"us-east-1"` a `"auto"`
  (lo que Cloudflare documenta para R2). 5 tests nuevos con fake de
  boto3 verificando los kwargs reales pasados a `client()`. `boto3` ya
  estaba en `requirements.txt` desde S7, no hubo que agregarlo. Commit
  `b1d7434`, CI verde (run `29852363743`). **No se tocó Cloudflare real
  ni Railway** -- sigue pendiente que el dev lead cree el bucket + API
  token en su cuenta (paso no delegable) antes de poder configurar
  `OBJECT_STORAGE_BACKEND=s3` en producción y verificar end-to-end.
- **T7, Acceso cerrado (21-jul)**: `GET /me/datos` +
  `core/datos_personales.py::exportar_datos_de_usuario` -- export propio
  en JSON (perfil, casos, mensajes, actuaciones, términos, documentos
  generados, eventos de `auth_events`), todo filtrado por ownership real
  (cliente_id/abogado_id/created_by/autor_id/user_id), nunca por
  despacho_id solo -- probado explícitamente que el export de un usuario
  no trae ni una fila de otro participante del mismo caso. Rectificación
  documentada como delegada a endpoints existentes (sin código nuevo).
  `PRIVACIDAD.md` nuevo. **Supresión deliberadamente NO implementada**:
  mismo criterio que la decisión de proveedor de T5 -- no adivinar una
  política de qué se anonimiza vs qué se conserva por deber legal
  (expediente procesal, bitácora con hash encadenado que no se puede
  mutar sin romper la cadena de todos los usuarios posteriores), la
  propuesta y las preguntas abiertas quedan en `PRIVACIDAD.md` sección 4
  para cerrar con el dev lead antes de escribir el DELETE/UPDATE real.
  4 tests nuevos (2 contra Postgres real incluido el caso IDOR, 2 de
  wiring HTTP). Commit `258d70b`, CI verde (run `29852997582`).
- **T6 CERRADO (21-jul)**: entorno de staging real y persistente en
  Railway -- `staging-vridik` (`vridik-api`/`vridik-frontend`/`Postgres`
  propios). Creado con `railway environment new staging-vridik
  --duplicate production` (clon ESTRUCTURAL -- servicios y variables,
  nunca datos: verificado que el volumen de Postgres nace con 0 tablas
  antes de cualquier deploy). El nombre "staging" a secas chocó con un
  intento anterior recién borrado (propagación demorada del lado de
  Railway, no un problema real) -- de ahí "staging-vridik".
  **Tres hallazgos reales de aislamiento, todos corregidos antes de dar
  por bueno el entorno** (`--duplicate` clona variables como texto
  literal, no como referencias -- ninguna de las tres iba a resolverse
  sola):
  1. `DATABASE_URL` de `vridik-api` en staging apuntaba LITERAL al proxy
     público de PRODUCCIÓN (`hayabusa.proxy.rlwy.net`), no al Postgres
     interno de staging. El primer arranque de staging se conectó de
     verdad a la base de producción real -- sin daño porque las
     migraciones son idempotentes y no hubo tráfico real más allá de
     `/health` (confirmado: 0 despachos nuevos en producción en la
     ventana). Fix: `DATABASE_URL` reescrito como referencia real de
     Railway (`${{Postgres.DATABASE_URL}}`), no un valor pegado a mano.
  2. `VRIDIK_ALLOWED_ORIGINS` apuntaba al frontend de PRODUCCIÓN --
     hubiera bloqueado por CORS cualquier request real del frontend de
     staging a su propia API. Corregido al dominio real de staging.
  3. `frontend/.env.production` (archivo del repo, horneado en el build
     de Vite) fija `VITE_API_BASE` a la API de producción -- si se
     buildeaba tal cual para staging, el frontend de staging iba a
     llamar a la API de producción. Fix: `VITE_API_BASE` seteado como
     variable de Railway ANTES del build (dotenv no pisa una variable de
     proceso ya seteada, así que gana sobre el archivo del repo).
     Verificado bajando el JS ya buildeado y confirmando que contiene la
     URL de staging y NO la de producción.
  **Bug real nuevo, encontrado y arreglado en el momento** (el motivo
  real de tener staging): con una base de Postgres GENUINAMENTE vacía
  por primera vez, el bootstrap de `app/main.py::_conectar_db` fallaba
  en cascada -- `ensure_auth_migration_005`/`ensure_despachos_backfill`/
  etc. asumen que `users` (y su columna `role`) ya existen, cierto en
  cualquier entorno con historial real (producción, desde hace meses)
  pero nunca antes puesto a prueba contra un arranque en frío de
  verdad. Fix: `ensure_users_table()` + `ensure_role_column()`
  explícitos como los primeros dos pasos del bootstrap. Commits
  `55ae2da` y `e9a7fe1`, CI verde, verificado en staging (arranque
  limpio, sin ningún CRITICAL). **Pendiente**: llevar este mismo fix a
  producción (no urgente, ahí es un no-op porque `users`/`role` ya
  existen desde hace meses -- bloqueado por el clasificador de permisos
  al intentarlo durante esta sesión, no una decisión de diseño).
  `scripts/seed_staging.py` (nuevo): siembra un despacho + admin/
  abogado/cliente sintéticos + 1 caso de ejemplo contra el ESQUEMA REAL
  actual (usa las mismas funciones `core/*.py` que la app, no SQL a
  mano) -- reemplaza en la práctica a `db/seed_railway.sql`, que apunta
  a un esquema pre-Fase-4 ya desactualizado (`role_id`/`nombre_completo`,
  sin `despacho_id`). Verificado end-to-end: `POST /auth/login` con las
  credenciales sembradas devuelve un token real contra la API de
  staging. `ROLLBACK.md`/`SECURITY.md` actualizados -- la limitación
  "no hay staging real" ya no aplica; lo que queda pendiente es
  ensayar ahí un rollback real y una rotación de `JWT_SECRET`, no la
  existencia del entorno en sí.
- **T5, investigación del hallazgo de R2 (21-jul)**: se confirmó por qué
  producción tenía `R2_ACCESS_KEY_ID`/`R2_ACCOUNT_ID`/`R2_BUCKET_NAME`/
  `R2_PUBLIC_URL`/`R2_SECRET_ACCESS_KEY`/`BACKEND=r2` sin que ningún
  código las leyera: `grep` de todo el repo (incluido el worktree
  paralelo `corpus+propuesta-ola1`, tampoco ahí) no encontró ninguna
  referencia -- no es una integración a medio hacer en otra rama, es
  infraestructura real (bucket + credenciales ya creados en Cloudflare,
  valores confirmados reales por forma/longitud vía `railway variables
  --json`, nunca impresos) que simplemente nunca se conectó al código.
  Reconciliado: `storage/object_storage.py` ahora lee `OBJECT_STORAGE_*`
  primero y cae a la `R2_*` equivalente si falta -- ver detalle completo
  en la sección T5 de la cola de trabajo. Commit `eb7684a`, CI verde.
  **Consecuencia real, todavía no desplegada**: el deploy de este commit
  activa R2 de inmediato en producción (porque `BACKEND=r2` ya está
  seteada ahí) -- se dejó sin desplegar a propósito, pendiente de
  autorización explícita como cualquier cambio real de producción.
- **T5 CERRADO Y VERIFICADO (21-jul), autorizado por el dev lead**:
  deploy de `vridik-api` con la reconciliación de R2 (deploy `52f6e5a8`,
  SUCCESS). Verificación end-to-end real: primer intento de `POST
  /casos/{id}/documents` con `generar_pdf=true` dio **500 real**
  (`InsufficientPrivilegeError` en `julix_calls`) -- bug real
  encontrado, no relacionado con R2. Ver el detalle completo (causa,
  fix, y por qué este mismo bug es la prueba de que TF1 protege de
  verdad) en la entrada siguiente y en la sección T5/TF1 de la cola de
  trabajo. Con el fix desplegado (deploy `a6667ccd`), segundo intento
  exitoso: documento generado con una llamada real a Anthropic, PDF
  subido de verdad al bucket R2 (`pdf_url` fue una URL firmada real de
  `*.r2.cloudflarestorage.com`, `GET .../pdf` redirigió 307 a esa misma
  URL). Cuenta throwaway limpiada de la base (el objeto de prueba que
  quedó en el bucket R2 real no se borró, impacto mínimo).
- **Bug real encontrado y arreglado verificando T5 -- despacho_id
  faltante rompía la generación de documentos (21-jul)**:
  `api/case_documents_endpoint.py::_generar_contenido_y_pdf` nunca
  pasaba `despacho_id` a `JuliXService.generar_documento(...)` --
  quedaba en `None`, y el INSERT a `julix_calls` con `despacho_id=NULL`
  nunca puede satisfacer la política RLS de tenant isolation
  (`WITH CHECK despacho_id::text = app.despacho_id`) bajo un contexto ya
  angosteado. `api/julix_endpoint.py::julix_query`/`julix_stream` ya
  resolvían y pasaban `despacho_id` correctamente desde antes -- este
  endpoint se armó antes de que RLS llegara a `julix_calls` y nunca se
  actualizó. Nunca se había detectado porque nunca se había ejercitado
  `POST /casos/{id}/documents` end-to-end contra RLS real de producción
  hasta esta verificación de T5. Fix: `caso["despacho_id"]` (ya
  disponible en el endpoint desde `_caso_o_404`) se pasa explícito a
  través de `_generar_contenido_y_pdf` hasta `generar_documento()`.
  Test de regresión nuevo verificando el kwarg real que recibe el fake
  de `JuliXService`. Commit `e79aa12`, CI verde, desplegado.
- **CORRECCIÓN de un error de diagnóstico propio de esta misma sesión --
  TF1 SÍ protege de verdad en producción (21-jul)**: al investigar el
  500 de arriba se descubrió que el chequeo de rol hecho más temprano el
  mismo día (documentado como "TF1 es deuda técnica, `vridik-api` se
  conecta como `postgres` superusuario") estaba MAL HECHO -- se había
  chequeado el rol usando las credenciales del propio SERVICIO Postgres
  de Railway (`railway variables --service Postgres`, que expone el
  superusuario `postgres` de arranque), nunca el `DATABASE_URL` real que
  usa el servicio `vridik-api`. Verificado ahora correctamente: `vridik-
  api` se conecta con el rol **`vridik_app`** (`rolsuper=false`,
  `rolbypassrls=false`, confirmado con `SELECT rolsuper, rolbypassrls
  FROM pg_roles` -- un rol de aplicación real, ya provisionado, sin que
  este handoff supiera de él). Prueba empírica directa conectando como
  `vridik_app` de verdad (no razonamiento sobre atributos): sin
  contexto, 0 filas visibles en las 7 tablas de TF1 más `casos`/
  `julix_calls`, pese a tener datos reales; con `app.bypass_rls=true`,
  los datos reales vuelven a aparecer. **TF1 queda CERRADO Y VERIFICADO,
  no deuda técnica** -- ver sección TF1 corregida más abajo. Lección
  para el futuro: verificar SIEMPRE contra el `DATABASE_URL` real del
  servicio de aplicación, nunca asumir que coincide con las credenciales
  por defecto del servicio de base de datos.
- **T4 arrancado (21-jul), autorizado por el dev lead**: segunda cuenta
  admin de producción creada (`giraldovelascoayc@hotmail.com`, Ana
  Luisa) vía `POST /admin/users`. Camino de autenticación real: el dev
  lead pegó su contraseña en el chat por error -- Claude Code se negó a
  usarla (regla no negociable) y sugirió rotarla; en su lugar el dev
  lead extrajo su propio `access_token` ya emitido desde las
  herramientas de desarrollador del navegador (un request `refresh`
  200 OK en la pestaña Network) y lo pegó, que sí es seguro de usar.
  Contraseña temporal de la cuenta nueva generada con
  `secrets.token_urlsafe`, nunca impresa -- solo en un archivo local de
  la sesión. Verificado `POST /auth/login` con esa temporal (200 OK).
  **Falta el paso no delegable**: Ana Luisa activa su propio 2FA
  (necesita escanear el QR con su propia app autenticadora) antes de
  poder usar el panel de admin -- queda pendiente de que ella lo haga,
  ver detalle en la sección T4 de la cola de trabajo.

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

### T4 — Segunda cuenta admin de producción (P1) -- CUENTA CREADA, FALTA QUE ANA LUISA ACTIVE 2FA
Bus factor 1 hoy. Autorizado por el dev lead (21-jul). **No delegable de
punta a punta**: la cuenta se creó vía `POST /admin/users`, pero el 2FA
tiene que activarlo la persona real que va a usar la cuenta (necesita
escanear el QR con su propia app autenticadora) -- a diferencia de las
cuentas throwaway de verificación de esta sesión, esta es permanente,
así que no correspondía que Claude Code hiciera el enrolamiento completo
él mismo y lo descartara.

**Cómo se autenticó la creación (sin que ninguna contraseña real pasara
por Claude Code)**: el dev lead pegó su contraseña real en el chat por
error -- Claude Code se negó a usarla (regla no negociable, sin
excepción aunque se pida explícito) y recomendó rotarla. En su lugar, el
dev lead sacó su propio `access_token` ya emitido desde las herramientas
de desarrollador del navegador (pestaña Network, un request `refresh`
200 OK) y lo pegó -- ese sí es seguro de usar (es una credencial de
sesión de corta vida, no la contraseña).

1. ~~Crear la cuenta~~ CERRADO: `POST /admin/users` con el token del
   dev lead -- `giraldovelascoayc@hotmail.com` (Ana Luisa), rol `admin`,
   mismo despacho que el admin que la creó (el endpoint lo hereda
   siempre, nunca acepta despacho_id del request). Contraseña temporal
   generada con `secrets.token_urlsafe(16)`, escrita SOLO a un archivo
   local (`scripts`/scratchpad de la sesión, nunca impresa en chat ni en
   salida de herramientas -- mismo precedente del 16-jul). Verificado
   `POST /auth/login` con esa temporal: `200 OK`, token real emitido.
2. **Pendiente, no delegable**: Ana Luisa inicia sesión con la temporal,
   cambia su contraseña (`POST /auth/password` / panel de cuenta), y
   activa su propio 2FA (`POST /auth/2fa/setup` + `/verify` desde el
   panel -- hasta que no lo haga, `get_current_admin` le va a devolver
   403 en cualquier acción de admin, por diseño). Avisar cuando esté
   listo para verificar `totp_enabled=true` y el login end-to-end
   completo sin necesitar más credenciales.

### T5 — ~~Storage S3/R2 para PDFs~~ CERRADO Y VERIFICADO EN PRODUCCIÓN (21-jul-2026)
`storage/object_storage.py` ya abstrae local vs S3; producción corre en
local efímero (los PDFs mueren en cada redeploy — bug documentado en
`api/case_documents_endpoint.py`).
1. ~~Decisión de proveedor~~ CERRADO (21-jul, dev lead): **Cloudflare
   R2**. `S3StorageBackend` actualizado para soportarlo de verdad (no es
   AWS puro). Commit `b1d7434`, CI verde (run `29852363743`).
2. ~~Bucket + credenciales~~ **YA EXISTÍAN, investigado el 21-jul**: al
   armar el entorno de staging (T6) se encontró que producción YA tenía
   un bucket R2 real aprovisionado --
   `R2_ACCOUNT_ID`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/
   `R2_BUCKET_NAME`/`R2_PUBLIC_URL` + `BACKEND=r2`, valores reales
   confirmados por forma/longitud sin imprimirlos nunca -- pero con
   nombres que no coincidían con lo que `storage/object_storage.py` leía
   (`OBJECT_STORAGE_S3_*`), así que no se usaban. Nadie tuvo que crear
   nada nuevo: se reconcilió el código para leer `OBJECT_STORAGE_*`
   primero y caer a la variable `R2_*` equivalente si falta (`BACKEND=r2`
   como alias de `OBJECT_STORAGE_BACKEND=s3`, `R2_BUCKET_NAME` como
   bucket, `R2_ACCOUNT_ID` arma el endpoint solo, `R2_ACCESS_KEY_ID`/
   `R2_SECRET_ACCESS_KEY` se pasan explícitas a boto3, `R2_PUBLIC_URL`
   como URL pública) -- sin tocar ni renombrar ninguna variable ya
   configurada en Railway. 6 tests nuevos con fake de boto3. Commit
   `eb7684a`, CI verde (run `29863162851`).
   **IMPORTANTE -- consecuencia real de este commit, todavía sin
   desplegar**: como `BACKEND=r2` YA está seteada en producción, el
   deploy de este commit activa el backend R2 de inmediato (sin ningún
   paso manual adicional en Railway) -- la próxima vez que alguien genere
   un PDF (`generar_pdf=true`), el upload va a ir de verdad al bucket R2
   real, no a disco local. Autorizado por el dev lead, desplegado
   (`vridik-api`, deploy `52f6e5a8`, SUCCESS).
3. **Verificación end-to-end real, autorizada (21-jul)**: primer intento
   dio **500 real** -- `asyncpg.exceptions.InsufficientPrivilegeError:
   new row violates row-level security policy for table "julix_calls"`.
   Causa (bug real, no relacionado con R2 en sí): `api/case_documents_
   endpoint.py::_generar_contenido_y_pdf` nunca pasaba `despacho_id` a
   `JuliXService.generar_documento(...)` (quedaba en el default `None`),
   así que el INSERT a `julix_calls` con `despacho_id=NULL` nunca podía
   satisfacer la política RLS de tenant isolation bajo un contexto ya
   angosteado -- `api/julix_endpoint.py` ya lo resolvía bien, este
   endpoint se armó antes de que RLS llegara a `julix_calls` y nunca se
   actualizó. **Este bug es también la prueba de que TF1 (y la RLS
   original de `julix_calls`) protegen de verdad en producción** -- ver
   la corrección completa en TF1 más abajo. Fix: `caso["despacho_id"]`
   pasado explícito a través de la cadena de llamadas. Test de regresión
   nuevo. Commit `e79aa12`, CI verde, desplegado (deploy `a6667ccd`).
   **Segundo intento, exitoso**: documento generado con `generar_pdf=
   true` de verdad (llamada real a Anthropic), `pdf_url` fue una URL
   real firmada del bucket R2
   (`https://<account>.r2.cloudflarestorage.com/vridik-producs/...`,
   con `X-Amz-Signature`), y `GET /casos/{id}/documents/{id}/pdf`
   redirigió (307) a esa misma URL real. Cuenta throwaway limpiada de la
   base después (el objeto que quedó en el bucket R2 real no se borró --
   es un PDF de prueba pequeño, impacto mínimo, no se automatizó su
   borrado esta vez).
4. Los PDFs viejos con rutas de filesystem quedan 404 con el mensaje de
   "almacenamiento efímero" ya existente — aceptable, documentarlo.

### T6 — ~~Staging mínimo~~ CERRADO (21-jul-2026)
Ver "Ya hecho". Entorno `staging-vridik` real en Railway (API+frontend+
Postgres propios, clon estructural sin datos reales), tres hallazgos de
aislamiento corregidos (DATABASE_URL/VRIDIK_ALLOWED_ORIGINS/
VITE_API_BASE apuntaban a producción tal cual se duplicaron), un bug
real de arranque en frío encontrado y arreglado (`ensure_users_table`/
`ensure_role_column` faltaban al principio del bootstrap), seed
sintético (`scripts/seed_staging.py`) contra el esquema real, verificado
end-to-end (login real contra la API de staging). **Corrección (21-jul,
más tarde el mismo día)**: el fix de arranque (commits `55ae2da`/
`e9a7fe1`) YA estaba en producción -- quedan 9 commits detrás del deploy
`a6667ccd` (el mismo que se verificó para T5), así que "falta el deploy"
era incorrecto, era no-op de verdad. **Pendiente, no bloqueante**:
ensayar un rollback real y una rotación de `JWT_SECRET` en staging (la
infraestructura para hacerlo ya existe, el ensayo en sí es trabajo
aparte).

### T7 — Endpoints ARCO + retención (P1, Ley 1581) -- ACCESO CERRADO, SUPRESIÓN PENDIENTE DE DISEÑO
`GET /me/datos` (`api/datos_personales_endpoint.py` +
`core/datos_personales.py::exportar_datos_de_usuario`): acceso real,
export JSON de perfil + casos + mensajes + actuaciones + términos +
documentos + eventos de auth propios, ownership real (nunca por
despacho_id solo). Rectificación: delegada a endpoints existentes, sin
código nuevo. `PRIVACIDAD.md` (nuevo) documenta todo esto y dedica una
sección explícita a la propuesta de qué se anonimizaría vs qué se
conservaría por deber legal en una supresión -- **la supresión en sí
sigue sin implementar a propósito**, es una decisión de producto/legal
pendiente de cerrar con el dev lead (mismo criterio de "no adivinar
políticas" que se usó con el proveedor de storage en T5). El registro
RNBD sigue siendo trámite del dev lead, no código. Tests contra Postgres
real incluido el caso IDOR (el export de un usuario nunca trae filas de
otro participante del mismo caso). Commit `258d70b`, CI verde (run
`29852997582`).

### T8 — ~~RLS a las 5 tablas restantes~~ CERRADO (21-jul-2026) == TF1
Misma tarea que TF1 de Track Forja (ver abajo) -- se cerró ahí.

## Track Forja — producto vendible (ref: auditoría "Cuida tus mascotas")

Contexto en `vridik_forja_audit.md` + `vridik_architecture_v2.json`.
Objetivo: que Vridik deje de ser "un gestor más". Estas tareas NO dependen
del GATE de JuliX (venden aunque JuliX siga en 35%), así que pueden correr
en paralelo al track T2/T3. Orden sugerido: TF1 → TF2 → TF3.

### TF1 — ~~RLS completo en las 5 tablas indirectas~~ CERRADO Y VERIFICADO EN PRODUCCIÓN (21-jul-2026) == T8
`core/rls.py::ensure_rls_policies_indirectas()`, commit `1c6da1c`,
desplegado en producción. **CORRECCIÓN de una conclusión propia
equivocada de esta misma sesión (21-jul, más tarde el mismo día)**: se
había documentado acá que TF1 era "deuda técnica" porque `vridik-api` se
conectaba como el rol `postgres` (superusuario, `rolbypassrls=true`,
que siempre se salta RLS) -- ESO ERA UN ERROR DE DIAGNÓSTICO: el chequeo
se hizo contra las credenciales del propio SERVICIO Postgres de Railway
(`railway variables --service Postgres`), nunca contra el `DATABASE_URL`
real que usa `vridik-api`. Verificado recién, en el momento correcto
(mientras se investigaba el bug de `julix_calls` de T5 más abajo):
`vridik-api` en realidad se conecta con el rol **`vridik_app`**
(`rolsuper=false`, `rolbypassrls=false` -- confirmado con `SELECT
rolsuper, rolbypassrls FROM pg_roles`), un rol de aplicación real, ya
provisionado (por el dev lead o una sesión anterior, no por este
handoff). **Prueba empírica directa, conectando como `vridik_app` de
verdad** (no razonamiento sobre atributos de rol): sin contexto seteado,
`SELECT count(*) FROM <tabla>` da **0 filas** en las 7 tablas de TF1
(`actuaciones`/`terminos`/`cobro_caso`/`case_documents`/`mensajes`) MÁS
las 2 originales (`casos`/`julix_calls`), pese a que esas tablas sí
tienen datos reales (22 casos, confirmado aparte); con
`set_config('app.bypass_rls', 'true', false)`, esos mismos 22 casos
vuelven a aparecer -- el mecanismo de GUC funciona en las dos
direcciones. **TF1 protege de verdad en producción, ahora mismo.** No
hace falta ningún cambio de infraestructura adicional -- ya está.

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
TF1/TF2/TF3 verificados funcionalmente en vivo -- **actualizado más
tarde el mismo 21-jul**: la nota de acá abajo sobre TF1 como "deuda
técnica" fue un error de diagnóstico propio (se chequeó el rol
equivocado), corregido y re-verificado empíricamente contra el rol real
`vridik_app` -- TF1 protege de verdad, ver la entrada de corrección más
arriba en "Ya hecho" y la sección TF1 actualizada más abajo.

**CI subido a Postgres 18 (21-jul, ~23:30) -- CERRADO**: el pendiente de
subir la versión de Postgres de CI (`postgres:15`) para que deje de
divergir de la versión real de producción (18) -- causa raíz del 500 de
TF2 -- ya está hecho. Tres intentos hasta dar con el fix real (todos
commits reales, no descartados):
1. `postgres:15` -> `postgres:18` + `pgvector/pgvector:pg15` ->
   `pgvector/pgvector:pg18` en ambos jobs. Commit `ca9fef2`.
2. Rompió el paso de hardening RLS: `ALTER ROLE vridik NOSUPERUSER` daba
   `permission denied to alter role -- The bootstrap superuser must have
   the SUPERUSER attribute` (protección nueva de PG18). Primer intento de
   fix: crear un rol `vridik_app` sin superuser/bypassrls y reapuntar
   `DATABASE_URL` a ese rol para pytest, en vez de degradar `vridik`.
   Commit `3c843e3` -- **insuficiente solo**: "permission denied for
   schema public" (desde PG15 el `public` schema no da CREATE por
   defecto a roles que no son dueños). Commit `1c41fca` agregó el GRANT
   del schema -- **tampoco alcanzó**: "must be owner of table users"
   (`ensure_rls_policies()` corre `ALTER TABLE ... FORCE ROW LEVEL
   SECURITY` + `CREATE POLICY`, que exige ser dueño, no solo tener
   privilegios). Se probó `REASSIGN OWNED BY vridik TO vridik_app`
   (commit `0693d93`) -- **tampoco**: "cannot reassign ownership of
   objects owned by role vridik because they are required by the
   database system" (misma protección del bootstrap superuser).
3. **Fix real** (commit `9d517f7`): reordenar el job para crear
   `vridik_app` y reapuntar `DATABASE_URL`/`TEST_DATABASE_URL` **antes**
   de aplicar `schema_semana1_vridik.sql`/seed, no después -- así
   `vridik_app` es dueño de todo lo que crea desde el principio, sin
   necesitar transferir nunca la propiedad. `pgcrypto`/`citext` son
   extensiones "trusted" desde PG13, así que `CREATE EXTENSION` funciona
   para un rol no-superusuario con `CREATE` en el schema. CI verde (run
   `29877327931`), ambos jobs, 96.7% de tests (526/544, igual que antes
   del bump -- ver nota de hallazgo abajo).

**Hallazgo aparte, NO nuevo, confirmado explícitamente**: los 18 tests
que fallan (`test_alertas_terminos`, `test_corpus_curation`,
`test_datos_personales`, `test_health_score`, todos con
`UndefinedTableError`/`UndefinedColumnError` sobre `actuaciones`/
`terminos`/`users.role`/`users.es_superadmin`) fallaban IDÉNTICO en el
run de CI inmediatamente anterior al bump (`29869746082`, previo a
tocar nada de PG18) -- mismo 96.7%, mismos 18 nombres. Es un bug
preexistente de dependencia de orden entre tests (esas tablas/columnas
se crean de forma perezosa dentro de la transacción con rollback de la
fixture `db` de algún otro test, no de forma persistente), ajeno a este
bump y no introducido por él. Sigue por debajo del gate de 90% así que
CI pasa, pero queda como deuda técnica real de la suite, sin tocar en
esta pasada (fuera de alcance del bump de Postgres).

### TF0 — Definición de producto (sin código, 1 semana, dev lead + Ana Luisa)
Las 4 etapas Forja que Vridik no tiene, ya redactadas en
`vridik_architecture_v2.json` (personas, journey del loop de término,
20 user stories, pre-mortem). Consolidar en un `PDR_VRIDIK.md`. No es
trabajo de Claude Code — es decisión de producto; queda apuntado para que
las fases siguientes tengan norte.

### TF4 — Rediseño UI "Ledger editorial" (P1, no depende del GATE)
Contexto: el dev lead no está conforme con el UX/UI actual — se ve
genérico (cards planas, todo con el mismo peso visual, como cualquier
admin panel). Se evaluaron 3 direcciones (ver conversación de auditoría
UX); se eligió esta por menor riesgo: extiende el lenguaje visual que YA
existe en `frontend/src/casos/CasoDetailPage.tsx` (`.caso-hero`: serif
`Cormorant Garamond`, acento dorado `--gold`, timeline) hacia atrás, en
vez de inventar un sistema nuevo. Cero librerías nuevas, cero tokens
nuevos en `index.css` — todo con las variables que ya están definidas
ahí (`--serif`, `--gold`, `--mono`, `--accent`, semáforos).

Principios (investigados contra tendencias SaaS/legal-tech 2026):
tipografía editorial con numerales estilo "ledger" (serif + monoespaciada
tabular para cifras, como un informe bien diseñado, no un dashboard
genérico) transmite la seriedad que un producto legal necesita;
disclosure progresivo — el caso más urgente se distingue del resto por
peso visual, no todos los casos pesan igual en la lista.

Cambios concretos en `frontend/src/casos/CasosListPage.tsx` +
`frontend/src/layout.css` (no tocar `index.css` salvo que falte algún
token):
1. **Jerarquía por health-score, no por fecha de creación.** El caso con
   `health_score` más alto (o el término más urgente si no hay
   health_score) se renderiza como una fila "hero": más padding, título
   en `var(--serif)` a mayor tamaño, borde `1px solid var(--gold)` +
   `border-left: 3px solid var(--danger)` si está en rojo, descripción
   visible completa (no truncada). El resto de los casos se comprimen a
   una fila de una sola línea (título + 2 badges + fecha), sin card
   individual pesada — más parecido a una lista densa que a una grilla
   de cards idénticas.
2. **Numerales tabulares en toda cifra**: `font-variant-numeric:
   tabular-nums` en `--mono` para `dias_restantes`, `health_score`,
   montos de `Cobro.tsx` — ya se usa `var(--mono)` en varios lados, solo
   falta esta propiedad.
3. **Título de página y nombres de caso en serif**, no solo en
   `CasoDetailPage`. Aplicar `var(--serif)` a `.page-title` cuando la
   página es de `casos` (no en `AdminPage`/`AccountPage`, que son
   utilitarias — el serif es la "voz del expediente", no de la UI en
   general).
4. **Un solo sistema de badge por fila**, no tres compitiendo
   (`badge-termino`, `badge-noleidos`, `EstadoPill` hoy aparecen juntos
   en `.caso-row-meta`). Consolidar en un badge de mayor jerarquía
   (riesgo) + un indicador secundario más discreto (no-leídos como punto,
   no como badge redondo del mismo tamaño).

Verificación: capturas de pantalla antes/después (dev lead ya vio un
mockup estático en la conversación de auditoría — comparar contra eso,
no reinventar el diseño). Sin cambios de backend; no requiere
autorización especial. Probar en mobile (`@media max-width: 560px`, ya
existe la regla para `.caso-row` — extenderla al nuevo hero).

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
