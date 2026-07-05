#!/usr/bin/env python3
"""
Vridik / JuliX — rag/ingest_ugpp.py
Sprint S6: ingesta de los PDFs base de UGPP hacia `rag_chunks` (pgvector).

Qué hace:
  1. Lee los PDFs de /data/ugpp/ (30 documentos base esperados).
  2. Extrae el texto de cada PDF (pypdf).
  3. Divide cada documento en chunks de ~800 tokens con solape de 100
     tokens (para no cortar un artículo justo en el límite de un chunk).
  4. Genera embeddings locales (mismo modelo que rag/context_builder.py:
     sentence-transformers/all-MiniLM-L6-v2, 384 dimensiones).
  5. Inserta en `rag_chunks` (rag/sql/rag_chunks_schema.sql), deduplicando
     por hash del texto (`hash_dedup`) para que reingestar el mismo PDF no
     duplique chunks.

Relación con el roadmap: esta es la versión mínima para arrancar el RAG en
S6. El pipeline curado con metadatos jurídicos ricos (jerarquía, vigencia,
revisión humana de 3 pasos, exclusiones editoriales) vive en S7-S9
(corpus_documents/corpus_chunks) — no reemplaza ese trabajo, lo antecede.

Metadatos (norma/artículo/párrafo): en esta versión se extraen con una
heurística simple sobre el nombre del archivo y el texto (regex de
"Art. N", "Ley N de AAAA", etc.). Es deliberadamente aproximada — la
extracción fina con revisión humana es exactamente el trabajo de S7.

Modo por defecto: --dry-run (lista los PDFs encontrados y cuántos chunks
generaría cada uno, sin extraer texto completo, sin cargar el modelo de
embeddings y sin tocar la base de datos). --check es un chequeo de salud aún
más liviano (solo confirma que la carpeta existe y tiene PDFs, pensado para
el arranque de Railway en scripts/railway_setup_rag.sh). --commit ejecuta
la ingesta real.

USO:
    python rag/ingest_ugpp.py --carpeta data/ugpp              # dry-run
    python rag/ingest_ugpp.py --carpeta data/ugpp --check      # chequeo de salud
    python rag/ingest_ugpp.py --carpeta data/ugpp --commit     # ingesta real

NO SE EJECUTA EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import argparse
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

# Repo layout: julix/, rag/ son hermanos en la raíz.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag.context_builder import embeber_texto  # noqa: E402

logger = logging.getLogger("vridik.rag.ingest_ugpp")

CHUNK_SIZE_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
CARPETA_PDFS_POR_DEFECTO = Path("data/ugpp")
PALABRAS_POR_TOKEN = 0.75  # aproximación cuando no hay tokenizer real disponible

_RE_ARTICULO = re.compile(r"Art(?:í|i)culo\s+(\d+[A-Za-z]?)", re.IGNORECASE)
_RE_LEY = re.compile(r"Ley\s+(\d+)\s+de\s+(\d{4})", re.IGNORECASE)
_RE_DECRETO = re.compile(r"Decreto\s+(\d+)\s+de\s+(\d{4})", re.IGNORECASE)


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


def extraer_texto_pdf(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("Falta la dependencia 'pypdf' (pip install pypdf)")
    lector = PdfReader(str(path))
    return "\n".join(pagina.extract_text() or "" for pagina in lector.pages)


def _contar_tokens_aprox(texto: str) -> int:
    return max(1, round(len(texto.split()) / PALABRAS_POR_TOKEN))


def _dividir_en_palabras_por_chunk(total_palabras_texto: int) -> tuple[int, int]:
    """Convierte el tamaño de chunk/solape en tokens a un tamaño en palabras
    (aprox.), para poder trocear con un simple slicing de `str.split()`."""
    palabras_por_chunk = max(1, round(CHUNK_SIZE_TOKENS * PALABRAS_POR_TOKEN))
    palabras_de_solape = max(0, round(CHUNK_OVERLAP_TOKENS * PALABRAS_POR_TOKEN))
    return palabras_por_chunk, palabras_de_solape


def chunkear_texto(texto: str) -> list[str]:
    """Chunking de ~800 tokens con solape de 100 tokens. Usa palabras como
    proxy de tokens (aproximación documentada; un tokenizer real como
    tiktoken daría un split más fiel, pero esta aproximación es suficiente
    para el RAG base de S6 y evita una dependencia pesada adicional)."""
    palabras = texto.split()
    if not palabras:
        return []

    palabras_por_chunk, palabras_de_solape = _dividir_en_palabras_por_chunk(len(palabras))
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


def inferir_norma_desde_texto(texto: str, nombre_archivo: str) -> str:
    """Heurística simple (S6): busca 'Ley N de AAAA' / 'Decreto N de AAAA' en
    el propio texto del chunk; si no encuentra nada, usa el nombre del PDF
    como respaldo. La extracción fina y verificada la hace la revisión
    humana de S7 (mini-herramienta de 3 pasos, no este script)."""
    m_ley = _RE_LEY.search(texto)
    if m_ley:
        return f"Ley {m_ley.group(1)} de {m_ley.group(2)}"
    m_decreto = _RE_DECRETO.search(texto)
    if m_decreto:
        return f"Decreto {m_decreto.group(1)} de {m_decreto.group(2)}"
    return Path(nombre_archivo).stem.replace("_", " ")


def inferir_articulo_desde_texto(texto: str) -> str:
    m = _RE_ARTICULO.search(texto)
    if m:
        return f"Art. {m.group(1)}"
    return "Artículo no identificado (revisar en S7)"


def _hash_dedup(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def procesar_pdf(path: Path) -> list[ChunkParaIngestar]:
    texto_completo = extraer_texto_pdf(path)
    trozos = chunkear_texto(texto_completo)

    resultado = []
    for idx, trozo in enumerate(trozos):
        resultado.append(
            ChunkParaIngestar(
                norma=inferir_norma_desde_texto(trozo, path.name),
                articulo=inferir_articulo_desde_texto(trozo),
                parrafo=None,  # heurística de párrafo se deja para S7 (revisión humana)
                texto=trozo,
                tokens=_contar_tokens_aprox(trozo),
                fuente_pdf=path.name,
                chunk_index=idx,
                hash_dedup=_hash_dedup(trozo),
            )
        )
    return resultado


async def insertar_chunk(db_connection, chunk: ChunkParaIngestar) -> bool:
    """Inserta un chunk con su embedding. Retorna True si se insertó, False
    si ya existía (dedup por hash_dedup) — idempotente ante reingesta."""
    from rag.context_builder import _embedding_a_literal_pgvector  # import local, evita ciclo

    embedding = embeber_texto(chunk.texto)
    literal = _embedding_a_literal_pgvector(embedding)

    query = """
        INSERT INTO rag_chunks (norma, articulo, parrafo, texto, tokens, fuente_pdf, chunk_index, hash_dedup, embedding)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::vector)
        ON CONFLICT (hash_dedup) DO NOTHING
        RETURNING id
    """
    fila = await db_connection.fetchrow(
        query,
        chunk.norma, chunk.articulo, chunk.parrafo, chunk.texto, chunk.tokens,
        chunk.fuente_pdf, chunk.chunk_index, chunk.hash_dedup, literal,
    )
    return fila is not None


def listar_pdfs(carpeta: Path) -> list[Path]:
    return sorted(carpeta.glob("*.pdf"))


async def ingestar_carpeta(carpeta: Path, db_connection, *, commit: bool) -> dict:
    pdfs = listar_pdfs(carpeta)
    print(f"\n=== Vridik/RAG — ingesta de {carpeta} ===")
    print(f"PDFs encontrados: {len(pdfs)}")

    if not commit:
        print("Modo dry-run: no se extrae texto completo, no se cargan embeddings, no se toca la BD.")
        for pdf in pdfs:
            print(f"  {pdf.name}")
        return {"pdfs": len(pdfs), "chunks_insertados": 0, "chunks_duplicados": 0, "modo": "dry_run"}

    total_insertados = 0
    total_duplicados = 0
    for pdf in pdfs:
        chunks = procesar_pdf(pdf)
        print(f"  {pdf.name}: {len(chunks)} chunks")
        for chunk in chunks:
            insertado = await insertar_chunk(db_connection, chunk)
            if insertado:
                total_insertados += 1
            else:
                total_duplicados += 1

    print(f"\nResumen: {total_insertados} chunks nuevos, {total_duplicados} duplicados omitidos (dedup por hash).")
    return {
        "pdfs": len(pdfs),
        "chunks_insertados": total_insertados,
        "chunks_duplicados": total_duplicados,
        "modo": "commit",
    }


def validar_carpeta(carpeta: Path) -> dict:
    """--check: valida que la carpeta de PDFs existe y tiene contenido, SIN
    extraer texto, SIN cargar el modelo de embeddings y SIN tocar la base de
    datos. Pensado para correr como chequeo de salud en el arranque de
    Railway (scripts/railway_setup_rag.sh), antes de decidir si se corre
    --commit manualmente."""
    if not carpeta.exists():
        return {"ok": False, "motivo": f"la carpeta {carpeta} no existe", "carpeta": str(carpeta), "pdfs_encontrados": 0}
    pdfs = listar_pdfs(carpeta)
    if not pdfs:
        return {"ok": False, "motivo": f"no se encontraron PDFs en {carpeta}", "carpeta": str(carpeta), "pdfs_encontrados": 0}
    return {"ok": True, "motivo": "carpeta válida", "carpeta": str(carpeta), "pdfs_encontrados": len(pdfs)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik/JuliX — ingesta de PDFs UGPP a rag_chunks (S6)")
    parser.add_argument("--carpeta", default=str(CARPETA_PDFS_POR_DEFECTO))
    parser.add_argument("--check", action="store_true", help="Solo valida que la carpeta tenga PDFs (sin embeddings ni BD) y termina")
    parser.add_argument("--commit", action="store_true", help="Ejecuta la ingesta real (embeddings + BD)")
    args = parser.parse_args()

    carpeta = Path(args.carpeta)

    if args.check:
        resultado = validar_carpeta(carpeta)
        print(f"\n=== Vridik/RAG — chequeo de carpeta ({resultado['carpeta']}) ===")
        if resultado["ok"]:
            print(f"OK: {resultado['pdfs_encontrados']} PDF(s) encontrados. Listo para --commit cuando se decida ejecutar la ingesta real.")
            return 0
        print(f"ERROR: {resultado['motivo']}", file=sys.stderr)
        return 1

    if not carpeta.exists():
        print(f"ERROR: no existe la carpeta {carpeta}", file=sys.stderr)
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
                return await ingestar_carpeta(carpeta, conn, commit=True)
            finally:
                await conn.close()

        asyncio.run(_run())
        return 0

    asyncio.run(ingestar_carpeta(carpeta, None, commit=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
