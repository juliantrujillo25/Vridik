"""
Vridik — api/orders_endpoint.py
Sprint S4: checkout y órdenes sobre core/order.py (S4) + core/product.py (S3).

POST /orders/checkout   requiere JWT (cualquier usuario autenticado). Valida
                         stock (SELECT FOR UPDATE, core.order.create_order),
                         calcula total_cents, crea orden + order_items,
                         descuenta stock. 400 si stock insuficiente, 404 si
                         algún producto no existe o está inactivo.
GET  /orders/me          requiere JWT, lista las órdenes del usuario (paginado).
GET  /orders/{id}        requiere JWT, detalle con items — 403 si no eres el
                          dueño ni admin.

`get_current_user` es api.admin_endpoint.get_current_user: cualquier
usuario autenticado, customer incluido (S6: necesario para que un customer
pueda hacer checkout — get_current_seller, en cambio, ya exige rol
seller/admin desde S6 y NO sirve acá).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.admin_endpoint import get_current_user
from api.auth_endpoint import _get_db
from core.order import (
    ProductoInactivoError,
    ProductoNoEncontradoError,
    StockInsuficienteError,
    create_order,
    ensure_order_tables,
    get_order,
    get_order_items,
    list_orders_by_user,
)
from core.permissions import check_owner

router = APIRouter(prefix="/orders", tags=["orders"])


class CheckoutItem(BaseModel):
    product_id: str
    quantity: int = Field(..., gt=0)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItem] = Field(..., min_length=1)


@router.post("/checkout", status_code=201)
async def checkout(payload: CheckoutRequest, request: Request, user: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_order_tables(conn)

    items = [{"product_id": item.product_id, "quantity": item.quantity} for item in payload.items]
    try:
        orden = await create_order(conn, user_id=user["id"], items=items)
    except ProductoNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductoInactivoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StockInsuficienteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"order_id": orden["id"], "total_cents": orden["total_cents"], "status": orden["status"]}


@router.get("/me")
async def get_my_orders(
    request: Request, skip: int = 0, limit: int = 20, user: dict = Depends(get_current_user),
):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    return await list_orders_by_user(conn, user_id=user["id"], skip=skip, limit=limit)


@router.get("/{order_id}")
async def get_order_detail(order_id: str, request: Request, user: dict = Depends(get_current_user)):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    orden = await get_order(conn, order_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if not check_owner(orden["user_id"], user):
        raise HTTPException(status_code=403, detail="No puedes ver esta orden")

    items = await get_order_items(conn, order_id)
    return {**orden, "items": items}
