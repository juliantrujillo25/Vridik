"""
JuliX — módulo de redacción asistida por IA de Vridik.

Frontera limpia (Sprint S4, Fase 1):
    service.py          orquestador de alto nivel
    client.py            wrapper del cliente Claude (reintentos, streaming, selección de modelo)
    context_builder.py    presupuesto de tokens y truncado con criterio
    ledger.py             costos, latencia y estado por llamada
    errors.py              taxonomía de fallos domados
    prompts/                prompts versionados en archivo, nunca en código
"""

from .service import JuliXService
from .errors import (
    JuliXError,
    JuliXTimeoutError,
    JuliXRateLimitError,
    JuliXOverloadedError,
    JuliXTruncatedError,
    JuliXInvalidFormatError,
)

__all__ = [
    "JuliXService",
    "JuliXError",
    "JuliXTimeoutError",
    "JuliXRateLimitError",
    "JuliXOverloadedError",
    "JuliXTruncatedError",
    "JuliXInvalidFormatError",
]
