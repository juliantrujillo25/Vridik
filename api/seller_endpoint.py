"""
Vridik — api/seller_endpoint.py
Sprint S6: vista "propia" de un seller sobre productos/órdenes — mismas
tablas y funciones de core/product.py (S3/S5) y core/order.py (S4) que ya
usan api/products_endpoint.py y api/orders_endpoint.py, pero acá siempre
filtradas por ownership (o `?all=true` si quien pregunta es admin).

GET    /seller/products                     solo los productos del seller
                                             autenticado (?all=true + admin
                                             ve el catálogo completo)
POST   /seller/products                     crea producto, seller_id =
                                             siempre el usuario autenticado
PATCH  /seller/products/{id}                solo si sos el dueño (o admin)
POST   /seller/products/{id}/images         idem — reutiliza
DELETE /seller/products/{id}/images/{id}    api.admin_endpoint._procesar_imagen_request
                                             (S5, sin tocar su comportamiento)

GET    /seller/orders                       órdenes que contienen AL MENOS
                                             un producto del seller (join
                                             order_items -> products,
                                             core.order.list_orders_for_seller)
GET    /seller/orders/{id}                  detalle, mismo filtro; 403 si
                                             la orden no tiene ningún
                                             producto del seller

Todas las rutas requieren get_current_seller() de api/admin_endpoint.py
(S6: exige role in ('seller', 'admin') — un customer nunca las alcanza).

Sprint S7: `CreateOwnProductRequest` suma `category`/`city` (mismo
validador de api.admin_endpoint.CreateProductRequest); el borrado de
imágenes usa core.storage (vía api.admin_endpoint._borrar_archivo_si_aplica,
ya async).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.admin_endpoint import (
    UpdateProductRequest,
    _borrar_archivo_si_aplica,
    _procesar_imagen_request,
    get_current_seller,
)
from api.auth_endpoint import _get_db
from core.order import (
    ensure_order_tables,
    get_order,
    get_order_items,
    list_orders_for_seller,
    order_has_seller_product,
)
from core.permissions import check_owner
from core.product import (
    CATEGORIAS_VALIDAS,
    add_image,
    create_product,
    delete_image,
    ensure_product_images_table,
    ensure_product_search_columns,
    get_image,
    get_product,
    list_products,
    update_product,
)

router = APIRouter(prefix="/seller", tags=["seller"])


class CreateOwnProductRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    price_cents: int = Field(..., ge=0)
    stock: int = Field(0, ge=0)
    category: str | None = None
    city: str | None = None

    @field_validator("category")
    @classmethod
    def _category_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"category debe ser una de {CATEGORIAS_VALIDAS}")
        return v


@router.get("/products")
async def get_my_products(
    request: Request, skip: int = 0, limit: int = 20, all: bool = False,
    current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)
    filtro_seller_id = None if (all and current["role"] == "admin") else str(current["id"])
    return await list_products(conn, skip=skip, limit=limit, active_only=False, seller_id=filtro_seller_id)


@router.post("/products", status_code=201)
async def post_my_product(
    payload: CreateOwnProductRequest, request: Request, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)
    existente = await conn.fetchrow("SELECT id FROM products WHERE sku = $1", payload.sku)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un producto con sku {payload.sku!r}")

    return await create_product(
        conn, sku=payload.sku, name=payload.name, description=payload.description,
        price_cents=payload.price_cents, stock=payload.stock, seller_id=str(current["id"]),
        category=payload.category, city=payload.city,
    )


@router.patch("/products/{product_id}")
async def patch_my_product(
    product_id: str, payload: UpdateProductRequest, request: Request,
    current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if not check_owner(producto["seller_id"], current):
        raise HTTPException(status_code=403, detail="Solo el admin o el seller dueño pueden editar este producto")

    cambios = payload.model_dump(exclude_unset=True)
    return await update_product(conn, product_id, cambios)


@router.post("/products/{product_id}/images", status_code=201)
async def post_my_product_image(
    product_id: str, request: Request, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_images_table(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if not check_owner(producto["seller_id"], current):
        raise HTTPException(
            status_code=403, detail="Solo el admin o el seller dueño pueden subir imágenes de este producto",
        )

    url, is_primary = await _procesar_imagen_request(request, product_id)
    return await add_image(conn, product_id=product_id, url=url, is_primary=is_primary)


@router.delete("/products/{product_id}/images/{image_id}", status_code=204)
async def delete_my_product_image(
    product_id: str, image_id: str, request: Request, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_images_table(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    if not check_owner(producto["seller_id"], current):
        raise HTTPException(
            status_code=403, detail="Solo el admin o el seller dueño pueden borrar imágenes de este producto",
        )

    imagen = await get_image(conn, image_id)
    if imagen is None or str(imagen["product_id"]) != product_id:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    await delete_image(conn, image_id)
    await _borrar_archivo_si_aplica(imagen)
    return None


@router.get("/orders")
async def get_my_seller_orders(
    request: Request, skip: int = 0, limit: int = 20, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    return await list_orders_for_seller(conn, seller_id=str(current["id"]), skip=skip, limit=limit)


@router.get("/orders/{order_id}")
async def get_my_seller_order_detail(
    order_id: str, request: Request, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    orden = await get_order(conn, order_id)
    if orden is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if current["role"] != "admin":
        contiene = await order_has_seller_product(conn, order_id, str(current["id"]))
        if not contiene:
            raise HTTPException(status_code=403, detail="Esta orden no contiene productos tuyos")

    items = await get_order_items(conn, order_id)
    return {**orden, "items": items}
