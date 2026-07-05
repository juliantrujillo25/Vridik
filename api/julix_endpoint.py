"""
Vridik / JuliX — api/julix_endpoint.py
Sprint S4: expone JuliX vía HTTP para el frontend de Vridik.
Sprint S10: agrega `?format=pdf` — la misma respuesta de JuliX, pero
devuelta como PDF con citas (julix/pdf_export.py) en vez de JSON.

POST /julix/query
  - Valida el JWT del header Authorization (HMAC, mismo secreto que S1).
  - Rate limit: 20 req/min por usuario, detrás de un feature flag propio
    (JULIX_RATE_LIMIT_ENABLED) — mismo patrón que USE_POSTGRES en
    core/feature_flag_legacy.py, para poder apagarlo en una corrida de humo
    sin tocar código.
  - Llama a julix.service.JuliXService.generar_documento(...) y consume el
    stream completo: esta ruta es de request/response simple (JSON con el
    documento final + costo, o PDF si `?format=pdf`); el streaming real al
    frontend vive en el canal SSE de S11, no aquí.
  - Responde con el documento y el costo/latencia/estado de la última
    llamada registrada en julix_calls (ver julix/ledger.py:obtener_ultima_llamada).
  - `?format=pdf`: en vez de JSON, responde con el PDF generado por
    julix/pdf_export.py (header Vridik Pro, cuerpo, "Fuentes citadas",
    disclaimer de borrador en el pie). Las fuentes del PDF son los mismos
    `chunks_candidatos` usados para generar la respuesta (los explícitos
    del payload si vinieron, o los recuperados del RAG si el servicio los
    trajo automáticamente — S6) — nunca se vuelve a consultar el RAG por
    separado solo para el PDF.

Autenticación: reutiliza el mismo JWT_SECRET y el mismo patrón de doble
lectura (`core.feature_flag_legacy.use_postgres`) que el resto de Vridik —
este endpoint no reimplementa autenticación, solo decodifica el JWT ya
emitido por el login (S1) y confía en su `sub`/`role`.

NO SE EJECUTA CONTRA CLAUDE REAL EN ESTE ENTREGABLE — FastAPI se importa y
se define la app, pero no se levanta ningún servidor ni se llama a Anthropic.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

try:
    import jwt as pyjwt
except ImportError:  # pragma: no cover
    pyjwt = None  # type: ignore

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.feature_flag_legacy import use_postgres
from julix.context_builder import RankedChunk
from julix.client import JuliXClient
from julix.ledger import obtener_ultima_llamada
from julix.pdf_export import FuenteCitada, generar_pdf
from julix.service import JuliXService
from rag.context_builder import buscar_contexto as rag_buscar_contexto

logger = logging.getLogger("vridik.julix.api")

app = FastAPI(title="Vridik — JuliX API", version="s4")

JWT_SECRET = os.environ.get("JWT_SECRET", "")

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60

# Ventanas deslizantes en memoria por usuario. Nota de producción: esto solo
# es correcto con una única instancia del proceso; en Railway con réplicas
# >1 esto debe moverse a un backend compartido (Redis, o una tabla
# `rate_limit_hits` en PostgreSQL) antes de escalar horizontalmente — se deja
# documentado aquí para no bloquear S4 con esa migración.
_rate_limit_buckets: dict[str, deque] = defaultdict(deque)


def rate_limiting_enabled() -> bool:
    """Feature flag propio de este endpoint (mismo patrón que USE_POSTGRES
    en core/feature_flag_legacy.py): permite apagar el rate limit en
    staging durante una corrida de humo sin tocar código."""
    return os.environ.get("JULIX_RATE_LIMIT_ENABLED", "true").strip().lower() == "true"


def _verificar_rate_limit(user_id: str) -> None:
    if not rate_limiting_enabled():
        return
    ahora = time.monotonic()
    bucket = _rate_limit_buckets[user_id]
    while bucket and ahora - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        logger.warning("Vridik/JuliX: rate limit excedido — user_id=%s", user_id)
        raise HTTPException(
            status_code=429,
            detail="Límite de 20 solicitudes/min a JuliX excedido. Intenta de nuevo en unos segundos.",
        )
    bucket.append(ahora)


def _decodificar_jwt(authorization: str | None) -> dict:
    if pyjwt is None:
        raise HTTPException(status_code=500, detail="PyJWT no está instalado en el servidor")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Falta el header Authorization: Bearer <token>")
    token = authorization[len("Bearer "):].strip()
    try:
        claims = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Token inválido: {exc}")
    return claims


class ChunkCandidato(BaseModel):
    referencia: str
    jerarquia: int
    vigente: bool = True
    tokens: int
    contenido: str


class JuliXQueryRequest(BaseModel):
    tarea: str = Field(..., examples=["ugpp_demanda", "laboral_consulta"])
    caso_id: str
    expediente_texto: str
    # S10: antes esta pregunta nunca llegaba a service.generar_documento()
    # (solo existía el parámetro `pregunta` en el service desde S6) — el
    # gap quedaba tapado porque en la práctica se usaba expediente_texto
    # como texto de búsqueda de respaldo. Se expone explícitamente aquí
    # para que el RAG (S9, boost por tipo/año) busque sobre la pregunta
    # real del usuario, no solo sobre el expediente completo.
    pregunta: str | None = None
    chunks: list[ChunkCandidato] = Field(default_factory=list)
    prompt_version: int | None = None


class JuliXQueryResponse(BaseModel):
    documento: str
    costo_usd: float | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    status: str
    model: str | None


def get_service(request: Request) -> JuliXService:
    """La app real de Vridik monta `db_connection` y `environment` en
    `app.state` durante el bootstrap (pool de PostgreSQL, entorno
    staging/producción). Este esqueleto asume que ya están disponibles ahí."""
    db_connection = getattr(request.app.state, "db_connection", None)
    environment = getattr(request.app.state, "environment", "staging")
    client = JuliXClient(environment=environment, db_connection=db_connection)
    return JuliXService(client=client, db_connection=db_connection)


async def _fuentes_citadas_para_pdf(
    request: Request,
    payload: "JuliXQueryRequest",
    chunks_candidatos: list[RankedChunk],
) -> list[FuenteCitada]:
    """Determina las fuentes a listar en 'Fuentes citadas' del PDF (S10).

    Si el payload ya trajo chunks explícitos, se usan tal cual (mismo
    criterio que usó service.generar_documento para NO tocar el RAG). Si
    no, se recuperan por separado con rag.context_builder.buscar_contexto
    usando la misma `pregunta`/`expediente_texto` de respaldo que usa el
    service internamente — el service no devuelve los chunks que recuperó,
    así que para armar el PDF se reproduce la misma búsqueda (mismo top_k
    por defecto, mismo texto de búsqueda), nunca se inventa una fuente."""
    if payload.chunks:
        return [FuenteCitada.desde_referencia(c.referencia) for c in chunks_candidatos]

    db_connection = getattr(request.app.state, "db_connection", None)
    if db_connection is None:
        return []
    texto_busqueda = payload.pregunta or payload.expediente_texto
    chunks_recuperados = await rag_buscar_contexto(db_connection, texto_busqueda)
    return [FuenteCitada.desde_chunk_recuperado(chunk) for chunk in chunks_recuperados]


@app.post("/julix/query")
async def julix_query(
    payload: JuliXQueryRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    format: str = Query(default="json", pattern="^(json|pdf)$"),
):
    claims = _decodificar_jwt(authorization)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin 'sub'")

    _verificar_rate_limit(user_id)

    backend_auth = "postgres" if use_postgres() else "legacy_env"
    logger.info(
        "Vridik/JuliX: query recibida — user_id=%s tarea=%s caso_id=%s backend_auth=%s formato=%s",
        user_id, payload.tarea, payload.caso_id, backend_auth, format,
    )

    service = get_service(request)
    chunks_candidatos = [RankedChunk(**c.model_dump()) for c in payload.chunks]

    documento = ""
    async for fragmento in service.generar_documento(
        user_id=user_id,
        caso_id=payload.caso_id,
        tarea=payload.tarea,
        expediente_texto=payload.expediente_texto,
        chunks_candidatos=chunks_candidatos or None,
        pregunta=payload.pregunta,
        prompt_version=payload.prompt_version,
    ):
        documento += fragmento

    ultima_llamada = None
    db_connection = getattr(request.app.state, "db_connection", None)
    if db_connection is not None:
        ultima_llamada = await obtener_ultima_llamada(db_connection, user_id)

    logger.info(
        "Vridik/JuliX: respuesta generada — user_id=%s caso_id=%s costo_usd=%s status=%s",
        user_id, payload.caso_id,
        ultima_llamada.get("costo_usd") if ultima_llamada else None,
        ultima_llamada.get("status") if ultima_llamada else "sin_ledger",
    )

    if format == "pdf":
        fuentes = await _fuentes_citadas_para_pdf(request, payload, chunks_candidatos)
        ruta_pdf = Path(tempfile.gettempdir()) / f"vridik_julix_{payload.caso_id}_{user_id}.pdf"
        generar_pdf(
            respuesta=documento,
            fuentes=fuentes,
            ruta_salida=ruta_pdf,
            tarea=payload.tarea,
            caso_id=payload.caso_id,
        )
        return FileResponse(
            path=str(ruta_pdf),
            media_type="application/pdf",
            filename=f"vridik-julix-{payload.caso_id}.pdf",
        )

    return JuliXQueryResponse(
        documento=documento,
        costo_usd=ultima_llamada["costo_usd"] if ultima_llamada else None,
        tokens_in=ultima_llamada["input_tokens"] if ultima_llamada else None,
        tokens_out=ultima_llamada["output_tokens"] if ultima_llamada else None,
        latency_ms=ultima_llamada["latency_ms"] if ultima_llamada else None,
        status=ultima_llamada["status"] if ultima_llamada else "sin_ledger",
        model=ultima_llamada["model"] if ultima_llamada else None,
    )


@app.get("/julix/health")
async def julix_health() -> dict:
    """Chequeo simple para Railway (healthcheck del servicio). No toca
    Anthropic ni PostgreSQL — solo confirma que la app respondió."""
    return {"status": "ok", "servicio": "vridik-julix-api"}


@app.get("/health")
async def health() -> dict:
    """Healthcheck genérico del servicio (Railway, railway.json:
    deploy.healthcheckPath) — alias de /julix/health con la ruta que
    Railway espera por convención. No toca Anthropic ni PostgreSQL."""
    return {"status": "ok", "servicio": "vridik-api"}
