#!/usr/bin/env python3
"""
Vridik / JuliX — workers/pdf_worker.py
Sprint S10 (roadmap): worker de conversión a PDF. Usa exclusivamente la
tabla `pdf_jobs` en PostgreSQL (sin Redis) como cola de trabajos.

Actualización (alineación con migrations/003_pdf_jobs.sql — decisión: el
esquema de la migración es el correcto para S10): este worker YA NO asume
que `pdf_jobs` trae la respuesta y las fuentes precalculadas (columnas
`tarea`/`caso_id`/`respuesta`/`fuentes` de una versión anterior de este
archivo, que nunca llegaron a tener una migración real). Ahora cada fila
solo trae `query` (la pregunta del usuario) y `user_id`; este worker genera
la respuesta de JuliX en el momento, llamando a `julix.service` (que ya
revisa `rag/cache.py` antes de tocar Anthropic — ver `generate_pdf()`).

Esquema real de `pdf_jobs` (ver migrations/003_pdf_jobs.sql, NO se tocó en
esta entrega):

    CREATE TABLE pdf_jobs (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        query      TEXT NOT NULL,
        user_id    TEXT,
        status     TEXT DEFAULT 'pending',
        pdf_url    TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP
    );

Qué hace, en loop cada 5 segundos (`PDF_WORKER_POLL_SECONDS`):
  1. `SELECT id, query, user_id FROM pdf_jobs WHERE status='pending' ...
     FOR UPDATE SKIP LOCKED` (hasta `PDF_WORKER_CONCURRENCY` a la vez) — si
     en el futuro corre más de una réplica de este worker (Railway
     `numReplicas`), dos réplicas nunca procesan el mismo trabajo dos veces.
  2. Para cada trabajo, `generate_pdf(query, user_id)` genera la respuesta
     de JuliX (con cache) y arma el PDF con `julix/pdf_export.py`.
  3. `UPDATE pdf_jobs SET status='done', pdf_url=?, updated_at=now() WHERE
     id=?` si todo sale bien; si falla, `status='error'` (columna
     `error_mensaje` de una versión anterior ya no existe en este esquema —
     el motivo del error solo queda en el log, no en la fila).
  4. Cada trabajo tiene un timeout duro de `PDF_JOB_TIMEOUT_SECONDS` (60s
     por defecto, roadmap S10) — si se excede, se mata esa conversión
     puntual (no todo el worker) y el trabajo queda en 'error'.

NO SE EJECUTA CONTRA POSTGRESQL NI ANTHROPIC REALES EN ESTE ENTREGABLE —
el loop principal solo arranca si se invoca `python workers/pdf_worker.py`
con `DATABASE_URL` configurado; queda verificado con `py_compile` y con
pruebas unitarias de `_ruta_pdf_para_job` de forma aislada.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from julix.client import JuliXClient  # noqa: E402
from julix.pdf_export import FuenteCitada, generar_pdf  # noqa: E402
from julix.router import TAREA_POR_AREA, route_by_area  # noqa: E402
from julix.service import JuliXService  # noqa: E402
from rag.context_builder import buscar_contexto as rag_buscar_contexto  # noqa: E402
from storage.object_storage import get_storage_backend  # noqa: E402

logger = logging.getLogger("vridik.workers.pdf_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

POLL_SECONDS = int(os.environ.get("PDF_WORKER_POLL_SECONDS", "5"))
CONCURRENCIA_MAXIMA = int(os.environ.get("PDF_WORKER_CONCURRENCY", "2"))
TIMEOUT_DURO_SEGUNDOS = int(os.environ.get("PDF_JOB_TIMEOUT_SECONDS", "60"))
DIRECTORIO_SALIDA_PDF = Path(os.environ.get("PDF_WORKER_OUTPUT_DIR", "/tmp/vridik-pdf-jobs"))
ENVIRONMENT = os.environ.get("VRIDIK_ENVIRONMENT", "staging")


def _ruta_pdf_para_job(job_id, user_id: str | None) -> Path:
    """Ruta LOCAL de trabajo del PDF generado para este trabajo — siempre
    se escribe primero aquí (ReportLab escribe a disco), sin importar el
    backend de almacenamiento configurado. `generate_pdf()` sube este
    archivo con `storage.object_storage.get_storage_backend()` para
    obtener el `pdf_url` final (S11-extra-9: antes esta ruta local se
    guardaba tal cual como `pdf_url`; ahora es solo el paso intermedio del
    backend local, o el archivo de origen para subir al backend S3)."""
    sufijo_usuario = f"_{user_id}" if user_id else ""
    nombre = f"pdf_job_{job_id}{sufijo_usuario}.pdf".replace("/", "_")
    return DIRECTORIO_SALIDA_PDF / nombre


async def generate_pdf(query: str, user_id: str | None, *, db_connection, job_id) -> str:
    """Punto de entrada pedido explícitamente: genera el PDF completo para
    una `query` de `pdf_jobs`, llamando a `julix.service.JuliXService` (que
    ya revisa `rag/cache.py` ANTES de llamar a Anthropic — ver
    `julix/service.py`, wiring de cache) para obtener la respuesta.

    Como `pdf_jobs` ya no trae `tarea` (columna eliminada en la alineación
    con migrations/003_pdf_jobs.sql), la tarea/prompt se decide en el
    momento con `julix.router.route_by_area(query)` — misma heurística que
    usaría cualquier otro punto de entrada de Vridik sin tarea explícita.

    Retorna la URL final (`pdf_url`) que debe guardarse en `pdf_jobs`: la
    ruta local si `OBJECT_STORAGE_BACKEND=local` (por defecto, sin cambio
    de comportamiento), o la URL pública/firmada del backend real
    (`OBJECT_STORAGE_BACKEND=s3`, ver storage/object_storage.py, S11-extra-9)."""
    area = route_by_area(query)
    tarea = TAREA_POR_AREA[area]

    client = JuliXClient(environment=ENVIRONMENT, db_connection=db_connection)
    service = JuliXService(client=client, db_connection=db_connection)

    respuesta = ""
    async for fragmento in service.generar_documento(
        user_id=user_id or "usuario_desconocido",
        caso_id=str(job_id),
        tarea=tarea,
        expediente_texto=query,
        pregunta=query,
    ):
        respuesta += fragmento

    # Mismas fuentes que vería el endpoint HTTP para el PDF (S10): se
    # reproduce la búsqueda RAG con la misma query, ya que el service no
    # devuelve los chunks que usó internamente (ver api/julix_endpoint.py:
    # _fuentes_citadas_para_pdf, mismo patrón).
    chunks_recuperados = await rag_buscar_contexto(db_connection, query)
    fuentes = [FuenteCitada.desde_chunk_recuperado(chunk) for chunk in chunks_recuperados]

    ruta_pdf = _ruta_pdf_para_job(job_id, user_id)

    # generar_pdf() es síncrona (ReportLab no es async) — se corre en un
    # executor aparte para no bloquear el event loop mientras se arma el PDF.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: generar_pdf(
            respuesta=respuesta,
            fuentes=fuentes,
            ruta_salida=ruta_pdf,
            tarea=tarea,
            caso_id=str(job_id),
        ),
    )

    # S11-extra-9: sube el PDF con el backend configurado
    # (OBJECT_STORAGE_BACKEND, ver storage/object_storage.py). Con el
    # backend "local" (por defecto) esto es un no-op que retorna la misma
    # ruta local de siempre — cero cambio de comportamiento hasta que se
    # configure explícitamente OBJECT_STORAGE_BACKEND=s3 en Railway.
    storage = get_storage_backend()
    pdf_url = await storage.upload_pdf(ruta_pdf, key=ruta_pdf.name)
    return pdf_url


async def _obtener_trabajos_pendientes(conn, limite: int) -> list:
    """SELECT ... FOR UPDATE SKIP LOCKED: si en el futuro corre más de una
    réplica de este worker, cada una toma trabajos distintos sin pisarse —
    los que ya están bloqueados por otra réplica se saltan en vez de
    esperar el lock (SKIP LOCKED), así el loop nunca se queda colgado
    esperando una fila que otra réplica ya está procesando."""
    return await conn.fetch(
        """
        SELECT id, query, user_id
        FROM pdf_jobs
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        limite,
    )


