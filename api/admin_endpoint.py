"""
Vridik — api/admin_endpoint.py
Sprint S2: panel admin (CRUD básico de usuarios) sobre la misma tabla
`users`/JWT de S1 (api/auth_endpoint.py) — reemplaza a api/admin_users_endpoint.py
(schema `roles`/`user_credentials` distinto, nunca compatible con los JWT
reales que emite core.auth.create_jwt: esperaba `role` DENTRO del JWT, que
S1 nunca emite). Ese archivo y core/admin_users.py quedan intactos en el
repo pero dejan de montarse en app/main.py.

GET   /admin/users              lista paginada (skip/limit)
POST  /admin/users              crea usuario (role: customer|seller|admin)
PATCH /admin/users/{id}/role    cambia el rol (un admin no puede cambiarse a sí mismo)

`get_current_admin()` reutiliza el JWT de S1 (core.auth.decode_jwt vía
api.auth_endpoint._claims_de_bearer): 401 si el token falta/es inválido,
403 si es válido pero `role` (columna `users.role`, no el JWT) no es 'admin'.

Sprint S3: gestión de productos (core/product.py) — el catálogo público vive
en api/products_endpoint.py, esto es solo lo que requiere JWT:
POST   /admin/products              admin o seller (S6: ver más abajo)
PATCH  /admin/products/{id}         admin, o el seller dueño (seller_id)
DELETE /admin/products/{id}         solo admin, soft delete (is_active=false)

Sprint S4: gestión de órdenes (core/order.py) — el checkout/consulta propia
vive en api/orders_endpoint.py, esto es solo lo que requiere rol admin:
GET   /admin/orders                 solo admin, lista todas (?status=&skip=&limit=)
PATCH /admin/orders/{id}/status     solo admin, cambia status; si pasa a
                                     'cancelled' restaura el stock reservado.

Sprint S5: imágenes de producto (core/product.py: product_images) — el
catálogo público las expone en api/products_endpoint.py, esto es solo lo
que requiere rol admin:
POST   /admin/products/{id}/images                sube una imagen: multipart
                                                    (campo 'file') o JSON
                                                    {"url": ...}. Máx 5MB,
                                                    solo jpg/png/webp si es
                                                    archivo.
DELETE /admin/products/{id}/images/{image_id}      borra el registro y,
                                                    si es un archivo local
                                                    (/uploads/...), el
                                                    archivo también.
POST   /admin/products/{id}/images/{image_id}/primary  la marca como principal.

Sprint S6 (core/permissions.py): RBAC más fino — tres roles (admin/seller/
customer, ver ROLES). Dos cambios importantes acá:
  - `get_current_seller()` YA NO significa "cualquier usuario autenticado"
    (eso ahora es `get_current_user()`, separado): pasa a exigir
    role in ('seller', 'admin') — un customer nunca la pasa. Antes de S6
    `get_current_user = get_current_seller` era un alias literal; dejaron
    de poder serlo porque customer necesita `get_current_user` sin
    restricción (checkout, api/orders_endpoint.py) pero nunca debe pasar
    `get_current_seller`.
  - POST /admin/products ahora también acepta sellers (antes solo admin):
    `seller_id` en el body queda opcional — si lo llama un seller, se
    auto-asigna su propio id sin importar qué venga en el body (nunca
    puede crear "para" otro seller); si lo llama un admin, puede usar el
    `seller_id` del body o, si no viene, su propio id.
  - `_procesar_imagen_request()`/`_borrar_archivo_si_aplica()` quedan
    factorizados acá para que api/seller_endpoint.py los reutilice en vez
    de reimplementar el manejo de upload — evita dos copias del mismo
    código divergiendo.

Sprint S7 (core/storage.py): `_guardar_archivo_imagen()`/
`_borrar_archivo_si_aplica()` ya no tocan el filesystem directamente —
usan `save_file`/`delete_file`/`key_from_url`, así que el backend
(local o R2) es transparente para este archivo. `CreateProductRequest`/
`UpdateProductRequest` suman `category` (especialidad legal) y `city`
(búsqueda, api/products_endpoint.py).
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from starlette.datastructures import UploadFile as StarletteUploadFile

from api.auth_endpoint import _claims_de_bearer, _get_db
from core.admin import change_role, create_user, ensure_role_column, list_users
from core.admin_users import UsuarioNoEncontradoError, actividad_usuario, resetear_password
from core.auth import hash_password
from core.order import ensure_order_tables, list_all_orders, update_status
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
    set_primary,
    soft_delete,
    update_product,
)
from core.storage import delete_file, key_from_url, save_file

router = APIRouter(prefix="/admin", tags=["admin"])

EXTENSIONES_IMAGEN_PERMITIDAS = {"jpg", "jpeg", "png", "webp"}
TAMANO_MAXIMO_IMAGEN_BYTES = 5 * 1024 * 1024  # 5MB


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: Literal["customer", "seller", "admin"] = "customer"


class ChangeRoleRequest(BaseModel):
    role: Literal["customer", "seller", "admin"]


class CreateProductRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    price_cents: int = Field(..., ge=0)
    stock: int = Field(0, ge=0)
    seller_id: str | None = None
    category: str | None = None
    city: str | None = None

    @field_validator("category")
    @classmethod
    def _category_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"category debe ser una de {CATEGORIAS_VALIDAS}")
        return v


class UpdateProductRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    category: str | None = None
    city: str | None = None

    @field_validator("category")
    @classmethod
    def _category_valida(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"category debe ser una de {CATEGORIAS_VALIDAS}")
        return v


class UpdateOrderStatusRequest(BaseModel):
    status: Literal["pending", "paid", "shipped", "cancelled"]


async def _resolver_usuario(request: Request, authorization: str | None) -> dict:
    claims = _claims_de_bearer(authorization)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin 'sub'")

    conn = _get_db(request)
    await ensure_role_column(conn)
    fila = await conn.fetchrow("SELECT id, email, role FROM users WHERE id = $1", user_id)
    if fila is None:
        raise HTTPException(status_code=401, detail="Usuario del token no existe")
    return dict(fila)


async def get_current_admin(request: Request, authorization: str | None = Header(default=None)) -> dict:
    usuario = await _resolver_usuario(request, authorization)
    if usuario["role"] != "admin":
        raise HTTPException(status_code=403, detail="Requiere rol admin")
    return usuario


async def get_current_seller(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """S6: exige role in ('seller', 'admin') — un customer nunca la pasa.
    Antes de S6 esto era "cualquier usuario autenticado"; ese contrato
    ahora lo cubre get_current_user()."""
    usuario = await _resolver_usuario(request, authorization)
    if usuario["role"] not in ("seller", "admin"):
        raise HTTPException(status_code=403, detail="Requiere rol seller o admin")
    return usuario


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Cualquier usuario autenticado, sin importar el rol — customer
    incluido (S6: necesario para checkout/orders, api/orders_endpoint.py).
    Antes de S6 era un alias de get_current_seller(); dejaron de poder
    serlo porque esa ahora SÍ exige seller/admin."""
    return await _resolver_usuario(request, authorization)


