"""
Vridik / JuliX — julix/ledger.py
Sprint S4: registro de costos, latencia y estado de cada llamada a Claude en
`julix_calls` (ver julix/sql/ledger_schema.sql). Fuente única de datos para
el widget de costos del Panel Vridik Pro y para fijar el costo promedio por
documento (Sprint S6).

Actualización S4 (semana 4-6), confirmada en semana 5:
  - Tabla de precios 2026 por modelo (input/output por millón de tokens);
    Sonnet 5 confirmado en $3.00/$15.00 por millón de tokens input/output.
  - `get_monthly_cost(user_id)` — costo mensual por usuario, para el widget
    de costos del Panel Vridik Pro (antes solo existía el agregado global
    por entorno).
  - `obtener_ultima_llamada` — usado por api/julix_endpoint.py para devolver
    el costo de la respuesta que se acaba de generar.
  - `JuliXLedger` — fachada orientada a objetos sobre las funciones de este
    módulo, pensada para inyectarse en el endpoint FastAPI y en el widget
    de costos sin pasar la conexión de BD en cada llamada.

NO SE EJECUTA CONTRA UNA BASE DE DATOS REAL EN ESTE ENTREGABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Tabla de precios 2026 (USD por millón de tokens).
# Confirmado por el dev lead en la semana 5: Claude Sonnet 5 (modelo de
# documentos de JuliX) = $3.00 / 1M tokens input, $15.00 / 1M tokens output.
# ---------------------------------------------------------------------------
PRICE_PER_MILLION_TOKENS_USD: dict[str, dict[str, float]] = {
    "claude-sonnet-5-20250624": {"input": 3.00, "output": 15.00},  # confirmado, semana 5 (S4/S5)
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
    "claude-opus-4-8": {"input": 15.0, "output": 75.0},
}

# Límite blando mensual (USD) — 80% aviso, 100% confirmación por documento,
# NUNCA bloqueo duro (ver README.md)
SOFT_MONTHLY_LIMIT_USD = 150.0
WARNING_THRESHOLD_RATIO = 0.8


def calcular_costo_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    precios = PRICE_PER_MILLION_TOKENS_USD.get(model)
    if not precios:
        raise ValueError(f"Modelo sin tarifa registrada en ledger.py: {model}")
    costo_input = (input_tokens / 1_000_000) * precios["input"]
    costo_output = (output_tokens / 1_000_000) * precios["output"]
    return round(costo_input + costo_output, 6)


@dataclass
class JuliXCallRecord:
    user_id: str
    caso_id: str | None
    tarea: str
    model: str
    prompt_version: int
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str  # 'ok' | 'timeout' | 'rate_limited' | 'overloaded_partial' | 'truncated' | 'invalid_format'
    environment: str  # 'staging' | 'production'
    costo_usd: float | None = None
    created_at: datetime | None = None

    def __post_init__(self):
        if self.costo_usd is None:
            self.costo_usd = calcular_costo_usd(self.model, self.input_tokens, self.output_tokens)
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


async def registrar_llamada(db_connection, record: JuliXCallRecord) -> None:
    """Inserta el registro en julix_calls. Implementación real usa el pool
    de conexiones de la app (asyncpg / SQLAlchemy async)."""
    query = """
        INSERT INTO julix_calls (
            user_id, caso_id, tarea, model, prompt_version, prompt_hash,
            input_tokens, output_tokens, costo_usd, latency_ms, status,
            environment, created_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
    """
    await db_connection.execute(
        query,
        record.user_id, record.caso_id, record.tarea, record.model,
        record.prompt_version, record.prompt_hash, record.input_tokens,
        record.output_tokens, record.costo_usd, record.latency_ms,
        record.status, record.environment, record.created_at,
    )


async def gasto_mensual_actual_usd(db_connection, environment: str = "production") -> float:
    """Suma costo_usd del mes calendario en curso para TODO el entorno.
    Alimenta el aviso del 80%/confirmación del 100% del límite blando."""
    query = """
        SELECT COALESCE(SUM(costo_usd), 0)
        FROM julix_calls
        WHERE environment = $1
          AND created_at >= date_trunc('month', now())
    """
    row = await db_connection.fetchrow(query, environment)
    return float(row[0]) if row else 0.0


async def costo_mensual_por_usuario(db_connection, user_id: str) -> float:
    """Suma costo_usd del mes calendario en curso para UN usuario. Fuente de
    datos del widget de costos del Panel Vridik Pro (a diferencia de
    gasto_mensual_actual_usd, que es el agregado global por entorno)."""
    query = """
        SELECT COALESCE(SUM(costo_usd), 0)
        FROM julix_calls
        WHERE user_id = $1
          AND created_at >= date_trunc('month', now())
    """
    row = await db_connection.fetchrow(query, user_id)
    return float(row[0]) if row else 0.0


async def obtener_ultima_llamada(db_connection, user_id: str) -> dict | None:
    """Devuelve la última llamada de JuliX para un usuario (costo, tokens,
    latencia, estado). Usado por api/julix_endpoint.py para responder al
    frontend con el costo exacto de la respuesta que se acaba de generar."""
    query = """
        SELECT costo_usd, input_tokens, output_tokens, latency_ms, status, model, created_at
        FROM julix_calls
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 1
    """
    row = await db_connection.fetchrow(query, user_id)
    if row is None:
        return None
    return {
        "costo_usd": float(row["costo_usd"]) if row["costo_usd"] is not None else None,
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "latency_ms": row["latency_ms"],
        "status": row["status"],
        "model": row["model"],
        "created_at": row["created_at"],
    }


async def requiere_confirmacion(db_connection, environment: str = "production") -> tuple[bool, bool]:
    """Retorna (mostrar_aviso_80, requiere_confirmacion_100). Nunca bloqueo duro:
    al 100% el usuario puede seguir, pero debe confirmar explícitamente por documento."""
    gasto = await gasto_mensual_actual_usd(db_connection, environment)
    ratio = gasto / SOFT_MONTHLY_LIMIT_USD if SOFT_MONTHLY_LIMIT_USD else 0
    return (ratio >= WARNING_THRESHOLD_RATIO, ratio >= 1.0)


class JuliXLedger:
    """Fachada orientada a objetos sobre este módulo. Pensada para
    inyectarse una sola vez (por ejemplo en `app.state` de FastAPI, ver
    api/julix_endpoint.py) en vez de pasar `db_connection` en cada llamada."""

    def __init__(self, db_connection):
        self.db = db_connection

    async def registrar(self, record: JuliXCallRecord) -> None:
        await registrar_llamada(self.db, record)

    async def gasto_mensual_actual(self, environment: str = "production") -> float:
        return await gasto_mensual_actual_usd(self.db, environment)

    async def get_monthly_cost(self, user_id: str) -> float:
        """Costo mensual acumulado de JuliX para un usuario — el dato que
        pinta el widget de costos del Panel Vridik Pro."""
        return await costo_mensual_por_usuario(self.db, user_id)

    async def ultima_llamada(self, user_id: str) -> dict | None:
        return await obtener_ultima_llamada(self.db, user_id)

    async def requiere_confirmacion(self, environment: str = "production") -> tuple[bool, bool]:
        return await requiere_confirmacion(self.db, environment)
