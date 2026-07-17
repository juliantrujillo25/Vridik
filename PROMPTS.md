# PROMPTS.md — bitácora de iteración de JuliX

S6-GAP-01 (`AUDITORIA_PARA_CLAUDE.md`): consolida en un solo lugar cada
versión de prompt en `julix/prompts/*.md`, su hipótesis de cambio, el
patrón de fallo que la motivó y el resultado de la corrida de prueba
correspondiente. Fuente de verdad de cada prompt: el propio archivo `.md`
(encabezado `v:`/`tarea:`/`hipotesis:`), este documento es un índice de
lectura rápida, no un duplicado — si hay discrepancia, manda el `.md`.

**Estado honesto de las corridas de prueba:** el banco de evaluación
(`eval/banco_casos_vridik.xlsx`, S5-GAP-01) recibió las 20 `respuesta_
esperada` de Ana Luisa el 15-jul-2026 y el GATE corrió por primera vez
contra Claude real ese mismo día (run `s5-20260715T233826Z-4f201beb`,
costo real $1.09 USD). Resultado: **3/20 aprobados (15%), GATE de Fase 1
(≥80%) NO APROBADO** — ver diagnóstico completo en la entrada de
`ugpp_demanda`/`laboral_consulta` v2 más abajo, las dos únicas tareas que
el banco de S5 ejercita hoy (`redaccion_ugpp`, `laboral_colombia` y
`litigio_colombia` siguen sin corrida real: ningún caso del banco actual
tiene `area` que mapee a esas tareas). Los prompts sin resultado medido
todavía dicen explícitamente "sin corrida real todavía" en vez de
inventar un número.

## Regla de oro heredable

Un cambio de prompt por experimento, con hipótesis escrita ANTES de
correrlo (no una explicación post-hoc de por qué funcionó o no). Jerarquía
de intervención, del roadmap original (Fase 1, Semana 6): reordenar
contexto → instrucciones negativas explícitas → razonamiento por etapas
→ ejemplos del patrón oro → cambio de modelo. Cada nivel se prueba antes
de saltar al siguiente.

## tarea: redaccion_ugpp

### v1 — `redaccion_ugpp_v1.md`
- **Modelo sugerido:** claude-sonnet-5
- **Hipótesis:** versión base — instrucción directa, sin ejemplos ni
  razonamiento por etapas explícito.
- **Patrón de fallo que la motivó:** ninguno todavía — es la versión de
  arranque de la tarea.
- **Resultado:** sin corrida real todavía (bloqueado en S5-GAP-01).

### v2 — `redaccion_ugpp_v2.md`
- **Modelo sugerido:** claude-sonnet-5
- **Hipótesis:** instrucción negativa explícita contra citar artículos
  derogados + razonamiento por etapas con procedibilidad obligatoria
  reduce alucinaciones y omisiones.
- **Patrón de fallo que la motivó:** detectado en la corrida 1 del banco
  (S5) — según la hipótesis del propio archivo, v1 permitía citar normas
  derogadas y omitir el análisis de procedibilidad.
- **Resultado:** sin corrida real todavía — la "corrida 1" que motivó
  esta hipótesis tampoco tiene artefacto de resultado en el repo
  (ver limitación de S5-GAP-01 en `AUDITORIA_PARA_CLAUDE.md`: la corrida
  1 documentada en `backlog_fase1_vridik.md` no dejó un JSON/reporte
  verificable, solo la narrativa del propio prompt).

## tarea: clasificacion_documento

### v1 — `clasificacion_documento_v1.md`
- **Modelo sugerido:** claude-haiku-4-5-20251001
- **Hipótesis:** clasificación corta con salida JSON estricta, sin
  razonamiento libre — tarea de triage, no de redacción, por eso el
  modelo más barato/rápido.
- **Patrón de fallo que la motivó:** ninguno todavía.
- **Resultado:** sin corrida real todavía.

## tarea: ugpp_demanda

### v1 — `v1_ugpp_demanda.md`
- **Modelo sugerido:** claude-sonnet-4-20250514 (histórico — ver nota de
  modelos abajo)
- **Hipótesis:** system prompt con jerarquía normativa colombiana
  explícita reduce citas de normas derogadas y respuestas sin fundamento
  jurisdiccional claro.
