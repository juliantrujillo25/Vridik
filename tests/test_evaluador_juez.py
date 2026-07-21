"""
Vridik — tests/test_evaluador_juez.py
Regresión del juez del banco de evaluación (S5), a partir del falso
positivo real UGPP-07 (corrida s5 del 16-jul-2026): el juez marcó
hallucination_flag=true por el Decreto 379/2026, que SÍ estaba en la
norma_clave entregada. La reclasificación fue manual (commit e1db508);
estos tests fijan las dos defensas que quedaron para que nadie las
revierta sin enterarse:

1. El bloque de "chequeo mecánico" del JUEZ_SYSTEM_PROMPT (instrucción
   al juez de verificar literalmente contra norma_clave antes de marcar
   alucinación).
2. `contrastar_flag_con_norma_clave()` — el contraste determinístico por
   regex (reusa julix.service._claves_citables) que anota
   `flag_cuestionado` cuando el juez marca alucinación pero todas las
   citas detectables están respaldadas. Nunca voltea el flag en
   silencio: solo anota para revisión humana.

Ningún test llama a Claude ni a PostgreSQL reales (regla del proyecto).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.evaluador import (  # noqa: E402
    JUEZ_SYSTEM_PROMPT,
    calificar_con_juez,
    contrastar_flag_con_norma_clave,
)

NORMA_CLAVE_UGPP07 = (
    "Decreto 379 de 2026, Artículo 12: los aportes al sistema de "
    "protección social se liquidarán sobre el ingreso base de cotización..."
)


# ---------------------------------------------------------------------------
# 1. El prompt del juez conserva el chequeo mecánico (fix del 16-jul-2026)
# ---------------------------------------------------------------------------

def test_juez_system_prompt_conserva_chequeo_mecanico_ugpp07():
    """Si alguien 'simplifica' el prompt del juez y borra el bloque del
    chequeo mecánico, el patrón UGPP-07 (falso positivo por norma que SÍ
    está en norma_clave) vuelve. Este test lo hace ruidoso."""
    assert "chequeo mecánico" in JUEZ_SYSTEM_PROMPT
    assert "texto de \"norma_clave\"" in JUEZ_SYSTEM_PROMPT
    assert "NO la inventó" in JUEZ_SYSTEM_PROMPT


def test_juez_system_prompt_mantiene_regla_alucinacion_score_1():
    assert "NUNCA puede ser mayor a 1" in JUEZ_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 2. Contraste mecánico del flag (regresión UGPP-07 exacta)
# ---------------------------------------------------------------------------

def test_regresion_ugpp07_flag_por_norma_respaldada_queda_cuestionado():
    """El escenario UGPP-07 literal: JuliX cita el Decreto 379 de 2026,
    la norma_clave LO CONTIENE, y aun así el juez marca alucinación.
    El contraste debe anotar flag_cuestionado=True y dejar rastro en el
    comentario — sin voltear el flag."""
    respuesta = (
        "Conforme al Decreto 379 de 2026, artículo 12, la liquidación de "
        "aportes procede sobre el ingreso base de cotización."
    )
    veredicto = {
        "score": 1, "precision_normativa": 1, "cita_correcta": False,
        "hallucination_flag": True,
        "comentario": "Cita el Decreto 379/2026, posiblemente inexistente.",
    }
    resultado = contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)

    assert resultado["flag_cuestionado"] is True
    assert resultado["hallucination_flag"] is True, "el flag NUNCA se voltea en silencio"
    assert "[flag_cuestionado]" in resultado["comentario"]
    assert "UGPP-07" in resultado["comentario"]


def test_flag_por_norma_realmente_ajena_no_se_cuestiona():
    """Si JuliX cita una norma que NO está en la norma_clave, el flag del
    juez es plausible y el contraste no lo cuestiona."""
    respuesta = "Según la Ley 9999 de 2030, artículo 1, procede la sanción."
    veredicto = {"score": 1, "hallucination_flag": True, "comentario": "Norma inventada."}
    resultado = contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)

    assert resultado["flag_cuestionado"] is False
    assert resultado["hallucination_flag"] is True
    assert "[flag_cuestionado]" not in resultado["comentario"]


def test_flag_con_mezcla_de_citas_respaldadas_y_ajenas_no_se_cuestiona():
    """Basta UNA cita sin respaldo para que el flag del juez sea plausible:
    el contraste solo cuestiona cuando TODAS las citas están respaldadas."""
    respuesta = (
        "El Decreto 379 de 2026 y la Ley 9999 de 2030 ordenan la liquidación."
    )
    veredicto = {"score": 1, "hallucination_flag": True, "comentario": ""}
    resultado = contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)

    assert resultado["flag_cuestionado"] is False


def test_sin_flag_no_se_toca_nada():
    respuesta = "Conforme al Decreto 379 de 2026 procede la liquidación."
    veredicto = {"score": 5, "hallucination_flag": False, "comentario": "Correcta."}
    resultado = contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)

    assert resultado["flag_cuestionado"] is False
    assert resultado["comentario"] == "Correcta."
    assert resultado["score"] == 5


def test_flag_sin_citas_detectables_queda_como_esta():
    """Una alucinación de cifras/plazos (sin cita de norma detectable por
    regex) no es contrastable mecánicamente: el veredicto del juez manda."""
    respuesta = "El plazo es de 45 días hábiles y la sanción del 60%."
    veredicto = {"score": 1, "hallucination_flag": True, "comentario": "Plazo inventado."}
    resultado = contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)

    assert resultado["flag_cuestionado"] is False
    assert resultado["hallucination_flag"] is True


def test_contraste_no_muta_el_veredicto_original():
    respuesta = "Conforme al Decreto 379 de 2026 procede."
    veredicto = {"score": 1, "hallucination_flag": True, "comentario": "X."}
    contrastar_flag_con_norma_clave(respuesta, NORMA_CLAVE_UGPP07, veredicto)
    assert "flag_cuestionado" not in veredicto, "debe operar sobre una copia"


# ---------------------------------------------------------------------------
# 3. El juez sigue siendo fail-closed (nunca aprobación silenciosa)
# ---------------------------------------------------------------------------

class _FakeClientJuezRoto:
    """Simula un juez cuya salida no es JSON válido."""

    async def stream_completion(self, **kwargs):
        yield "esto no es json"

    @staticmethod
    def validar_json(texto):
        from julix.client import JuliXClient
        return JuliXClient.validar_json(texto)


class _CasoStub:
    id = "UGPP-07"
    area = "UGPP"
    pregunta = "¿Procede la liquidación?"
    respuesta_esperada = "Sí, conforme al Decreto 379 de 2026."
    norma_clave = NORMA_CLAVE_UGPP07
    dificultad = 3


@pytest.mark.asyncio
async def test_salida_del_juez_invalida_nunca_aprueba():
    resultado = await calificar_con_juez(_FakeClientJuezRoto(), _CasoStub(), "respuesta")
    assert resultado["score"] == 0
    assert resultado["hallucination_flag"] is True


class _FakeClientJuezIntermitente:
    """Simula el ruido real encontrado el 21-jul corriendo T3 contra
    producción: el mismo input a veces devuelve JSON inválido y a veces
    válido -- reintentar antes de aplicar el fallback punitivo evita que
    ese ruido de formato se cuente como si JuliX hubiera alucinado."""

    def __init__(self, fallos_antes_de_ok: int):
        self.fallos_antes_de_ok = fallos_antes_de_ok
        self.llamadas = 0

    async def stream_completion(self, **kwargs):
        self.llamadas += 1
        if self.llamadas <= self.fallos_antes_de_ok:
            yield "esto no es json"
        else:
            yield '{"score": 3, "precision_normativa": 3, "cita_correcta": true, "hallucination_flag": false, "comentario": "ok"}'

    @staticmethod
    def validar_json(texto):
        from julix.client import JuliXClient
        return JuliXClient.validar_json(texto)


@pytest.mark.asyncio
async def test_reintenta_cuando_la_salida_del_juez_es_intermitente():
    """Regresión real (21-jul, T3 contra producción): re-enviar el MISMO
    input al juez a veces produce JSON inválido y a veces válido -- no es
    un bug determinístico de un caso puntual. Sin reintento, ~15% de los
    casos del banco caían al fallback punitivo solo por este ruido."""
    fake = _FakeClientJuezIntermitente(fallos_antes_de_ok=1)
    resultado = await calificar_con_juez(fake, _CasoStub(), "respuesta")
    assert fake.llamadas == 2
    assert resultado["score"] == 3
    assert resultado["hallucination_flag"] is False


@pytest.mark.asyncio
async def test_fallback_punitivo_solo_tras_agotar_los_reintentos():
    """Si el ruido persiste más allá de los reintentos configurados, el
    fail-closed de siempre sigue aplicando -- el reintento no vuelve
    permisivo al juez, solo lo hace tolerante a ruido transitorio."""
    fake = _FakeClientJuezIntermitente(fallos_antes_de_ok=99)
    resultado = await calificar_con_juez(fake, _CasoStub(), "respuesta")
    assert resultado["score"] == 0
    assert resultado["hallucination_flag"] is True
