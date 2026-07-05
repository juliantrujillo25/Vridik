# rag/ingest_desktop.py — Ingesta económica de documentos de cliente (S11)

Pipeline de ingesta para documentos de escritorio de clientes (Giraldo Velasco,
Marta Arias, etc.) diseñado para **minimizar llamadas a embeddings y evitar
reprocesar contenido ya indexado**.

## Uso

```bash
# 1. Simulación — no toca Postgres, no llama a sentence-transformers,
#    no persiste nada. Solo reporta qué pasaría.
python rag/ingest_desktop.py --source ~/Desktop --dry-run

# 2. Ingesta real — anonimiza, genera embeddings (batch de 32) y escribe
#    en rag_chunks. Requiere DATABASE_URL configurada.
python rag/ingest_desktop.py --source ~/Desktop --commit
```

`--source` acepta múltiples carpetas (`--source A --source B`). El nombre de
cada carpeta de primer nivel se usa como `fuente` (ver `normalizar_fuente()`),
por ejemplo `GIRALDO VELASCO ABOGADOS` → `"Giraldo Velasco"`.

## Qué hace cada modo

**`--dry-run`**: escanea archivos, calcula SHA256, compara contra
`data/desktop_manifest.csv` de corridas previas (o contra hashes vistos en la
misma corrida) para marcar `skip`. Para archivos nuevos, extrae texto,
anonimiza, chunkea (600/120) y cuenta chunks/tokens estimados — **sin
llamar a embeddings ni tocar la base de datos**. Archivos >8MB (p. ej.
libros mayores escaneados) se marcan `nuevo_pesado` y solo reciben una
estimación de tokens por tamaño de archivo, sin extracción completa (ver
`TAMANIO_MAXIMO_EXTRACCION_DRY_RUN_BYTES`).

**`--commit`**: mismo flujo, pero el dedup se verifica contra `rag_chunks`
real (`metadata->>'sha256'` a nivel archivo, `hash_dedup` a nivel chunk), el
texto se anonimiza con `rag/anonymizer.py` antes de cualquier embedding, los
chunks nuevos se embeben en lotes de 32 (`embeber_lote`) y se insertan con
`ON CONFLICT (hash_dedup) DO NOTHING`. Este modo **no se ha ejecutado nunca
contra carpetas de clientes reales** en este entorno de validación — queda
como código verificado (`py_compile` + tests) pendiente de ejecución en el
entorno de producción de Vridik, bajo los procedimientos de manejo de datos
del despacho.

## Ahorro de tokens — mecanismos

1. **Dedup a nivel archivo** (SHA256 del archivo completo): un archivo ya
   indexado se salta por completo, sin extraer texto ni chunkear.
2. **Dedup a nivel chunk** (hash del chunk tras anonimizar): plantillas
   repetidas (poderes, formatos de UGPP, anexos reenviados) solo se
   embeben una vez aunque aparezcan en documentos distintos.
3. **Batch embedding de 32 chunks por llamada** (`TAMANIO_LOTE_EMBEDDING`):
   reduce el número de invocaciones a `sentence-transformers` frente a
   embeber chunk por chunk.
4. **Salvaguarda de tamaño en `--dry-run`** (8MB): evita extracción completa
   de PDFs escaneados pesados (ej. libros contables de 12-25MB) durante la
   simulación, usando en su lugar una estimación barata por tamaño de
   archivo (`_estimar_tokens_por_tamano`).

## Anonimización (`rag/anonymizer.py`)

Se aplica **siempre antes de cualquier embedding**, en dos pasos:

- Identificadores (NIT, cédula) vía regex → `[ID]`.
- Personas vía NER de spaCy (`es_core_news_sm`) si está instalado; si no,
  fallback heurístico por mayúsculas (`modo_ner_activo()` reporta cuál está
  activo — se registra en el log de cada corrida).

Esto no es anonimización certificada para fines forenses/regulatorios —
es higiene previa a la ingesta; la revisión humana sigue siendo la última
línea de defensa contra fugas de PII en las respuestas de JuliX.

