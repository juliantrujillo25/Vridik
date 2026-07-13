"""
Vridik / JuliX — julix/client.py
Sprint S4: cliente real de Anthropic Claude para JuliX.

Responsabilidades (todas en este módulo, según alcance de S4):
  - Conectar a Anthropic usando ANTHROPIC_API_KEY (o las variantes por
    entorno ANTHROPIC_API_KEY_STAGING/PROD si están configuradas — se
    prueban primero por compatibilidad con el resto de S4).
  - Streaming real vía AsyncAnthropic, timeout duro de 30s por intento.
  - Retry con backoff exponencial (máx. 3 intentos) SOLO para errores
    transitorios de red/timeout, y nunca si ya hubo streaming parcial
    visible para el usuario (regla de oro de S4, ver julix/errors.py).
  - Registrar cada llamada (éxito o fallo) en `julix_calls`
    (julix/sql/ledger_schema.sql) a través de julix/ledger.py — este
    módulo es dueño del logging de la llamada; julix/service.py ya no
    duplica ese registro (ver julix/service.py actualizado en S4).

La interacción cruda con el SDK vive en `_abrir_stream_sdk`, aislada del
resto de `stream_completion` a propósito: así los tests de S4 pueden
sustituir únicamente esa pieza (mock del SDK) y ejercitar de verdad la
lógica de retry/timeout/ledger, sin llamar nunca a Claude real.

NO SE EJECUTA CONTRA ANTHROPIC REAL EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore

from .errors import (
    JuliXInvalidFormatError,
    JuliXOverloadedError,
    JuliXRateLimitError,
    JuliXTimeoutError,
    JuliXTruncatedError,
)
from .ledger import JuliXCallRecord, ensure_julix_calls_table, registrar_llamada

logger = logging.getLogger("vridik.julix.client")


# ---------------------------------------------------------------------------
# Excepciones del SDK — con un fallback dummy si 'anthropic' no está instalado,
# para que el módulo importe limpio en cualquier entorno (el error real de
# "SDK no instalado" se levanta explícitamente en _abrir_stream_sdk).
# ---------------------------------------------------------------------------
class _SDKNoDisponibleError(Exception):
    """Placeholder cuando 'anthropic' no está instalado; nunca debería
    dispararse en un entorno con requirements.txt aplicado correctamente."""


if anthropic is not None:
    _RateLimitSDKError = anthropic.RateLimitError
    _OverloadedSDKError = anthropic.OverloadedError
    _TimeoutSDKError = anthropic.APITimeoutError
    _ConnectionSDKError = anthropic.APIConnectionError
else:  # pragma: no cover
    _RateLimitSDKError = _SDKNoDisponibleError
    _OverloadedSDKError = _SDKNoDisponibleError
    _TimeoutSDKError = _SDKNoDisponibleError
    _ConnectionSDKError = _SDKNoDisponibleError


# ---------------------------------------------------------------------------
# Modelo por tarea — única fuente de verdad (ver README.md)
#
# Ajuste de modelo (dev lead, semana 5): se confirma claude-sonnet-5 como
# modelo de documentos de JuliX. Configurable vía ANTHROPIC_MODEL_JULIX para
# poder apuntar a otra versión sin tocar código (staging vs. banco de
# evaluación de S5, por ejemplo).
#
# Nota (verificación S7-extra): "claude-sonnet-5-20250624" nunca fue un model
# ID válido de la API de Anthropic -- causaba 404 not_found_error en toda
# llamada real a /julix/query, nunca detectado porque el código nunca se
# había ejercitado contra Claude real hasta ahora. El ID correcto es
# "claude-sonnet-5" (sin sufijo de fecha).
# ---------------------------------------------------------------------------
MODELO_DOCUMENTOS_POR_DEFECTO = os.environ.get("ANTHROPIC_MODEL_JULIX", "claude-sonnet-5")
MODELO_CLASIFICACION_POR_DEFECTO = os.environ.get("ANTHROPIC_MODEL_JULIX_HAIKU", "claude-haiku-4-5-20251001")

MODEL_BY_TASK: dict[str, str] = {
    "redaccion_ugpp": MODELO_DOCUMENTOS_POR_DEFECTO,
    "redaccion_laboral": MODELO_DOCUMENTOS_POR_DEFECTO,
    "ugpp_demanda": MODELO_DOCUMENTOS_POR_DEFECTO,
    "laboral_consulta": MODELO_DOCUMENTOS_POR_DEFECTO,
    "clasificacion_documento": MODELO_CLASIFICACION_POR_DEFECTO,
    "resumen_comunicacion": MODELO_CLASIFICACION_POR_DEFECTO,
    "evaluacion_juez": MODELO_DOCUMENTOS_POR_DEFECTO,  # banco de evaluación S5 (eval/evaluador.py)
}

MAX_TOKENS_BY_TASK: dict[str, int] = {
    "redaccion_ugpp": 8000,
    "redaccion_laboral": 8000,
    "ugpp_demanda": 8000,
    "laboral_consulta": 6000,
    "clasificacion_documento": 500,
    "resumen_comunicacion": 1000,
    "evaluacion_juez": 800,  # salida corta: JSON de calificación
}

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2


def _resolve_api_key(environment: str) -> str:
    """Prefiere la key específica del entorno (ANTHROPIC_API_KEY_STAGING /
    ANTHROPIC_API_KEY_PROD, ver S4 original); si no existe, cae a la
    variable genérica ANTHROPIC_API_KEY pedida explícitamente para S4.
    Nunca usa una key de otro entorno como fallback silencioso."""
    var_especifica = "ANTHROPIC_API_KEY_PROD" if environment == "production" else "ANTHROPIC_API_KEY_STAGING"
    key = os.environ.get(var_especifica) or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            f"No se encontró API key de Anthropic. Configura {var_especifica} o ANTHROPIC_API_KEY."
        )
    return key


@dataclass
class CompletionResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str
    stop_reason: str | None = None


class JuliXClient:
    """Cliente único de acceso a Claude para todo Vridik. service.py nunca
    importa el SDK de Anthropic directamente — solo pasa por aquí.

    Si se construye con `db_connection`, cada llamada a `stream_completion`
    queda registrada en `julix_calls` (éxito o fallo) sin que el llamador
    tenga que hacerlo aparte."""

    def __init__(self, environment: str = "staging", db_connection=None):
        self.environment = environment
        self.db_connection = db_connection
        self.api_key = _resolve_api_key(environment)
        self._sdk_client = (
            anthropic.AsyncAnthropic(api_key=self.api_key, timeout=REQUEST_TIMEOUT_SECONDS)
            if anthropic is not None
            else None
        )

    def model_for(self, tarea: str) -> str:
        return MODEL_BY_TASK.get(tarea, MODELO_DOCUMENTOS_POR_DEFECTO)

    def max_tokens_for(self, tarea: str) -> int:
        return MAX_TOKENS_BY_TASK.get(tarea, 4000)

    # -----------------------------------------------------------------
    # Único punto que toca el SDK real. Aislado para poder monkeypatchear
    # solo esta pieza en los tests (ver tests/test_julix.py) y ejercitar de
    # verdad el resto de stream_completion (retry, timeout, ledger).
    # -----------------------------------------------------------------
    def _abrir_stream_sdk(self, *, model: str, max_tokens: int, system_prompt: str, user_content: str):
        if self._sdk_client is None:
            raise _SDKNoDisponibleError("El SDK 'anthropic' no está instalado (pip install anthropic)")
        return self._sdk_client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )

    async def stream_completion(
        self,
        *,
        tarea: str,
        system_prompt: str,
        user_content: str,
        user_id: str | None = None,
        caso_id: str | None = None,
        prompt_version: int = 0,
        prompt_hash: str = "",
    ):
        """Generador async de chunks de texto, compatible con el canal SSE
        /api/events/stream de S11. Registra la llamada en `julix_calls` al
        finalizar (éxito o fallo) si se construyó con `db_connection`.

        Manejo de fallos (ver errors.py):
          - timeout/red      -> JuliXTimeoutError, backoff, sin reintento
                                 silencioso si ya hubo streaming parcial
          - 429               -> JuliXRateLimitError (respeta retry-after, sin reintento inmediato)
          - 529 (overloaded)   -> JuliXOverloadedError (devuelve partial_text)
          - truncado           -> JuliXTruncatedError (marcado, nunca 'completo')
          - formato inválido    -> JuliXInvalidFormatError (marcado, no autocorregido; ver validar_json)
        """
        model = self.model_for(tarea)
        max_tokens = self.max_tokens_for(tarea)

        started_at = time.monotonic()
        texto_completo = ""
        streamed_any = False
        status = "ok"
        input_tokens = 0
        output_tokens = 0
        attempt = 0
        error_final: Exception | None = None

        while attempt < MAX_RETRIES:
            try:
                async with self._abrir_stream_sdk(
                    model=model, max_tokens=max_tokens,
                    system_prompt=system_prompt, user_content=user_content,
                ) as stream:
                    async for chunk in stream.text_stream:
                        streamed_any = True
                        texto_completo += chunk
                        yield chunk

                    final = await stream.get_final_message()
                    input_tokens = getattr(final.usage, "input_tokens", 0)
                    output_tokens = getattr(final.usage, "output_tokens", 0)

                    if final.stop_reason == "max_tokens":
                        status = "truncated"
                        error_final = JuliXTruncatedError(
                            "Respuesta truncada por max_tokens", partial_text=texto_completo
                        )
                break  # éxito (o truncado, que no se reintenta): salir del retry loop

            except _RateLimitSDKError as exc:  # 429
                status = "rate_limited"
                retry_after = 5
                headers = getattr(getattr(exc, "response", None), "headers", None)
                if headers:
                    try:
                        retry_after = int(headers.get("retry-after", 5))
                    except (TypeError, ValueError):
                        retry_after = 5
                logger.warning("Vridik/JuliX: rate limit (429) en tarea=%s, retry-after=%ss", tarea, retry_after)
                error_final = JuliXRateLimitError(str(exc), retry_after_seconds=retry_after)
                break  # nunca reintento inmediato ante 429

            except _OverloadedSDKError as exc:  # 529
                status = "overloaded_partial"
                logger.warning("Vridik/JuliX: modelo sobrecargado (529) en tarea=%s, borrador parcial conservado", tarea)
                error_final = JuliXOverloadedError(str(exc), partial_text=texto_completo)
                break

            except (_TimeoutSDKError, _ConnectionSDKError) as exc:
                attempt += 1
                if streamed_any:
                    # Ya hubo streaming parcial visible: nunca reintento silencioso
                    status = "timeout"
                    error_final = JuliXTimeoutError(str(exc), partial_text=texto_completo)
                    logger.error("Vridik/JuliX: timeout tras streaming parcial en tarea=%s — no se reintenta", tarea)
                    break
                if attempt >= MAX_RETRIES:
                    status = "timeout"
                    error_final = JuliXTimeoutError(str(exc))
                    logger.error("Vridik/JuliX: timeout definitivo tras %s intentos en tarea=%s", MAX_RETRIES, tarea)
                    break
                espera = BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    "Vridik/JuliX: timeout/red en tarea=%s (intento %s/%s), reintentando en %ss",
                    tarea, attempt, MAX_RETRIES, espera,
                )
                await asyncio.sleep(espera)
                continue

        latency_ms = int((time.monotonic() - started_at) * 1000)

        if self.db_connection is not None:
            record = JuliXCallRecord(
                user_id=user_id or "desconocido",
                caso_id=caso_id,
                tarea=tarea,
                model=model,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                status=status,
                environment=self.environment,
            )
            # ensure_* antes del INSERT -- julix_calls nunca tuvo un
            # bootstrap propio (a diferencia de casos/mensajes/totp/etc.),
            # así que sin esto una tabla ausente rompía acá con un error
            # crudo de Postgres en vez de generar el documento igual.
            await ensure_julix_calls_table(self.db_connection)
            await registrar_llamada(self.db_connection, record)
            logger.info(
                "Vridik/JuliX: llamada registrada en julix_calls — user_id=%s tarea=%s model=%s status=%s costo_usd=%s",
                user_id, tarea, model, status, record.costo_usd,
            )

        if error_final is not None:
            raise error_final

    @staticmethod
    def validar_json(texto: str) -> dict:
        """Helper para tareas de clasificación (S4/Fase 2): valida que la
        salida sea el JSON esperado. Nunca corrige en silencio — si el
        formato es inválido, se marca y se propaga (ver errors.py)."""
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            raise JuliXInvalidFormatError(f"Salida no es JSON válido: {exc}", partial_text=texto) from exc
