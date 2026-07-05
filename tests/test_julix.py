"""
Vridik — tests/test_julix.py (Sprint S3, actualizado en S4 semana 4-6 y S6)
9 tests: context_builder, prompts versionados, ledger (costo + registro),
client.py end-to-end con el SDK de Anthropic mockeado, y (S6) la inyección
de contexto RAG en julix/service.py.

Actualización S4: JuliXClient ya NO se sustituye reemplazando
`stream_completion` completo (eso saltaba retry/timeout/ledger, que ahora
viven dentro del propio client). En su lugar se mockea únicamente
`_abrir_stream_sdk` — el único punto que toca el SDK real — vía
FakeSDKStream/FakeSDKStreamFactory (tests/support/fakes.py). Así el test
ejercita de verdad la lógica de retry, timeout y registro en julix_calls,
sin llamar nunca a Anthropic. ANTHROPIC_API_KEY se mockea en
tests/conftest.py (fixture autouse `_env_base`).

Actualización S6: dos tests nuevos verifican que julix/service.py (a) NUNCA
llama a rag_buscar_contexto explícito si no hay chunks, sino que recupera
contexto real vía RAG, y (b) cuando el RAG no encuentra nada, la directiva
de fuente obligatoria llega al system_prompt del SDK (mockeado) — no se
verifica que Claude "obedezca" la instrucción (eso lo mide el banco de S5),
solo que la señal llega correctamente construida hasta el SDK.
"""

from __future__ import annotations

import pytest

import julix.service as julix_service_module
from julix import prompts
from julix.client import JuliXClient
from julix.context_builder import (
    ContextBudget,
    RankedChunk,
    construir_contexto,
    ordenar_por_prioridad_normativa,
    truncar_con_criterio,
)
from julix.ledger import JuliXCallRecord, calcular_costo_usd, registrar_llamada
from julix.service import JuliXService
from rag.context_builder import ChunkRecuperado
from tests.support.fakes import FakeLedgerDB, FakeSDKStream, FakeSDKStreamFactory


# ---------------------------------------------------------------------------
# context_builder
# ---------------------------------------------------------------------------
def test_context_builder_ordena_por_jerarquia_y_vigencia():
    chunks = [
        RankedChunk(referencia="Art. 10 Decreto X", jerarquia=3, vigente=True, tokens=100, contenido="..."),
        RankedChunk(referencia="Art. 1 Constitución", jerarquia=1, vigente=True, tokens=100, contenido="..."),
        RankedChunk(referencia="Art. 5 Ley derogada", jerarquia=2, vigente=False, tokens=100, contenido="..."),
    ]
    ordenados = ordenar_por_prioridad_normativa(chunks)
    assert ordenados[0].referencia == "Art. 1 Constitución"  # vigente + mayor jerarquía
    assert ordenados[-1].referencia == "Art. 5 Ley derogada"  # derogado siempre al final


def test_context_builder_trunca_respetando_presupuesto():
    chunks = [
        RankedChunk(referencia=f"Art. {i}", jerarquia=2, vigente=True, tokens=1000, contenido="x")
        for i in range(5)
    ]
    seleccionados = truncar_con_criterio(chunks, presupuesto_tokens=2500)
    assert len(seleccionados) == 2  # 2*1000 cabe, el tercero (3000) no
    assert sum(c.tokens for c in seleccionados) <= 2500


# ---------------------------------------------------------------------------
# prompts versionados (S4 semana 4-6: loader ya no depende del nombre de archivo)
# ---------------------------------------------------------------------------
def test_prompts_carga_ugpp_demanda_con_prioridad_normativa():
    prompt = prompts.load_prompt("ugpp_demanda")
    assert prompt.version == 1
    assert prompt.archivo == "v1_ugpp_demanda.md"
    assert "jerarquía kelseniana" in prompt.contenido.lower() or "jerarquia" in prompt.contenido.lower()
    assert len(prompt.hash) == 16


