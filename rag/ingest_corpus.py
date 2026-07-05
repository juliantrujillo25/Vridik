#!/usr/bin/env python3
"""
Vridik / JuliX — rag/ingest_corpus.py
Sprint S7: expansión del corpus (85 -> 400 chunks). Sucesor de
rag/ingest_ugpp.py, generalizado para leer el manifiesto curado
data/corpus_manifest.csv en vez de escanear una única carpeta a ciegas.

Diferencias frente a rag/ingest_ugpp.py (que sigue existiendo, sin tocar,
para cargas puntuales sin manifiesto):
  - `--source csv`: lee data/corpus_manifest.csv (columnas fuente, tipo,
    norma, articulos_clave, prioridad) — la fuente de verdad de QUÉ se
    ingesta y con qué metadata, en vez de inferir norma/artículo por regex
    sobre el texto crudo.
  - `--priority {alta,media,baja,todas}` (acepta también los alias en
    inglés high/medium/low/all): filtra qué filas del manifiesto entran en
    esta corrida — permite cargar por olas (alta primero), igual que las
    4 olas de S8-S9 del roadmap.
  - `--offset` / `--limit`: paginación sobre las filas filtradas, para que
    scripts/ingest_batch.sh pueda correr en lotes de 50 sin cargar los 400
    chunks en una sola corrida larga.
  - Chunking de 600 tokens con solape de 120 (vs. 800/100 de
    ingest_ugpp.py) — calibración más fina: los considerandos de
    jurisprudencia suelen ser más cortos que un artículo de ley completo.
  - Metadata enriquecida por fila: `norma` y `articulo` (aproximado desde
    `articulos_clave`) vienen del CSV, no de una heurística sobre el texto;
    `anio` y `tribunal` se infieren del propio campo `norma`.

Modo por defecto: --dry-run (lista qué filas del manifiesto entrarían en la
corrida, sin extraer texto, sin cargar el modelo de embeddings y sin tocar
la base de datos). --commit ejecuta la ingesta real.

USO:
    python rag/ingest_corpus.py --source csv --priority alta                       # dry-run
    python rag/ingest_corpus.py --source csv --priority alta --offset 0 --limit 50 --commit

NO SE EJECUTA EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag.context_builder import embeber_texto, _embedding_a_literal_pgvector  # noqa: E402

logger = logging.getLogger("vridik.rag.ingest_corpus")

CHUNK_SIZE_TOKENS = 600
CHUNK_OVERLAP_TOKENS = 120
PALABRAS_POR_TOKEN = 0.75  # misma aproximación que ingest_ugpp.py

MANIFEST_POR_DEFECTO = Path("data/corpus_manifest.csv")
COLUMNAS_REQUERIDAS = {"fuente", "tipo", "norma", "articulos_clave", "prioridad"}
TIPOS_VALIDOS = {"ley", "decreto", "jurisprudencia"}

_ALIAS_PRIORIDAD = {
    "high": "alta", "alta": "alta",
    "medium": "media", "media": "media",
    "low": "baja", "baja": "baja",
    "all": "todas", "todas": "todas",
}

_RE_ANIO = re.compile(r"(19|20)\d{2}")
_TRIBUNALES_CONOCIDOS = [
    "Consejo de Estado", "Corte Suprema de Justicia", "Corte Constitucional",
    "Tribunal Administrativo", "Tribunal Superior",
]


@dataclass
class FilaManifiesto:
    fuente: str
    tipo: str
    norma: str
    articulos_clave: str
    prioridad: str  # normalizada a 'alta'|'media'|'baja'


@dataclass
class ChunkParaIngestar:
    norma: str
    articulo: str
    parrafo: str | None
    texto: str
    tokens: int
    fuente_pdf: str
    chunk_index: int
    hash_dedup: str
    anio: int | None
    tribunal: str | None
    tipo_fuente: str
    prioridad: str


def leer_manifiesto(path: Path) -> list[FilaManifiesto]:
    with open(path, encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas = set(lector.fieldnames or [])
        faltantes = COLUMNAS_REQUERIDAS - columnas
        if faltantes:
            raise ValueError(f"Manifiesto {path} no tiene las columnas requeridas: {faltantes}")

        filas = []
        for fila in lector:
            tipo = fila["tipo"].strip().lower()
            if tipo not in TIPOS_VALIDOS:
                logger.warning("Vridik/RAG: tipo desconocido '%s' en fila de %s — se omite", tipo, fila.get("fuente"))
                continue
            prioridad_raw = fila["prioridad"].strip().lower()
            prioridad = _ALIAS_PRIORIDAD.get(prioridad_raw, prioridad_raw)
            filas.append(
                FilaManifiesto(
                    fuente=fila["fuente"].strip(),
                    tipo=tipo,
                    norma=fila["norma"].strip(),
                    articulos_clave=fila["articulos_clave"].strip(),
                    prioridad=prioridad,
                )
            )
        return filas


def filtrar_por_prioridad(filas: list[FilaManifiesto], prioridad: str) -> list[FilaManifiesto]:
    prioridad_normalizada = _ALIAS_PRIORIDAD.get(prioridad.strip().lower(), prioridad.strip().lower())
    if prioridad_normalizada == "todas":
        return filas
    return [f for f in filas if f.prioridad == prioridad_normalizada]


def inferir_anio(norma: str) -> int | None:
    coincidencias = _RE_ANIO.findall(norma)
    if not coincidencias:
        return None
    # Si hay varios años en el texto (poco común), se toma el último —
    # normalmente es el año de expedición/decisión, que suele ir al final.
    match_completo = _RE_ANIO.search(norma)
    todos = re.findall(r"(?:19|20)\d{2}", norma)
    return int(todos[-1]) if todos else None


def inferir_tribunal(tipo: str, norma: str) -> str | None:
    if tipo != "jurisprudencia":
        return None
    for tribunal in _TRIBUNALES_CONOCIDOS:
        if tribunal.lower() in norma.lower():
            return tribunal
    return "Tribunal no identificado (revisar en curaduría)"


def _dividir_en_palabras_por_chunk() -> tuple[int, int]:
    palabras_por_chunk = max(1, round(CHUNK_SIZE_TOKENS * PALABRAS_POR_TOKEN))
    palabras_de_solape = max(0, round(CHUNK_OVERLAP_TOKENS * PALABRAS_POR_TOKEN))
    return palabras_por_chunk, palabras_de_solape


def chunkear_texto(texto: str) -> list[str]:
    """Chunking de ~600 tokens con solape de 120 (calibración S7, distinta
    de los 800/100 de ingest_ugpp.py — ver docstring del módulo)."""
    palabras = texto.split()
    if not palabras:
        return []
    palabras_por_chunk, palabras_de_solape = _dividir_en_palabras_por_chunk()
    paso = max(1, palabras_por_chunk - palabras_de_solape)

    chunks = []
    inicio = 0
    while inicio < len(palabras):
        fin = min(inicio + palabras_por_chunk, len(palabras))
        chunks.append(" ".join(palabras[inicio:fin]))
        if fin == len(palabras):
            break
        inicio += paso
    return chunks


def _contar_tokens_aprox(texto: str) -> int:
    return max(1, round(len(texto.split()) / PALABRAS_POR_TOKEN))


def _hash_dedup(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def extraer_texto_pdf(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("Falta la dependencia 'pypdf' (pip install pypdf)")
    lector = PdfReader(str(path))
    return "\n".join(pagina.extract_text() or "" for pagina in lector.pages)


def procesar_fila(fila: FilaManifiesto) -> list[ChunkParaIngestar]:
    """Extrae texto de `fila.fuente` (si el archivo existe) y lo divide en
    chunks, adjuntando la metadata del manifiesto (más confiable que
    inferirla del texto). Si el archivo no existe (manifiesto con
    referencias aún no descargadas/copiadas), retorna lista vacía con una
    advertencia — nunca interrumpe el resto del lote."""
    path = Path(fila.fuente)
    if not path.exists():
        logger.warning("Vridik/RAG: no existe el archivo '%s' referenciado en el manifiesto — se omite esta fila", fila.fuente)
        return []

    texto_completo = extraer_texto_pdf(path)
    trozos = chunkear_texto(texto_completo)
    anio = inferir_anio(fila.norma)
    tribunal = inferir_tribunal(fila.tipo, fila.norma)

    resultado = []
    for idx, trozo in enumerate(trozos):
        resultado.append(
            ChunkParaIngestar(
                norma=fila.norma,
                articulo=fila.articulos_clave,
                parrafo=None,
                texto=trozo,
                tokens=_contar_tokens_aprox(trozo),
                fuente_pdf=fila.fuente,
                chunk_index=idx,
                hash_dedup=_hash_dedup(trozo),
                anio=anio,
                tribunal=tribunal,
                tipo_fuente=fila.tipo,
                prioridad=fila.prioridad,
            )
        )
    return resultado


async def insertar_chunk(db_connection, chunk: ChunkParaIngestar) -> bool:
    embedding = embeber_texto(chunk.texto)
    literal = _embedding_a_literal_pgvector(embedding)

    query = """
        INSERT INTO rag_chunks (
            norma, articulo, parrafo, texto, tokens, fuente_pdf, chunk_index,
            hash_dedup, embedding, anio, tribunal, tipo_fuente, prioridad
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::vector,$10,$11,$12,$13)
        ON CONFLICT (hash_dedup) DO NOTHING
        RETURNING id
    """
    fila_insertada = await db_connection.fetchrow(
        query,
        chunk.norma, chunk.articulo, chunk.parrafo, chunk.texto, chunk.tokens,
        chunk.fuente_pdf, chunk.chunk_index, chunk.hash_dedup, literal,
        chunk.anio, chunk.tribunal, chunk.tipo_fuente, chunk.prioridad,
    )
    return fila_insertada is not None


def seleccionar_lote(
    filas: list[FilaManifiesto], *, offset: int, limit: int | None
) -> list[FilaManifiesto]:
    if limit is None:
        return filas[offset:]
    return filas[offset: offset + limit]


def simular_extraccion_y_chunking(lote: list[FilaManifiesto]) -> dict:
    """Simulación de dry-run "detallada" (pedida explícitamente en la
    validación posterior a S7): para cada fila del lote, revisa si el PDF
    referenciado existe en disco y, si existe, lo extrae y lo divide en
    chunks con `chunkear_texto` — exactamente la misma lógica que usaría
    `--commit`, pero SIN llamar a `embeber_texto` (nunca se carga
    sentence-transformers) y SIN tocar ninguna base de datos.

    Detecta duplicados por hash (sha256 del texto del chunk) tanto DENTRO
    de este lote como si dos filas del manifiesto apuntan al mismo PDF
    (p.ej. filas repetidas por error) — nunca contra rag_chunks real, ya
    que este modo no toca Postgres.

    Si el archivo no existe (caso esperado en este entorno, donde los PDFs
    reales de `/data/ugpp/` y `/data/cst/` aún no se han cargado), la fila
    se cuenta como 'no encontrada' y NO se inventa texto ni chunks para
    ella — reportar 0 es más honesto que simular contenido falso."""
    archivos_encontrados = 0
    archivos_no_encontrados = 0
    chunks_generados = 0
    tokens_totales = 0
    duplicados_detectados = 0
    hashes_vistos: set[str] = set()
    detalle_no_encontrados: list[str] = []

    for fila in lote:
        path = Path(fila.fuente)
        if not path.exists():
            archivos_no_encontrados += 1
            detalle_no_encontrados.append(fila.fuente)
            continue

        archivos_encontrados += 1
        try:
            texto = extraer_texto_pdf(path)
        except Exception as exc:  # pragma: no cover — solo si pypdf falla en un PDF real
            logger.warning("Vridik/RAG: no se pudo extraer texto de '%s': %s", fila.fuente, exc)
            continue

        for trozo in chunkear_texto(texto):
            chunks_generados += 1
            tokens_totales += _contar_tokens_aprox(trozo)
            h = _hash_dedup(trozo)
            if h in hashes_vistos:
                duplicados_detectados += 1
            else:
                hashes_vistos.add(h)

    tokens_promedio_por_chunk = round(tokens_totales / chunks_generados) if chunks_generados else 0
    tokens_ahorrados_por_dedup = duplicados_detectados * tokens_promedio_por_chunk

    return {
        "archivos_encontrados": archivos_encontrados,
        "archivos_no_encontrados": archivos_no_encontrados,
        "detalle_no_encontrados": detalle_no_encontrados,
        "chunks_generados": chunks_generados,
        "tokens_estimados_totales": tokens_totales,
        "duplicados_detectados": duplicados_detectados,
        "tokens_ahorrados_por_dedup": tokens_ahorrados_por_dedup,
    }


async def ingestar_manifiesto(
    manifest_path: Path,
    db_connection,
    *,
    prioridad: str,
    offset: int,
    limit: int | None,
    commit: bool,
) -> dict:
    todas_las_filas = leer_manifiesto(manifest_path)
    filtradas = filtrar_por_prioridad(todas_las_filas, prioridad)
    lote = seleccionar_lote(filtradas, offset=offset, limit=limit)

    print(f"\n=== Vridik/RAG — ingesta de corpus ({manifest_path}) ===")
    print(f"Filas totales: {len(todas_las_filas)} | prioridad='{prioridad}': {len(filtradas)} | lote (offset={offset}, limit={limit}): {len(lote)}")

    if not commit:
        print("Modo dry-run: no se cargan embeddings (sentence-transformers) y no se toca la BD.")
        for fila in lote:
            print(f"  [{fila.tipo:14s}] {fila.norma} — {fila.articulos_clave} (prioridad={fila.prioridad})")

        print("\n--- Simulación de extracción/chunking (sin embeddings, sin BD) ---")
        simulacion = simular_extraccion_y_chunking(lote)
        print(f"Archivos encontrados en disco:     {simulacion['archivos_encontrados']} / {len(lote)}")
        print(f"Archivos NO encontrados:            {simulacion['archivos_no_encontrados']} / {len(lote)}")
        if simulacion["detalle_no_encontrados"]:
            print("  (rutas referenciadas en el manifiesto que aún no existen en disco):")
            for ruta in simulacion["detalle_no_encontrados"]:
                print(f"    - {ruta}")
        print(f"Chunks que se generarían:           {simulacion['chunks_generados']}")
        print(f"Tokens estimados (aprox. 0.75 palabras/token): {simulacion['tokens_estimados_totales']}")
        print(f"Duplicados detectados (por hash):   {simulacion['duplicados_detectados']}")
        print(f"Tokens de embedding ahorrados por dedup: {simulacion['tokens_ahorrados_por_dedup']}")

        return {
            "filas_totales": len(todas_las_filas),
            "filas_en_lote": len(lote),
            "chunks_insertados": 0,
            "chunks_duplicados": 0,
            "modo": "dry_run",
            **simulacion,
        }

    total_insertados = 0
    total_duplicados = 0
    total_omitidas_sin_archivo = 0
    for fila in lote:
        chunks = procesar_fila(fila)
        if not chunks:
            total_omitidas_sin_archivo += 1
            continue
        print(f"  {fila.norma} ({fila.fuente}): {len(chunks)} chunks")
        for chunk in chunks:
            insertado = await insertar_chunk(db_connection, chunk)
            if insertado:
                total_insertados += 1
            else:
                total_duplicados += 1

    print(
        f"\nResumen del lote: {total_insertados} chunks nuevos, {total_duplicados} duplicados omitidos, "
        f"{total_omitidas_sin_archivo} filas omitidas por archivo no encontrado."
    )
    return {
        "filas_totales": len(todas_las_filas),
        "filas_en_lote": len(lote),
        "chunks_insertados": total_insertados,
        "chunks_duplicados": total_duplicados,
        "filas_omitidas_sin_archivo": total_omitidas_sin_archivo,
        "modo": "commit",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik/JuliX — ingesta de corpus curado a rag_chunks (S7)")
    # --source acepta el valor histórico 'csv' (usa --manifest / el default)
    # o, por compatibilidad con el comando de validación pedido por el dev
    # lead ("--source data/corpus_manifest.csv"), una ruta directa al CSV.
    parser.add_argument("--source", default="csv", help="'csv' (usa --manifest) o una ruta directa al manifiesto CSV")
    parser.add_argument("--manifest", default=None, help="Ruta al manifiesto (por defecto: data/corpus_manifest.csv, o el valor de --source si es una ruta)")
    parser.add_argument("--priority", default="alta", help="alta|media|baja|todas (o high/medium/low/all)")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None, help="Tamaño del lote; None = sin límite (todas las filas filtradas)")
    parser.add_argument("--dry-run", action="store_true", help="Explícito (ya es el comportamiento por defecto si no se pasa --commit)")
    parser.add_argument("--commit", action="store_true", help="Ejecuta la ingesta real (embeddings + BD)")
    args = parser.parse_args()

    if args.dry_run and args.commit:
        print("ERROR: --dry-run y --commit son mutuamente excluyentes", file=sys.stderr)
        return 1

    if args.manifest:
        manifest_path = Path(args.manifest)
    elif args.source not in ("csv",):
        # --source trae una ruta directa (p.ej. "data/corpus_manifest.csv")
        manifest_path = Path(args.source)
    else:
        manifest_path = MANIFEST_POR_DEFECTO

    if not manifest_path.exists():
        print(f"ERROR: no existe el manifiesto {manifest_path}", file=sys.stderr)
        return 1

    import asyncio

    if args.commit:
        try:
            import asyncpg  # type: ignore
        except ImportError:
            print("ERROR: falta 'asyncpg' para --commit (pip install asyncpg)", file=sys.stderr)
            return 1
        import os

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("ERROR: DATABASE_URL no configurado; requerido para --commit", file=sys.stderr)
            return 1

        async def _run():
            conn = await asyncpg.connect(database_url)
            try:
                return await ingestar_manifiesto(
                    manifest_path, conn, prioridad=args.priority,
                    offset=args.offset, limit=args.limit, commit=True,
                )
            finally:
                await conn.close()

        asyncio.run(_run())
        return 0

    asyncio.run(
        ingestar_manifiesto(
            manifest_path, None, prioridad=args.priority,
            offset=args.offset, limit=args.limit, commit=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
