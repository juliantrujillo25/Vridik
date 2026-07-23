"""
Vridik — tests/test_rls_coverage.py
Hardening (core/rls.py): red de seguridad contra el riesgo real del diseño
fail-open elegido para RLS -- cada conexión nueva arranca con
`app.bypass_rls='true'` por defecto (ver docstring de core/rls.py), y solo
se angosta al despacho real cuando algo llama explícitamente a
`aplicar_contexto_despacho()`. Un endpoint FUTURO que decodifique su
propio JWT en vez de depender de `get_current_user`/`get_current_admin`/
`get_current_superadmin` (que sí angostan, vía `_resolver_usuario`)
heredaría el bypass en silencio -- exactamente lo que le pasaba HOY a
`api/julix_endpoint.py::julix_query`/`julix_stream` antes de esta pasada
(encontrado por revisión manual, no por ningún test -- este archivo existe
para que la próxima vez lo atrape un test).

Chequeo estático (AST), deliberadamente simple y con un allowlist
explícito: recorre cada handler de ruta en `api/*_endpoint.py` y exige que
dependa de una de las tres dependencies que angostan, O esté en el
allowlist de abajo con una razón documentada. No es un analizador
semántico completo (no rastrea si una función `core.*` llamada
internamente toca una de las 4 tablas protegidas) -- es una barrera barata
contra la clase de bug concreta que ya pasó una vez, no una prueba
exhaustiva de que RLS está bien aplicado en todos lados (eso lo prueba
tests/test_rls.py).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"

# Dependencies de api/admin_endpoint.py que, al resolverse, llaman
# core.rls.aplicar_contexto_despacho() vía _resolver_usuario -- cualquier
# handler que dependa de una de estas ya queda angosteado antes de correr
# su cuerpo.
_DEPENDENCIAS_QUE_ANGOSTAN = {"get_current_user", "get_current_admin", "get_current_superadmin"}

# (archivo, nombre de función) -> razón por la que está exenta a
# propósito. Cualquier ruta NUEVA que no dependa de una dependency de
# arriba y no esté acá hace fallar este test -- agregarla a mano, con
# razón, es la forma correcta de silenciarlo (nunca in-line en el código
# de producción).
_ALLOWLIST: dict[tuple[str, str], str] = {
    ("auth_endpoint.py", "register"): "crea un despacho nuevo -- todavía no existe despacho_id que angostar",
    ("auth_endpoint.py", "login"): "lookup por email cross-tenant, antes de saber a qué despacho pertenece",
    ("auth_endpoint.py", "login_2fa"): "mismo motivo que login (todavía no pasó por _resolver_usuario)",
    ("auth_endpoint.py", "refresh"): (
        "solo toca refresh_tokens -- RLS indirecto vía user_id->despacho_id (ensure_rls_policies_"
        "soporte), este handler nunca llama aplicar_contexto_despacho() pero la conexión se queda "
        "en bypass_rls='true' (default del middleware), así que ve su propio refresh_token igual"
    ),
    ("auth_endpoint.py", "logout"): (
        "solo toca refresh_tokens -- mismo motivo que refresh (bypass_rls='true' por defecto, nunca "
        "angosteado acá)"
    ),
    ("auth_endpoint.py", "me"): "lee su propia fila de users por PK del JWT, mismo criterio que _resolver_usuario",
    ("auth_endpoint.py", "cambiar_password"): "misma PK propia, nunca cross-tenant",
    ("auth_endpoint.py", "setup_2fa"): "misma PK propia, nunca cross-tenant",
    ("auth_endpoint.py", "verify_2fa"): "misma PK propia, nunca cross-tenant",
    ("auth_endpoint.py", "regenerate_backup_codes"): "misma PK propia, nunca cross-tenant",
    ("julix_endpoint.py", "julix_query"): "resuelve despacho_id y llama aplicar_contexto_despacho() explícitamente",
    ("julix_endpoint.py", "julix_stream"): "ídem, dentro de _generar_stream_sse (conexión dedicada propia)",
    ("julix_endpoint.py", "julix_health"): "no toca la base de datos",
    ("julix_endpoint.py", "health"): "no toca la base de datos",
}

_DECORADORES_DE_RUTA = {"get", "post", "patch", "put", "delete"}


def _es_decorador_de_ruta(decorator: ast.expr) -> bool:
    """True si el decorador es router.<verbo>(...) o app.<verbo>(...) --
    api/julix_endpoint.py usa `app` (FastAPI() propio), el resto usa
    `router` (APIRouter)."""
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _DECORADORES_DE_RUTA:
        return False
    return isinstance(func.value, ast.Name) and func.value.id in ("router", "app")


def _depende_de_narrowing(func_def: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """Busca `Depends(get_current_user)` (o *_admin/*_superadmin) entre los
    valores por defecto de los parámetros del handler."""
    defaults = list(func_def.args.defaults) + list(func_def.args.kw_defaults)
    for default in defaults:
        if default is None or not isinstance(default, ast.Call):
            continue
        if not (isinstance(default.func, ast.Name) and default.func.id == "Depends"):
            continue
        for arg in default.args:
            if isinstance(arg, ast.Name) and arg.id in _DEPENDENCIAS_QUE_ANGOSTAN:
                return True
    return False


def _handlers_sin_narrowing(ruta_archivo: Path) -> list[str]:
    arbol = ast.parse(ruta_archivo.read_text(encoding="utf-8"))
    sin_narrowing = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not any(_es_decorador_de_ruta(d) for d in nodo.decorator_list):
            continue
        if _depende_de_narrowing(nodo):
            continue
        if (ruta_archivo.name, nodo.name) in _ALLOWLIST:
            continue
        sin_narrowing.append(nodo.name)
    return sin_narrowing


def test_todo_handler_de_ruta_angosta_el_contexto_o_esta_en_el_allowlist():
    archivos = sorted(API_DIR.glob("*_endpoint.py"))
    assert archivos, "no se encontraron archivos api/*_endpoint.py -- ¿cambió la estructura del repo?"

    hallazgos: dict[str, list[str]] = {}
    for archivo in archivos:
        sin_narrowing = _handlers_sin_narrowing(archivo)
        if sin_narrowing:
            hallazgos[archivo.name] = sin_narrowing

    assert not hallazgos, (
        "Handlers de ruta que no dependen de get_current_user/get_current_admin/"
        "get_current_superadmin y no están en el allowlist de tests/test_rls_coverage.py "
        f"(revisar si necesitan aplicar_contexto_despacho() explícito, o agregarlos al "
        f"allowlist con una razón): {hallazgos}"
    )


def test_el_allowlist_no_tiene_entradas_obsoletas():
    """Si una función del allowlist ya no existe (se borró o se renombró),
    o ya dejó de necesitar la excepción (empezó a depender de una
    dependency que angosta), avisa -- un allowlist que crece sin nunca
    reducirse es una señal de que nadie lo revisa."""
    for archivo_nombre, nombre_funcion in _ALLOWLIST:
        ruta_archivo = API_DIR / archivo_nombre
        assert ruta_archivo.exists(), f"{archivo_nombre} en el allowlist ya no existe"
        arbol = ast.parse(ruta_archivo.read_text(encoding="utf-8"))
        nombres_definidos = {
            n.name for n in ast.walk(arbol) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
        }
        assert nombre_funcion in nombres_definidos, (
            f"{archivo_nombre}::{nombre_funcion} está en el allowlist pero ya no existe -- "
            "borrar la entrada de tests/test_rls_coverage.py"
        )