- **Patrón de fallo que la motivó:** ninguno todavía.
- **Resultado (15-jul-2026, run `s5-20260715T233826Z-4f201beb`, 12
  casos UGPP reales contra Claude):** 4/12 aprobados. Patrón dominante:
  **abstención, no alucinación** — en 7 de los 8 casos reprobados, JuliX
  se negó a dar tarifas/plazos/fórmulas de una norma que SÍ se le había
  nombrado como fuente aplicable (p.ej. "art. 179 Ley 1607/2012"), solo
  porque se le entregó la cita y no el texto literal completo; la regla 1
  ("si una norma citada no aparece en las fuentes entregadas, NO la
  cites") y `DIRECTIVA_FUENTE_OBLIGATORIA` v1 (`julix/service.py`) no
  distinguían eso de "aplicar el contenido de una norma que SÍ fue
  nombrada". Un subconjunto más chico (UGPP-04/06/08/09) sí alucinó de
  verdad: citó artículos fuera de `norma_clave`. UGPP-07 se sacó de esta
  lista — ver corrección del 16-jul-2026 abajo, es en realidad un caso de
  abstención, no de alucinación.

  **Corrección (16-jul-2026), verificada contra `julix_evals` real, run
  `s5-20260715T233826Z-4f201beb`** (la corrida oficial del GATE, 15%):
  UGPP-07 SÍ tenía "Decreto 379 de 2026" como fuente autorizada en
  `norma_clave` de ese caso, y **el decreto es real** (confirmado contra
  Función Pública y el sitio oficial de la UGPP — regula el traslado a la
  UGPP de la potestad de fijar costos presuntos de independientes,
  vigente desde may-2026, ver `data/PROPUESTA_CORPUS_OLA1.md` en la rama
  `worktree-corpus+propuesta-ola1`). JuliX no inventó el decreto — lo
  citó porque se le dio como fuente autorizada, pero luego **dudó de su
  propia existencia** ("se requiere confirmar que dicha norma exista...
  si resulta aplicable *ratione temporis*"), presumiblemente por ser una
  norma muy reciente y estar cerca del borde de lo que el modelo conoce
  de memoria. El juez tomó esa duda como si JuliX hubiera "introducido un
  decreto inexistente" y marcó `hallucination_flag=true`, score=0 — el
  mismo bug de juez que este documento ya identificaba arriba, aplicado
  específicamente a este caso. La fila de `julix_evals` de esa corrida
  oficial **nunca se corrigió retroactivamente** (el fix de
  `JUEZ_SYSTEM_PROMPT` solo aplicó hacia adelante). En la corrida
  siguiente (`s5-20260716T023451Z-46812ab1`, S6, 35%) el mismo caso ya no
  tiene `hallucination_flag`, score=3 (correcto, aunque sigue sin llegar
  al umbral de "aprobado" ≥4). **No cambia el % de aprobación reportado
  de ninguna corrida de forma material** (incluso re-juzgado sin el bug,
  UGPP-07 probablemente seguiría sin aprobar por score <4) — el valor de
  esta corrección es de diagnóstico: UGPP-07 pertenece al balde de
  "abstención/sobre-cautela" ya documentado como patrón dominante, no al
  balde más chico de "alucinación real". Patrón nuevo a vigilar en
  próximas iteraciones de prompt: JuliX puede llegar a **dudar de normas
  reales autorizadas solo por ser muy recientes** — un tipo de error
  distinto tanto de la abstención por falta de texto como de la
  alucinación por citar algo no autorizado.

### v2 — `v2_ugpp_demanda.md`
- **Modelo sugerido:** claude-sonnet-5-20250624
- **Hipótesis:** separar explícitamente "nunca introducir una norma NO
  autorizada" de "SÍ aplicar el conocimiento jurídico del contenido de
  una norma que SÍ fue autorizada" reduce las abstenciones sin abrir la
  puerta a alucinar normas no autorizadas. Mismo cambio en paralelo en
  `DIRECTIVA_FUENTE_OBLIGATORIA` v2 (`julix/service.py`, se aplica a
  TODAS las tareas, no solo esta).
- **Patrón de fallo que la motivó:** el de v1 arriba.
- **Resultado:** ver corrida conjunta al final de esta sección.

## tarea: laboral_consulta

### v1 — `v2_laboral_consulta.md`
- **Modelo sugerido:** claude-sonnet-4-20250514 (histórico)
- **Hipótesis:** consulta laboral enfocada en CST con checklist de
  procedibilidad (reclamación administrativa, prescripción) reduce
  respuestas genéricas sin anclaje al articulado.
- **Patrón de fallo que la motivó:** ninguno todavía.
- **Resultado (15-jul-2026, run `s5-20260715T233826Z-4f201beb`, 8 casos
  Laboral reales contra Claude):** 2/8 aprobados (LAB-03, LAB-04). Mismo
  patrón dominante de abstención que `ugpp_demanda` v1. Caso adicional:
  LAB-06 fue penalizado por citar el art. 488 CST para prescripción —
  contenido que la propia sección "Procedibilidad y prescripción" de este
  prompt le indica a JuliX que revise por defecto, aunque ese artículo no
  estuviera en la `norma_clave` restringida de ese caso puntual (el
  checklist de la v1 no aclaraba que es una guía de análisis, no una
  licencia para citar fuera de las fuentes del caso concreto).

### v2 — `laboral_consulta_v2.md`
- **Modelo sugerido:** claude-sonnet-5-20250624
- **Hipótesis:** misma distinción que `ugpp_demanda` v2 (nunca introducir
  norma no autorizada, sí aplicar contenido de norma sí autorizada), más
  una aclaración explícita de que el checklist de procedibilidad/
  prescripción es una guía de análisis, no una licencia para citar
  artículos fuera de las fuentes nombradas en el caso concreto.
- **Patrón de fallo que la motivó:** el de v1 arriba.
- **Resultado:** ver corrida conjunta abajo.

### Corrida de verificación de `ugpp_demanda` v2 + `laboral_consulta` v2 (15/16-jul-2026)

Banco completo (20 casos), mismo `eval/evaluador.py --commit`, después de
publicar ambas v2 y `DIRECTIVA_FUENTE_OBLIGATORIA` v2 (run
`s5-20260716T023451Z-46812ab1`, costo real $1.38 USD).

**Resultado: 7/20 aprobados (35%)** — más del doble que v1 (15%), GATE de
Fase 1 (≥80%) sigue **NO APROBADO**. La hipótesis de v2 se confirmó
parcialmente: la abstención bajó de forma medible (UGPP-01 pasó de score 1
a 3, varios casos que antes se negaban por completo ahora sí dan
tarifas/plazos), pero surgió un **patrón dominante nuevo**: cifras
concretas pero **incorrectas** en lugar de abstención total —
UGPP-03 (20% en vez del 5/20/35% escalonado del patrón oro), UGPP-05/10
(confunde plazos de recursos, inventa "dos meses" donde son "diez días"),
UGPP-12 (regla de riesgo laboral I-III vs. IV-V invertida), LAB-01/02
(porcentajes de recargo y días de indemnización distintos al patrón oro).

**Diagnóstico de fondo (no es solo un problema de prompt):** `norma_clave`
en el banco de S5 es SOLO la cita (ley/decreto/artículo), nunca el texto
literal del artículo — a diferencia del RAG real de producción
(`rag/context_builder.py`), que si recupera contenido verbatim de
`rag_chunks`. v2 le pidió al modelo que aplicara su conocimiento jurídico
del contenido de una norma ya citada; el modelo ahora SÍ responde, pero su
memoria paramétrica de cifras exactas (porcentajes, días, tramos) no
siempre es precisa — un modelo que "sabe aproximadamente" pero no tiene el
texto real inevitablemente va a errar cifras específicas alguna vez. Este
es un límite estructural del banco de S5 tal como está armado hoy (citas
sin texto), no algo que otra iteración de prompt por sí sola resuelva de
forma confiable: cualquier ajuste sigue moviendo la aguja entre "abstenerse"
y "adivinar con confianza", nunca hacia "tener el texto real". La solución
de fondo es que `norma_clave` incluya el texto verbatim del artículo (o que
el banco se corra contra el corpus real de RAG una vez esté completo,
S8-S9) — decisión pendiente con el usuario, no tomada unilateralmente acá.

**Caveat de medición:** 2/20 casos (UGPP-06, LAB-05) recibieron
score=0/hallucination_flag=true por una falla de formato JSON del juez
("Expecting ',' delimiter"), no por la respuesta real de JuliX —
`JuliXClient.validar_json()` no logró parsear la salida del juez en esos
dos casos. El % real de aprobación podría ser algo más alto si se
resuelve esa falla de parseo antes de la próxima corrida.

## tarea: laboral_colombia

### v3 — `v3_laboral_colombia.md`
- **Modelo sugerido:** claude-sonnet-5 (histórico, ver nota de modelos)
- **Hipótesis:** versión de litigio laboral (CST + CPT), distinta de
  `laboral_consulta` (asesoría) — fusiona guardrails de cita verbatim,
  etiquetas de procedencia y nota del revisor con calibración CPT/oralidad
  para reducir alucinaciones en escritos de demanda/contestación.
- **Patrón de fallo que la motivó:** ninguno todavía (arranca en v3
  directamente, sin v1/v2 propias — hereda el diseño de guardrails de
  `litigio_colombia`).
- **Resultado:** sin corrida real todavía.

## tarea: litigio_colombia

### v3 — `v3_litigio_colombia.md`
- **Modelo sugerido:** claude-sonnet-5 (histórico, ver nota de modelos)
- **Hipótesis:** fusiona guardrails de calidad (etiquetas de procedencia,
  nota del revisor, cita verbatim, dato-no-instrucción) con calibración
  CPACA/CGP colombiana para reducir alucinaciones y mejorar la utilidad
  del borrador para Ana Luisa.
- **Patrón de fallo que la motivó:** ninguno todavía.
- **Resultado:** sin corrida real todavía.

## Nota sobre los `modelo_sugerido` de los encabezados

Varios archivos referencian `claude-sonnet-5-20250624` o
`claude-sonnet-4-20250514` en su campo `modelo_sugerido` — esos IDs
**nunca existieron** en la API real de Anthropic (confirmado con una
llamada real, ver commit `cf518dc`: 404 `not_found_error`). El selector
real de modelo (`julix/client.py::MODEL_BY_TASK`, la única fuente de
verdad para qué modelo se usa de verdad) ya está corregido a
`claude-sonnet-5`. Los campos `modelo_sugerido` de los `.md` NO se
editaron — son metadata histórica de la hipótesis original de cada
prompt, y los prompts nunca se tocan fuera de un experimento con
hipótesis propia (ver regla de oro heredable arriba); corregir ese campo
aisladamente no es un experimento, es limpieza de metadata, y se deja
para cuando cada prompt reciba su próxima iteración real.
