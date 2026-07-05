"""
Vridik — tests/test_generador.py (Sprint S3)
8 tests: plantilla UGPP, fuente, justificado.

Usa FakeGeneradorService (ver tests/support/fakes.py): contrato estable hoy
(Generador Word 75%, deuda 'sin PDF' que resuelve S10). Estos tests validan
la parte docx; S10 agrega su propia suite para PDF (fuentes embebidas,
páginas, metadatos).
"""

from __future__ import annotations

import pytest

from tests.support.fakes import FakeGeneradorService


@pytest.fixture
def generador():
    return FakeGeneradorService()


# 1. Render básico de plantilla UGPP
def test_render_plantilla_ugpp_requerimiento(generador):
    doc = generador.renderizar(
        plantilla="ugpp_requerimiento", fuente="Arial", justificado=True,
        variables={"radicado": "2026-UGPP-001", "cliente": "Empresa X"},
    )
    assert doc["plantilla"] == "ugpp_requerimiento"
    assert "2026-UGPP-001" in doc["cuerpo"]


# 2. Render de plantilla UGPP alterna (recurso)
def test_render_plantilla_ugpp_recurso(generador):
    doc = generador.renderizar(
        plantilla="ugpp_recurso", fuente="Times New Roman", justificado=True,
        variables={"radicado": "2026-UGPP-002"},
    )
    assert doc["plantilla"] == "ugpp_recurso"


# 3. Plantilla desconocida levanta error explícito (nunca silencioso)
def test_plantilla_desconocida_levanta_error(generador):
    with pytest.raises(ValueError, match="Plantilla desconocida"):
        generador.renderizar(plantilla="no_existe", fuente="Arial", justificado=True, variables={})


# 4. Fuente configurable: Arial
def test_fuente_configurable_arial(generador):
    doc = generador.renderizar(plantilla="laboral_generico", fuente="Arial", justificado=False, variables={})
    assert doc["fuente"] == "Arial"


# 5. Fuente configurable: Calibri
def test_fuente_configurable_calibri(generador):
    doc = generador.renderizar(plantilla="laboral_generico", fuente="Calibri", justificado=False, variables={})
    assert doc["fuente"] == "Calibri"


# 6. Fuente no soportada levanta error explícito
def test_fuente_no_soportada_levanta_error(generador):
    with pytest.raises(ValueError, match="Fuente no soportada"):
        generador.renderizar(plantilla="laboral_generico", fuente="ComicSans", justificado=False, variables={})


# 7. Justificado activado se refleja en el documento generado
def test_justificado_activado(generador):
    doc = generador.renderizar(plantilla="laboral_generico", fuente="Arial", justificado=True, variables={})
    assert doc["justificado"] is True


# 8. El documento generado hoy es siempre docx (PDF es deuda de S10, no de S3)
def test_formato_actual_es_docx_pdf_pendiente_s10(generador):
    doc = generador.renderizar(plantilla="laboral_generico", fuente="Arial", justificado=False, variables={})
    assert doc["formato"] == "docx"