async def _marcar_processing(conn, job_id) -> None:
    await conn.execute(
        "UPDATE pdf_jobs SET status = 'processing', updated_at = now() WHERE id = $1",
        job_id,
    )


async def _marcar_done(conn, job_id, pdf_url: str) -> None:
    await conn.execute(
        "UPDATE pdf_jobs SET status = 'done', pdf_url = $2, updated_at = now() WHERE id = $1",
        job_id, pdf_url,
    )


async def _marcar_error(conn, job_id) -> None:
    # El esquema de migrations/003_pdf_jobs.sql no tiene columna de mensaje
    # de error (a diferencia de una versión anterior de este worker); el
    # motivo queda solo en el log (logger.exception/error más abajo), nunca
    # se inventa una columna que la migración no tiene.
    await conn.execute(
        "UPDATE pdf_jobs SET status = 'error', updated_at = now() WHERE id = $1",
        job_id,
    )


async def _procesar_trabajo(conn, job) -> None:
    """Procesa un único trabajo con timeout duro (roadmap S10: 60s). Si el
    timeout se cumple, se mata SOLO esta conversión (no el worker) y el
    trabajo queda en 'error' — nunca se reintenta en silencio ni se deja
    'processing' colgado."""
    job_id = job["id"]
    try:
        await _marcar_processing(conn, job_id)
        pdf_url = await asyncio.wait_for(
            generate_pdf(job["query"], job["user_id"], db_connection=conn, job_id=job_id),
            timeout=TIMEOUT_DURO_SEGUNDOS,
        )
        await _marcar_done(conn, job_id, pdf_url)
        logger.info("Vridik/pdf_worker: job_id=%s completado -> %s", job_id, pdf_url)
    except asyncio.TimeoutError:
        logger.error(
            "Vridik/pdf_worker: job_id=%s timeout duro de %ss excedido generando el PDF",
            job_id, TIMEOUT_DURO_SEGUNDOS,
        )
        await _marcar_error(conn, job_id)
    except Exception:  # noqa: BLE001 — un trabajo con error nunca debe tumbar el loop
        logger.exception("Vridik/pdf_worker: job_id=%s falló generando el PDF", job_id)
        await _marcar_error(conn, job_id)


