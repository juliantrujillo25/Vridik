#!/usr/bin/env python3
"""
Vridik / JuliX — rag/ingest_desktop.py
Ingesta de documentos de clientes reales (carpetas de escritorio del
despacho: p.ej. "Giraldo Velasco Abogados", "Marta Arias") al RAG, con
dedup en dos niveles y anonimización obligatoria antes de generar
cualquier embedding.

Dedup en dos niveles (pensado para "economizar tokens" — nunca se paga el
costo de extracción/anonimización/embedding dos veces por el mismo
contenido):
  1. Nivel ARCHIVO: sha256 del contenido completo del archivo. Si ya existe
     una fila en rag_chunks con metadata->>'sha256' == este hash, el
     archivo se salta por completo (nunca se re-extrae texto, nunca se
     re-embebe) -> log "skip - ya indexado".
  2. Nivel CHUNK: dentro de un archivo nuevo, cada chunk (ya anonimizado)
     tiene su propio hash_dedup; si ese chunk específico ya existe en
     rag_chunks (texto repetido entre dos documentos distintos — muy común
     en expedientes UGPP: la misma plantilla de poder, el mismo anexo
     reenviado en dos memoriales) tampoco se re-embebe.

Pipeline por archivo NUEVO:
    extraer texto -> anonimizar (rag/anonymizer.py: personas -> [CLIENTE],
    NIT/cédula -> [ID]) -> chunking 600/120 (mismo chunker que
    rag/ingest_corpus.py) -> por cada chunk: si el hash_chunk ya existe se
    omite; los chunks nuevos se agrupan en lotes de 32 para una sola
    llamada de embedding por lote (menos invocaciones al modelo local) y
    se insertan en rag_chunks con metadata JSONB {sha256, fuente, norma,
    articulo}.

IMPORTANTE — alcance de este entregable:
  - El `--dry-run` SÍ es seguro de correr contra carpetas reales de
    clientes: solo calcula hashes y cuenta chunks/tokens en memoria: NUNCA
    escribe el texto extraído a disco, nunca llama a sentence-transformers,
    nunca toca Postgres. El `data/desktop_manifest.csv` que genera solo
    tiene rutas, hashes y conteos — cero texto de documentos.
  - El `--commit` (extracción real + anonimización + embeddings +
    inserción en rag_chunks) SÍ requiere DATABASE_URL y SÍ llama a
    sentence-transformers localmente. No se ejecutó `--commit` contra las
    carpetas reales de clientes en este entregable — ver README.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover
    docx = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag.ingest_corpus import chunkear_texto, _hash_dedup, _contar_tokens_aprox  # noqa: E402
from rag.anonymizer import anonimizar_texto, is_duplicate, modo_ner_activo  # noqa: E402

logger = logging.getLogger("vridik.rag.ingest_desktop")

EXTENSIONES_SOPORTADAS = {".pdf", ".docx", ".txt"}
TAMANIO_LOTE_EMBEDDING = 32
MANIFEST_POR_DEFECTO = Path("data/desktop_manifest.csv")

# Salvaguarda de rendimiento: algunos anexos contables reales (mayores y
# balances auxiliares en PDF, p.ej. "Movimiento Auxiliar ... .pdf") pesan
# 15-25MB y tardan minutos en extraerse página por página con pypdf. Por
# encima de este umbral, el --dry-run NO extrae el texto completo —usa la
# estimación barata por tamaño (_estimar_tokens_por_tamano) y lo marca
# como "nuevo_pesado" para que el equipo decida aparte si vale la pena
# ingestar ese anexo (normalmente son tablas contables, no texto jurídico
# citable). --commit sí extrae estos archivos completos si se decide
# ingestarlos explícitamente (no aplica este límite).
TAMANIO_MAXIMO_EXTRACCION_DRY_RUN_BYTES = 8 * 1024 * 1024  # 8 MB

# Normalización del nombre de carpeta -> etiqueta 'fuente' consistente,
# para que rag/context_builder.py pueda hacer boost sin depender de la
# capitalización exacta del sistema de archivos ("GIRALDO VELASCO ABOGADOS"
# vs "Giraldo Velasco").
_ALIAS_FUENTE = {
    "giraldo velasco abogados": "Giraldo Velasco",
    "giraldo velasco": "Giraldo Velasco",
    "marta arias": "Marta Arias",
    "juris-ia": "Juris-IA",
}


def normalizar_fuente(nombre_carpeta: str) -> str:
    return _ALIAS_FUENTE.get(nombre_carpeta.strip().lower(), nombre_carpeta.strip())


@dataclass
class ArchivoEscaneado:
    ruta: Path
    fuente: str  # etiqueta normalizada de la carpeta de origen


@dataclass
class ResultadoArchivo:
    ruta: str
    sha256: str
    estado: str  # 'nuevo' | 'skip' | 'no_soportado' | 'error'
    chunks_nuevos: int = 0
    chunks_duplicados: int = 0
    tokens_usados: int = 0
    tokens_ahorrados: int = 0
    detalle: str = ""


def escanear_carpetas(fuentes: list[Path]) -> tuple[list[ArchivoEscaneado], list[str]]:
    """Recorre recursivamente cada carpeta y clasifica cada archivo por
    extensión soportada. Retorna (archivos_soportados, rutas_omitidas) —
    las omitidas (xlsx, jpeg, etc.) se reportan aparte, nunca en silencio."""
    archivos: list[ArchivoEscaneado] = []
    omitidas: list[str] = []
    for carpeta in fuentes:
        if not carpeta.exists():
            logger.warning("Vridik/RAG: carpeta '%s' no existe — se omite", carpeta)
            continue
        fuente = normalizar_fuente(carpeta.name)
        for path in sorted(carpeta.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in EXTENSIONES_SOPORTADAS:
                archivos.append(ArchivoEscaneado(ruta=path, fuente=fuente))
            else:
                omitidas.append(str(path))
    return archivos, omitidas


def calcular_sha256_archivo(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extraer_texto(path: Path) -> str:
    sufijo = path.suffix.lower()
    if sufijo == ".pdf":
        if PdfReader is None:
            raise RuntimeError("Falta 'pypdf' para extraer PDFs (pip install pypdf)")
        lector = PdfReader(str(path))
        return "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
    if sufijo == ".docx":
        if docx is None:
            raise RuntimeError("Falta 'python-docx' para extraer .docx (pip install python-docx)")
        documento = docx.Document(str(path))
        return "\n".join(p.text for p in documento.paragraphs)
    if sufijo == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Extensión no soportada: {sufijo}")


def _estimar_tokens_por_tamano(path: Path) -> int:
    """Estimación BARATA de tokens sin extraer texto — usada solo para
    reportar 'tokens_ahorrados' de archivos que se saltan por estar ya
    indexados (si ya sabemos que se van a saltar, extraer el texto real
    sería precisamente el trabajo que estamos evitando). Heurística: ~6
    bytes por carácter equivalente de texto en PDFs/DOCX comprimidos,
    ~0.75 palabras/token (misma convención que rag/ingest_corpus.py)."""
    tamano_bytes = path.stat().st_size
    caracteres_aprox = max(1, tamano_bytes // 2)  # aproximación conservadora
    palabras_aprox = caracteres_aprox / 5.5  # ~5.5 caracteres/palabra en español
    return max(1, round(palabras_aprox / 0.75))


async def archivo_ya_indexado(db_connection, sha256: str) -> bool:
    """Chequeo de dedup nivel-archivo contra rag_chunks.metadata (JSONB).
    Requiere la migración rag/sql/003_rag_chunks_metadata_jsonb.sql."""
    if db_connection is None:
        return False
    fila = await db_connection.fetchrow(
        "SELECT 1 FROM rag_chunks WHERE metadata->>'sha256' = $1 LIMIT 1", sha256
    )
    return fila is not None


async def chunk_ya_indexado(db_connection, hash_chunk: str) -> bool:
    if db_connection is None:
        return False
    fila = await db_connection.fetchrow(
        "SELECT 1 FROM rag_chunks WHERE hash_dedup = $1 LIMIT 1", hash_chunk
    )
    return fila is not None


def embeber_lote(textos: list[str], *, batch_size: int = TAMANIO_LOTE_EMBEDDING) -> list[list[float]]:
    """Embebe una lista de textos en lotes de `batch_size` — UNA sola
    llamada a sentence-transformers por lote de hasta 32 chunks, en vez de
    una llamada por chunk. Con corpus de clientes (cientos de chunks por
    expediente) esto reduce el número de invocaciones al modelo local en
    ~32x, que es la optimización de tokens/latencia pedida explícitamente
    para esta ingesta."""
    from rag.context_builder import _cargar_modelo_embedding

    modelo = _cargar_modelo_embedding()
    vectores: list[list[float]] = []
    for inicio in range(0, len(textos), batch_size):
        lote = textos[inicio : inicio + batch_size]
        embebidos = modelo.encode(lote, normalize_embeddings=True, batch_size=batch_size)
        vectores.extend(v.tolist() for v in embebidos)
    return vectores


async def insertar_chunk_desktop(
    db_connection, *, norma: str, articulo: str, texto: str, tokens: int,
    fuente_pdf: str, chunk_index: int, hash_dedup: str, embedding_literal: str,
    sha256: str, fuente: str,
) -> bool:
    import json

    metadata = json.dumps({"sha256": sha256, "fuente": fuente, "norma": norma, "articulo": articulo}, ensure_ascii=False)
    query = """
        INSERT INTO rag_chunks (
            norma, articulo, parrafo, texto, tokens, fuente_pdf, chunk_index,
            hash_dedup, embedding, metadata
        )
        VALUES ($1,$2,NULL,$3,$4,$5,$6,$7,$8::vector,$9::jsonb)
        ON CONFLICT (hash_dedup) DO NOTHING
        RETURNING id
    """
    fila = await db_connection.fetchrow(
        query, norma, articulo, texto, tokens, fuente_pdf, chunk_index, hash_dedup, embedding_literal, metadata,
    )
    return fila is not None


def _norma_y_articulo_para_cliente(archivo: ArchivoEscaneado, chunk_index: int) -> tuple[str, str]:
    """Los documentos de clientes no son 'norma/artículo' en el sentido
    legislativo (ver rag/ingest_corpus.py) — son piezas de un expediente.
    Se reutilizan estas dos columnas (ya existentes en rag_chunks) para
    guardar una referencia citable equivalente: el nombre del documento y
    la posición del fragmento, de forma que ChunkRecuperado.cita siga
    produciendo una referencia legible en las respuestas de JuliX."""
    norma = f"Expediente {archivo.fuente} — {archivo.ruta.name}"
    articulo = f"Fragmento {chunk_index + 1}"
    return norma, articulo


def procesar_archivo_dry_run(
    archivo: ArchivoEscaneado, *, hashes_archivo_vistos: set[str], hashes_chunk_vistos: set[str],
) -> ResultadoArchivo:
    """Simulación completa SIN llamar a sentence-transformers y SIN tocar
    Postgres. Dedup nivel-archivo se resuelve contra `hashes_archivo_vistos`
    (in-memory, acumulado durante esta corrida — el chequeo real contra
    rag_chunks solo ocurre en --commit, que si tiene DATABASE_URL)."""
    try:
        sha = calcular_sha256_archivo(archivo.ruta)
    except Exception as exc:
        logger.warning("Vridik/RAG: no se pudo leer '%s': %s", archivo.ruta, exc)
        return ResultadoArchivo(ruta=str(archivo.ruta), sha256="", estado="error", detalle=str(exc))

    if is_duplicate(sha, hashes_archivo_vistos):
        return ResultadoArchivo(
            ruta=str(archivo.ruta), sha256=sha, estado="skip",
            tokens_ahorrados=_estimar_tokens_por_tamano(archivo.ruta),
            detalle="ya indexado (mismo sha256 visto antes en esta corrida)",
        )
    hashes_archivo_vistos.add(sha)

    if archivo.ruta.stat().st_size > TAMANIO_MAXIMO_EXTRACCION_DRY_RUN_BYTES:
        return ResultadoArchivo(
            ruta=str(archivo.ruta), sha256=sha, estado="nuevo_pesado",
            tokens_usados=_estimar_tokens_por_tamano(archivo.ruta),
            detalle=(
                f"archivo > {TAMANIO_MAXIMO_EXTRACCION_DRY_RUN_BYTES // (1024*1024)}MB — "
                "estimación por tamaño, no se extrajo el texto completo en --dry-run"
            ),
        )

    try:
        texto = extraer_texto(archivo.ruta)
    except Exception as exc:
        logger.warning("Vridik/RAG: no se pudo extraer texto de '%s': %s", archivo.ruta, exc)
        return ResultadoArchivo(ruta=str(archivo.ruta), sha256=sha, estado="error", detalle=str(exc))

    # La anonimización SÍ se ejecuta en dry-run (es barata, sin red, sin
    # BD) para que el conteo de tokens/chunks sea el real que tendría
    # --commit — pero el texto anonimizado se descarta en memoria al
    # terminar de contar; nunca se escribe a disco ni al manifest.
    texto_anonimizado = anonimizar_texto(texto)
    trozos = chunkear_texto(texto_anonimizado)

    nuevos = 0
    duplicados = 0
    tokens_usados = 0
    for trozo in trozos:
        h = _hash_dedup(trozo)
        if is_duplicate(h, hashes_chunk_vistos):
            duplicados += 1
            continue
        hashes_chunk_vistos.add(h)
        nuevos += 1
        tokens_usados += _contar_tokens_aprox(trozo)

    return ResultadoArchivo(
        ruta=str(archivo.ruta), sha256=sha, estado="nuevo",
        chunks_nuevos=nuevos, chunks_duplicados=duplicados, tokens_usados=tokens_usados,
    )


async def procesar_archivo_commit(
    archivo: ArchivoEscaneado, db_connection,
) -> ResultadoArchivo:
    """Pipeline real: dedup contra rag_chunks (BD), anonimización,
    chunking, embedding en lotes de 32, e inserción. Requiere
    DATABASE_URL y sentence-transformers instalado."""
    from rag.context_builder import _embedding_a_literal_pgvector

    sha = calcular_sha256_archivo(archivo.ruta)
    if await archivo_ya_indexado(db_connection, sha):
        return ResultadoArchivo(ruta=str(archivo.ruta), sha256=sha, estado="skip", detalle="ya indexado (sha256 en rag_chunks)")

    texto = extraer_texto(archivo.ruta)
    texto_anonimizado = anonimizar_texto(texto)
    trozos = chunkear_texto(texto_anonimizado)

    # Primero se filtran los chunks ya existentes (sin gastar embedding en
    # ellos), y solo el remanente se agrupa en lotes de 32.
    trozos_nuevos: list[str] = []
    hashes_nuevos: list[str] = []
    duplicados = 0
    for idx, trozo in enumerate(trozos):
        h = _hash_dedup(trozo)
        if await chunk_ya_indexado(db_connection, h):
            duplicados += 1
            continue
        trozos_nuevos.append(trozo)
        hashes_nuevos.append(h)

    insertados = 0
    tokens_usados = 0
    if trozos_nuevos:
        embeddings = embeber_lote(trozos_nuevos, batch_size=TAMANIO_LOTE_EMBEDDING)
        for idx, (trozo, h, emb) in enumerate(zip(trozos_nuevos, hashes_nuevos, embeddings)):
            norma, articulo = _norma_y_articulo_para_cliente(archivo, idx)
            literal = _embedding_a_literal_pgvector(emb)
            ok = await insertar_chunk_desktop(
                db_connection, norma=norma, articulo=articulo, texto=trozo,
                tokens=_contar_tokens_aprox(trozo), fuente_pdf=str(archivo.ruta),
                chunk_index=idx, hash_dedup=h, embedding_literal=literal,
                sha256=sha, fuente=archivo.fuente,
            )
            if ok:
                insertados += 1
                tokens_usados += _contar_tokens_aprox(trozo)

    return ResultadoArchivo(
        ruta=str(archivo.ruta), sha256=sha, estado="nuevo",
        chunks_nuevos=insertados, chunks_duplicados=duplicados, tokens_usados=tokens_usados,
    )


def escribir_manifest(resultados: list[ResultadoArchivo], ruta: Path) -> None:
    """Escribe SOLO metadata (ruta, hash, estado, conteos) — nunca texto de
    documentos ni nombres de personas detectadas. Seguro de compartir/versionar."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["ruta", "sha256", "estado", "chunks_nuevos", "tokens_usados"])
        for r in resultados:
            escritor.writerow([r.ruta, r.sha256, r.estado, r.chunks_nuevos, r.tokens_usados])


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik/JuliX — ingesta de documentos de clientes con dedup y anonimización")
    parser.add_argument("--source", action="append", required=True, help="Carpeta a escanear (repetible: --source A --source B)")
    parser.add_argument("--manifest", default=str(MANIFEST_POR_DEFECTO))
    parser.add_argument("--dry-run", action="store_true", help="Explícito (comportamiento por defecto si no se pasa --commit)")
    parser.add_argument("--commit", action="store_true", help="Ejecuta la ingesta real (anonimiza + embeddings + BD)")
    args = parser.parse_args()

    if args.dry_run and args.commit:
        print("ERROR: --dry-run y --commit son mutuamente excluyentes", file=sys.stderr)
        return 1

    carpetas = [Path(s).expanduser() for s in args.source]
    archivos, omitidas = escanear_carpetas(carpetas)

    print("=== Vridik/RAG — ingesta de documentos de clientes ===")
    print(f"Carpetas: {', '.join(str(c) for c in carpetas)}")
    print(f"Archivos soportados encontrados ({', '.join(sorted(EXTENSIONES_SOPORTADAS))}): {len(archivos)}")
    print(f"Archivos con extensión no soportada (omitidos): {len(omitidas)}")
    print(f"Modo de anonimización activo: {modo_ner_activo()}")

    if args.commit:
        try:
            import asyncpg  # type: ignore
        except ImportError:
            print("ERROR: falta 'asyncpg' para --commit (pip install asyncpg)", file=sys.stderr)
            return 1
        import asyncio
        import os

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("ERROR: DATABASE_URL no configurado; requerido para --commit", file=sys.stderr)
            return 1

        async def _run():
            conn = await asyncpg.connect(database_url)
            try:
                resultados = []
                for archivo in archivos:
                    r = await procesar_archivo_commit(archivo, conn)
                    resultados.append(r)
                    print(f"  [{r.estado:10s}] {r.ruta} — {r.chunks_nuevos} chunks nuevos, {r.chunks_duplicados} duplicados")
                return resultados
            finally:
                await conn.close()

        resultados = asyncio.run(_run())
        escribir_manifest(resultados, Path(args.manifest))
        nuevos = sum(1 for r in resultados if r.estado == "nuevo")
        skip = sum(1 for r in resultados if r.estado == "skip")
        print(f"\nResumen: {nuevos} archivos nuevos, {skip} archivos skip, manifest en {args.manifest}")
        return 0

    # --dry-run (por defecto)
    hashes_archivo_vistos: set[str] = set()
    hashes_chunk_vistos: set[str] = set()
    resultados = [
        procesar_archivo_dry_run(a, hashes_archivo_vistos=hashes_archivo_vistos, hashes_chunk_vistos=hashes_chunk_vistos)
        for a in archivos
    ]
    escribir_manifest(resultados, Path(args.manifest))

    archivos_nuevos = sum(1 for r in resultados if r.estado == "nuevo")
    archivos_nuevos_pesados = sum(1 for r in resultados if r.estado == "nuevo_pesado")
    archivos_skip = sum(1 for r in resultados if r.estado == "skip")
    archivos_error = sum(1 for r in resultados if r.estado == "error")
    chunks_nuevos_total = sum(r.chunks_nuevos for r in resultados)
    chunks_duplicados_total = sum(r.chunks_duplicados for r in resultados)
    tokens_usados_total = sum(r.tokens_usados for r in resultados)
    tokens_ahorrados_total = sum(r.tokens_ahorrados for r in resultados)

    print("\n--- Resumen dry-run (sin embeddings, sin BD) ---")
    print(f"archivos_nuevos:               {archivos_nuevos}")
    print(f"archivos_nuevos_pesados (>8MB, solo estimados): {archivos_nuevos_pesados}")
    print(f"archivos_skip:                 {archivos_skip}")
    print(f"archivos_error:                {archivos_error}")
    print(f"chunks_nuevos:                 {chunks_nuevos_total}")
    print(f"chunks_duplicados:             {chunks_duplicados_total}")
    print(f"tokens_usados (est.):          {tokens_usados_total}")
    print(f"tokens_ahorrados (est., por archivos ya indexados): {tokens_ahorrados_total}")
    print(f"Manifest escrito en: {args.manifest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
