"""
Vridik — core/permissions.py
Sprint S6: matriz de roles/permisos para RBAC más fino entre admin, abogado
y cliente (vocabulario migrado del marketplace original -- admin/seller/
customer -- al vocabulario del producto real, decisión del dev lead).

`cliente` = usuario registrado sin rol especial. `seller_id` (columna FK)
es un concepto de dominio del marketplace que sigue vivo mientras exista
`products`/`orders` -- se revisa en fases posteriores del desmantelamiento
(ver Instrucciones - CLAUDE.md, "Consolidación de producto").
`get_current_seller()` (S6) se quitó en la fase 2 -- ya no la usaba nadie
tras sacar api/seller_endpoint.py (fase 1) y la gestión admin de productos.

Este módulo es deliberadamente el único lugar sin Request/Header de todo el
sistema de permisos: la matriz PERMISSIONS documenta la intención (qué
puede hacer cada rol) y `check_owner()` centraliza el criterio de ownership
ya usado en S3/S4/S5 ("dueño del recurso O admin"), pero las dependencias
de FastAPI que resuelven el JWT (get_current_user/get_current_admin) siguen
viviendo en api/admin_endpoint.py — mismo lugar de siempre — porque
necesitan Request/Header y `_get_db`, algo que core/ nunca importa desde
api/.
"""

from __future__ import annotations

ROLES = ("admin", "abogado", "cliente")

PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "abogado": {
        "products:read:own",
        "orders:read:own",
    },
    "cliente": {
        "products:read",
        "orders:create",
        "orders:read:own",
    },
}


def has_permission(role: str, permission: str) -> bool:
    otorgados = PERMISSIONS.get(role, set())
    return "*" in otorgados or permission in otorgados


def check_owner(resource_seller_id, user: dict) -> bool:
    """True si `user` es admin, o si es el dueño del recurso
    (`resource_seller_id` == `user['id']`) — mismo criterio de ownership de
    S3 (productos) y S4 (órdenes), ahora centralizado en un solo lugar."""
    if user.get("role") == "admin":
        return True
    return str(resource_seller_id) == str(user.get("id"))
