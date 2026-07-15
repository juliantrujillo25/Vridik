"""
Vridik — tests/test_case_documents.py
Prueba api/case_documents_endpoint.py: generación de documentos de caso
con JuliX sobre un `caso` propio (core/case.py) -- POST/GET
/casos/{caso_id}/documents. Mismo patrón que tests/test_julix_stream.py
(JuliXService se monkeypatchea con un fake `generar_documento` async
generator) — no se toca Anthropic ni PostgreSQL reales.

Desmantelamiento del marketplace (fase 4): la ruta legacy
/orders/{order_id}/documents se quitó de api/case_documents_endpoint.py —
este archivo dejó de probarla junto con ella.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.case_documents_endpoint as case_documents_module
from api.case_documents_endpoint import router as case_documents_router
from api.casos_endpoint import router as casos_router
from core.auth import create_jwt


class _FakeCaseDocumentsDB:
    """Fake de `users` (role) + `casos` + `case_documents`."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.casos: dict[str, dict] = {}
        self.case_documents: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "cliente", despacho_id: str = "despacho-1") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role, "despacho_id": despacho_id}
        return self.users[user_id]

    def seed_caso(
        self, *, cliente_id: str, abogado_id: str | None = None, titulo: str = "Caso de prueba",
        despacho_id: str = "despacho-1",
    ) -> dict:
        caso_id = str(uuid.uuid4())
        self.casos[caso_id] = {
            "id": caso_id, "cliente_id": cliente_id, "abogado_id": abogado_id, "despacho_id": despacho_id,
            "titulo": titulo, "descripcion": None, "estado": "abierto",
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return self.casos[caso_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if "SELECT id, email, role, despacho_id FROM users WHERE id" in q:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM casos WHERE id" in q:
            (caso_id,) = args
            c = self.casos.get(caso_id)
            return dict(c) if c else None
        if q.startswith("INSERT INTO case_documents"):
            caso_id, created_by, tarea, pregunta, contenido, pdf_url = args
            doc_id = str(uuid.uuid4())
            documento = {
                "id": doc_id, "caso_id": caso_id, "created_by": created_by, "tarea": tarea,
                "pregunta": pregunta, "contenido": contenido, "pdf_url": pdf_url,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            self.case_documents[doc_id] = documento
            return dict(documento)
        if q.startswith("SELECT") and "FROM case_documents WHERE id" in q:
            (doc_id,) = args
            d = self.case_documents.get(doc_id)
            return dict(d) if d else None
        return None

    async def fetch(self, query: str, *args):
        if "FROM case_documents" in query and "WHERE caso_id" in query:
            (caso_id,) = args
            filas = [d for d in self.case_documents.values() if d["caso_id"] == caso_id]
            filas.sort(key=lambda d: d["created_at"], reverse=True)
            return [{k: v for k, v in f.items() if k != "contenido"} for f in filas]
        return []

    def seed_document(
        self, *, caso_id: str, created_by: str, tarea: str = "tarea", pregunta: str = "pregunta",
        contenido: str = "contenido", pdf_url: str | None = None,
    ) -> dict:
        doc_id = str(uuid.uuid4())
        documento = {
            "id": doc_id, "caso_id": caso_id, "created_by": created_by, "tarea": tarea,
            "pregunta": pregunta, "contenido": contenido, "pdf_url": pdf_url,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.case_documents[doc_id] = documento
        return documento


class _FakeJuliXServiceOK:
    def __init__(self, **kwargs):
        pass

    async def generar_documento(self, **kwargs):
        for fragmento in ["Primero. ", "Segundo."]:
            yield fragmento


@pytest.fixture(autouse=True)
def _fake_julix(monkeypatch):
    """Nunca se llama a Anthropic real: JuliXClient/JuliXService quedan
    reemplazados por fakes — mismo patrón que tests/test_julix_stream.py."""
    monkeypatch.setattr(case_documents_module, "JuliXClient", lambda **kwargs: object())
    monkeypatch.setattr(case_documents_module, "JuliXService", _FakeJuliXServiceOK)


@pytest.fixture
def cd_db():
    return _FakeCaseDocumentsDB()


@pytest.fixture
def cd_client(cd_db):
    app = FastAPI()
    app.include_router(casos_router)
    app.include_router(case_documents_router)
    app.state.db_connection = cd_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_cliente_of_caso_can_create_document(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso1@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    token = _token_de(cliente)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents",
        json={"pregunta": "¿Qué aportes debo declarar a la UGPP?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contenido"] == "Primero. Segundo."
    assert body["caso_id"] == caso["id"]


def test_abogado_asignado_puede_crear_documento(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso2@vridik.local")
    abogado = cd_db.seed_user(email="abogado_caso2@vridik.local", role="abogado")
    caso = cd_db.seed_caso(cliente_id=cliente["id"], abogado_id=abogado["id"])
    token = _token_de(abogado)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text


def test_usuario_sin_relacion_al_caso_forbidden(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso3@vridik.local")
    otro = cd_db.seed_user(email="otro_caso3@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    token = _token_de(otro)

    r = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_puede_listar_y_ver_documento_de_caso(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso4@vridik.local")
    admin = cd_db.seed_user(email="admin_caso4@vridik.local", role="admin")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    cliente_token = _token_de(cliente)
    admin_token = _token_de(admin)

    creado = cd_client.post(
        f"/casos/{caso['id']}/documents", json={"pregunta": "texto"},
        headers={"Authorization": f"Bearer {cliente_token}"},
    ).json()

    r_list = cd_client.get(f"/casos/{caso['id']}/documents", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1
    assert "contenido" not in r_list.json()[0]

    r_get = cd_client.get(
        f"/casos/{caso['id']}/documents/{creado['id']}", headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_get.status_code == 200
    assert r_get.json()["contenido"] == "Primero. Segundo."


def test_caso_not_found_returns_404(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_caso5@vridik.local")
    token = _token_de(cliente)

    r = cd_client.post(
        f"/casos/{uuid.uuid4()}/documents", json={"pregunta": "texto"}, headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET .../pdf -- bug real de producción (15-jul-2026): pdf_url del backend
# local es una ruta de filesystem del contenedor, nunca una URL pública sin
# auth (ver storage/object_storage.py). Esta ruta exige el mismo ownership
# que el resto del router y sirve/redirige según corresponda.
# ---------------------------------------------------------------------------
def test_descargar_pdf_backend_local_sirve_el_archivo(cd_db, cd_client, tmp_path):
    cliente = cd_db.seed_user(email="cliente_pdf1@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    ruta_pdf = tmp_path / "documento.pdf"
    ruta_pdf.write_bytes(b"%PDF-fake-content")
    documento = cd_db.seed_document(caso_id=caso["id"], created_by=cliente["id"], pdf_url=str(ruta_pdf))
    token = _token_de(cliente)

    r = cd_client.get(
        f"/casos/{caso['id']}/documents/{documento['id']}/pdf", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-fake-content"


def test_descargar_pdf_backend_s3_redirige_a_la_url_real(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_pdf2@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    url_s3 = "https://vridik-pdfs.s3.amazonaws.com/documento.pdf?signed=1"
    documento = cd_db.seed_document(caso_id=caso["id"], created_by=cliente["id"], pdf_url=url_s3)
    token = _token_de(cliente)

    r = cd_client.get(
        f"/casos/{caso['id']}/documents/{documento['id']}/pdf",
        headers={"Authorization": f"Bearer {token}"}, follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == url_s3


def test_descargar_pdf_archivo_perdido_por_almacenamiento_efimero_da_404(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_pdf3@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    documento = cd_db.seed_document(
        caso_id=caso["id"], created_by=cliente["id"], pdf_url="/tmp/vridik-pdf-jobs/ya-no-existe.pdf",
    )
    token = _token_de(cliente)

    r = cd_client.get(
        f"/casos/{caso['id']}/documents/{documento['id']}/pdf", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_descargar_pdf_documento_sin_pdf_da_404(cd_db, cd_client):
    cliente = cd_db.seed_user(email="cliente_pdf4@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    documento = cd_db.seed_document(caso_id=caso["id"], created_by=cliente["id"], pdf_url=None)
    token = _token_de(cliente)

    r = cd_client.get(
        f"/casos/{caso['id']}/documents/{documento['id']}/pdf", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_descargar_pdf_usuario_sin_relacion_al_caso_forbidden(cd_db, cd_client, tmp_path):
    cliente = cd_db.seed_user(email="cliente_pdf5@vridik.local")
    otro = cd_db.seed_user(email="otro_pdf5@vridik.local")
    caso = cd_db.seed_caso(cliente_id=cliente["id"])
    ruta_pdf = tmp_path / "documento.pdf"
    ruta_pdf.write_bytes(b"%PDF-fake")
    documento = cd_db.seed_document(caso_id=caso["id"], created_by=cliente["id"], pdf_url=str(ruta_pdf))
    token = _token_de(otro)

    r = cd_client.get(
        f"/casos/{caso['id']}/documents/{documento['id']}/pdf", headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
