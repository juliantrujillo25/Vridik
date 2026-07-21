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

## Cola de trabajo, en orden

### T1 — ~~Rotación de credenciales Postgres~~ CERRADO (20-jul-2026)
Confirmado con el dev lead: password rotada en Railway.

### T2 — Corpus verbatim para el banco (P0, causa raíz del gate reprobado) -- EN CURSO, ver "Ya hecho"
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

### T8 — RLS a las 5 tablas restantes (P1)
`core/rls.py` cubre users/casos/julix_calls/matriz_riesgo. Extender a
`actuaciones`, `terminos`, `cobro_caso`, `case_documents`, `mensajes`
(hoy dependen de WHERE manual vía join con casos). Mismo patrón
fail-open-con-narrowing documentado en el propio archivo. Tests contra
Postgres real de CI (fixture existente), no fakes.

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
