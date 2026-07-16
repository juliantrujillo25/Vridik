"""
Vridik — core/cumplimiento.py
Fase 4 (SAGRILAFT lite, roadmap): "matriz de riesgo, listas restrictivas,
reportes Supersociedades" — esta pasada arranca únicamente con la matriz de
riesgo (decisión explícita del dev lead); listas restrictivas queda con el
esquema preparado pero SIN datos ni lógica de cruce todavía (necesita
definir fuente de datos real -- proveedor pago vs. carga manual de las
listas públicas ONU/OFAC/PEP -- no es algo que se resuelva por código).

**Esto es una herramienta de apoyo, no un motor de compliance certificado.**
`calcular_nivel_riesgo()` es una heurística simplificada y transparente
(documentada abajo), pensada para que el despacho DOCUMENTE su propio
criterio de forma consistente y auditable — nunca sustituye el juicio del
oficial de cumplimiento real. El disclaimer se repite en la UI
(frontend/src/clientes/ClienteDetailPage.tsx).

Diseño (mismo principio que core/cobro.py::honorarios_liquidados):
`nivel_riesgo_calculado` SIEMPRE lo calcula el backend a partir de los
factores ya guardados -- nunca se acepta como input directo del cliente de
la API.

Por CLIENTE, no por caso: el KYC/SAGRILAFT se hace una vez por relación con
el cliente (`cliente_id`, PK), no se repite por cada caso nuevo -- distinto
del criterio de core/cobro.py, que sí es por caso (el valor en disputa y los
honorarios son propios de cada mandato). `despacho_id` denormalizado, mismo
criterio que `casos.despacho_id`/`julix_calls.despacho_id` (evita un join
extra, y deja auditable a qué despacho pertenecía la evaluación aunque el
cliente cambiara de despacho más adelante, algo que hoy no puede pasar pero
que no vale la pena resolver por join en este momento).
"""

from __future__ import annotations

from core.despachos import ensure_despachos_table

_COLUMNAS = (
    "cliente_id, despacho_id, tipo_persona, actividad_economica_riesgo, jurisdiccion_riesgo, "
    "canal, es_pep, nivel_riesgo_calculado, evaluado_por, created_at, updated_at"
)

TIPOS_PERSONA_VALIDOS = ("natural", "juridica")
NIVELES_RIESGO_VALIDOS = ("bajo", "medio", "alto")
CANALES_VALIDOS = ("presencial", "no_presencial")

_RIESGO_POR_CANAL = {"presencial": "bajo", "no_presencial": "medio"}
_ORDEN_RIESGO = {"bajo": 0, "medio": 1, "alto": 2}


class CumplimientoError(Exception):
    """Base de errores de negocio de este módulo."""


class FactorInvalidoError(CumplimientoError):
    pass


class ClienteDeOtroDespachoError(CumplimientoError):
    """El cliente_id no pertenece al despacho_id de quien evalúa -- nunca
    se permite una matriz de riesgo cruzando el aislamiento de tenant."""