@router.get("/users")
async def get_users(
    request: Request, skip: int = 0, limit: int = 20, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    return await list_users(conn, skip=skip, limit=limit)


@router.post("/users", status_code=201)
async def post_users(
    payload: CreateUserRequest, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    existente = await conn.fetchrow("SELECT id FROM users WHERE email = $1", payload.email)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un usuario con email {payload.email!r}")

    password_hash = hash_password(payload.password)
    return await create_user(conn, email=payload.email, password_hash=password_hash, role=payload.role)


@router.patch("/users/{user_id}/role")
async def patch_user_role(
    user_id: str, payload: ChangeRoleRequest, request: Request, admin: dict = Depends(get_current_admin),
):
    if user_id == str(admin["id"]):
        raise HTTPException(status_code=400, detail="No puedes cambiar tu propio rol")

    conn = _get_db(request)
    actualizado = await change_role(conn, user_id=user_id, new_role=payload.role)
    if actualizado is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return actualizado


@router.get("/users/{user_id}/actividad")
async def get_user_actividad(
    user_id: str, request: Request, limite: int = 50, admin: dict = Depends(get_current_admin),
):
    """S2-GAP-01 (AUDITORIA_PARA_CLAUDE.md): lee auth_events del usuario,
    más recientes primero (core.admin_users.actividad_usuario, ya
    implementado y probado -- solo faltaba montarlo en el router real)."""
    conn = _get_db(request)
    return await actividad_usuario(conn, user_id=user_id, limite=limite)


@router.post("/users/{user_id}/reset-password")
async def post_user_reset_password(
    user_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    """S2-GAP-01: contraseña temporal nueva + revoca refresh tokens activos
    + fuerza must_change. La password_temporal se devuelve en texto plano
    UNA sola vez -- nunca se puede volver a leer después de esta respuesta."""
    conn = _get_db(request)
    try:
        resultado = await resetear_password(conn, actor_id=str(admin["id"]), user_id=user_id)
    except UsuarioNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user_id": resultado.user_id, "password_temporal": resultado.password_temporal}


@router.post("/products", status_code=201)
async def post_products(
    payload: CreateProductRequest, request: Request, current: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)

    if current["role"] == "admin":
        seller_id = payload.seller_id or str(current["id"])
    else:
        # Un seller siempre crea para sí mismo — cualquier seller_id ajeno
        # que venga en el body se ignora, nunca puede crear "para" otro.
        seller_id = str(current["id"])

    existente = await conn.fetchrow("SELECT id FROM products WHERE sku = $1", payload.sku)
    if existente is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un producto con sku {payload.sku!r}")

    return await create_product(
        conn, sku=payload.sku, name=payload.name, description=payload.description,
        price_cents=payload.price_cents, stock=payload.stock, seller_id=seller_id,
        category=payload.category, city=payload.city,
    )


@router.patch("/products/{product_id}")
async def patch_product(
    product_id: str, payload: UpdateProductRequest, request: Request,
    seller: dict = Depends(get_current_seller),
):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if not check_owner(producto["seller_id"], seller):
        raise HTTPException(status_code=403, detail="Solo el admin o el seller dueño pueden editar este producto")

    cambios = payload.model_dump(exclude_unset=True)
    return await update_product(conn, product_id, cambios)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: str, request: Request, admin: dict = Depends(get_current_admin)):
    conn = _get_db(request)
    await ensure_product_search_columns(conn)
    eliminado = await soft_delete(conn, product_id)
    if eliminado is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return None


@router.get("/orders")
async def get_orders(
    request: Request, status: str | None = None, skip: int = 0, limit: int = 20,
    admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    return await list_all_orders(conn, skip=skip, limit=limit, status=status)


@router.patch("/orders/{order_id}/status")
async def patch_order_status(
    order_id: str, payload: UpdateOrderStatusRequest, request: Request,
    admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_order_tables(conn)
    actualizada = await update_status(conn, order_id, payload.status)
    if actualizada is None:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return actualizada


async def _guardar_archivo_imagen(product_id: str, archivo: StarletteUploadFile) -> str:
    nombre_original = archivo.filename or ""
    ext = nombre_original.rsplit(".", 1)[-1].lower() if "." in nombre_original else ""
    if ext not in EXTENSIONES_IMAGEN_PERMITIDAS:
        raise HTTPException(
            status_code=400, detail=f"Extensión no permitida: {ext!r} (solo jpg/png/webp)",
        )

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_IMAGEN_BYTES:
        raise HTTPException(status_code=400, detail="El archivo supera el máximo de 5MB")

    content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
    key = f"products/{product_id}/{uuid.uuid4()}.{ext}"
    return await save_file(key, contenido, content_type=content_type)


async def _procesar_imagen_request(request: Request, product_id: str) -> tuple[str, bool]:
    """(url, is_primary) a partir del body — multipart con campo 'file' o
    JSON {"url": ...}. Factorizado de S5 sin cambios de comportamiento para
    que api/seller_endpoint.py (S6) lo reutilice en vez de reimplementarlo."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        archivo = form.get("file")
        # request.form() (Starlette puro, sin pasar por la inyección de
        # parámetros de FastAPI) devuelve starlette.datastructures.UploadFile
        # — fastapi.UploadFile es una SUBclase de esa, así que un isinstance
        # contra fastapi.UploadFile nunca matchea acá; hay que comparar
        # contra la clase base de Starlette.
        if not isinstance(archivo, StarletteUploadFile):
            raise HTTPException(status_code=400, detail="Falta el campo 'file'")
        url = await _guardar_archivo_imagen(product_id, archivo)
        is_primary = str(form.get("is_primary", "")).lower() in ("true", "1", "yes")
    else:
        payload = await request.json()
        url = payload.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="Falta 'url' (o envía un archivo multipart en 'file')")
        is_primary = bool(payload.get("is_primary", False))
    return url, is_primary


async def _borrar_archivo_si_aplica(imagen: dict) -> None:
    # Solo borra el archivo si es una subida nuestra (local o R2, sin
    # importar el BACKEND activo ahora — key_from_url() lo detecta por el
    # prefijo de la url) — nunca borra un archivo externo (modo
    # {"url": ...} con un link de terceros).
    key = key_from_url(imagen["url"])
    if key is not None:
        await delete_file(key)


@router.post("/products/{product_id}/images", status_code=201)
async def post_product_image(
    product_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_product_images_table(conn)
    producto = await get_product(conn, product_id)
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    url, is_primary = await _procesar_imagen_request(request, product_id)
    return await add_image(conn, product_id=product_id, url=url, is_primary=is_primary)


@router.delete("/products/{product_id}/images/{image_id}", status_code=204)
async def delete_product_image(
    product_id: str, image_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_product_images_table(conn)
    imagen = await get_image(conn, image_id)
    if imagen is None or str(imagen["product_id"]) != product_id:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    await delete_image(conn, image_id)
    await _borrar_archivo_si_aplica(imagen)
    return None


@router.post("/products/{product_id}/images/{image_id}/primary")
async def post_product_image_primary(
    product_id: str, image_id: str, request: Request, admin: dict = Depends(get_current_admin),
):
    conn = _get_db(request)
    await ensure_product_images_table(conn)
    imagen = await get_image(conn, image_id)
    if imagen is None or str(imagen["product_id"]) != product_id:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    return await set_primary(conn, image_id)
