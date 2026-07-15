# Vridik — SECURITY.md

Prácticas y procedimientos de seguridad del backend de Vridik. Pedido por
el roadmap (`vridik_roadmap.md`, Semana 12-13, hardening: *"rotación de
JWT secret con doble clave ensayada en staging (`SECURITY.md`)"*).

## Secretos y variables de entorno sensibles

| Variable | Qué protege | Notas |
|---|---|---|
| `JWT_SECRET` | Firma de los access tokens (15 min) y, derivada, de los temp tokens de 2FA (5 min). | SIEMPRE del vault de secretos de Railway, nunca vacío en producción (`api/julix_endpoint.py` loguea CRITICAL si arranca vacío). Rotable — ver abajo. |
| `JWT_SECRET_PREVIOUS` | Solo existe DURANTE una rotación de `JWT_SECRET`. | Contiene la clave vieja mientras dura la ventana de rotación; se borra al cerrarla. |
| `TOTP_ENCRYPTION_KEY` | Cifrado en reposo de `users.totp_secret` (Fernet). | Independiente de `JWT_SECRET` (desacoplada a propósito — ver más abajo). Rotar `JWT_SECRET` NO afecta el 2FA. |
| `ANTHROPIC_API_KEY_PROD` / `ANTHROPIC_API_KEY_STAGING` | Cuál credencial de Anthropic usa cada llamada de JuliX, según `VRIDIK_ENVIRONMENT` (`julix/client.py::_resolve_api_key`). | **Corregido el 15-jul-2026**: `VRIDIK_ENVIRONMENT` nunca estuvo seteado en `vridik-api` (caía al default `"staging"` en todo el código), y solo existía `ANTHROPIC_API_KEY_STAGING` -- la key real de producción vivía ahí con el nombre equivocado, no había ninguna key separada de prod. Se copió el valor (nunca impreso, pipe directo `railway variable list --kv \| grep ... \| railway variable set --stdin`) a `ANTHROPIC_API_KEY_PROD` y recién después se seteó `VRIDIK_ENVIRONMENT=production`, para no dejar una ventana sin ninguna key resuelta. Verificado con una llamada real post-fix: ledger (`julix_calls`) etiqueta `environment='production'` como corresponde. |

### Qué NO depende de `JWT_SECRET`

- **Refresh tokens** (`core/refresh_tokens.py`): NO son JWT. Son tokens
  opacos aleatorios, guardados solo como hash SHA-256 en la tabla
  `refresh_tokens`. Rotar `JWT_SECRET` no los invalida — una sesión con
  refresh token válido se recupera sola tras la rotación pidiendo un
  access token nuevo por `POST /auth/refresh`.
- **Contraseñas** (`user_credentials.password_hash`): bcrypt, sin relación
  con `JWT_SECRET`.
- **`totp_secret`**: cifrado con `TOTP_ENCRYPTION_KEY`, no con
  `JWT_SECRET` (desde el hardening de S12-13). Antes SÍ dependía de
  `JWT_SECRET` — rotarlo habría vuelto indescifrable todo secreto TOTP ya
  guardado. Ese acople se rompió deliberadamente ANTES de habilitar la
  rotación de `JWT_SECRET`, justamente para que rotar la clave de sesión
  nunca pueda romper el 2FA de nadie. `core/totp_2fa.py::_desencriptar_secreto()`
  mantiene un fallback a la derivación vieja (`_fernet_legacy()`) para
  secretos cifrados antes de que `TOTP_ENCRYPTION_KEY` existiera.

## Rotación de `JWT_SECRET` (sin downtime)

El backend acepta tokens firmados con DOS claves a la vez durante una
ventana de rotación: la actual (`JWT_SECRET`) y la anterior
(`JWT_SECRET_PREVIOUS`). Los tokens nuevos SIEMPRE se firman con la
actual. Esto permite rotar sin invalidar de golpe las sesiones activas.

Implementación: `core/auth.py::jwt_secrets_para_verificar()` (reutilizada
por `api/julix_endpoint.py::_decodificar_jwt`) — las claves se leen de
`os.environ` en cada verificación, no como constante de módulo, así que
una rotación toma efecto con un redeploy (Railway no recarga env vars con
un simple restart — hace falta `railway up`).

### Procedimiento

Las claves nuevas deben generarse con entropía real. Ejemplo (nunca
imprimir el valor en un log o en una terminal compartida):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

1. **Guardar la clave actual como anterior.** En Railway, setear
   `JWT_SECRET_PREVIOUS` = el valor actual de `JWT_SECRET`.
2. **Poner la clave nueva.** Setear `JWT_SECRET` = la clave nueva
   generada. (Ambos pasos disparan un redeploy en Railway; se pueden
   hacer juntos para un solo redeploy.)
3. **Verificar la ventana de rotación.** Tras el redeploy:
   - Un token viejo (firmado con la clave anterior, todavía dentro de sus
     15 min) sigue validando → se acepta vía `JWT_SECRET_PREVIOUS`.
   - Un token nuevo (emitido después del redeploy) se firma con
     `JWT_SECRET` y valida normal.
   - `POST /auth/refresh` con un refresh token válido devuelve un access
     token nuevo firmado con la clave nueva.
4. **Esperar a que caduquen los tokens viejos.** El JWT de vida más larga
   es el access token: 15 min (`JWT_EXPIRE_MINUTES`). Tras ~15 min desde
   el paso 2, ningún token firmado con la clave vieja sigue vigente.
   (El temp token de 2FA vive 5 min, cubierto de sobra por esa ventana.)
5. **Cerrar la rotación.** Borrar `JWT_SECRET_PREVIOUS` en Railway.
   **OJO (verificado en la rotación real del 2026-07-13):** a diferencia
   de `variable set`, `railway variable delete` no siempre dispara el
   redeploy automático que uno esperaría (mismo comportamiento en
   `set --skip-deploys`, pero acá no se pidió `--skip-deploys`). No
   confiar en que el borrado solo ya cerró la ventana -- confirmar con
   `railway deployment list --service vridik-api` que apareció un
   deployment nuevo DESPUÉS del delete. Si no apareció, forzar uno con
   `railway redeploy --service vridik-api --yes` antes de dar la
   rotación por cerrada. Sin este chequeo, la variable queda "borrada"
   en el panel de Railway pero el proceso corriendo sigue con el
   entorno viejo en memoria y sigue aceptando tokens firmados con la
   clave anterior indefinidamente -- exactamente el resultado que la
   rotación buscaba evitar. Una vez confirmado el redeploy real, solo
   se acepta la clave nueva; un token viejo que por lo que sea siga
   circulando ya no valida.

### Cuándo rotar

- Sospecha de que `JWT_SECRET` se filtró (log expuesto, commit accidental,
  acceso no autorizado al entorno de Railway).
- Rotación preventiva periódica (opcional; el roadmap no fija cadencia).

### Limitación honesta: "ensayado en staging"

El roadmap pide la rotación *"ensayada en staging"*. Este proyecto **no
tiene un entorno de staging real** — solo Railway producción y el service
container efímero de Postgres que usa CI (se destruye al terminar cada
job). Lo que sí se verificó, sin tocar la sesión de nadie en producción:

- **Tests reales del soporte de doble clave** (`tests/test_jwt_rotation.py`):
  token firmado con la clave vieja valida durante la ventana
  (`JWT_SECRET_PREVIOUS` seteada) y deja de valer al cerrarla; token
  firmado con la clave nueva valida; una clave desconocida se rechaza; el
  temp token de 2FA emitido antes de rotar se canjea durante la ventana.
- **El desacople `TOTP_ENCRYPTION_KEY`** se verificó end-to-end en
  producción real (enrolar + login con 2FA sobre un usuario de prueba)
  antes de habilitar cualquier rotación de `JWT_SECRET`.
- **Rotación real ejecutada contra producción, 2026-07-13** (no un
  ensayo): los 5 pasos completos, con verificación en cada uno contra la
  API real (token viejo válido durante la ventana, token nuevo válido,
  `POST /auth/refresh` con la clave nueva, espera real de los ~15min de
  vida del access token, cierre). Encontró y corrigió en el momento el
  hueco de `railway variable delete` documentado arriba (paso 5) — sin
  esa verificación, la rotación habría quedado "cerrada" en el papel
  pero abierta de verdad. Esta ejecución real, con ese hallazgo incluido,
  es más evidencia que cualquier ensayo en un staging que no existe.

Si en algún momento se arma un staging persistente, ensayar ahí el
procedimiento completo de 5 pasos (con un login real abierto que
sobreviva la rotación vía refresh) antes de confiar ciegamente en este
documento contra producción.

## Otras defensas ya implementadas (resumen)

- **Rate limiting de login** por email+IP (10 fallos/15 min) y de TOTP (5
  fallos/15 min) — `core/rate_limit.py`, sobre `auth_events`.
- **2FA TOTP obligatorio para admin** (`must_enroll`) — `api/admin_endpoint.py::get_current_admin`.
- **Códigos de respaldo de 2FA** de un solo uso, guardados solo como hash.
- **Headers de seguridad** en toda respuesta (HSTS, `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, CSP en Report-Only) — `api/julix_endpoint.py`.
- **CORS fail-closed**: sin `VRIDIK_ALLOWED_ORIGINS` configurado, se
  rechaza cualquier origen cross-origin.
- **Bitácora de auth** (`auth_events`, append-only) — login exitoso/fallido,
  refresh, detección de reuso de refresh token, logout, resets, cambios de 2FA.

## Reporte de vulnerabilidades

No hay un canal formal de disclosure definido todavía. Ante una
vulnerabilidad, contactar directamente al dev lead del proyecto.
