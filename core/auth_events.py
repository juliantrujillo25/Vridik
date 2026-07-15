"""
Vridik — core/auth_events.py
Fase B (S1-GAP-01, AUDITORIA_PARA_CLAUDE.md): bitácora probatoria del
roadmap Fase 3 ("bitácora sellada de notificaciones con acuse -- crece
sobre auth_events + hash encadenado").

`registrar_evento()` es append-only por convención de aplicación — nunca se
hace UPDATE/DELETE sobre `auth_events` desde código de negocio, solo INSERT.
Falla silenciosamente nunca: si la tabla no existe todavía (Fase A no
aplicada en algún entorno), levanta el error de Postgres tal cual, no lo
traga -- registrar un evento de auditoría es parte del contrato, no un
best-effort.

Hash encadenado (Fase 3): cada fila guarda `hash_actual = SHA-256(hash_
anterior + contenido_canónico_de_esta_fila)`. Alterar o borrar CUALQUIER
fila intermedia rompe el hash de todas las filas posteriores -- eso es lo
que hace la bitácora "sellada": no impide escribir (es append-only por
convención, no por permisos de DB), pero cualquier alteración retroactiva
queda matemáticamente detectable con `verificar_cadena()`.

Concurrencia: dos inserts concurrentes que lean el mismo "último hash" y
escriban en paralelo bifurcarían la cadena -- `pg_advisory_xact_lock()`
(constante fija `hashtext('vridik_auth_events_chain')`) serializa TODOS
los appends de esta bitácora entre sí, liberado solo al terminar la
transacción. El volumen de escritura acá (eventos de auth + notificaciones
con acuse) es bajo -- serializar por completo es correcto y simple, no
hace falta nada más fino.

ÚNICO punto de escritura de runtime real a `auth_events` en toda la app
-- `core/admin_users.py` y `core/feature_flag_legacy.py` delegaban antes
en un INSERT propio duplicado; se consolidaron acá el mismo día que se
agregó el hash chain (si hubiera quedado un segundo punto de escritura
sin encadenar, la "bitácora sellada" tendría un hueco real). Los scripts
de operación en `migrations/` (fuera del runtime de `app/main.py`,
ejecutados manualmente y fuera de banda) quedan afuera a propósito --
limitación conocida, no se pretende que la cadena cubra migraciones
manuales de datos.

`created_at` se genera en Python (no con el DEFAULT de Postgres) para
poder incluirlo en el contenido canónico ANTES del insert -- si se dejara
que la base de datos lo pusiera, el hash no podría calcularse hasta
después de insertar, y esta bitácora nunca hace un UPDATE posterior sobre
una fila ya escrita.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

_LOCK_KEY_CADENA = "vridik_auth_events_chain"

# Roadmap: "notificaciones con acuse" -- event_types que representan un
# aviso a un cliente/usuario que puede confirmarse (ver confirmar_acuse()).
# No todo evento de auth_events es "notificable" (login_failed, por
# ejemplo, no tiene sentido que el usuario lo "acuse").
EVENT_TYPES_NOTIFICABLES = frozenset({"actuacion_notificada"})


def _contenido_canonico(
    *, event_type: str, user_id: str | None, actor_id: str | None,
    metadata: dict, ip_address: str | None, user_agent: str | None, created_at: datetime,
) -> str:
    """Representación determinística de una fila -- mismas claves, mismo
    orden (sort_keys), siempre, para que el hash sea reproducible al
    verificar más tarde."""
    return json.dumps(
        {
            "event_type": event_type, "user_id": user_id, "actor_id": actor_id,
            "metadata": metadata, "ip_address": ip_address, "user_agent": user_agent,
            "created_at": created_at.isoformat(),
        },
        sort_keys=True, default=str,
    )


def _calcular_hash(*, hash_anterior: str | None, contenido: str) -> str:
    return hashlib.sha256(f"{hash_anterior or ''}{contenido}".encode("utf-8")).hexdigest()


async def ensure_bitacora_hash_chain(conn) -> None:
    """Migración aditiva: agrega las columnas del hash chain a
    `auth_events` si todavía no existen. Nunca borra ni reordena nada de
    lo que ya había."""
    await conn.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS hash_anterior TEXT")
    await conn.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS hash_actual TEXT")


@asynccontextmanager
async def _conexion_dedicada(conn):
    """`conn` acá puede ser un `asyncpg.Pool` (sin `.transaction()` propio
    -- para sostener un lock+lectura+insert como una sola operación
    atómica hace falta adquirir una conexión dedicada del pool primero),
    una `Connection` individual ya adquirida (p.ej. dentro de
    `app/main.py::_bucle_alertas_terminos`, que hace su propio
    `pool.acquire()`), o un fake de test simple. Se detecta por duck
    typing -- nunca se asume cuál de los dos es."""
    if hasattr(conn, "acquire"):
        async with conn.acquire() as conexion:
            yield conexion
    else:
        yield conn


@asynccontextmanager
async def _transaccion_si_disponible(conexion):
    """Los fakes de test (y, en teoría, cualquier conexión sin soporte
    real de transacciones) no tienen `.transaction()` -- se degrada a
    no-op ahí. Contra Postgres real (Connection de verdad) SIEMPRE hay
    `.transaction()`, así que en producción esto nunca se salta."""
    if hasattr(conexion, "transaction"):
        async with conexion.transaction():
            yield
    else:
        yield


async def registrar_evento(
    conn,
    *,
    event_type: str,
    user_id: str | None = None,
    actor_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Inserta un evento encadenado. Devuelve la fila completa (incluido
    `id` y `hash_actual`) -- útil para wirear un acuse sobre este mismo
    evento sin una segunda consulta."""
    cuerpo = metadata or {}
    created_at = datetime.now(timezone.utc)
    contenido = _contenido_canonico(
        event_type=event_type, user_id=user_id, actor_id=actor_id, metadata=cuerpo,
        ip_address=ip_address, user_agent=user_agent, created_at=created_at,
    )

    async with _conexion_dedicada(conn) as conexion:
        async with _transaccion_si_disponible(conexion):
            # Serializa todos los appends de la bitácora -- sin esto, dos
            # inserts concurrentes podrían leer el mismo "último hash" y
            # bifurcar la cadena.
            await conexion.execute("SELECT pg_advisory_xact_lock(hashtext($1))", _LOCK_KEY_CADENA)

            anterior = await conexion.fetchrow("SELECT hash_actual FROM auth_events ORDER BY id DESC LIMIT 1")
            hash_anterior = anterior["hash_actual"] if anterior is not None else None
            hash_actual = _calcular_hash(hash_anterior=hash_anterior, contenido=contenido)

            fila = await conexion.fetchrow(
                """
                INSERT INTO auth_events
                    (user_id, actor_id, event_type, metadata, ip_address, user_agent,
                     created_at, hash_anterior, hash_actual)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
                RETURNING id, user_id, actor_id, event_type, metadata, ip_address, user_agent,
                          created_at, hash_anterior, hash_actual
                """,
                user_id, actor_id, event_type, json.dumps(cuerpo), ip_address, user_agent,
                created_at, hash_anterior, hash_actual,
            )
    # `metadata` en el RETURNING viene como jsonb crudo (string) -- se
    # devuelve `cuerpo` (el dict Python que ya se tenía en memoria) en su
    # lugar, para que un endpoint HTTP no lo mande double-encoded.
    return {**dict(fila), "metadata": cuerpo}


