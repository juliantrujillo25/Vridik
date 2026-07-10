-- =====================================================================
-- Vridik — migrations/006_roles_vocabulario_legal.sql
-- Migración de vocabulario de roles (decisión del dev lead): el producto
-- real es el despacho legal (JuliX/RAG), no el marketplace -- los roles
-- pasan de admin/seller/customer (vocabulario de marketplace) a
-- admin/abogado/cliente (vocabulario del producto real).
--
-- Se aplica DESPUÉS de que el código que lee estos valores ya esté
-- desplegado (ver core/permissions.py, api/admin_endpoint.py) -- nunca
-- antes, para no dejar una ventana donde el código viejo (que espera
-- 'seller'/'customer') no reconozca los valores nuevos.
--
-- `seller_id` (columna FK en products/orders) NO se toca -- es un
-- concepto de dominio del marketplace (quién es dueño de un producto),
-- no un valor de rol; se revisa en la fase de desmantelamiento, no acá.
--
-- Migración idempotente: los UPDATE con WHERE codigo/role = '...viejo'
-- se vuelven no-op solos una vez aplicados (nada queda con el valor
-- viejo para volver a actualizar).
-- =====================================================================

BEGIN;

UPDATE roles SET codigo = 'abogado' WHERE codigo = 'seller';
UPDATE roles SET codigo = 'cliente' WHERE codigo = 'customer';

UPDATE users SET role = 'abogado' WHERE role = 'seller';
UPDATE users SET role = 'cliente' WHERE role = 'customer';

COMMIT;

-- Rollback de referencia:
-- UPDATE users SET role = 'seller' WHERE role = 'abogado';
-- UPDATE users SET role = 'customer' WHERE role = 'cliente';
-- UPDATE roles SET codigo = 'seller' WHERE codigo = 'abogado';
-- UPDATE roles SET codigo = 'customer' WHERE codigo = 'cliente';
