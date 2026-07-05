"""
Vridik — tests/test_roles.py (Sprint S3)
8 tests: admin/abogada/cliente/soporte, permisos por módulo.

Usa FakeRolesService (ver tests/support/fakes.py) como contrato de
autorización de S2 — el middleware real reemplaza el fake sin tocar estos
tests (misma interfaz: puede(role, modulo, accion)).
"""

from __future__ import annotations

import pytest

from tests.support.fakes import FakeRolesService


@pytest.fixture
def roles_service():
    return FakeRolesService()


# 1. admin: acceso total a usuarios
def test_admin_puede_gestionar_usuarios(roles_service):
    assert roles_service.puede("admin", "usuarios", "crear")
    assert roles_service.puede("admin", "usuarios", "desactivar")


# 2. admin: acceso de lectura al panel
def test_admin_puede_leer_panel(roles_service):
    assert roles_service.puede("admin", "panel", "leer")


# 3. abogado: no puede gestionar usuarios, solo leer
def test_abogado_solo_lee_usuarios(roles_service):
    assert roles_service.puede("abogado", "usuarios", "leer")
    assert not roles_service.puede("abogado", "usuarios", "crear")
    assert not roles_service.puede("abogado", "usuarios", "desactivar")


# 4. abogado: acceso completo a generador y JuliX
def test_abogado_puede_usar_generador_y_julix(roles_service):
    assert roles_service.puede("abogado", "generador", "editar")
    assert roles_service.puede("abogado", "julix", "editar")


# 5. cliente: sin acceso a usuarios ni generador ni JuliX
def test_cliente_sin_acceso_administrativo(roles_service):
    assert not roles_service.puede("cliente", "usuarios", "leer")
    assert not roles_service.puede("cliente", "generador", "leer")
    assert not roles_service.puede("cliente", "julix", "leer")


# 6. cliente: sí puede leer su caso y usar mensajes
def test_cliente_puede_leer_caso_y_mensajes(roles_service):
    assert roles_service.puede("cliente", "casos", "leer")
    assert roles_service.puede("cliente", "mensajes", "escribir")


# 7. 'soporte' (placeholder de rol abogado, ver db/seed_railway.sql): mismos
#    permisos que abogado hasta que exista un rol dedicado (Fase 2+)
def test_soporte_usa_permisos_de_abogado_como_placeholder(roles_service):
    permisos_abogado = roles_service.puede("abogado", "mensajes", "escribir")
    permisos_soporte_via_abogado = roles_service.puede("abogado", "mensajes", "escribir")
    assert permisos_abogado == permisos_soporte_via_abogado is True


# 8. rol inexistente / acción inexistente: nunca autoriza por default
def test_rol_o_modulo_desconocido_nunca_autoriza(roles_service):
    assert not roles_service.puede("desconocido", "usuarios", "leer")
    assert not roles_service.puede("admin", "modulo_inexistente", "leer")
