"""
Vridik — tests/test_datos_personales.py
Roadmap T7 (Ley 1581 de 2012, derecho ARCO de Acceso): prueba
core/datos_personales.py::exportar_datos_de_usuario contra Postgres real
(join real con despachos, y ownership real por cliente_id/abogado_id/
created_by/autor_id/user_id -- no algo que valga la pena reimplementar en
Python contra un fake) + un smoke test del endpoint HTTP con un fake
mínimo, mismo estilo que tests/test_terminos_endpoint.py.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.datos_personales_endpoint import router as datos_personales_router
from core.actuaciones import ensure_actuaciones_table
from core.auth import create_jwt
from core.auth_events import ensure_bitacora_hash_chain
from core.case import create_caso, ensure_casos_table
from core.case_documents import ensure_case_documents_table
from core.datos_personales import exportar_datos_de_usuario
from core.mensajes import ensure_mensajes_tables
from core.terminos import ensure_terminos_table


# ---------------------------------------------------------------------------
# PostgreSQL real: exportar_datos_de_usuario junta todo lo que es de verdad
# del usuario, y nada de lo que no le pertenece.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exportar_datos_de_usuario_inexistente_da_none(db):
    assert await exportar_datos_de_usuario(db, user_id=str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_exportar_datos_de_usuario_junta_todo_lo_propio(db, make_despacho, make_user):
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_terminos_table(db)
    await ensure_case_documents_table(db)
    await ensure_mensajes_tables(db)
    await ensure_bitacora_hash_chain(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    caso = await create_caso(db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso de prueba")

    await db.execute(
        "INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza) "
        "VALUES ($1, $2, 'una actuación', 'otro', 0.9)",
        caso["id"], cliente["id"],
    )
    await db.execute(
        "INSERT INTO terminos (caso_id, created_by, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento) "
        "VALUES ($1, $2, 'un término', CURRENT_DATE, 5, CURRENT_DATE + 7)",
        caso["id"], cliente["id"],
    )
    await db.execute(
        "INSERT INTO case_documents (caso_id, created_by, tarea, pregunta, contenido) "
        "VALUES ($1, $2, 'tarea', 'pregunta', 'contenido del documento')",
        caso["id"], cliente["id"],
    )
    conv_id = await db.fetchval(
        "INSERT INTO conversaciones (caso_id) VALUES ($1) RETURNING id", caso["id"],
    )
    await db.execute(
        "INSERT INTO mensajes (conversacion_id, autor_id, texto) VALUES ($1, $2, 'hola')",
        conv_id, cliente["id"],
    )
    await db.execute(
        "INSERT INTO auth_events (user_id, event_type) VALUES ($1, 'login_ok')", cliente["id"],
    )

    datos = await exportar_datos_de_usuario(db, user_id=cliente["id"])

    assert datos["perfil"]["email"] == cliente["email"]
    assert datos["perfil"]["despacho_id"] == despacho_id
    assert len(datos["casos"]) == 1 and datos["casos"][0]["id"] == caso["id"]
    assert len(datos["actuaciones"]) == 1 and datos["actuaciones"][0]["texto"] == "una actuación"
    assert len(datos["terminos"]) == 1 and datos["terminos"][0]["descripcion"] == "un término"
    assert len(datos["documentos_generados"]) == 1
    assert datos["documentos_generados"][0]["contenido"] == "contenido del documento"
    assert len(datos["mensajes"]) == 1 and datos["mensajes"][0]["texto"] == "hola"
    assert any(e["event_type"] == "login_ok" for e in datos["eventos_de_autenticacion"])


@pytest.mark.asyncio
async def test_exportar_datos_de_usuario_no_trae_datos_de_otro_usuario(db, make_despacho, make_user):
    """El caso IDOR más simple: el export de A no debe traer ni una fila
    que en realidad le pertenece a B, aunque compartan despacho y caso."""
    await ensure_casos_table(db)
    await ensure_actuaciones_table(db)
    await ensure_mensajes_tables(db)

    despacho_id = await make_despacho()
    cliente = await make_user(role="cliente", despacho_id=despacho_id)
    abogado = await make_user(role="abogado", despacho_id=despacho_id)
    caso = await create_caso(
        db, cliente_id=cliente["id"], despacho_id=despacho_id, titulo="Caso compartido", abogado_id=abogado["id"],
    )

    # Actuación creada por el ABOGADO, no por el cliente.
    await db.execute(
        "INSERT INTO actuaciones (caso_id, created_by, texto, categoria, confianza) "
        "VALUES ($1, $2, 'del abogado', 'otro', 0.9)",
        caso["id"], abogado["id"],
    )
    conv_id = await db.fetchval(
        "INSERT INTO conversaciones (caso_id) VALUES ($1) RETURNING id", caso["id"],
    )
    # Mensaje escrito por el ABOGADO, no por el cliente.
    await db.execute(
        "INSERT INTO mensajes (conversacion_id, autor_id, texto) VALUES ($1, $2, 'del abogado')",
        conv_id, abogado["id"],
    )

    datos_cliente = await exportar_datos_de_usuario(db, user_id=cliente["id"])

    # El caso sí aparece (el cliente es dueño del caso), pero ni la
    # actuación ni el mensaje del abogado son suyos.
    assert len(datos_cliente["casos"]) == 1
    assert datos_cliente["actuaciones"] == []
    assert datos_cliente["mensajes"] == []


# ---------------------------------------------------------------------------
# Endpoint HTTP: smoke test con fake mínimo -- confirma el wiring de auth,
# no reimplementa la lógica de exportar_datos_de_usuario (ya probada arriba).
# ---------------------------------------------------------------------------
class _FakeDatosPersonalesDB:
    def __init__(self, usuario: dict):
        self.usuario = usuario

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        # Cubre tanto _resolver_usuario (api/admin_endpoint.py, la query
        # simple que exige get_current_user) como la del propio
        # perfil de exportar_datos_de_usuario (con LEFT JOIN despachos) --
        # el dict de self.usuario ya trae todas las columnas que cualquiera
        # de las dos pide.
        q = query.strip()
        if "FROM users" in q:
            return dict(self.usuario)
        return None

    async def fetch(self, query: str, *args):
        return []

    async def fetchval(self, query: str, *args):
        # core/auth_events.py::_backfill_hash_chain -- "no hay pendientes"
        # es la única respuesta que necesita este fake para no intentar un
        # backfill real contra datos que no existen acá.
        return False


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_exportar_mis_datos_endpoint_exige_autenticacion():
    app = FastAPI()
    app.include_router(datos_personales_router)
    app.state.db_connection = _FakeDatosPersonalesDB({})
    client = TestClient(app)

    r = client.get("/me/datos")
    assert r.status_code == 401


def test_exportar_mis_datos_endpoint_devuelve_el_propio_perfil():
    usuario = {
        "id": str(uuid.uuid4()), "email": "yo@vridik.local", "role": "cliente",
        "is_active": True, "totp_enabled": False, "despacho_id": "despacho-1",
        "despacho_nombre": "Mi despacho", "es_superadmin": False, "created_at": None,
    }
    app = FastAPI()
    app.include_router(datos_personales_router)
    app.state.db_connection = _FakeDatosPersonalesDB(usuario)
    client = TestClient(app)
    token = _token_de(usuario)

    r = client.get("/me/datos", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["perfil"]["email"] == "yo@vridik.local"
    assert body["casos"] == []
