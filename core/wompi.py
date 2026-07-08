"""
Vridik — core/wompi.py
Sprint S7: integración con Wompi (pasarela de pagos, Colombia).

`create_transaction()` crea una transacción en la API real de Wompi
(sandbox por default vía WOMPI_API_BASE, o producción si se apunta ahí)
usando WOMPI_PRIVATE_KEY — el frontend completa el checkout con
WOMPI_PUBLIC_KEY y el `reference` devuelto.

`verify_signature()` valida la firma de un evento de webhook: concatena
los valores de `signature.properties` (en el orden que el propio evento
indica, extraídos de `data` por ruta punteada) + `timestamp` +
WOMPI_EVENTS_SECRET, SHA-256, compara contra `signature.checksum` — nunca
se marca una orden como pagada sin esto (api/payments_endpoint.py).

NO SE PROBÓ CONTRA LA API REAL DE WOMPI en este entregable (sin
credenciales reales disponibles) — create_transaction() falla explícito
(RuntimeError) si falta WOMPI_PRIVATE_KEY, en vez de intentar una llamada
real "a ver si funciona". verify_signature() sí está completamente
verificada con tests unitarios (HMAC/SHA-256 puro, sin red,
tests/test_payments.py).
"""

from __future__ import annotations

import hashlib
import os

import httpx

WOMPI_API_BASE = os.environ.get("WOMPI_API_BASE", "https://sandbox.wompi.co/v1")


def _valor_anidado(data: dict, ruta_punteada: str):
    """"transaction.status" -> data["transaction"]["status"]."""
    valor = data
    for parte in ruta_punteada.split("."):
        if not isinstance(valor, dict) or parte not in valor:
            return None
        valor = valor[parte]
    return valor


async def create_transaction(
    *, amount_cents: int, currency: str, reference: str, customer_email: str,
) -> dict:
    """Crea una transacción en Wompi (checkout redirigido — el frontend usa
    el `id` devuelto junto con WOMPI_PUBLIC_KEY para completar el pago).
    Requiere WOMPI_PRIVATE_KEY configurado; nunca intenta la llamada sin
    él."""
    private_key = os.environ.get("WOMPI_PRIVATE_KEY", "")
    if not private_key:
        raise RuntimeError("WOMPI_PRIVATE_KEY no configurado")

    async with httpx.AsyncClient(timeout=15) as cliente:
        respuesta = await cliente.post(
            f"{WOMPI_API_BASE}/transactions",
            headers={"Authorization": f"Bearer {private_key}"},
            json={
                "amount_in_cents": amount_cents,
                "currency": currency,
                "reference": reference,
                "customer_email": customer_email,
            },
        )
        respuesta.raise_for_status()
        return respuesta.json()


def verify_signature(payload: dict) -> bool:
    """Verifica la firma de un evento de webhook de Wompi. Sin
    WOMPI_EVENTS_SECRET configurado, o sin los campos esperados en el
    payload, siempre devuelve False — nunca se asume válido un evento que
    no se pudo verificar de verdad."""
    events_secret = os.environ.get("WOMPI_EVENTS_SECRET", "")
    if not events_secret:
        return False

    firma = payload.get("signature") or {}
    checksum_esperado = firma.get("checksum")
    propiedades = firma.get("properties") or []
    timestamp = payload.get("timestamp")
    if not checksum_esperado or not propiedades or timestamp is None:
        return False

    data = payload.get("data") or {}
    valores = [str(_valor_anidado(data, prop)) for prop in propiedades]
    cadena = "".join(valores) + str(timestamp) + events_secret
    checksum_calculado = hashlib.sha256(cadena.encode("utf-8")).hexdigest()
    return checksum_calculado == checksum_esperado
