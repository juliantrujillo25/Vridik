# Contribuir a Vridik

Tres reglas, del roadmap original (Fase 1, Semana 3 — Suite de tests + CI):

## 1. Un bug en producción gana un test antes que su fix

Si encuentras un bug ya desplegado (no algo que rompiste tú mismo mientras
escribías código nuevo), el orden es:

1. Escribe un test que reproduzca el bug — debe fallar contra el código
   actual.
2. Recién después, arregla el código hasta que ese test pase.

Un fix sin test que lo cubra es, por definición, un fix sin verificar: no
hay forma de saber si de verdad corrigió la causa raíz o solo el síntoma
que viste una vez.

## 2. Un test flaky se arregla o se borra esa misma semana

Un test que falla de forma intermitente sin que el código haya cambiado
(carrera de datos, dependencia de tiempo real, orden de ejecución) no se
deja "en observación" ni se re-ejecuta hasta que pase. Esa misma semana:

- Se arregla la causa raíz (casi siempre: dependencia de tiempo/orden mal
  controlada, no un bug real en el código bajo prueba), o
- Se borra. Un test flaky sin arreglar entrena al equipo a ignorar fallas
  de CI — es peor que no tener el test.

## 3. Los contratos solo cambian con anuncio

Un "contrato" es cualquier forma de respuesta HTTP, schema de tabla, o
firma de función pública que otro código (frontend, otro servicio, otro
desarrollador) ya está consumiendo. Ejemplos en este repo: el shape JSON
de `POST /auth/login`, las columnas de `users`, la firma de
`core.auth.create_jwt`.

Cambiar un contrato sin avisar rompe a quien lo consume sin que se entere
hasta que falla en producción. Antes de cambiar uno:

- Avisa explícitamente (mensaje al equipo, o al menos un commit separado
  con el cambio bien documentado en su propio mensaje).
- Si es posible, hazlo aditivo (agregar un campo nuevo) en vez de
  destructivo (renombrar/quitar uno existente) — mismo principio que las
  migraciones SQL idempotentes de este repo (`ADD COLUMN IF NOT EXISTS`,
  nunca `DROP`/`RENAME` sin una fase de transición).

## Cómo correr las pruebas

```bash
pip install -r requirements-test.txt
pytest -q
```

CI (`.github/workflows/ci.yml`) exige además:
- ≥90% de los tests en verde (`scripts/check_pass_ratio.py`).
- ≥60% de cobertura real (`coverage report --fail-under=60`).

Ningún test llama a Anthropic ni a PostgreSQL de producción por defecto —
todo corre contra fakes o, en CI, contra un contenedor de PostgreSQL
efímero que se destruye al terminar el job.
