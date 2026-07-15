"""
Vridik — core/cobro.py
Fase 3 (Cobro Inteligente, roadmap): "Valor en disputa por caso... esquemas
de honorarios (fijo/cuota litis/mixto) con liquidación automática del éxito
al cierre de etapa". Arranca con lo que no depende de un proveedor externo
(la factura DIAN sí depende -- "integrar, no construir", ver
api/cobro_endpoint.py) -- valor en disputa y honorarios son datos propios
del despacho, sin ninguna integración necesaria.

Mismo principio que procesal/calendario_judicial.py con el vencimiento de
un término: `honorarios_liquidados` SIEMPRE lo calcula el backend a partir
de la fórmula del esquema elegido -- nunca se acepta como input directo.
Lo único que el humano aporta al liquidar es `valor_recuperado` (el
resultado real del caso, un dato que el sistema no puede inferir solo).

Esquemas:
  - 'fijo': honorarios = monto_fijo (no depende de lo recuperado).
  - 'cuota_litis': honorarios = valor_recuperado * porcentaje_cuota_litis / 100.
  - 'mixto': honorarios = monto_fijo + valor_recuperado * porcentaje_cuota_litis / 100.

`liquidar_honorarios()` es una acción de una sola vez -- una vez liquidado
un caso, no se vuelve a liquidar (evita sobrescribir un cierre financiero
ya hecho por error o dos veces). Para corregir un error real, hace falta
tocar la fila a mano (no hay endpoint de "deshacer" a propósito, mismo
criterio que julix_calls: el ledger no se edita, se audita).
"""

from __future__ import annotations

from decimal import Decimal

from core.case import ensure_casos_table

_COLUMNAS = (
    "caso_id, valor_en_disputa, esquema_honorarios, monto_fijo, porcentaje_cuota_litis, "
    "valor_recuperado, honorarios_liquidados, liquidado_en, created_at, updated_at"
)

ESQUEMAS_VALIDOS = ("fijo", "cuota_litis", "mixto")


async def ensure_cobro_table(db_connection) -> None:
    await ensure_casos_table(db_connection)
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS cobro_caso (
            caso_id UUID PRIMARY KEY REFERENCES casos(id),
            valor_en_disputa NUMERIC(14, 2),
            esquema_honorarios TEXT CHECK (esquema_honorarios IN ('fijo', 'cuota_litis', 'mixto')),
            monto_fijo NUMERIC(14, 2),
            porcentaje_cuota_litis NUMERIC(5, 2)
                CHECK (porcentaje_cuota_litis IS NULL OR (porcentaje_cuota_litis >= 0 AND porcentaje_cuota_litis <= 100)),
            valor_recuperado NUMERIC(14, 2),
            honorarios_liquidados NUMERIC(14, 2),
            liquidado_en TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _validar_esquema(
    esquema_honorarios: str, *, monto_fijo: Decimal | None, porcentaje_cuota_litis: Decimal | None,
) -> None:
    if esquema_honorarios not in ESQUEMAS_VALIDOS:
        raise ValueError(f"esquema_honorarios inválido: {esquema_honorarios!r} (válidos: {ESQUEMAS_VALIDOS})")
    if esquema_honorarios in ("fijo", "mixto") and monto_fijo is None:
        raise ValueError(f"esquema {esquema_honorarios!r} requiere monto_fijo")
    if esquema_honorarios in ("cuota_litis", "mixto") and porcentaje_cuota_litis is None:
        raise ValueError(f"esquema {esquema_honorarios!r} requiere porcentaje_cuota_litis")


async def set_cobro(
    db_connection, *, caso_id: str, valor_en_disputa: Decimal | None = None,
    esquema_honorarios: str | None = None, monto_fijo: Decimal | None = None,
    porcentaje_cuota_litis: Decimal | None = None,
) -> dict:
    """Configura (o reconfigura, mientras el caso siga sin liquidar) el
    valor en disputa y el esquema de honorarios. Nunca toca
    valor_recuperado/honorarios_liquidados -- eso solo lo escribe
    liquidar_honorarios()."""
    if esquema_honorarios is not None:
        _validar_esquema(esquema_honorarios, monto_fijo=monto_fijo, porcentaje_cuota_litis=porcentaje_cuota_litis)

    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO cobro_caso (caso_id, valor_en_disputa, esquema_honorarios, monto_fijo, porcentaje_cuota_litis)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (caso_id) DO UPDATE SET
            valor_en_disputa = EXCLUDED.valor_en_disputa,
            esquema_honorarios = EXCLUDED.esquema_honorarios,
            monto_fijo = EXCLUDED.monto_fijo,
            porcentaje_cuota_litis = EXCLUDED.porcentaje_cuota_litis,
            updated_at = now()
        RETURNING {_COLUMNAS}
        """,
        caso_id, valor_en_disputa, esquema_honorarios, monto_fijo, porcentaje_cuota_litis,
    )
    return dict(fila)


async def get_cobro(db_connection, caso_id: str) -> dict | None:
    fila = await db_connection.fetchrow(f"SELECT {_COLUMNAS} FROM cobro_caso WHERE caso_id = $1", caso_id)
    return dict(fila) if fila is not None else None


def calcular_honorarios(
    *, esquema_honorarios: str, valor_recuperado: Decimal,
    monto_fijo: Decimal | None, porcentaje_cuota_litis: Decimal | None,
) -> Decimal:
    if esquema_honorarios == "fijo":
        return monto_fijo  # type: ignore[return-value]  -- ya validado que no es None
    if esquema_honorarios == "cuota_litis":
        return valor_recuperado * porcentaje_cuota_litis / Decimal(100)  # type: ignore[operator]
    if esquema_honorarios == "mixto":
        return monto_fijo + valor_recuperado * porcentaje_cuota_litis / Decimal(100)  # type: ignore[operator]
    raise ValueError(f"esquema_honorarios inválido: {esquema_honorarios!r}")


async def liquidar_honorarios(db_connection, *, caso_id: str, valor_recuperado: Decimal) -> dict:
    """Calcula honorarios_liquidados con la fórmula del esquema YA
    configurado (nunca se acepta como input) y lo persiste junto con
    valor_recuperado/liquidado_en. Levanta ValueError si no hay esquema
    configurado todavía, o si el caso ya fue liquidado antes."""
    cobro = await get_cobro(db_connection, caso_id)
    if cobro is None or cobro["esquema_honorarios"] is None:
        raise ValueError("El caso no tiene un esquema de honorarios configurado -- configuralo antes de liquidar")
    if cobro["liquidado_en"] is not None:
        raise ValueError("El caso ya fue liquidado -- no se vuelve a liquidar")

    honorarios = calcular_honorarios(
        esquema_honorarios=cobro["esquema_honorarios"], valor_recuperado=valor_recuperado,
        monto_fijo=cobro["monto_fijo"], porcentaje_cuota_litis=cobro["porcentaje_cuota_litis"],
    )

    fila = await db_connection.fetchrow(
        f"""
        UPDATE cobro_caso SET
            valor_recuperado = $2, honorarios_liquidados = $3, liquidado_en = now(), updated_at = now()
        WHERE caso_id = $1
        RETURNING {_COLUMNAS}
        """,
        caso_id, valor_recuperado, honorarios,
    )
    return dict(fila)