def test_prompts_carga_laboral_consulta_enfocado_en_cst():
    prompt = prompts.load_prompt("laboral_consulta")
    assert prompt.tarea == "laboral_consulta"
    assert prompt.archivo == "v2_laboral_consulta.md"
    assert "CST" in prompt.contenido


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
def test_ledger_calcula_costo_usd_con_tabla_de_precios_2026():
    costo_sonnet4 = calcular_costo_usd("claude-sonnet-5-20250624", input_tokens=1000, output_tokens=500)
    costo_haiku = calcular_costo_usd("claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500)
    assert costo_sonnet4 > 0
    assert costo_haiku < costo_sonnet4  # Haiku es el modelo barato de clasificación


@pytest.mark.asyncio
async def test_ledger_registra_llamada_en_bd():
    db = FakeLedgerDB()
    record = JuliXCallRecord(
        user_id="julian", caso_id="caso-1", tarea="ugpp_demanda", model="claude-sonnet-5-20250624",
        prompt_version=1, prompt_hash="abc1234567890def", input_tokens=1000, output_tokens=300,
        latency_ms=1200, status="ok", environment="staging",
    )
    await registrar_llamada(db, record)
    assert len(db.llamadas_registradas) == 1
    query, args = db.llamadas_registradas[0]
    assert "INSERT INTO julix_calls" in query
    assert "ugpp_demanda" in args


# ---------------------------------------------------------------------------
# client.py end-to-end con el SDK de Anthropic mockeado (nunca Claude real)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_stream_completion_exitoso_registra_ledger(monkeypatch):
    monkeypatch.setenv("USE_POSTGRES", "false")
    db = FakeLedgerDB()
    client = JuliXClient(environment="staging", db_connection=db)
    factory = FakeSDKStreamFactory(FakeSDKStream(["Hechos: ", "el caso trata de...", " Fin del borrador."]))
    client._abrir_stream_sdk = factory

    texto = ""
    async for chunk in client.stream_completion(
        tarea="ugpp_demanda", system_prompt="Eres JuliX", user_content="Hechos del expediente",
        user_id="julian", caso_id="caso-1", prompt_version=1, prompt_hash="abcd1234abcd1234",
    ):
        texto += chunk

    assert "Fin del borrador" in texto
    assert len(factory.llamadas) == 1
    assert factory.llamadas[0]["model"] == client.model_for("ugpp_demanda")

    assert len(db.llamadas_registradas) == 1
    _, args = db.llamadas_registradas[0]
    assert "ok" in args  # status persistido
    assert "julian" in args  # user_id persistido



# ---------------------------------------------------------------------------
# RAG (S6): inyección de contexto en julix/service.py antes de llamar a Sonnet 5
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_sin_contexto_rag_responde_no_tengo_fuente(monkeypatch):
    """Si rag_buscar_contexto no encuentra nada, la directiva de fuente
    obligatoria debe llegar al system_prompt real que recibe el SDK — la
    respuesta 'No tengo fuente suficiente' viene del modelo mockeado, pero
    lo que este test prueba es que la señal llegó bien construida."""
    monkeypatch.setenv("USE_POSTGRES", "false")
    db = FakeLedgerDB()
    client = JuliXClient(environment="staging", db_connection=db)
    factory = FakeSDKStreamFactory(FakeSDKStream(["No tengo fuente suficiente."]))
    client._abrir_stream_sdk = factory

    async def fake_rag_sin_resultados(db_connection, pregunta, **kwargs):
        return []

    monkeypatch.setattr(julix_service_module, "rag_buscar_contexto", fake_rag_sin_resultados)

    service = JuliXService(client=client, db_connection=db)
    texto = ""
    async for chunk in service.generar_documento(
        user_id="julian", caso_id="caso-sin-contexto", tarea="ugpp_demanda",
        expediente_texto="Consulta fuera del corpus disponible",
        pregunta="¿Qué sanción aplica a un supuesto que no está en el corpus?",
    ):
        texto += chunk

    assert "No tengo fuente suficiente" in texto
    assert len(factory.llamadas) == 1
    assert "No tengo fuente suficiente" in factory.llamadas[0]["system_prompt"]


@pytest.mark.asyncio
async def test_service_con_contexto_ugpp_cita_art_179(monkeypatch):
    """Si el RAG recupera un chunk de Art. 179, esa referencia debe llegar
    tanto al user_content del SDK (prueba de que la inyección de contexto
    funciona) como aparecer en la respuesta (mockeada) de JuliX."""
    monkeypatch.setenv("USE_POSTGRES", "false")
    db = FakeLedgerDB()
    client = JuliXClient(environment="staging", db_connection=db)
    factory = FakeSDKStreamFactory(
        FakeSDKStream(["La sanción aplicable es del 160%, según el Art. 179 de la Ley 1607 de 2012."])
    )
    client._abrir_stream_sdk = factory

    chunk_recuperado = ChunkRecuperado(
        norma="Ley 1607 de 2012", articulo="Art. 179", parrafo=None,
        texto="Sanción por inexactitud: 160% del mayor valor dejado de aportar.",
        distancia=0.05,
    )

    async def fake_rag_con_resultado(db_connection, pregunta, **kwargs):
        return [chunk_recuperado]

    monkeypatch.setattr(julix_service_module, "rag_buscar_contexto", fake_rag_con_resultado)

    service = JuliXService(client=client, db_connection=db)
    texto = ""
    async for chunk in service.generar_documento(
        user_id="julian", caso_id="caso-ugpp-179", tarea="ugpp_demanda",
        expediente_texto="Caso de inexactitud en autoliquidación UGPP",
        pregunta="¿Qué sanción aplica por inexactitud en la autoliquidación?",
    ):
        texto += chunk

    assert "Art. 179" in texto
    assert len(factory.llamadas) == 1
    assert "Art. 179" in factory.llamadas[0]["user_content"]
