"""
JuliX — taxonomía de los 5 modos de fallo domados (Sprint S4).

Regla de oro: ningún fallo se presenta como éxito silencioso. Todo error
termina en un `julix_calls.status` explícito (ver ledger.py) y en un
mensaje honesto para el usuario. Nunca se reintenta en silencio después
de que ya hubo streaming parcial visible para el usuario.
"""

from __future__ import annotations


class JuliXError(Exception):
    """Base de todos los errores de JuliX. Siempre lleva un `status` para el ledger."""

    status: str = "error"

    def __init__(self, message: str, *, partial_text: str | None = None):
        super().__init__(message)
        self.partial_text = partial_text  # streaming parcial recuperable, si existe


class JuliXTimeoutError(JuliXError):
    """Timeout de red o del cliente Anthropic. Backoff exponencial en client.py.
    Si ya hubo streaming parcial, NO se reintenta automáticamente: se marca
    'timeout' y se ofrece reintento manual al usuario."""

    status = "timeout"


class JuliXRateLimitError(JuliXError):
    """HTTP 429. Se respeta el header `retry-after`. Nunca reintento inmediato:
    se encola y se avisa al usuario cuánto debe esperar."""

    status = "rate_limited"

    def __init__(self, message: str, retry_after_seconds: int, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after_seconds = retry_after_seconds


class JuliXOverloadedError(JuliXError):
    """HTTP 529 (sobrecarga del proveedor). Se devuelve el borrador parcial
    recuperable ya generado, marcado explícitamente como incompleto."""

    status = "overloaded_partial"


class JuliXTruncatedError(JuliXError):
    """Respuesta cortada por `max_tokens`. Se marca 'truncated' y jamás se
    presenta al usuario como documento completo, aunque el texto parezca
    gramaticalmente cerrado."""

    status = "truncated"


class JuliXInvalidFormatError(JuliXError):
    """La salida no cumple el formato esperado (p.ej. JSON de clasificación
    inválido). Se marca 'invalid_format'; no se corrige en silencio ni se
    reintenta con un prompt distinto sin dejar rastro en el ledger."""

    status = "invalid_format"