async def ensure_matriz_riesgo_table(db_connection) -> None:
    await ensure_despachos_table(db_connection)
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS matriz_riesgo (
            cliente_id UUID PRIMARY KEY REFERENCES users(id),
            despacho_id UUID NOT NULL REFERENCES despachos(id),
            tipo_persona TEXT NOT NULL CHECK (tipo_persona IN ('natural', 'juridica')),
            actividad_economica_riesgo TEXT NOT NULL CHECK (actividad_economica_riesgo IN ('bajo', 'medio', 'alto')),
            jurisdiccion_riesgo TEXT NOT NULL CHECK (jurisdiccion_riesgo IN ('bajo', 'medio', 'alto')),
            canal TEXT NOT NULL CHECK (canal IN ('presencial', 'no_presencial')),
            es_pep BOOLEAN NOT NULL DEFAULT false,
            nivel_riesgo_calculado TEXT NOT NULL CHECK (nivel_riesgo_calculado IN ('bajo', 'medio', 'alto')),
            evaluado_por UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_matriz_riesgo_despacho_id ON matriz_riesgo (despacho_id)"
    )

    # --- Placeholder de listas restrictivas (Fase 4, pasada futura) --------
    # Estructura preparada para no rehacer el modelo de datos después, pero
    # SIN datos ni lógica de cruce todavía -- nada en esta pasada llena ni
    # lee estas dos tablas. Ver docstring del módulo.
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS listas_restrictivas (
            id BIGSERIAL PRIMARY KEY,
            tipo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            identificador TEXT,
            fuente TEXT NOT NULL,
            cargado_en TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await db_connection.execute(
        """
        CREATE TABLE IF NOT EXISTS coincidencias_lista_restrictiva (
            id BIGSERIAL PRIMARY KEY,
            cliente_id UUID NOT NULL REFERENCES users(id),
            lista_id BIGINT NOT NULL REFERENCES listas_restrictivas(id),
            estado_revision TEXT NOT NULL DEFAULT 'pendiente'
                CHECK (estado_revision IN ('pendiente', 'falso_positivo', 'confirmado')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def calcular_nivel_riesgo(
    *, actividad_economica_riesgo: str, jurisdiccion_riesgo: str, canal: str, es_pep: bool,
) -> str:
    """Heurística simplificada y transparente -- NO es un modelo de
    compliance certificado, es un punto de partida documentado que el
    despacho puede ajustar con su propio criterio.

    Regla 1 (no negociable): PEP (persona expuesta políticamente) siempre
    da nivel "alto", sin importar los demás factores -- esto no es una
    decisión arbitraria de este código, es la regla real de SAGRILAFT: la
    sola condición de PEP exige debida diligencia intensificada.

    Regla 2: si no es PEP, el nivel es el MÁXIMO entre actividad_economica_
    riesgo, jurisdiccion_riesgo, y el riesgo fijo del canal (presencial=
    bajo, no_presencial=medio) -- conservador por diseño: un solo factor de
    alto riesgo ya eleva el resultado global, nunca se "diluye" promediando
    con factores bajos."""
    if actividad_economica_riesgo not in NIVELES_RIESGO_VALIDOS:
        raise FactorInvalidoError(f"actividad_economica_riesgo inválido: {actividad_economica_riesgo!r}")
    if jurisdiccion_riesgo not in NIVELES_RIESGO_VALIDOS:
        raise FactorInvalidoError(f"jurisdiccion_riesgo inválido: {jurisdiccion_riesgo!r}")
    if canal not in CANALES_VALIDOS:
        raise FactorInvalidoError(f"canal inválido: {canal!r}")

    if es_pep:
        return "alto"

    riesgo_canal = _RIESGO_POR_CANAL[canal]
    factores = (actividad_economica_riesgo, jurisdiccion_riesgo, riesgo_canal)
    return max(factores, key=lambda nivel: _ORDEN_RIESGO[nivel])


async def set_matriz_riesgo(
    db_connection, *, cliente_id: str, despacho_id: str, actor_id: str,
    tipo_persona: str, actividad_economica_riesgo: str, jurisdiccion_riesgo: str,
    canal: str, es_pep: bool,
) -> dict:
    """Crea o actualiza (upsert) la matriz de riesgo del cliente. Valida
    PRIMERO que el cliente pertenezca al despacho de quien evalúa -- nunca
    se confía en que el llamador ya lo haya chequeado antes."""
    if tipo_persona not in TIPOS_PERSONA_VALIDOS:
        raise FactorInvalidoError(f"tipo_persona inválido: {tipo_persona!r}")

    cliente = await db_connection.fetchrow(
        "SELECT id FROM users WHERE id = $1 AND despacho_id = $2 AND role = 'cliente'",
        cliente_id, despacho_id,
    )
    if cliente is None:
        raise ClienteDeOtroDespachoError(f"Cliente no encontrado en este despacho: {cliente_id!r}")

    nivel_riesgo_calculado = calcular_nivel_riesgo(
        actividad_economica_riesgo=actividad_economica_riesgo,
        jurisdiccion_riesgo=jurisdiccion_riesgo, canal=canal, es_pep=es_pep,
    )

    fila = await db_connection.fetchrow(
        f"""
        INSERT INTO matriz_riesgo (
            cliente_id, despacho_id, tipo_persona, actividad_economica_riesgo,
            jurisdiccion_riesgo, canal, es_pep, nivel_riesgo_calculado, evaluado_por
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (cliente_id) DO UPDATE SET
            tipo_persona = EXCLUDED.tipo_persona,
            actividad_economica_riesgo = EXCLUDED.actividad_economica_riesgo,
            jurisdiccion_riesgo = EXCLUDED.jurisdiccion_riesgo,
            canal = EXCLUDED.canal,
            es_pep = EXCLUDED.es_pep,
            nivel_riesgo_calculado = EXCLUDED.nivel_riesgo_calculado,
            evaluado_por = EXCLUDED.evaluado_por,
            updated_at = now()
        RETURNING {_COLUMNAS}
        """,
        cliente_id, despacho_id, tipo_persona, actividad_economica_riesgo,
        jurisdiccion_riesgo, canal, es_pep, nivel_riesgo_calculado, actor_id,
    )
    return dict(fila)


async def obtener_matriz_riesgo(db_connection, *, cliente_id: str, despacho_id: str) -> dict | None:
    fila = await db_connection.fetchrow(
        f"SELECT {_COLUMNAS} FROM matriz_riesgo WHERE cliente_id = $1 AND despacho_id = $2",
        cliente_id, despacho_id,
    )
    return dict(fila) if fila is not None else None
