"""
Vridik — procesal/clasificador_actuaciones.py
Fase 2 (Copiloto Procesal): clasificación IA de una actuación judicial ya
en texto -- auto_admisorio / requerimiento / fallo / traslado / otro,
sobre Haiku (roadmap: "Clasificador IA de actuaciones (auto admisorio,
requerimiento, fallo, traslado) sobre Haiku").

Reusa el prompt versionado que YA existía para esto
(julix/prompts/clasificacion_documento_v1.md, tarea "clasificacion_documento")
en vez de duplicar uno nuevo -- las 5 categorías de ese prompt (las 4 del
roadmap de Fase 2 más "otro" como válvula de seguridad) son exactamente
las que hacen falta acá. No hace falta un feed de actuaciones en vivo
para que esto funcione: solo el texto de la actuación, ya extraído por
quien sea (proveedor de monitoreo, scraping propio, o pegado a mano) --
esa capa de ingesta es la que sigue bloqueada en la decisión de negocio
"build-vs-integrate" (ver procesal/__init__.py), esta no.
"""

from __future__ import annotations

from dataclasses import dataclass

from julix import prompts
from julix.client import JuliXClient
from julix.errors import JuliXInvalidFormatError

TAREA = "clasificacion_documento"

CATEGORIAS_VALIDAS = frozenset({"auto_admisorio", "requerimiento", "fallo", "traslado", "otro"})


@dataclass
class ResultadoClasificacion:
    categoria: str
    confianza: float
    texto_bruto: str  # respuesta cruda del modelo (JSON), para auditoría/debug


async def clasificar_actuacion(
    client: JuliXClient,
    *,
    texto_actuacion: str,
    user_id: str,
    caso_id: str | None = None,
    prompt_version: int | None = None,
) -> ResultadoClasificacion:
    """Clasifica el texto de una actuación en una de CATEGORIAS_VALIDAS.

    Nunca inventa una categoría fuera de la lista ni corrige en silencio
    una salida mal formada -- si el modelo no devuelve JSON válido, o
    devuelve una categoría desconocida, o `confianza` no es numérico, se
    levanta JuliXInvalidFormatError (mismo principio que el resto de
    JuliX en julix/errors.py: ningún fallo se disfraza de éxito). Los
    demás fallos de JuliX (timeout/rate_limit/overloaded, ver
    julix/client.py) se propagan tal cual -- el llamador decide cómo
    presentarlos, esta función no los oculta."""
    if not texto_actuacion.strip():
        raise ValueError("texto_actuacion no puede estar vacío")

    prompt = prompts.load_prompt(TAREA, version=prompt_version)

    texto_bruto = ""
    async for chunk in client.stream_completion(
        tarea=TAREA,
        system_prompt=prompt.contenido,
        user_content=texto_actuacion,
        user_id=user_id,
        caso_id=caso_id,
        prompt_version=prompt.version,
        prompt_hash=prompt.hash,
    ):
        texto_bruto += chunk

    datos = JuliXClient.validar_json(texto_bruto)

    categoria = datos.get("categoria")
    if categoria not in CATEGORIAS_VALIDAS:
        raise JuliXInvalidFormatError(
            f"Categoría fuera de la lista esperada: {categoria!r}", partial_text=texto_bruto,
        )

    try:
        confianza = float(datos.get("confianza", 0.0))
    except (TypeError, ValueError) as exc:
        raise JuliXInvalidFormatError(
            f"'confianza' no es numérico: {datos.get('confianza')!r}", partial_text=texto_bruto,
        ) from exc

    return ResultadoClasificacion(categoria=categoria, confianza=confianza, texto_bruto=texto_bruto)
