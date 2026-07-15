"""
Vridik — tests/test_clasificador_actuaciones.py
procesal/clasificador_actuaciones.py: clasificación IA de una actuación
judicial (Fase 2, Copiloto Procesal) sobre el prompt/modelo que YA existía
para "clasificacion_documento" (julix/prompts/clasificacion_documento_v1.md,
Haiku) -- mismo estilo de test que tests/test_julix.py: se mockea
únicamente `_abrir_stream_sdk` (el único punto que toca el SDK real de
Anthropic), el resto (ledger, retry, parseo) se ejercita de verdad.
"""

from __future__ import annotations

import pytest

from julix.client import JuliXClient
from julix.errors import JuliXInvalidFormatError
from procesal.clasificador_actuaciones import CATEGORIAS_VALIDAS, clasificar_actuacion
from tests.support.fakes import FakeLedgerDB, FakeSDKStream, FakeSDKStreamFactory


def _cliente_con_respuesta(json_texto: str, *, db=None) -> tuple[JuliXClient, FakeSDKStreamFactory]:
    client = JuliXClient(environment="staging", db_connection=db)
    factory = FakeSDKStreamFactory(FakeSDKStream([json_texto]))
    client._abrir_stream_sdk = factory
    return client, factory


@pytest.mark.asyncio
async def test_clasificar_actuacion_reconoce_auto_admisorio():
    client, factory = _cliente_con_respuesta('{"categoria": "auto_admisorio", "confianza": 0.92}')

    resultado = await clasificar_actuacion(client, texto_actuacion="Por medio del presente auto se admite la demanda...", user_id="user-1")

    assert resultado.categoria == "auto_admisorio"
    assert resultado.confianza == pytest.approx(0.92)
    assert factory.llamadas[0]["model"] == client.model_for("clasificacion_documento")


@pytest.mark.asyncio
async def test_clasificar_actuacion_reconoce_las_cuatro_categorias_del_roadmap():
    for categoria in ("auto_admisorio", "requerimiento", "fallo", "traslado"):
        client, _ = _cliente_con_respuesta(f'{{"categoria": "{categoria}", "confianza": 0.7}}')
        resultado = await clasificar_actuacion(client, texto_actuacion="texto de prueba", user_id="user-1")
        assert resultado.categoria == categoria
    assert CATEGORIAS_VALIDAS == {"auto_admisorio", "requerimiento", "fallo", "traslado", "otro"}


@pytest.mark.asyncio
async def test_clasificar_actuacion_registra_en_el_ledger():
    db = FakeLedgerDB()
    client, _ = _cliente_con_respuesta('{"categoria": "fallo", "confianza": 0.85}', db=db)

    await clasificar_actuacion(client, texto_actuacion="Por medio de la presente sentencia se resuelve...", user_id="user-1", caso_id="caso-1")

    inserts = [c for c in db.llamadas_registradas if c[0].strip().startswith("INSERT INTO julix_calls")]
    assert len(inserts) == 1
    _, args = inserts[0]
    # El ledger registra tarea/modelo/usuario/costo -- nunca la categoría
    # resultante de la clasificación (eso vive solo en el resultado que
    # devuelve clasificar_actuacion, no en julix_calls).
    assert "clasificacion_documento" in args
    assert "user-1" in args


@pytest.mark.asyncio
async def test_clasificar_actuacion_tolera_json_envuelto_en_code_fence():
    """Bug real de producción (15-jul-2026): Claude Haiku envolvió la
    respuesta en ```json ... ``` a pesar de que el prompt pide "solo el
    JSON, sin texto alrededor" -- json.loads() crudo fallaba con
    "Expecting value: line 1 column 1" en el 100% de las clasificaciones
    reales. Ver julix/client.py::validar_json (fix real, no solo el test)."""
    client, _ = _cliente_con_respuesta('```json\n{"categoria": "traslado", "confianza": 0.88}\n```')

    resultado = await clasificar_actuacion(client, texto_actuacion="texto de prueba", user_id="user-1")

    assert resultado.categoria == "traslado"
    assert resultado.confianza == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_clasificar_actuacion_rechaza_json_invalido():
    client, _ = _cliente_con_respuesta("esto no es JSON")

    with pytest.raises(JuliXInvalidFormatError):
        await clasificar_actuacion(client, texto_actuacion="texto de prueba", user_id="user-1")


@pytest.mark.asyncio
async def test_clasificar_actuacion_rechaza_categoria_fuera_de_la_lista():
    """Nunca inventa una categoría fuera de CATEGORIAS_VALIDAS, ni siquiera
    si el modelo devuelve JSON válido con un valor inesperado -- mismo
    principio que julix/errors.py: ningún fallo se disfraza de éxito."""
    client, _ = _cliente_con_respuesta('{"categoria": "sentencia_definitiva", "confianza": 0.5}')

    with pytest.raises(JuliXInvalidFormatError, match="fuera de la lista"):
        await clasificar_actuacion(client, texto_actuacion="texto de prueba", user_id="user-1")


@pytest.mark.asyncio
async def test_clasificar_actuacion_rechaza_confianza_no_numerica():
    client, _ = _cliente_con_respuesta('{"categoria": "otro", "confianza": "alta"}')

    with pytest.raises(JuliXInvalidFormatError, match="numérico"):
        await clasificar_actuacion(client, texto_actuacion="texto de prueba", user_id="user-1")


@pytest.mark.asyncio
async def test_clasificar_actuacion_rechaza_texto_vacio():
    client, _ = _cliente_con_respuesta('{"categoria": "otro", "confianza": 0.1}')

    with pytest.raises(ValueError):
        await clasificar_actuacion(client, texto_actuacion="   ", user_id="user-1")
