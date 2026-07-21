# Vridik — PRIVACIDAD.md

Política de tratamiento y retención de datos personales (Ley 1581 de 2012,
Colombia — "Habeas Data"). Pedido por el roadmap (T7: *"Endpoints ARCO +
retención"*).

**Estado: BORRADOR.** El Acceso (sección 2) ya tiene endpoint real. La
Rectificación (sección 3) se ejerce con endpoints ya existentes. La
Supresión (sección 4) todavía NO está implementada — qué se anonimiza vs
qué se conserva por deber legal es una decisión de producto/legal que
falta cerrar con el dev lead antes de escribir el `DELETE`/`UPDATE` real
sobre datos de un usuario. El registro ante el RNBD (Registro Nacional de
Bases de Datos) es un trámite del dev lead, no código — no lo cubre este
documento.

## 1. Qué datos personales trata Vridik

El esquema de `users` en sí es mínimo — solo `email`, `role`,
`despacho_id`, estado de 2FA. La mayoría del dato personal real vive
DERIVADO de la actividad del usuario, no en su fila de perfil:

| Dato | Dónde vive | Por qué existe |
|---|---|---|
| Email | `users.email` | Identificador de cuenta / login. |
| Actividad en casos (como cliente o abogado) | `casos` | Núcleo del producto — sin esto no hay copiloto legal. |
| Mensajes enviados | `mensajes` | Comunicación cliente↔abogado sobre un caso. |
| Actuaciones/términos que registró | `actuaciones`, `terminos` | Expediente procesal del caso. |
| Documentos generados con JuliX | `case_documents` | Resultado del producto — puede contener datos personales de terceros (p.ej. de la contraparte) si el usuario los pegó en el prompt. |
| Eventos de autenticación (login, 2FA, etc.) | `auth_events` | Bitácora de seguridad — **hash-encadenada** (`core/auth_events.py`), es evidencia de integridad, no un log descartable. |

## 2. Acceso

`GET /me/datos` (`api/datos_personales_endpoint.py`, autenticado con el
token propio del usuario — nunca se puede pedir el export de otra cuenta)
devuelve en un solo JSON:

- Perfil (`users` + nombre del despacho).
- Casos donde el usuario es cliente o abogado.
- Mensajes que escribió (no los del otro participante del caso — ese es
  el derecho de acceso de esa otra persona, no del que pide el export).
- Actuaciones, términos y documentos que él mismo creó.
- Sus propios eventos de `auth_events`.

Implementación: `core/datos_personales.py::exportar_datos_de_usuario`.
Probado contra Postgres real (`tests/test_datos_personales.py`), incluido
el caso de que el export de un usuario NUNCA traiga filas que en
realidad pertenecen a otro participante del mismo caso.

## 3. Rectificación

No hay un endpoint nuevo para esto — se ejerce con lo que ya existe:

- Contraseña propia: `POST /auth/password`.
- Rol/estado de una cuenta (por un admin): `PATCH /admin/users/{id}/role`,
  endpoints de `api/admin_endpoint.py`.
- No hay campos de "nombre completo", "teléfono", etc. en `users` hoy —
  si se agregan a futuro, la rectificación de esos campos necesitaría su
  propio endpoint de self-service.

## 4. Supresión — PENDIENTE DE DISEÑO

Qué se anonimiza vs qué se conserva por deber legal, propuesta inicial a
discutir (NO implementada):

- **Se anonimizaría**: `users.email` (reemplazado por un placeholder
  único, p.ej. `usuario-eliminado-<id>@vridik.invalid`), `is_active =
  false`, invalidar todos los `refresh_tokens` y desactivar 2FA.
- **Se conservaría, con el `user_id` intacto**: `casos`, `actuaciones`,
  `terminos`, `case_documents` — son el expediente procesal del caso, con
  valor probatorio/legal propio; borrarlos podría perjudicar al OTRO
  participante del caso (cliente o abogado) que sigue teniendo derecho a
  su propio historial.
- **Se conservaría, nunca se mutaría**: `auth_events` — tiene hash
  encadenado (`core/auth_events.py::verificar_cadena`); UPDATE o DELETE
  ahí rompe la cadena para TODAS las filas posteriores de TODOS los
  usuarios, no solo las del que pide la supresión. Un `user_id UUID
  REFERENCES users(id) ON DELETE SET NULL` ya está preparado para que
  borrar (no anonimizar) un usuario no rompa la FK, pero anonimizar en
  vez de borrar directamente evita tener que decidir eso.
- **Sin resolver todavía**: mensajes que escribió (¿se anonimiza el
  autor pero se conserva el texto, porque el otro participante del caso
  también tiene derecho a su propia conversación? ¿o se reemplaza el
  texto por un placeholder?); qué pasa si el usuario es el ÚNICO admin de
  su despacho (¿se bloquea la supresión hasta que haya un segundo admin,
  mismo problema que T4 del roadmap — bus factor 1?).

Antes de escribir código de supresión real: cerrar esta lista con el dev
lead, y confirmar si aplica alguna excepción de conservación por deber
legal bajo la normativa colombiana relevante al ejercicio de la
abogacía (plazos de conservación de expedientes, etc. — consulta legal,
no técnica).

## 5. Registro Nacional de Bases de Datos (RNBD)

Trámite administrativo ante la SIC, responsabilidad del dev lead — no es
código y no lo cubre este documento.
