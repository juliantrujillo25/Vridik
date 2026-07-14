"""
Vridik — tests/test_calendario_judicial.py
procesal/calendario_judicial.py: motor de cálculo de términos procesales
sobre el calendario judicial colombiano (festivos + vacancia judicial).
Las fechas de referencia (día de la semana de cada fecha usada abajo) se
verificaron con `datetime.date.strftime('%A')` antes de escribir el test,
no a mano -- ver el docstring del módulo para las fuentes de los festivos
y las ventanas de vacancia judicial.
"""

from __future__ import annotations

from datetime import date

import pytest

from procesal.calendario_judicial import (
    es_dia_habil,
    es_festivo,
    es_vacancia_judicial,
    sumar_dias_habiles,
    vacancia_fin_de_ano_pendiente_de_anuncio,
)


def test_es_festivo_reconoce_fechas_fijas_y_moviles():
    assert es_festivo(date(2026, 12, 25)) is True   # Navidad, fijo
    assert es_festivo(date(2026, 7, 20)) is True     # Independencia, fijo
    assert es_festivo(date(2026, 1, 12)) is True     # Reyes Magos, móvil a lunes
    assert es_festivo(date(2027, 6, 7)) is True      # Sagrado Corazón 2027, móvil
    assert es_festivo(date(2026, 2, 2)) is False


def test_es_vacancia_judicial_reconoce_las_dos_ventanas_confirmadas():
    assert es_vacancia_judicial(date(2026, 1, 5)) is True    # dentro de fin de año 2025-2026
    assert es_vacancia_judicial(date(2025, 12, 20)) is True  # primer día de esa ventana
    assert es_vacancia_judicial(date(2026, 1, 10)) is True   # último día de esa ventana
    assert es_vacancia_judicial(date(2026, 1, 13)) is False  # ya se retomaron labores
    assert es_vacancia_judicial(date(2026, 3, 30)) is True   # dentro de Semana Santa 2026
    assert es_vacancia_judicial(date(2026, 6, 15)) is False


def test_es_dia_habil_descarta_fin_de_semana_festivo_y_vacancia():
    assert es_dia_habil(date(2026, 2, 2)) is True    # lunes normal
    assert es_dia_habil(date(2026, 2, 7)) is False    # sábado
    assert es_dia_habil(date(2026, 2, 8)) is False    # domingo
    assert es_dia_habil(date(2026, 7, 20)) is False   # festivo (lunes)
    assert es_dia_habil(date(2026, 1, 5)) is False    # vacancia judicial


def test_sumar_dias_habiles_caso_simple_sin_obstaculos():
    # Lunes 2026-02-02 + 3 hábiles, sin festivos/vacancia cerca -> jueves.
    resultado = sumar_dias_habiles(date(2026, 2, 2), 3)
    assert resultado.fecha_vencimiento == date(2026, 2, 5)
    assert resultado.dias_no_habiles_saltados == []
    assert resultado.incluye_ventana_sin_confirmar is False


def test_sumar_dias_habiles_salta_fin_de_semana():
    # Viernes 2026-02-06 + 1 hábil -> lunes 2026-02-09 (salta sáb/dom).
    resultado = sumar_dias_habiles(date(2026, 2, 6), 1)
    assert resultado.fecha_vencimiento == date(2026, 2, 9)
    assert resultado.dias_no_habiles_saltados == [date(2026, 2, 7), date(2026, 2, 8)]


def test_sumar_dias_habiles_salta_fin_de_semana_y_festivo_juntos():
    # Viernes 2026-07-17 + 1 hábil -> salta sáb 18, dom 19, festivo (lunes) 20 -> martes 21.
    resultado = sumar_dias_habiles(date(2026, 7, 17), 1)
    assert resultado.fecha_vencimiento == date(2026, 7, 21)
    assert resultado.dias_no_habiles_saltados == [date(2026, 7, 18), date(2026, 7, 19), date(2026, 7, 20)]


def test_sumar_dias_habiles_salta_vacancia_fin_de_ano_completa():
    # Lunes 2026-01-05 (ya dentro de la vacancia) + 1 hábil: saltan el
    # resto de la vacancia (6-10 ene), el fin de semana (11) y el festivo
    # de Reyes Magos (12, lunes) -> primer día hábil real es 2026-01-13.
    resultado = sumar_dias_habiles(date(2026, 1, 5), 1)
    assert resultado.fecha_vencimiento == date(2026, 1, 13)
    assert resultado.dias_no_habiles_saltados == [
        date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9),
        date(2026, 1, 10), date(2026, 1, 11), date(2026, 1, 12),
    ]
    assert resultado.incluye_ventana_sin_confirmar is False


def test_sumar_dias_habiles_rechaza_cantidad_no_positiva():
    with pytest.raises(ValueError):
        sumar_dias_habiles(date(2026, 2, 2), 0)
    with pytest.raises(ValueError):
        sumar_dias_habiles(date(2026, 2, 2), -1)


def test_vacancia_fin_de_ano_pendiente_de_anuncio_marca_la_ventana_sin_confirmar():
    assert vacancia_fin_de_ano_pendiente_de_anuncio(date(2026, 12, 24)) is True
    assert vacancia_fin_de_ano_pendiente_de_anuncio(date(2027, 1, 12)) is True
    assert vacancia_fin_de_ano_pendiente_de_anuncio(date(2026, 12, 10)) is False
    assert vacancia_fin_de_ano_pendiente_de_anuncio(date(2027, 1, 20)) is False
    assert vacancia_fin_de_ano_pendiente_de_anuncio(date(2026, 7, 1)) is False


def test_sumar_dias_habiles_avisa_cuando_cruza_la_ventana_de_fin_de_ano_2026_2027_sin_confirmar():
    """La vacancia de fin de año 2026-2027 todavía no está anunciada
    (ver docstring del módulo) -- el resultado mecánico solo cuenta
    festivo/fin de semana en esa ventana, pero debe avisar que puede
    estar mal apenas se anuncie la vacancia real."""
    # Jueves 2026-12-24 + 1 hábil: salta Navidad (vier 25), sáb 26, dom 27 -> lunes 28.
    resultado = sumar_dias_habiles(date(2026, 12, 24), 1)
    assert resultado.fecha_vencimiento == date(2026, 12, 28)
    assert resultado.incluye_ventana_sin_confirmar is True
