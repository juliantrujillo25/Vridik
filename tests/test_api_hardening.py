"""
Vridik — tests/test_api_hardening.py (Sprint S13)
Prueba el hardening agregado a api/julix_endpoint.py: headers de seguridad
en toda respuesta y que CORS rechace por defecto un origen no autorizado
(VRIDIK_ALLOWED_ORIGINS vacío = falla cerrado, nunca "*").

HSTS + CSP (roadmap S12-13) se agregaron en la sesión que cerró S11 --
ver el docstring de _agregar_headers_seguridad() en api/julix_endpoint.py
para el porqué de Content-Security-Policy-Report-Only (no el header que
aplica de verdad todavía).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.julix_endpoint import app


def test_healthcheck_incluye_headers_de_seguridad():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert resp.headers["Content-Security-Policy-Report-Only"] == "default-src 'none'; frame-ancestors 'none'"


def test_cors_sin_origenes_configurados_no_refleja_origen_arbitrario():
    """Sin VRIDIK_ALLOWED_ORIGINS configurado, la lista de orígenes
    permitidos queda vacía — CORSMiddleware no debe reflejar un origen
    cross-origin cualquiera en Access-Control-Allow-Origin (falla cerrado)."""
    client = TestClient(app)
    resp = client.get("/health", headers={"Origin": "https://sitio-no-autorizado.example"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers.keys()}
