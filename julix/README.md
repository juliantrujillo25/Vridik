# /julix/ — Módulo de redacción asistida por IA de Vridik

JuliX es el motor de generación documental de Vridik: recibe un caso, construye contexto desde
el RAG y el expediente, llama a Claude y entrega un borrador con streaming, costo conocido y
fallos ruidosos. Este directorio es el esqueleto de Sprint S4 (Fase 1 — "JuliX con Claude real").

## Estructura

```
julix/
├── __init__.py
├── service.py          # orquestador: recibe la petición, arma contexto, llama al client, persiste ledger
├── client.py            # wrapper del SDK de Anthropic: reintentos, timeouts, streaming, selección de modelo
├── context_builder.py    # presupuesto de tokens por parte del documento, truncado con criterio jurídico
├── ledger.py             # registro de costos/latencia/estado en julix_calls + límites blandos
├── errors.py              # taxonomía de los 5 modos de fallo domados
├── prompts/
│   ├── __init__.py        # loader de prompts versionados (lee encabezado `v:`)
│   ├── redaccion_ugpp_v1.md
│   ├── redaccion_ugpp_v2.md
│   └── clasificacion_documento_v1.md
└── sql/
    └── ledger_schema.sql  # tabla julix_calls (PostgreSQL)
```

## Convención de prompts versionados

Cada archivo en `prompts/` es texto plano con un encabezado obligatorio:

```
---
v: 2
tarea: redaccion_ugpp
modelo_sugerido: claude-sonnet-5
hipotesis: "Instrucción negativa explícita contra citar artículos derogados reduce alucinaciones"
---
```

`prompts/__init__.py` expone `load_prompt(tarea, version=None)`, que si `version` es `None` carga
la versión más alta encontrada. El hash del contenido (sin el encabezado) se calcula en tiempo de
carga y se guarda junto a cada llamada en `julix_calls.prompt_hash` — esto es lo que hace
reproducible la corrida del banco de evaluación (S5) y el script de S6.

## Selección de modelo por tarea

- **Documentos de fondo** (redacción UGPP, laboral): `claude-sonnet-5` por defecto; escalar a
  un modelo superior solo si el banco de evaluación (S5) lo exige con evidencia.
- **Clasificación / comunicaciones cortas**: `claude-haiku-4-5-20251001`.

La selección vive en `client.py::MODEL_BY_TASK` y es la única fuente de verdad — nunca hardcodear
el nombre del modelo en `service.py` ni en el frontend.

## Los 5 modos de fallo domados (`errors.py`)

| Fallo | Tratamiento |
|---|---|
| Timeout / error de red | Backoff exponencial; **sin reintento silencioso** si ya hubo streaming parcial al cliente |
| 429 (rate limit) | Respeta `retry-after`; encola y avisa al usuario, nunca reintento inmediato |
| 529 (sobrecarga) | Devuelve borrador parcial recuperable, marcado explícitamente como incompleto |
| Truncado por `max_tokens` | Se marca `status='truncated'`; **nunca se presenta como documento completo** |
| Formato de salida inválido | Se marca `status='invalid_format'`; no se corrige en silencio ni se reintenta sin registro |

## Ledger de costos (`ledger.py` + `sql/ledger_schema.sql`)

Cada llamada a Claude se registra en `julix_calls` con modelo, `prompt_version`, `prompt_hash`,
tokens de entrada/salida, costo en USD, latencia y estado. Límite blando mensual: 80% dispara
aviso, 100% exige confirmación explícita por documento (nunca bloqueo duro). Techo de tokens por
petición configurable por tarea. El widget de costos del Panel Vridik Pro lee de esta misma tabla.

## Streaming

`client.py` expone `stream_completion()` como generador async que emite chunks SSE compatibles con
el canal `/api/events/stream` de S11 (patrón notificar-y-buscar: el stream lleva el texto, su cierre
dispara la persistencia final en `julix_calls` y el documento queda disponible vía fetch normal).
El frontend debe poder cancelar visible en cualquier momento (`AbortController`).
