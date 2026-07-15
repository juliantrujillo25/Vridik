"""
Vridik — tests/test_bitacora.py
Fase 3: "Bitácora sellada de notificaciones con acuse -- crece sobre
auth_events + hash encadenado" (core/auth_events.py).

Tres capas, mismo criterio que tests/test_events.py:
1. Fake mínimo: registrar_evento()/verificar_cadena()/confirmar_acuse()
   arman el hash chain correctamente -- rápido, sin red, corre siempre.
2. PostgreSQL real (fixture `db` de conftest.py): confirma el hash chain
   contra SQL real, incluido el advisory lock.
3. api/bitacora_endpoint.py end-to-end (FastAPI TestClient) sobre el
   mismo fake de la capa 1.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import create_jwt
from core.auth_events import (
    AcuseInvalidoError,
    EventoNoEncontradoError,
    NoEsDestinatarioError,
    confirmar_acuse,
    registrar_evento,
    verificar_cadena,
)


# ---------------------------------------------------------------------------
# Fake: hash chain, verificación de integridad, acuse.
# ---------------------------------------------------------------------------
class _FakeBitacoraConn:
    def __init__(self):
        self.filas: list[dict] = []

    async def execute(self, query: str, *args):
        return "OK"  # advisory lock y ALTER TABLE -- no-op

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO auth_events"):
            user_id, actor_id, event_type, metadata, ip_address, user_agent, created_at, hash_anterior, hash_actual = args
            fila = {
                "id": len(self.filas) + 1, "user_id": user_id, "actor_id": actor_id,
                "event_type": event_type, "metadata": metadata, "ip_address": ip_address,
                "user_agent": user_agent, "created_at": created_at,
                "hash_anterior": hash_anterior, "hash_actual": hash_actual,
            }
            self.filas.append(fila)
            return dict(fila)
        if q == "SELECT hash_actual FROM auth_events ORDER BY id DESC LIMIT 1":
            return {"hash_actual": self.filas[-1]["hash_actual"]} if self.filas else None
        if q.strip().startswith("SELECT id, user_id, event_type FROM auth_events WHERE id"):
            (evento_id,) = args
            f = next((f for f in self.filas if f["id"] == evento_id), None)
            return dict(f) if f else None
        return None

    async def fetchval(self, query: str, *args):
        if "notificacion_acuse" in query and "evento_original_id" in query:
            (evento_id,) = args
            return any(
                f["event_type"] == "notificacion_acuse" and json.loads(f["metadata"]).get("evento_original_id") == evento_id
                for f in self.filas
            )
        return False

    async def fetch(self, query: str, *args):
        return [dict(f) for f in self.filas]  # verificar_cadena, orden de inserción


@pytest.mark.asyncio
async def test_registrar_evento_arma_el_hash_encadenado():
    conn = _FakeBitacoraConn()
    primero = await registrar_evento(conn, event_type="login_success", user_id="user-1")
    segundo = await registrar_evento(conn, event_type="login_success", user_id="user-2")

    assert primero["hash_anterior"] is None  # primer eslabón de la cadena
    assert segundo["hash_anterior"] == primero["hash_actual"]
    assert primero["hash_actual"] != segundo["hash_actual"]


@pytest.mark.asyncio
async def test_registrar_evento_devuelve_metadata_como_dict_no_string():
    conn = _FakeBitacoraConn()
    evento = await registrar_evento(conn, event_type="user_created", metadata={"email": "x@vridik.local"})
    assert evento["metadata"] == {"email": "x@vridik.local"}  # nunca double-encoded


@pytest.mark.asyncio
async def test_verificar_cadena_integra_tras_varios_eventos():
    conn = _FakeBitacoraConn()
    for i in range(5):
        await registrar_evento(conn, event_type="login_success", user_id=f"user-{i}")

    resultado = await verificar_cadena(conn)
    assert resultado == {"integra": True, "total_verificados": 5, "primera_ruptura_id": None}


@pytest.mark.asyncio
async def test_verificar_cadena_detecta_una_fila_alterada():
    conn = _FakeBitacoraConn()
    await registrar_evento(conn, event_type="login_success", user_id="user-1")
    await registrar_evento(conn, event_type="login_success", user_id="user-2")
    await registrar_evento(conn, event_type="login_success", user_id="user-3")

    # Simula una alteración retroactiva -- exactamente lo que la bitácora
    # sellada tiene que poder detectar.
    conn.filas[1]["event_type"] = "login_success_ALTERADO"

    resultado = await verificar_cadena(conn)
    assert resultado["integra"] is False
    assert resultado["primera_ruptura_id"] == 2


@pytest.mark.asyncio
async def test_verificar_cadena_detecta_una_fila_borrada_del_medio():
    conn = _FakeBitacoraConn()
    await registrar_evento(conn, event_type="login_success", user_id="user-1")
    await registrar_evento(conn, event_type="login_success", user_id="user-2")
    await registrar_evento(conn, event_type="login_success", user_id="user-3")

    del conn.filas[1]  # borra la fila del medio -- rompe hash_anterior de la última

    resultado = await verificar_cadena(conn)
    assert resultado["integra"] is False


@pytest.mark.asyncio
async def test_confirmar_acuse_registra_un_evento_nuevo_encadenado():
    conn = _FakeBitacoraConn()
    notificacion = await registrar_evento(
        conn, event_type="actuacion_notificada", user_id="user-1",
        metadata={"caso_id": "caso-1", "actuacion_id": "act-1"},
    )

    acuse = await confirmar_acuse(conn, evento_id=notificacion["id"], user_id="user-1")

    assert acuse["event_type"] == "notificacion_acuse"
    assert acuse["metadata"]["evento_original_id"] == notificacion["id"]
    # El acuse es un evento NUEVO -- nunca se mutó la fila original.
    assert conn.filas[0]["event_type"] == "actuacion_notificada"
    assert len(conn.filas) == 2


@pytest.mark.asyncio
async def test_confirmar_acuse_evento_inexistente():
    conn = _FakeBitacoraConn()
    with pytest.raises(EventoNoEncontradoError):
        await confirmar_acuse(conn, evento_id=999, user_id="user-1")


@pytest.mark.asyncio
async def test_confirmar_acuse_de_otro_usuario_rechazado():
    conn = _FakeBitacoraConn()
    notificacion = await registrar_evento(conn, event_type="actuacion_notificada", user_id="user-1")
    with pytest.raises(NoEsDestinatarioError):
        await confirmar_acuse(conn, evento_id=notificacion["id"], user_id="user-2")


@pytest.mark.asyncio
async def test_confirmar_acuse_no_notificable_rechazado():
    conn = _FakeBitacoraConn()
    login = await registrar_evento(conn, event_type="login_success", user_id="user-1")
    with pytest.raises(AcuseInvalidoError):
        await confirmar_acuse(conn, evento_id=login["id"], user_id="user-1")


@pytest.mark.asyncio
async def test_confirmar_acuse_dos_veces_rechazado_la_segunda():
    conn = _FakeBitacoraConn()
    notificacion = await registrar_evento(conn, event_type="actuacion_notificada", user_id="user-1")
    await confirmar_acuse(conn, evento_id=notificacion["id"], user_id="user-1")
    with pytest.raises(AcuseInvalidoError):
        await confirmar_acuse(conn, evento_id=notificacion["id"], user_id="user-1")


# ---------------------------------------------------------------------------
# api/bitacora_endpoint.py end-to-end sobre el mismo fake.
# ---------------------------------------------------------------------------
from api.bitacora_endpoint import router as bitacora_router  # noqa: E402


class _FakeBitacoraHttpConn(_FakeBitacoraConn):
    """Suma `users` al fake de arriba -- api/admin_endpoint.py::get_current_
    user/get_current_admin resuelven el rol consultando la DB (el JWT solo
    lleva sub/email, nunca el rol, ver core/auth.py::create_jwt)."""

    def __init__(self):
        super().__init__()
        self.users: dict[str, dict] = {}

    def seed_user(self, *, role: str = "cliente", totp_enabled: bool = True) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": f"{user_id}@vridik.local", "role": role, "totp_enabled": totp_enabled,
        }
        return self.users[user_id]

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return {"id": u["id"], "email": u["email"], "role": u["role"]} if u else None
        if q.strip() == "SELECT totp_enabled FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return {"totp_enabled": u["totp_enabled"]} if u else None
        return await super().fetchrow(query, *args)

    async def fetch(self, query: str, *args):
        q = query.strip()
        if "FROM auth_events e" in q and "LEFT JOIN auth_events a" in q:
            user_id, tipos_notificables = args
            acuses = {
                f["metadata_dict"]["evento_original_id"]: f["created_at"]
                for f in (dict(x, metadata_dict=json.loads(x["metadata"])) for x in self.filas)
                if f["event_type"] == "notificacion_acuse"
            }
            filas = [
                {
                    "id": f["id"], "event_type": f["event_type"], "metadata": f["metadata"],
                    "created_at": f["created_at"], "acuse_en": acuses.get(f["id"]),
                }
                for f in self.filas
                if f["user_id"] == user_id and f["event_type"] in tipos_notificables
            ]
            filas.sort(key=lambda f: f["created_at"], reverse=True)
            return filas
        return await super().fetch(query, *args)


@pytest.fixture
def bdb():
    return _FakeBitacoraHttpConn()


@pytest.fixture
def bclient(bdb):
    app = FastAPI()
    app.include_router(bitacora_router)
    app.state.db_connection = bdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_verificar_endpoint_solo_admin(bdb, bclient):
    cliente = bdb.seed_user(role="cliente")
    r = bclient.get("/bitacora/verificar", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 403


def test_verificar_endpoint_admin_ve_integridad(bdb, bclient):
    admin = bdb.seed_user(role="admin")
    r = bclient.get("/bitacora/verificar", headers={"Authorization": f"Bearer {_token_de(admin)}"})
    assert r.status_code == 200, r.text
    assert r.json()["integra"] is True


def test_mis_notificaciones_devuelve_solo_las_propias(bdb, bclient):
    import asyncio
    cliente1 = bdb.seed_user()
    cliente2 = bdb.seed_user()
    asyncio.run(registrar_evento(bdb, event_type="actuacion_notificada", user_id=cliente1["id"], metadata={"x": 1}))
    asyncio.run(registrar_evento(bdb, event_type="actuacion_notificada", user_id=cliente2["id"], metadata={"x": 2}))

    r = bclient.get("/bitacora/mis-notificaciones", headers={"Authorization": f"Bearer {_token_de(cliente1)}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["acuse_en"] is None


def test_confirmar_acuse_endpoint_de_punta_a_punta(bdb, bclient):
    import asyncio
    cliente = bdb.seed_user()
    notificacion = asyncio.run(
        registrar_evento(bdb, event_type="actuacion_notificada", user_id=cliente["id"], metadata={"x": 1}),
    )

    token = _token_de(cliente)
    r = bclient.post(
        f"/bitacora/eventos/{notificacion['id']}/acuse", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["event_type"] == "notificacion_acuse"

    r2 = bclient.get("/bitacora/mis-notificaciones", headers={"Authorization": f"Bearer {token}"})
    assert r2.json()[0]["acuse_en"] is not None


def test_confirmar_acuse_endpoint_de_otro_usuario_da_403(bdb, bclient):
    import asyncio
    cliente = bdb.seed_user()
    otro = bdb.seed_user()
    notificacion = asyncio.run(registrar_evento(bdb, event_type="actuacion_notificada", user_id=cliente["id"]))

    r = bclient.post(
        f"/bitacora/eventos/{notificacion['id']}/acuse", headers={"Authorization": f"Bearer {_token_de(otro)}"},
    )
    assert r.status_code == 403


def test_confirmar_acuse_endpoint_inexistente_da_404(bdb, bclient):
    cliente = bdb.seed_user()
    r = bclient.post("/bitacora/eventos/999/acuse", headers={"Authorization": f"Bearer {_token_de(cliente)}"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PostgreSQL real: el hash chain contra SQL real (fixture `db`, rollback
# transaccional -- no hace falta autocommit acá, a diferencia de
# tests/test_events.py con NOTIFY/LISTEN).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hash_chain_real_contra_postgres(db):
    await db.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS hash_anterior TEXT")
    await db.execute("ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS hash_actual TEXT")

    e1 = await registrar_evento(db, event_type="login_success", user_id=None)
    e2 = await registrar_evento(db, event_type="login_success", user_id=None)
    e3 = await registrar_evento(db, event_type="login_success", user_id=None)

    assert e2["hash_anterior"] == e1["hash_actual"]
    assert e3["hash_anterior"] == e2["hash_actual"]

    resultado = await verificar_cadena(db)
    assert resultado["integra"] is True
