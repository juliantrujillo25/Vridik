#!/usr/bin/env python3
"""
Vridik / JuliX — rag/quality_gate.py
Sprint S8: puerta de calidad del corpus curado. Valida cada chunk de
`rag_chunks` (o cada `ChunkParaIngestar` antes de insertarlo, ver
rag/ingest_corpus.py) contra 3 reglas mínimas y genera un reporte JSON.

Reglas de aceptación (las 3 deben cumplirse):
  1. El chunk tiene metadata de cita: `norma` y `articulo` no vacíos.
  2. El texto del chunk tiene al menos 100 caracteres (un chunk más corto
     casi nunca aporta contexto jurídico útil — típicamente es ruido de
     extracción de PDF: encabezados, pies de página, tablas rotas).
  3. El propio texto del chunk contiene un patrón de cita reconocible
     (Art./Artículo/Ley/Decreto/Sentencia) — no basta con que la metadata
     lo diga; el texto mismo debe sostenerlo, o el chunk probablemente es
     un fragmento fuera de contexto (p.ej. solo el título de una sección).

Un chunk que falla cualquiera de las 3 reglas se RECHAZA — nunca se corrige
en silencio ni se completa con metadata inventada (mismo principio de
julix/errors.py: ningún fallo se presenta como éxito silencioso).

NO SE EJECUTA CONTRA UNA BASE DE DATOS REAL EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LONGITUD_MINIMA_CARACTERES = 100

_RE_PATRON_CITA = re.compile(
    r"\b(art(í|i)culo|art\.|ley\s+\d+|decreto\s+\d+|sentencia|resoluci(ó|o)n)\b",
    re.IGNORECASE,
)


@dataclass
class ChunkEvaluable:
    """Forma mínima que necesita el quality gate — compatible tanto con
    rag.ingest_corpus.ChunkParaIngestar como con una fila leída de
    rag_chunks (basta con tener estos 4 campos)."""

    norma: str
    articulo: str
    texto: str
    identificador: str = ""  # hash_dedup o id de BD, para trazabilidad en el reporte


@dataclass
class ResultadoValidacion:
    identificador: str
    aceptado: bool
    motivos_rechazo: list[str] = field(default_factory=list)


def evaluar_chunk(chunk: ChunkEvaluable) -> ResultadoValidacion:
    """Aplica las 3 reglas. Acumula TODOS los motivos de rechazo que
    apliquen (no se detiene en el primero) — así el reporte es más útil
    para decidir si el problema es sistemático (p.ej. todo un PDF mal
    extraído) o puntual."""
    motivos: list[str] = []

    if not chunk.norma or not chunk.norma.strip():
        motivos.append("falta 'norma' en la metadata")
    if not chunk.articulo or not chunk.articulo.strip():
        motivos.append("falta 'articulo' en la metadata")

    if len(chunk.texto.strip()) < LONGITUD_MINIMA_CARACTERES:
        motivos.append(f"texto con menos de {LONGITUD_MINIMA_CARACTERES} caracteres ({len(chunk.texto.strip())})")

    if not _RE_PATRON_CITA.search(chunk.texto):
        motivos.append("el texto del chunk no contiene un patrón de cita reconocible (Art./Ley/Decreto/Sentencia)")

    return ResultadoValidacion(
        identificador=chunk.identificador or chunk.norma[:40],
        aceptado=len(motivos) == 0,
        motivos_rechazo=motivos,
    )


@dataclass
class ReporteCalidad:
    total: int
    aceptados: int
    rechazados: int
    porcentaje_aceptacion: float
    motivos_frecuentes: dict[str, int]
    detalle_rechazados: list[dict]
    generado_en: str

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "aceptados": self.aceptados,
            "rechazados": self.rechazados,
            "porcentaje_aceptacion": self.porcentaje_aceptacion,
            "motivos_frecuentes": self.motivos_frecuentes,
            "detalle_rechazados": self.detalle_rechazados,
            "generado_en": self.generado_en,
        }


def generar_reporte(chunks: list[ChunkEvaluable]) -> ReporteCalidad:
    resultados = [evaluar_chunk(c) for c in chunks]
    aceptados = [r for r in resultados if r.aceptado]
    rechazados = [r for r in resultados if not r.aceptado]

    conteo_motivos: dict[str, int] = {}
    for r in rechazados:
        for motivo in r.motivos_rechazo:
            conteo_motivos[motivo] = conteo_motivos.get(motivo, 0) + 1

    total = len(resultados)
    porcentaje = round(100 * len(aceptados) / total, 1) if total else 0.0

    return ReporteCalidad(
        total=total,
        aceptados=len(aceptados),
        rechazados=len(rechazados),
        porcentaje_aceptacion=porcentaje,
        motivos_frecuentes=dict(sorted(conteo_motivos.items(), key=lambda kv: kv[1], reverse=True)),
        detalle_rechazados=[
            {"identificador": r.identificador, "motivos": r.motivos_rechazo} for r in rechazados
        ],
        generado_en=datetime.now(timezone.utc).isoformat(),
    )


def escribir_reporte(reporte: ReporteCalidad, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(reporte.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


async def ejecutar_quality_gate_sobre_bd(
    db_connection, *, ruta_reporte: Path = Path("rag_quality_report.json")
) -> ReporteCalidad:
    """Lee todos los chunks de rag_chunks, corre el quality gate y escribe
    el reporte. Pensado para correr periódicamente (o tras cada ola de
    ingesta de S8-S9) como auditoría, no como bloqueo de la ingesta misma
    (rag/ingest_corpus.py ya filtra filas sin archivo; esto audita lo que
    ya quedó insertado)."""
    filas = await db_connection.fetch("SELECT hash_dedup, norma, articulo, texto FROM rag_chunks")
    chunks = [
        ChunkEvaluable(norma=f["norma"], articulo=f["articulo"], texto=f["texto"], identificador=f["hash_dedup"])
        for f in filas
    ]
    reporte = generar_reporte(chunks)
    escribir_reporte(reporte, ruta_reporte)
    return reporte


def _chunks_demo_representativos() -> list[ChunkEvaluable]:
    """Lote de demostración usado por `--report` cuando no hay DATABASE_URL
    configurado (o no se pidió `--manifest`) — nunca toca Postgres. Mezcla
    deliberadamente chunks válidos e inválidos (mismo patrón que
    tests/test_rag_quality.py) para que el reporte generado sea
    representativo de lo que el gate detecta, en vez de un 100% trivial
    sin ningún caso de rechazo."""
    return [
        ChunkEvaluable(
            norma="Ley 1607 de 2012", articulo="Art. 178",
            texto=(
                "El artículo 178 de la Ley 1607 de 2012 establece las sanciones aplicables "
                "por inexactitud en el reporte de aportes a la UGPP, incluyendo el "
                "procedimiento de determinación oficial y las causales de exoneración."
            ),
            identificador="demo-valido-ley-179",
        ),
        ChunkEvaluable(
            norma="Decreto 1625 de 2016", articulo="Art. 1.2.4.1.1",
            texto=(
                "El Decreto 1625 de 2016, artículo 1.2.4.1.1, regula el ingreso base de "
                "cotización para los trabajadores independientes frente a la UGPP y su "
                "procedimiento de fiscalización periódica."
            ),
            identificador="demo-valido-decreto-124",
        ),
        ChunkEvaluable(
            norma="Consejo de Estado - Sección Cuarta", articulo="Sentencia 25000-23-37-000-2022-00567-01",
            texto=(
                "La Sentencia del Consejo de Estado, Sección Cuarta, radicado "
                "25000-23-37-000-2022-00567-01 de 2022, fija la línea decisional sobre "
                "la carga probatoria de los contratistas independientes ante la UGPP."
            ),
            identificador="demo-valido-jurisprudencia-2022",
        ),
        ChunkEvaluable(
            norma="Ley 2010 de 2019", articulo="Art. 108",
            texto="Fragmento truncado en la extracción.",
            identificador="demo-invalido-texto-corto",
        ),
        ChunkEvaluable(
            norma="", articulo="",
            texto=(
                "x" * 40 + " este chunk perdió su metadata de norma y artículo durante "
                "la extracción del PDF y por eso debe rechazarse " + "y" * 40
            ),
            identificador="demo-invalido-sin-metadata",
        ),
    ]


def _chunks_desde_manifiesto_sin_bd(manifest_path: Path, prioridad: str) -> list[ChunkEvaluable]:
    """Extrae chunks REALES (si los PDFs del manifiesto existen en disco)
    reutilizando rag.ingest_corpus (misma extracción/chunking), sin cargar
    embeddings ni tocar la BD — permite correr `--report --manifest ...`
    contra el corpus real una vez que los PDFs estén cargados, sin
    depender de que ya se haya hecho `--commit` en Postgres."""
    from rag.ingest_corpus import leer_manifiesto, filtrar_por_prioridad, procesar_fila

    filas = filtrar_por_prioridad(leer_manifiesto(manifest_path), prioridad)
    chunks: list[ChunkEvaluable] = []
    for fila in filas:
        for chunk in procesar_fila(fila):
            chunks.append(
                ChunkEvaluable(
                    norma=chunk.norma, articulo=chunk.articulo, texto=chunk.texto,
                    identificador=chunk.hash_dedup,
                )
            )
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Vridik/JuliX — quality gate del corpus RAG (S8)")
    parser.add_argument("--reporte", default="rag_quality_report.json", help="Ruta de salida del JSON")
    parser.add_argument(
        "--report", action="store_true",
        help="Genera el reporte (comportamiento por defecto del comando; flag aceptado por compatibilidad "
             "con 'python rag/quality_gate.py --report')",
    )
    parser.add_argument("--umbral-aprobacion", type=float, default=90.0, help="Porcentaje mínimo de aceptación para salir con código 0")
    parser.add_argument(
        "--manifest", default=None,
        help="Si se pasa, valida los chunks reales extraídos de este manifiesto CSV (sin BD, sin embeddings) "
             "en vez de conectarse a rag_chunks o usar el lote de demostración.",
    )
    parser.add_argument("--priority", default="alta", help="Solo con --manifest: alta|media|baja|todas")
    args = parser.parse_args()

    import os

    database_url = os.environ.get("DATABASE_URL")

    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"ERROR: no existe el manifiesto {manifest_path}", file=sys.stderr)
            return 1
        chunks = _chunks_desde_manifiesto_sin_bd(manifest_path, args.priority)
        origen = f"manifiesto '{manifest_path}' (prioridad={args.priority}, sin BD, sin embeddings)"
        if not chunks:
            print(
                "AVISO: el manifiesto no produjo chunks reales (los PDFs referenciados no existen "
                "todavía en disco) — se usa el lote de demostración para validar el gate.",
                file=sys.stderr,
            )
            chunks = _chunks_demo_representativos()
            origen = "lote de demostración (fallback: el manifiesto no tenía PDFs reales disponibles)"
    elif database_url:
        # Modo real contra rag_chunks (requiere PostgreSQL — no se usa en
        # esta validación porque el dev lead pidió explícitamente no tocar
        # Postgres; se deja disponible para producción/CI).
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            print("ERROR: falta 'asyncpg' (pip install asyncpg)", file=sys.stderr)
            return 1

        import asyncio

        async def _run():
            import asyncpg

            conn = await asyncpg.connect(database_url)
            try:
                return await ejecutar_quality_gate_sobre_bd(conn, ruta_reporte=Path(args.reporte))
            finally:
                await conn.close()

        reporte = asyncio.run(_run())
        print(f"Vridik/RAG — quality gate (rag_chunks real): {reporte.aceptados}/{reporte.total} aceptados ({reporte.porcentaje_aceptacion}%)")
        print(f"Reporte escrito en {args.reporte}")
        return 0 if reporte.porcentaje_aceptacion >= args.umbral_aprobacion else 1
    else:
        chunks = _chunks_demo_representativos()
        origen = "lote de demostración (sin DATABASE_URL configurado — no se toca Postgres)"

    reporte = generar_reporte(chunks)
    escribir_reporte(reporte, Path(args.reporte))

    print(f"Vridik/RAG — quality gate — origen: {origen}")
    print(f"{reporte.aceptados}/{reporte.total} aceptados ({reporte.porcentaje_aceptacion}%)")
    if reporte.motivos_frecuentes:
        print("Motivos de rechazo más frecuentes:")
        for motivo, conteo in reporte.motivos_frecuentes.items():
            print(f"  - {motivo}: {conteo}")
    print(f"Reporte escrito en {args.reporte}")

    return 0 if reporte.porcentaje_aceptacion >= args.umbral_aprobacion else 1


if __name__ == "__main__":
    raise SystemExit(main())
