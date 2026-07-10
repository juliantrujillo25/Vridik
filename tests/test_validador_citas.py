"""
Vridik / JuliX — tests/test_validador_citas.py (S7-GAP-01)
Prueba julix.service.validar_citas_post_generacion() de forma aislada
(función pura, sin red ni Anthropic real): dado un texto de respuesta y
las referencias citables que JuliX tuvo disponibles como contexto
(BuiltContext.chunks_incluidos, ya `list[str]` -- ver
julix/context_builder.py), verifica que toda cita de norma/artículo
detectada por regex tenga respaldo en al menos una de esas referencias.
"""

from __future__ import annotations

from julix.service import validar_citas_post_generacion


def test_cita_respaldada_no_se_marca():
    referencias = ["Art. 33 CST"]
    respuesta = "Según el Artículo 33, el trabajador tiene derecho a..."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert resultado == respuesta
    assert "[revisar]" not in resultado


def test_cita_sin_respaldo_se_marca_revisar():
    referencias = ["Art. 33 CST"]
    respuesta = "Según la Ley 1607 de 2012, el aporte a seguridad social..."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert "[revisar]" in resultado
    assert "ley 1607 de 2012" in resultado.lower()


def test_sin_citas_detectadas_no_se_marca():
    referencias = ["Art. 33 CST"]
    respuesta = "No tengo fuente suficiente."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert resultado == respuesta
    assert "[revisar]" not in resultado


def test_multiples_citas_una_sin_respaldo_se_marca():
    referencias = ["Ley 1607 de 2012"]
    respuesta = "Aplica la Ley 1607 de 2012 y también el Decreto 1625 de 2016."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert "[revisar]" in resultado
    assert "decreto 1625 de 2016" in resultado.lower()
    # La cita SÍ respaldada no debe aparecer listada como pendiente de revisar.
    marcador = resultado.split("[revisar]")[1]
    assert "ley 1607 de 2012" not in marcador.lower()


def test_sin_referencias_disponibles_toda_cita_se_marca():
    respuesta = "Según el Artículo 33..."

    resultado = validar_citas_post_generacion(respuesta, [])

    assert "[revisar]" in resultado


def test_cita_case_insensitive_y_variantes_de_articulo():
    referencias = ["Artículo 179 del CST"]
    respuesta = "El art. 179 establece que..."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert "[revisar]" not in resultado


def test_referencia_combinada_norma_y_articulo():
    """BuiltContext.chunks_incluidos combina norma+artículo en una sola
    referencia por chunk (ver julix/context_builder.py:
    RankedChunk.referencia via rag_a_ranked_chunks) -- una sola entrada
    debe respaldar ambas citas si el texto las trae juntas."""
    referencias = ["Ley 1607 de 2012, Art. 179"]
    respuesta = "La sanción aplicable es del 160%, según el Art. 179 de la Ley 1607 de 2012."

    resultado = validar_citas_post_generacion(respuesta, referencias)

    assert resultado == respuesta
    assert "[revisar]" not in resultado
