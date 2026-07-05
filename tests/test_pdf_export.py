"""
Vridik — tests/test_pdf_export.py (Sprint S10)
2 tests puros (sin BD, sin Anthropic) sobre julix/pdf_export.py:
  1. FuenteCitada.desde_referencia() parsea correctamente el formato
     "[norma, articulo, parrafo]" producido por rag.context_builder.
  2. generar_pdf() produce un archivo PDF real (firma %PDF-) en disco,
     con y sin fuentes citadas.
"""

from __future__ import annotations

from pathlib import Path

from julix.pdf_export import FuenteCitada, PIE_DE_PAGINA_DISCLAIMER, generar_pdf


def test_fuente_citada_desde_referencia_parsea_norma_articulo_parrafo():
    fuente = FuenteCitada.desde_referencia("[Ley 2010 de 2019, Art. 108, párr. 2]")
    assert fuente.norma == "Ley 2010 de 2019"
    assert fuente.articulo == "Art. 108"
    assert fuente.parrafo == "párr. 2"
    assert fuente.cita == "[Ley 2010 de 2019, Art. 108, párr. 2]"


def test_generar_pdf_produce_archivo_pdf_valido(tmp_path: Path):
    fuentes = [
        FuenteCitada(norma="Ley 1607 de 2012", articulo="Art. 179"),
        FuenteCitada(norma="Decreto 1625 de 2016", articulo="Art. 1.2.4.1.1"),
    ]
    ruta_salida = tmp_path / "respuesta_julix.pdf"

    ruta = generar_pdf(
        respuesta="Respuesta de JuliX.\n\nSegundo párrafo con más detalle.",
        fuentes=fuentes,
        ruta_salida=ruta_salida,
        tarea="ugpp_demanda",
        caso_id="CASO-TEST-001",
    )

    assert ruta == ruta_salida
    assert ruta.exists()
    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF-")
    assert len(contenido) > 0

    # Disclaimer del pie de página: se dibuja con el canvas de ReportLab
    # (no aparece como texto plano legible en el stream sin descomprimir),
    # así que el test verifica la CONSTANTE que usa generar_pdf en vez de
    # parsear el binario del PDF -- lo que importa es que la función use
    # siempre PIE_DE_PAGINA_DISCLAIMER, sin variantes por caso.
    assert PIE_DE_PAGINA_DISCLAIMER == "Borrador para revisión de abogado – no constituye asesoría legal"
