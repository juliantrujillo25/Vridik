"""
Vridik — tests/test_panel.py (Sprint S3)
5 tests: KPIs, vencimientos.

Usa FakePanelService (ver tests/support/fakes.py): contrato de KPIs del
Panel Vridik Pro (Estado Actual: 90%, deuda 'vencimientos manuales, no
calculados'). El motor de términos calculados llega en Fase 2; estos tests
validan que el panel distingue explícitamente manual vs calculado ya desde
S3, para que Fase 2 solo tenga que subir el porcentaje calculado, no cambiar
el contrato.
"""

from __future__ import annotations

from tests.support.fakes import FakePanelService


def _panel():
    return FakePanelService()


# 1. KPIs básicos con datos normales
def test_kpis_basicos():
    panel = _panel()
    resultado = panel.kpis(casos_activos=10, casos_con_vencimiento_manual=8, casos_con_vencimiento_calculado=2)
    assert resultado["casos_activos"] == 10
    assert resultado["vencimientos_manuales"] == 8
    assert resultado["vencimientos_calculados"] == 2


# 2. Porcentaje calculado se computa correctamente
def test_porcentaje_calculado_correcto():
    panel = _panel()
    resultado = panel.kpis(casos_activos=20, casos_con_vencimiento_manual=15, casos_con_vencimiento_calculado=5)
    assert resultado["porcentaje_calculado"] == 25.0


# 3. Sin casos activos: no debe lanzar ZeroDivisionError (panel vacío honesto)
def test_kpis_sin_casos_activos_no_falla():
    panel = _panel()
    resultado = panel.kpis(casos_activos=0, casos_con_vencimiento_manual=0, casos_con_vencimiento_calculado=0)
    assert resultado["porcentaje_calculado"] == 0.0


# 4. Hoy (Fase 1, pre motor de términos) casi todos los vencimientos son manuales
def test_estado_actual_mayoria_vencimientos_manuales():
    panel = _panel()
    resultado = panel.kpis(casos_activos=12, casos_con_vencimiento_manual=12, casos_con_vencimiento_calculado=0)
    assert resultado["vencimientos_calculados"] == 0
    assert resultado["porcentaje_calculado"] == 0.0


# 5. Todos calculados (escenario objetivo de Fase 2, motor de términos completo)
def test_escenario_objetivo_fase2_todos_calculados():
    panel = _panel()
    resultado = panel.kpis(casos_activos=8, casos_con_vencimiento_manual=0, casos_con_vencimiento_calculado=8)
    assert resultado["porcentaje_calculado"] == 100.0