async def verificar_cadena(conn, *, limite: int = 5000) -> dict:
    """Recorre la bitácora en orden y recalcula cada hash a partir del
    contenido almacenado -- si alguna fila fue alterada o borrada después
    de escrita, el hash recalculado no coincide con el guardado (o la
    cadena de hash_anterior se corta) y queda detectado acá.

    Nunca "arregla" nada -- es de solo lectura, siempre. Si la cadena está
    rota, corregirla es una decisión humana (y probablemente un incidente
    de seguridad), no algo que este código deba intentar resolver solo."""
    filas = await conn.fetch(
        """
        SELECT id, user_id, actor_id, event_type, metadata, ip_address, user_agent,
               created_at, hash_anterior, hash_actual
        FROM auth_events
        ORDER BY id ASC
        LIMIT $1
        """,
        limite,
    )

    hash_previo_esperado: str | None = None
    for fila in filas:
        metadata = fila["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        contenido = _contenido_canonico(
            event_type=fila["event_type"], user_id=fila["user_id"], actor_id=fila["actor_id"],
            metadata=metadata, ip_address=fila["ip_address"], user_agent=fila["user_agent"],
            created_at=fila["created_at"],
        )
        esperado = _calcular_hash(hash_anterior=hash_previo_esperado, contenido=contenido)

        if fila["hash_anterior"] != hash_previo_esperado or fila["hash_actual"] != esperado:
            return {
                "integra": False, "total_verificados": len(filas),
                "primera_ruptura_id": fila["id"],
            }
        hash_previo_esperado = fila["hash_actual"]

    return {"integra": True, "total_verificados": len(filas), "primera_ruptura_id": None}


