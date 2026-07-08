"""
Vridik — api/payments_endpoint.py
Sprint S7: pagos con Wompi (core/payment.py + core/wompi.py) sobre
`orders` (S4).

POST /orders/{id}/pay      requiere JWT — dueño de la orden o admin (mismo
                            criterio de siempre, core.permissions.check_owner).
                            Crea un `payments` pendiente con `reference`
                            única y arranca la transacción en Wompi si
                            WOMPI_PRIVATE_KEY está configurado (si no, el
                            payment queda igual creado como 'pending' — el
                            frontend puede reintentar).
POST /webhooks/wompi       público (Wompi llama esto directamente, sin
                            JWT) — verifica la firma HMAC
                            (core.wompi.verify_signature) ANTES de tocar
                            nada; si el evento trae status APPROVED, marca
                            el payment y la orden como pagados.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.order import get_order, update_status
from core.payment import create_payment, ensure_payment_table, get_payment_by_reference, update_payment_status
from core.permissions import check_owner
from core.wompi import create_transaction, verify_signature

router = APIRouter(tags=["payments"])

_WOMPI_STATUS_A_PAYMENT_STATUS = {"APPROVED": "approved", "DECLINED": "declined"}


@router.post("/orders/{order_id}/pay", status_code=201)
async def pay_order(order_id: str, request: Request, user: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_payment_table(conn)

    orden = await get_order(conn, order_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    if not check_owner(orden["user_id"], user):
        raise HTTPException(status_code=403, detail="No puedes pagar esta orden")

    reference = f"vridik-{order_id}-{uuid.uuid4().hex[:8]}"
    pago = await create_payment(conn, order_id=order_id, reference=reference, amount_cents=orden["total_cents"])

    respuesta = {
        "payment_id": pago["id"], "reference": reference, "amount_cents": orden["total_cents"],
        "status": pago["status"], "public_key": os.environ.get("WOMPI_PUBLIC_KEY", ""),
    }
    try:
        transaccion = await create_transaction(
            amount_cents=orden["total_cents"], currency="COP", reference=reference, customer_email=user["email"],
        )
        respuesta["wompi_transaction_id"] = (transaccion.get("data") or {}).get("id")
    except Exception:
        # Sin WOMPI_PRIVATE_KEY real (o la API de Wompi no responde), el
        # payment queda igual creado en 'pending' — el checkout widget de
        # Wompi en el frontend puede tomar el `reference` directamente sin
        # depender de esta llamada.
        pass

    return respuesta


@router.post("/webhooks/wompi")
async def wompi_webhook(request: Request):
    conn = _get_db(request)
    await ensure_payment_table(conn)

    payload = await request.json()
    if not verify_signature(payload):
        raise HTTPException(status_code=401, detail="Firma inválida")

    transaccion = ((payload.get("data") or {}).get("transaction")) or {}
    reference = transaccion.get("reference")
    status_wompi = transaccion.get("status")
    transaction_id = transaccion.get("id")
    if not reference:
        raise HTTPException(status_code=400, detail="Evento sin reference")

    pago = await get_payment_by_reference(conn, reference)
    if pago is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    nuevo_status = _WOMPI_STATUS_A_PAYMENT_STATUS.get(status_wompi)
    if nuevo_status is None:
        return {"ok": True, "ignorado": status_wompi}

    await update_payment_status(conn, reference, status=nuevo_status, transaction_id=transaction_id)
    if nuevo_status == "approved":
        await update_status(conn, pago["order_id"], "paid")

    return {"ok": True}
