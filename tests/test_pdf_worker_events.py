"""
Vridik — tests/test_pdf_worker_events.py
Roadmap Semana 11, Fase D: prueba workers/pdf_worker.py::_notificar_pdf() --
la "prueba de genericidad" del canal SSE (core/events.py) llamada desde un
proceso completamente distinto al servidor web. No prueba el resto de
pdf_worker.py (fuera de alcance de esta fase; no había tests previos de
ese archivo).
"""

from __future__ import annotations

import json

import pytest

from workers.pdf_worker import _notificar_pdf


class _FakeConn:
    def __init__(self, *, falla: bool = False):
        self.llamadas: list[tuple[str, tuple]] = []
        self._falla = falla
        self._siguiente_id = 1

    async def execute(self, query: str, *args):
        self.llamadas.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args):
        if self._falla:
            raise RuntimeError("boom")
        self.llamadas.append((query, args))
        if query.strip().startswith("INSERT INTO user_events"):
            evento_id = self._siguiente_id
            self._siguiente_id += 1
            return {"id": evento_id}
        return None


@pytest.mark.asyncio
async def test_notificar_pdf_ready_arma_payload_con_job_id_y_pdf_url():
    conn = _FakeConn()
    await _notificar_pdf(conn, user_id="user-1", job_id="job-1", tipo="pdf.ready", pdf_url="https://x/y.pdf")

    llamadas_notify = [c for c in conn.llamadas if "pg_notify" in c[0]]
    assert len(llamadas_notify) == 1
    _, (_, cuerpo) = llamadas_notify[0]
    data = json.loads(cuerpo)
    assert data["type"] == "pdf.ready"
    assert data["job_id"] == "job-1"
    assert data["pdf_url"] == "https://x/y.pdf"


@pytest.mark.asyncio
async def test_notificar_pdf_error_no_lleva_pdf_url():
    conn = _FakeConn()
    await _notificar_pdf(conn, user_id="user-1", job_id="job-2", tipo="pdf.error")

    _, (_, cuerpo) = [c for c in conn.llamadas if "pg_notify" in c[0]][0]
    data = json.loads(cuerpo)
    assert data["type"] == "pdf.error"
    assert data["pdf_url"] is None


@pytest.mark.asyncio
async def test_notificar_pdf_sin_user_id_no_hace_nada():
    conn = _FakeConn()
    await _notificar_pdf(conn, user_id=None, job_id="job-3", tipo="pdf.ready", pdf_url="x")
    assert conn.llamadas == []


@pytest.mark.asyncio
async def test_notificar_pdf_nunca_propaga_el_error_de_notificar_evento():
    """user_id no-UUID (legacy) haría fallar el INSERT en user_events (columna
    UUID) -- _notificar_pdf debe tragarse eso, nunca dejar el job a medias."""
    conn = _FakeConn(falla=True)
    await _notificar_pdf(conn, user_id="no-es-un-uuid", job_id="job-4", tipo="pdf.ready", pdf_url="x")
    # No lanzó -- eso es lo que se prueba acá.
