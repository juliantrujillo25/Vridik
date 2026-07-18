"""
Vridik — tests/test_corpus_endpoint.py
api/corpus_endpoint.py end-to-end (FastAPI TestClient) sobre un fake mínimo:
solo el gate de autorización (get_current_superadmin), igual que
tests/test_platform_endpoint.py -- la lógica real de corpus_drafts (CRUD,
validaciones, publicación) está probada contra Postgres real en
tests/test_corpus_curation.py, no acá.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.corpus_endpoint import router as corpus_router
from core.auth import create_jwt


class _FakeCorpusDB:
    def __init__(self):
        self.users: dict[str, dict] = {}

    def seed_user(self, *, role: str = "cliente", totp_enabled: bool = True, es_superadmin: bool = False) -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id, "email": f"{user_id}@vridik.local", "role": role,
            "totp_enabled": totp_enabled, "despacho_id": str(uuid.uuid4()), "es_superadmin": es_superadmin,
        }
        return self.users[user_id]

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        q = query.strip()
        if q == "SELECT id, email, role, despacho_id, es_superadmin FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if q == "SELECT totp_enabled FROM users WHERE id = $1":
            (user_id,) = args
            u = self.users.get(user_id)
            return {"totp_enabled": u["totp_enabled"]} if u else None
        return None

    async def fetch(self, query: str, *args):
        return []


@pytest.fixture
def cdb():
    return _FakeCorpusDB()


@pytest.fixture
def cclient(cdb):
    app = FastAPI()
    app.include_router(corpus_router)
    app.state.db_connection = cdb
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def test_sin_token_da_401(cclient):
    r = cclient.get("/platform/corpus/borradores")
    assert r.status_code == 401


def test_admin_de_despacho_no_alcanza_para_listar_borradores(cdb, cclient):
    admin = cdb.seed_user(role="admin")
    r = cclient.get("/platform/corpus/borradores", headers={"Authorization": f"Bearer {_token_de(admin)}"})
    assert r.status_code == 403


def test_admin_de_despacho_no_alcanza_para_crear_borrador(cdb, cclient):
    admin = cdb.seed_user(role="admin")
    r = cclient.post(
        "/platform/corpus/borradores",
        json={"nombre_fuente": "x.pdf", "texto": "contenido"},
        headers={"Authorization": f"Bearer {_token_de(admin)}"},
    )
    assert r.status_code == 403


def test_superadmin_sin_2fa_rechazado(cdb, cclient):
    superadmin = cdb.seed_user(es_superadmin=True, totp_enabled=False)
    r = cclient.get("/platform/corpus/borradores", headers={"Authorization": f"Bearer {_token_de(superadmin)}"})
    assert r.status_code == 403
    assert "2FA" in r.json()["detail"]


def test_superadmin_alcanza_el_gate_y_llega_a_listar(cdb, cclient):
    """No prueba el contenido de la lista (eso es tests/test_corpus_curation.py
    contra Postgres real) -- solo que el gate de autorización deja pasar a
    un superadmin con 2FA activo hasta la lógica real."""
    superadmin = cdb.seed_user(es_superadmin=True)
    r = cclient.get("/platform/corpus/borradores", headers={"Authorization": f"Bearer {_token_de(superadmin)}"})
    assert r.status_code == 200
    assert r.json() == []


def test_extraer_pdf_rechaza_extension_no_pdf(cdb, cclient):
    superadmin = cdb.seed_user(es_superadmin=True)
    r = cclient.post(
        "/platform/corpus/extraer-pdf",
        files={"archivo": ("documento.txt", b"contenido", "text/plain")},
        headers={"Authorization": f"Bearer {_token_de(superadmin)}"},
    )
    assert r.status_code == 422