class BitacoraError(Exception):
    """Base de errores de negocio de este módulo -- el llamador HTTP
    (api/bitacora_endpoint.py) los traduce a códigos de estado."""


class EventoNoEncontradoError(BitacoraError):
    pass


class NoEsDestinatarioError(BitacoraError):
    pass


class AcuseInvalidoError(BitacoraError):
    """Evento que no es de un tipo notificable, o que ya fue confirmado."""


async def confirmar_acuse(conn, *, evento_id: int, user_id: str) -> dict:
    """Roadmap: "notificaciones CON ACUSE". El acuse nunca muta la fila
    original (append-only, ver docstring del módulo) -- es un evento
    NUEVO, encadenado, que referencia al original en su metadata. Solo el
    destinatario real de la notificación puede confirmarla, y solo una
    vez."""
    original = await conn.fetchrow(
        "SELECT id, user_id, event_type FROM auth_events WHERE id = $1", evento_id,
    )
    if original is None:
        raise EventoNoEncontradoError(f"Evento {evento_id!r} no encontrado")
    if original["event_type"] not in EVENT_TYPES_NOTIFICABLES:
        raise AcuseInvalidoError(f"El evento {evento_id!r} no es un tipo notificable ({original['event_type']!r})")
    if str(original["user_id"]) != str(user_id):
        raise NoEsDestinatarioError("Solo el destinatario de la notificación puede confirmarla")

    ya_confirmado = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1 FROM auth_events
            WHERE event_type = 'notificacion_acuse' AND (metadata->>'evento_original_id')::bigint = $1
        )
        """,
        evento_id,
    )
    if ya_confirmado:
        raise AcuseInvalidoError(f"El evento {evento_id!r} ya fue confirmado")

    return await registrar_evento(
        conn, event_type="notificacion_acuse", user_id=user_id,
        metadata={"evento_original_id": evento_id},
    )


async def listar_notificaciones(conn, *, user_id: str) -> list[dict]:
    """Notificaciones (event_type en EVENT_TYPES_NOTIFICABLES) del usuario,
    más recientes primero, con `acuse_en` (None si todavía no las confirmó).
    Portal Cliente Vridik: la lista que el cliente ve para saber qué le
    falta confirmar."""
    filas = await conn.fetch(
        """
        SELECT e.id, e.event_type, e.metadata, e.created_at, a.created_at AS acuse_en
        FROM auth_events e
        LEFT JOIN auth_events a
            ON a.event_type = 'notificacion_acuse'
            AND (a.metadata->>'evento_original_id')::bigint = e.id
        WHERE e.user_id = $1 AND e.event_type = ANY($2::text[])
        ORDER BY e.created_at DESC
        """,
        user_id, list(EVENT_TYPES_NOTIFICABLES),
    )
    resultado = []
    for f in filas:
        fila = dict(f)
        # asyncpg devuelve columnas jsonb como texto crudo salvo que se
        # registre un codec (no es el caso acá, ver app/main.py) -- se
        # parsea acá para que el endpoint HTTP no lo mande double-encoded.
        if isinstance(fila["metadata"], str):
            fila["metadata"] = json.loads(fila["metadata"])
        resultado.append(fila)
    return resultado
