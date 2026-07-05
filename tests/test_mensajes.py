"""
Vridik — tests/test_mensajes.py (Sprint S3)
7 tests: crear chat, adjunto, badge (no-leídos), borrado.

Usa FakeMensajesService (ver tests/support/fakes.py): contrato estable de
Mensajes hoy (85% según Estado Actual del roadmap); S11 le agrega SSE encima
sin cambiar esta capa de datos.
"""

from __future__ import annotations

import pytest

from tests.support.fakes import FakeMensajesService


@pytest.fixture
def mensajes():
    return FakeMensajesService()


# 1. Crear chat básico
def test_crear_mensaje_basico(mensajes):
    msg = mensajes.crear_chat(conversacion_id="conv-1", autor_id="ana", texto="Hola, caso actualizado")
    assert msg.texto == "Hola, caso actualizado"
    assert msg.borrado is False


# 2. Crear mensaje con adjunto
def test_crear_mensaje_con_adjunto(mensajes):
    msg = mensajes.crear_chat(
        conversacion_id="conv-1", autor_id="ana", texto="Ver documento adjunto",
        adjunto_url="https://vridik.local/adjuntos/req-ugpp.pdf",
    )
    assert msg.adjunto_url is not None
    assert msg.adjunto_url.endswith(".pdf")


# 3. Mensaje sin adjunto: adjunto_url es None por defecto
def test_mensaje_sin_adjunto_por_defecto(mensajes):
    msg = mensajes.crear_chat(conversacion_id="conv-1", autor_id="ana", texto="Sin adjunto")
    assert msg.adjunto_url is None


# 4. Badge de no-leídos: cuenta mensajes de otros autores no leídos
def test_badge_no_leidos_cuenta_correctamente(mensajes):
    mensajes.crear_chat(conversacion_id="conv-2", autor_id="ana", texto="Mensaje 1")
    mensajes.crear_chat(conversacion_id="conv-2", autor_id="ana", texto="Mensaje 2")
    assert mensajes.no_leidos_para("cliente1", "conv-2") == 2


# 5. Badge de no-leídos: mensajes propios no cuentan como no-leídos
def test_badge_no_cuenta_mensajes_propios(mensajes):
    mensajes.crear_chat(conversacion_id="conv-3", autor_id="cliente1", texto="Mi propio mensaje")
    assert mensajes.no_leidos_para("cliente1", "conv-3") == 0


# 6. Marcar como leído reduce el contador de no-leídos
def test_marcar_leido_reduce_badge(mensajes):
    msg = mensajes.crear_chat(conversacion_id="conv-4", autor_id="ana", texto="Actualización de término")
    assert mensajes.no_leidos_para("cliente1", "conv-4") == 1
    mensajes.marcar_leido(msg.id, "cliente1")
    assert mensajes.no_leidos_para("cliente1", "conv-4") == 0


# 7. Borrado: solo el autor puede borrar (soft-delete)
def test_borrado_solo_autor_y_es_soft_delete(mensajes):
    msg = mensajes.crear_chat(conversacion_id="conv-5", autor_id="ana", texto="Mensaje a borrar")

    borrado_por_otro = mensajes.borrar(msg.id, actor_id="cliente1")
    assert borrado_por_otro is False
    assert msg.borrado is False

    borrado_por_autor = mensajes.borrar(msg.id, actor_id="ana")
    assert borrado_por_autor is True
    assert msg.borrado is True