async def _ciclo_una_vez(pool) -> int:
    """Un ciclo del loop: toma hasta CONCURRENCIA_MAXIMA trabajos pendientes
    y los procesa en paralelo. Retorna cuántos trabajos se tomaron (0 si no
    había nada pendiente) — usado por tests para no depender de sleep()."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            trabajos = await _obtener_trabajos_pendientes(conn, CONCURRENCIA_MAXIMA)
            if not trabajos:
                return 0
            await asyncio.gather(*(_procesar_trabajo(conn, job) for job in trabajos))
            return len(trabajos)


async def run_worker() -> None:
    """Loop principal: corre cada PDF_WORKER_POLL_SECONDS (5s por defecto)
    hasta que el proceso se detenga (SIGTERM de Railway en un redeploy, por
    ejemplo) — Railway reinicia el proceso solo si termina con código de
    error (restartPolicyType: ON_FAILURE en railway.json), así que un ciclo
    sin trabajos pendientes simplemente espera al siguiente, sin salir."""
    if asyncpg is None:
        raise RuntimeError("Falta la dependencia 'asyncpg' (pip install asyncpg)")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL no configurado — requerido para vridik-pdf-worker")

    DIRECTORIO_SALIDA_PDF.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Vridik/pdf_worker: iniciando — poll=%ss concurrencia=%s timeout_duro=%ss",
        POLL_SECONDS, CONCURRENCIA_MAXIMA, TIMEOUT_DURO_SEGUNDOS,
    )
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=max(2, CONCURRENCIA_MAXIMA))
    try:
        while True:
            procesados = await _ciclo_una_vez(pool)
            if procesados:
                logger.info("Vridik/pdf_worker: %s trabajo(s) procesado(s) en este ciclo", procesados)
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
