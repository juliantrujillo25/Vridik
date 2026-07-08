"""
Vridik — core/permissions.py
Sprint S6: matriz de roles/permisos para RBAC más fino entre admin, seller y
customer.

`customer` = usuario registrado sin rol especial. Antes de S6 el default de
`users.role` (core/admin.py:ensure_role_column) era `'seller'` — un
provisional de S2 que nunca distinguía sellers de clientes comunes; desde
S6 el default pasa a `'customer'` (ver core/admin.py).

Este módulo es deliberadamente el único lugar sin Request/Header de todo el
sistema de permisos: la matriz PERMISSIONS documenta la intención (qué
puede hacer cada rol) y `check_owner()` centraliza el criterio de ownership
ya usado en S3/S4/S5 ("dueño del recurso O admin"), pero las dependencias
de FastAPI que resuelven el JWT (get_current_user/get_current_seller/
get_current_admin) siguen viviendo en api/admin_endpoint.py — mismo lugar
de siempre — porque necesitan Request/Header y `_get_db`, algo que core/
nunca importa desde api/.
"""

from __future__ import annotations

ROLES = ("admin", "seller", "customer")

PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "seller": {
        "products:create:own",
        "products:update:own",
        "products:read:own",
        "products:images:own",
        "orders:read:own",
    },
    "customer": {
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
