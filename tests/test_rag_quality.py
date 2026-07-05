"""
Vridik — tests/test_rag_quality.py (Sprint S8)
3 tests puros (sin BD, sin Anthropic) sobre rag/quality_gate.py:
  1. Un chunk válido (norma+articulo presentes, texto largo, con cita) se acepta.
  2. Un chunk con texto < 100 caracteres se rechaza con el motivo correcto.
  3. generar_reporte() agrega correctamente accept/reject y porcentaje sobre
     una mezcla de chunks válidos e inválidos.
"""

from __future__ import annotations

from rag.quality_gate import ChunkEvaluable, evaluar_chunk, generar_reporte


def test_chunk_valido_es_aceptado():
    chunk = ChunkEvaluable(
        norma="Ley 1607 de 2012",
        articulo="Art. 178",
        texto=(
            "El artículo 178 de la Ley 1607 de 2012 establece las sanciones "
            "aplicables por inexactitud en el reporte de aportes a la UGPP, "
            "incluyendo el procedimiento de determinación oficial."
        ),
        identificador="chunk-valido-001",
    )
    resultado = evaluar_chunk(chunk)
    assert resultado.aceptado is True
    assert resultado.motivos_rechazo == []


def test_chunk_corto_es_rechazado_por_longitud():
    chunk = ChunkEvaluable(
        norma="Ley 1607 de 2012",
        articulo="Art. 178",
        texto="Texto muy corto.",
        identificador="chunk-corto-001",
    )
    resultado = evaluar_chunk(chunk)
    assert resultado.aceptado is False
    assert any("100 caracteres" in motivo for motivo in resultado.motivos_rechazo)


def test_generar_reporte_agrega_aceptados_y_rechazados():
    valido = ChunkEvaluable(
        norma="Decreto 1625 de 2016",
        articulo="Art. 1.2.4.1.1",
        texto=(
            "El Decreto 1625 de 2016, artículo 1.2.4.1.1, regula el ingreso "
            "base de cotización para los trabajadores independientes frente "
            "a la UGPP y su procedimiento de fiscalización."
        ),
    )
    sin_cita = ChunkEvaluable(norma="Ley X", articulo="Art. 1", texto="y" * 150)
    sin_metadata = ChunkEvaluable(norma="", articulo="", texto="z" * 150)

    reporte = generar_reporte([valido, sin_cita, sin_metadata])

    assert reporte.total == 3
    assert reporte.aceptados == 1
    assert reporte.rechazados == 2
    assert reporte.porcentaje_aceptacion == round(100 / 3, 1)
    assert len(reporte.detalle_rechazados) == 2