## Filtro/boost por fuente en recuperación (`rag/context_builder.py`)

`buscar_contexto()` acepta `solo_fuentes: list[str] | None` para filtrar
duro por `metadata->>'fuente'`. Además, chunks cuya `fuente_cliente` esté en
`FUENTES_CLIENTE_PRIORITARIAS = {"Giraldo Velasco", "Marta Arias"}` reciben
un bonus de `+0.08` en su `.score`, priorizándolos frente a jurisprudencia
genérica cuando la pregunta es sobre un caso de cliente específico.

## Manifiesto (`data/desktop_manifest.csv`)

Columnas: `ruta, sha256, estado, chunks_nuevos, tokens_usados`.
`estado` ∈ {`nuevo`, `nuevo_pesado`, `skip`, `no_soportado`, `error`}.

El manifiesto **nunca contiene texto de documentos ni nombres detectados**
— solo rutas, hashes y conteos — por lo que es seguro versionarlo o
compartirlo aunque referencie archivos reales de clientes.

### Corrida real de validación (2026-07, `--dry-run` únicamente)

Ejecutado contra las carpetas reales `GIRALDO VELASCO ABOGADOS` y
`MARTA ARIAS` (conectadas con autorización explícita del usuario, **solo
para simulación** — nunca se llamó a embeddings ni se escribió en Postgres):

| Métrica | Valor |
|---|---|
| Archivos nuevos (chunkeados) | 93 |
| Archivos nuevos pesados (>8MB, solo estimado) | 11 |
| Archivos skip (ya vistos / duplicados) | 7 |
| Chunks nuevos | 396 |
| Chunks duplicados evitados | 4 |
| Tokens reales estimados (93 archivos chunkeados) | ≈213,250 |
| Tokens estimados por tamaño (11 archivos pesados, NO chunkeados) | ≈28,006,370 |

**Nota importante**: los ≈28M "tokens" de los archivos pesados son una
estimación por tamaño de archivo, no un conteo real de chunks/tokens
procesados — esos 11 archivos (libros contables escaneados) fueron
deliberadamente excluidos de la extracción completa en `--dry-run`. No deben
sumarse a los 213,250 tokens reales como si fueran costo real de embedding.

Deduplicación real confirmada: archivos idénticos presentes en más de una
carpeta (`83954788.pdf`, `CC MARTA ARIAS.pdf`, `PLANILLAS PAGADAS.pdf`,
`SOPORTE PAGO SANCION.pdf`, `Anexo_0.pdf`) fueron correctamente marcados
`skip` en su segunda aparición.

### `JURIS IA` — fuera de alcance (decisión explícita del usuario)

Se conectó también `C:\Users\Julian Trujillo\Desktop\JURIS IA` para
inspección, pero resultó ser el **repositorio del propio proyecto**
(código fuente, `.git`, `node_modules`, `venv`, `juris_ia.db`, contratos de
API, ~126,980 archivos en total), no una carpeta de expedientes de cliente
como Giraldo Velasco o Marta Arias. Ante esta diferencia se preguntó al
usuario cómo proceder; su decisión fue **no escanear esta carpeta** en
absoluto — ni siquiera los documentos sueltos de la raíz. `JURIS IA` queda
excluida del alcance de `rag/ingest_desktop.py` en este sprint.

Se evaluó además migrar `JURIS IA/juris_ia.db` (SQLite) como fuente
alternativa de chunks/embeddings ya procesados. Inspección real del schema:
3 tablas (`analisis`, `procesos`, `generaciones`), **ninguna con columna de
embeddings/vector**, y las 3 con **0 filas**. Lo más cercano es
`analisis.texto_extraido` + `analisis.hash_pdf` (texto plano sin vectorizar,
tabla vacía). Se decidió no construir el extractor todavía — no hay nada
real que migrar — y dejarlo pendiente para cuando `juris_ia.db` tenga datos.
