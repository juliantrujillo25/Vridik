"""
Vridik — core/clientes.py
Fase 4 (SAGRILAFT lite): vista de "cliente" independiente del caso -- hasta
esta pasada, un cliente solo existía como `cliente_id` colgado de un `caso`
puntual (`core/case.py`), sin ningún lugar que agrupe "todos los casos de
este cliente" ni "el perfil de este cliente" en sí mismo.

Necesario porque la matriz de riesgo SAGRILAFT es una evaluación por
RELACIÓN con el cliente (KYC se hace una vez, no se repite por cada caso
nuevo) -- ver core/cumplimiento.py. Este módulo es deliberadamente chico:
solo lectura, scoping por despacho (mismo principio de aislamiento de toda
la Fase 4 -- nunca se filtra un cliente solo por su id, siempre también por
el despacho de quien pregunta).
"""

from __future__ import annotations

from core.case import COLUMNAS_CASO


async def listar_clientes(db_connection, *, despacho_id: str) -> list[dict]:
    """Clientes del despacho -- mismo criterio de scoping que
    core.admin.list_users, pero filtrado a role='cliente'."""
    filas = await db_connection.fetch(
        """
        SELECT id, email, created_at
        FROM users
        WHERE despacho_id = $1 AND role = 'cliente'
        ORDER BY created_at DESC
        """,
        despacho_id,
    )
    return [dict(f) for f in filas]


async def obtener_cliente(db_connection, *, cliente_id: str, despacho_id: str) -> dict | None:
    """None si el cliente no existe O si existe pero es de OTRO despacho --
    a propósito no se distingue el motivo (mismo criterio que el resto de
    la Fase 4: nunca confirmar por otro canal que un id pertenece a un
    despacho ajeno)."""
    fila = await db_connection.fetchrow(
        "SELECT id, email, created_at FROM users WHERE id = $1 AND despacho_id = $2 AND role = 'cliente'",
        cliente_id, despacho_id,
    )
    return dict(fila) if fila is not None else None


async def listar_casos_de_cliente(db_connection, *, cliente_id: str, despacho_id: str) -> list[dict]:
    """Historial de casos del cliente, para su perfil -- reutiliza las
    columnas de core.case (nunca duplica la lista de columnas)."""
    filas = await db_connection.fetch(
        f"""
        SELECT {COLUMNAS_CASO} FROM casos
        WHERE cliente_id = $1 AND despacho_id = $2
        ORDER BY created_at DESC
        """,
        cliente_id, despacho_id,
    )
    return [dict(f) for f in filas]
