"""
Vridik — api/products_endpoint.py
Sprint S3: catálogo de productos, endpoints PÚBLICOS (sin JWT obligatorio)
sobre core/product.py.

GET /products             lista paginada (?skip=0&limit=20&q=texto), solo
                           is_active=true, campos resumidos (id/sku/name/
                           price_cents/stock) + images[].
GET /products/{id}        detalle completo + images[]. Si el producto está
                           inactivo, 404 — salvo que el JWT (opcional:
                           Authorization Bearer, si viene) pertenezca al
                           admin o al seller dueño, mismo criterio que
                           api/admin_endpoint.py.

Sprint S5: `images` sale de core.product.list_images(), ya ordenada
is_primary desc / position asc — nunca se reordena acá.

Sprint S6: el chequeo de ownership para mostrar un producto inactivo usa
core.permissions.check_owner() (mismo criterio de siempre: dueño o admin),
en vez de la comparación inline que había antes.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from api.auth_endpoint import _get_db
from core.auth import decode_jwt
from core.permissions import check_owner
from core.product import ensure_product_images_table, ensure_product_table, get_product, list_images, list_products

router = APIRouter(prefix="/products", tags=["products"])


def _resumen_imagen(imagen: dict) -> dict:
    return {"id": imagen["id"], "url": imagen["url"], "is_primary": imagen["is_primary"], "position": imagen["position"]}


async def _claims_opcionales(authorization: str | None) -> dict | None:
    """A diferencia de api.auth_endpoint._claims_de_bearer (S1), acá un
    token ausente o inválido NO es un error — este endpoint es público; el
    JWT solo se usa (si viene) para decidir si mostrar un producto inactivo."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return decode_jwt(authorization[len("Bearer "):])
    except ValueError:
        return None


@router.get("")
async def get_products(request: Request, skip: int = 0, limit: int = 20, q: str | None = None):
    conn = _get_db(request)
    await ensure_product_table(conn)
    await ensure_product_images_table(conn)
    productos = await list_products(conn, skip=skip, limit=limit, q=q, active_only=True)
    resultado = []
    for p in productos:
        imagenes = await list_images(conn, p["id"])
        resultado.append({
            "id": p["id"], "sku": p["sku"], "name": p["name"], "price_cents": p["price_cents"], "stock": p["stock"],
            "images": [_resumen_imagen(img) for img in imagenes],
        })
    return resultado


@router.get("/{product_id}")
async def get_product_detail(
    product_id: str, request: Request, authorization: str | None = Header(default=None),
):
    conn = _get_db(request)
    await ensure_product_table(conn)
    await ensure_product_images_table(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if not producto["is_active"]:
        claims = await _claims_opcionales(authorization)
        user_id = claims.get("sub") if claims else None
        autorizado = False
        if user_id is not None:
            fila = await conn.fetchrow("SELECT role FROM users WHERE id = $1", user_id)
            role = fila["role"] if fila is not None else None
            autorizado = check_owner(producto["seller_id"], {"id": user_id, "role": role})
        if not autorizado:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

    imagenes = await list_images(conn, product_id)
    return {**producto, "images": [_resumen_imagen(img) for img in imagenes]}
