"""
Vridik — tests/test_mensajes_endpoint.py
Roadmap Semana 11, Fase A: prueba api/mensajes_endpoint.py + core/mensajes.py
end-to-end (FastAPI TestClient) sobre un fake mínimo de conexión asyncpg —
mismo estilo que tests/test_casos.py. No confundir con
tests/test_mensajes.py (Sprint S3, contrato de FakeMensajesService sobre
tests/support/fakes.py) -- ese sigue documentando el contrato de datos
original; este prueba la implementación real que lo reemplaza.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.mensajes_endpoint as mensajes_module
from api.mensajes_endpoint import router as mensajes_router
from core.auth import create_jwt


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeMensajesDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.conversaciones: dict[str, dict] = {}
        self.mensajes: dict[str, dict] = {}
        self.conversation_reads: dict[tuple[str, str], str] = {}
        self.notificaciones: list[tuple[str, str]] = []  # (canal, payload)
        self.user_events: list[dict] = []

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role, "despacho_id": despacho_id}
        return self.users[user_id]

    def seed_caso(self, *, cliente_id: str, abogado_id: str | None = None, despacho_id: str = "despacho-1") -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "despacho_id": despacho_id,
            "titulo": "caso", "descripcion": None, "estado": "abierto", "created_at": _ahora(), "updated_at": _ahora(),
        }
        return self.casos[caso_id]

    async def execute(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO conversation_reads"):
            conversacion_id, user_id, last_read_at = args
            clave = (conversacion_id, user_id)
            actual = self.conversation_reads.get(clave)
            self.conversation_reads[clave] = max(actual, last_read_at) if actual else last_read_at
        elif q.startswith("SELECT pg_notify"):
            canal, payload = args
            self.notificaciones.append((canal, payload))
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q.startswith("INSERT INTO user_events"):
            user_id, event_type, payload = args
            evento_id = len(self.user_events) + 1
            self.user_events.append(
                {"id": evento_id, "user_id": user_id, "event_type": event_type, "payload": payload},
            )
            return {"id": evento_id}
        if "SELECT id, email, role, despacho_id FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if "SELECT id, caso_id, created_at FROM conversaciones WHERE caso_id" in q:
            (caso_id,) = args
            conv = next((c for c in self.conversaciones.values() if c["caso_id"] == caso_id), None)
            return dict(conv) if conv else None
        if q.startswith("INSERT INTO conversaciones"):
            (caso_id,) = args
            existente = next((c for c in self.conversaciones.values() if c["caso_id"] == caso_id), None)
            if existente is not None:
                return dict(existente)
            conv_id = str(uuid.uuid4())
            conv = {"id": conv_id, "caso_id": caso_id, "created_at": _ahora()}
            self.conversaciones[conv_id] = conv
            return dict(conv)
        if q.startswith("INSERT INTO mensajes"):
            conversacion_id, autor_id, texto, adjunto_url, adjunto_nombre = args
            msg_id = str(uuid.uuid4())
            msg = {
                "id": msg_id, "conversacion_id": conversacion_id, "autor_id": autor_id, "texto": texto,
                "adjunto_url": adjunto_url, "adjunto_nombre": adjunto_nombre, "borrado": False,
                "created_at": _ahora(),
            }
            self.mensajes[msg_id] = msg
            return dict(msg)
        if "FROM mensajes WHERE id" in q and not q.startswith("UPDATE"):
            (mensaje_id,) = args
            m = self.mensajes.get(mensaje_id)
            return dict(m) if m else None
        if q.startswith("UPDATE mensajes SET borrado"):
            mensaje_id, actor_id = args
            m = self.mensajes.get(mensaje_id)
            if m is not None and m["autor_id"] == actor_id:
                m["borrado"] = True
                return {"id": mensaje_id}
            return None
        return None

    async def fetch(self, query: str, *args):
        if "FROM mensajes" in query and "WHERE conversacion_id" in query:
            conversacion_id, skip, limit = args
            filas = [m for m in self.mensajes.values() if m["conversacion_id"] == conversacion_id]
            filas.sort(key=lambda m: m["created_at"], reverse=True)
            return [dict(m) for m in filas[skip:skip + limit]]
        return []

    async def fetchval(self, query: str, *args):
        if "FROM mensajes m" in query and "conversation_reads" in query:
            user_id, conversacion_id = args
            cursor = self.conversation_reads.get((conversacion_id, user_id), "")
            return sum(
                1 for m in self.mensajes.values()
                if m["conversacion_id"] == conversacion_id
                and not m["borrado"]
                and m["autor_id"] != user_id
                and m["created_at"] > cursor
            )
        return 0


@pytest.fixture
def mdb():
    return _FakeMensajesDB()


@pytest.fixture
def mclient(mdb):
    app = FastAPI()
    app.include_router(mensajes_router)
    app.state.db_connection = mdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_cliente_crea_y_lista_mensajes(mdb, mclient):
    cliente = mdb.seed_user(email="cliente1@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "hola"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["texto"] == "hola"
    assert r.json()["autor_id"] == cliente["id"]

    r = mclient.get(f"/casos/{caso['id']}/mensajes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_abogado_asignado_puede_escribir(mdb, mclient):
    cliente = mdb.seed_user(email="cliente2@vridik.local")
    abogado = mdb.seed_user(email="abogado2@vridik.local", role="abogado")
    caso = mdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "respuesta"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_crear_mensaje_notifica_message_new_al_otro_participante(mdb, mclient):
    """Fase B: el cliente escribe -- debe notificarse SOLO al abogado
    asignado (core/events.py::canal_de_usuario), nunca al propio autor."""
    cliente = mdb.seed_user(email="cliente_notif@vridik.local")
    abogado = mdb.seed_user(email="abogado_notif@vridik.local", role="abogado")
    caso = mdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "hola abogado"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text

    assert len(mdb.notificaciones) == 1
    canal, payload = mdb.notificaciones[0]
    assert canal == f"vridik_events_{abogado['id']}"
    assert '"type": "message.new"' in payload
    assert caso["id"] in payload


def test_crear_mensaje_sin_abogado_asignado_no_notifica_a_nadie(mdb, mclient):
    """Sin abogado asignado todavía, el único destinatario posible sería el
    propio autor (el cliente) -- se descarta, así que no hay notify."""
    cliente = mdb.seed_user(email="cliente_notif2@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "hola"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    assert mdb.notificaciones == []


def test_usuario_sin_relacion_al_caso_forbidden(mdb, mclient):
    cliente = mdb.seed_user(email="cliente3@vridik.local")
    otro = mdb.seed_user(email="otro3@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "x"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_caso_inexistente_404(mdb, mclient):
    cliente = mdb.seed_user(email="cliente4@vridik.local")
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{uuid.uuid4()}/mensajes", json={"texto": "x"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_no_leidos_cuenta_mensajes_del_otro_y_baja_al_marcar_leido(mdb, mclient):
    cliente = mdb.seed_user(email="cliente5@vridik.local")
    abogado = mdb.seed_user(email="abogado5@vridik.local", role="abogado")
    caso = mdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token_cliente = _token_de(cliente)
    token_abogado = _token_de(abogado)

    mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "uno"}, headers={"Authorization": f"Bearer {token_abogado}"},
    )
    m2 = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "dos"}, headers={"Authorization": f"Bearer {token_abogado}"},
    ).json()

    r = mclient.get(f"/casos/{caso['id']}/mensajes/no-leidos", headers={"Authorization": f"Bearer {token_cliente}"})
    assert r.json()["no_leidos"] == 2

    # Propios mensajes nunca cuentan como no leídos.
    r = mclient.get(f"/casos/{caso['id']}/mensajes/no-leidos", headers={"Authorization": f"Bearer {token_abogado}"})
    assert r.json()["no_leidos"] == 0

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes/{m2['id']}/leido", headers={"Authorization": f"Bearer {token_cliente}"},
    )
    assert r.status_code == 200, r.text

    r = mclient.get(f"/casos/{caso['id']}/mensajes/no-leidos", headers={"Authorization": f"Bearer {token_cliente}"})
    assert r.json()["no_leidos"] == 0


def test_autor_puede_borrar_su_mensaje(mdb, mclient):
    cliente = mdb.seed_user(email="cliente6@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    creado = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "borrame"}, headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = mclient.delete(f"/casos/{caso['id']}/mensajes/{creado['id']}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204
    assert mdb.mensajes[creado["id"]]["borrado"] is True


def test_otro_usuario_no_puede_borrar_mensaje_ajeno(mdb, mclient):
    cliente = mdb.seed_user(email="cliente7@vridik.local")
    abogado = mdb.seed_user(email="abogado7@vridik.local", role="abogado")
    caso = mdb.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token_cliente = _token_de(cliente)
    token_abogado = _token_de(abogado)

    creado = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "mio"}, headers={"Authorization": f"Bearer {token_cliente}"},
    ).json()

    r = mclient.delete(
        f"/casos/{caso['id']}/mensajes/{creado['id']}", headers={"Authorization": f"Bearer {token_abogado}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Adjuntos (roadmap S11: "Chat interno con adjuntos") -- POST .../adjuntos
# sube el archivo, GET .../{mensaje_id}/adjunto lo descarga autenticado
# (mismo criterio que api/case_documents_endpoint.py::descargar_pdf_de_
# documento, bug real de producción encontrado y corregido el mismo día:
# la ruta de disco NUNCA es un link público sin auth).
# ---------------------------------------------------------------------------
def test_subir_adjunto_guarda_el_archivo_y_devuelve_url_y_nombre(mdb, mclient, tmp_path, monkeypatch):
    monkeypatch.setattr(mensajes_module, "DIRECTORIO_ADJUNTOS", tmp_path)
    cliente = mdb.seed_user(email="cliente_adj1@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes/adjuntos",
        files={"archivo": ("contrato.pdf", b"%PDF-fake-content", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["adjunto_nombre"] == "contrato.pdf"
    ruta_guardada = Path(body["adjunto_url"])
    assert ruta_guardada.is_file()
    assert ruta_guardada.read_bytes() == b"%PDF-fake-content"
    assert ruta_guardada.suffix == ".pdf"
    # El nombre en disco nunca es el nombre original tal cual (evita path
    # traversal / colisiones) -- ver subir_adjunto_endpoint.
    assert ruta_guardada.name != "contrato.pdf"


def test_subir_adjunto_extension_no_permitida_da_422(mdb, mclient, tmp_path, monkeypatch):
    monkeypatch.setattr(mensajes_module, "DIRECTORIO_ADJUNTOS", tmp_path)
    cliente = mdb.seed_user(email="cliente_adj2@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes/adjuntos",
        files={"archivo": ("script.exe", b"MZ...", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_subir_adjunto_supera_tamano_maximo_da_413(mdb, mclient, tmp_path, monkeypatch):
    monkeypatch.setattr(mensajes_module, "DIRECTORIO_ADJUNTOS", tmp_path)
    monkeypatch.setattr(mensajes_module, "TAMANO_MAXIMO_ADJUNTO_BYTES", 10)
    cliente = mdb.seed_user(email="cliente_adj3@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes/adjuntos",
        files={"archivo": ("foto.png", b"x" * 100, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 413


def test_subir_adjunto_usuario_sin_relacion_al_caso_forbidden(mdb, mclient, tmp_path, monkeypatch):
    monkeypatch.setattr(mensajes_module, "DIRECTORIO_ADJUNTOS", tmp_path)
    cliente = mdb.seed_user(email="cliente_adj4@vridik.local")
    otro = mdb.seed_user(email="otro_adj4@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes/adjuntos",
        files={"archivo": ("foto.png", b"contenido", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_mensaje_con_adjunto_de_punta_a_punta(mdb, mclient, tmp_path, monkeypatch):
    monkeypatch.setattr(mensajes_module, "DIRECTORIO_ADJUNTOS", tmp_path)
    cliente = mdb.seed_user(email="cliente_adj5@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    subida = mclient.post(
        f"/casos/{caso['id']}/mensajes/adjuntos",
        files={"archivo": ("foto.png", b"imagen-fake", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = mclient.post(
        f"/casos/{caso['id']}/mensajes",
        json={"texto": "mirá esto", "adjunto_url": subida["adjunto_url"], "adjunto_nombre": subida["adjunto_nombre"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    mensaje = r.json()
    assert mensaje["adjunto_nombre"] == "foto.png"

    r = mclient.get(
        f"/casos/{caso['id']}/mensajes/{mensaje['id']}/adjunto", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.content == b"imagen-fake"


def test_descargar_adjunto_mensaje_sin_adjunto_da_404(mdb, mclient):
    cliente = mdb.seed_user(email="cliente_adj6@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    mensaje = mclient.post(
        f"/casos/{caso['id']}/mensajes", json={"texto": "sin adjunto"}, headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = mclient.get(
        f"/casos/{caso['id']}/mensajes/{mensaje['id']}/adjunto", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_descargar_adjunto_archivo_perdido_por_almacenamiento_efimero_da_404(mdb, mclient):
    cliente = mdb.seed_user(email="cliente_adj7@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    mensaje = mclient.post(
        f"/casos/{caso['id']}/mensajes",
        json={"texto": "x", "adjunto_url": "/tmp/vridik-mensajes-adjuntos/ya-no-existe.png", "adjunto_nombre": "y.png"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    r = mclient.get(
        f"/casos/{caso['id']}/mensajes/{mensaje['id']}/adjunto", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_descargar_adjunto_usuario_sin_relacion_al_caso_forbidden(mdb, mclient, tmp_path):
    cliente = mdb.seed_user(email="cliente_adj8@vridik.local")
    otro = mdb.seed_user(email="otro_adj8@vridik.local")
    caso = mdb.seed_caso(cliente_id=cliente["id"])
    token_cliente = _token_de(cliente)
    token_otro = _token_de(otro)

    ruta = tmp_path / "archivo.png"
    ruta.write_bytes(b"contenido")
    mensaje = mclient.post(
        f"/casos/{caso['id']}/mensajes",
        json={"texto": "x", "adjunto_url": str(ruta), "adjunto_nombre": "archivo.png"},
        headers={"Authorization": f"Bearer {token_cliente}"},
    ).json()

    r = mclient.get(
        f"/casos/{caso['id']}/mensajes/{mensaje['id']}/adjunto", headers={"Authorization": f"Bearer {token_otro}"},
    )
    assert r.status_code == 403
