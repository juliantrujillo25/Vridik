# PROMPTS.md — bitácora de iteración de JuliX

S6-GAP-01 (`AUDITORIA_PARA_CLAUDE.md`): consolida en un solo lugar cada
versión de prompt en `julix/prompts/*.md`, su hipótesis de cambio, el
patrón de fallo que la motivó y el resultado de la corrida de prueba
correspondiente. Fuente de verdad de cada prompt: el propio archivo `.md`
(encabezado `v:`/`tarea:`/`hipotesis:`), este documento es un índice de
lectura rápida, no un duplicado — si hay discrepancia, manda el `.md`.

**Estado honesto de las corridas de prueba:** el banco de evaluación
(`eval/banco_casos_vridik.xlsx`, S5-GAP-01) sigue sin `respuesta_esperada`
llenada por Ana Luisa — el GATE nunca corrió contra Claude real. Ningún
prompt de este documento tiene todavía un resultado medido; el campo
"Resultado" de cada versión dice explícitamente "sin corrida real
todavía" en vez de inventar un número. Actualizar este documento es parte
del criterio de cierre de S5-GAP-01, no de este.

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
- **Resultado:** sin corrida real todavía.

## tarea: laboral_consulta

### v1 — `v2_laboral_consulta.md`
- **Modelo sugerido:** claude-sonnet-4-20250514 (histórico)
- **Hipótesis:** consulta laboral enfocada en CST con checklist de
  procedibilidad (reclamación administrativa, prescripción) reduce
  respuestas genéricas sin anclaje al articulado.
- **Patrón de fallo que la motivó:** ninguno todavía.
- **Resultado:** sin corrida real todavía.

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
