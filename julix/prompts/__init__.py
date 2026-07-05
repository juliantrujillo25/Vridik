"""
Vridik / JuliX — prompts/__init__.py
Loader de prompts versionados en archivo. Nunca se escriben prompts en
código Python: viven aquí como archivos .md con un encabezado obligatorio,
para que S6 (iteración de prompts) pueda diffear versiones y S5 (banco de
evaluación) pueda referenciar exactamente qué versión se usó por hash.

Formato de archivo (ver prompts/v1_ugpp_demanda.md):

    ---
    v: 1
    tarea: ugpp_demanda
    modelo_sugerido: claude-sonnet-4-20250514
    hipotesis: "..."
    ---
    <contenido del prompt de sistema>

Actualización S4: el loader ya NO asume ningún patrón de nombre de archivo
(antes exigía `{tarea}_v*.md`). Ahora escanea TODOS los .md de este
directorio y filtra por el campo `tarea` del encabezado — así conviven sin
conflicto archivos con distintas convenciones de nombre acumuladas en
distintos sprints (p.ej. `redaccion_ugpp_v1.md` de S4 original junto con
`v1_ugpp_demanda.md` / `v2_laboral_consulta.md` de esta actualización),
sin necesidad de renombrar nada ya publicado.

NO SE EJECUTA EN ESTE ENTREGABLE — esqueleto de referencia para Sprint S4.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent
_HEADER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


@dataclass
class PromptVersion:
    tarea: str
    version: int
    modelo_sugerido: str
    hipotesis: str
    contenido: str
    hash: str
    archivo: str


def _parse_archivo(path: Path) -> PromptVersion:
    texto = path.read_text(encoding="utf-8")
    match = _HEADER_RE.match(texto)
    if not match:
        raise ValueError(f"Prompt sin encabezado v: válido: {path.name}")
    header_raw, contenido = match.groups()
    campos = dict(_FIELD_RE.findall(header_raw))

    if "v" not in campos or "tarea" not in campos:
        raise ValueError(f"Encabezado incompleto (falta v/tarea) en {path.name}")

    contenido = contenido.strip()
    content_hash = hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:16]

    return PromptVersion(
        tarea=campos["tarea"],
        version=int(campos["v"]),
        modelo_sugerido=campos.get("modelo_sugerido", "claude-sonnet-4-20250514"),
        hipotesis=campos.get("hipotesis", ""),
        contenido=contenido,
        hash=content_hash,
        archivo=path.name,
    )


def _todas_las_versiones(tarea: str) -> list[PromptVersion]:
    """Escanea todos los .md del directorio (sin asumir convención de
    nombre) y filtra por el campo `tarea` del encabezado."""
    versiones = []
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        try:
            prompt = _parse_archivo(path)
        except ValueError:
            continue  # archivo sin encabezado válido (p.ej. README futuro) — se ignora, no rompe el loader
        if prompt.tarea == tarea:
            versiones.append(prompt)
    if not versiones:
        raise FileNotFoundError(f"No hay prompts para la tarea '{tarea}' en {PROMPTS_DIR}")
    return sorted(versiones, key=lambda p: p.version)


def load_prompt(tarea: str, version: int | None = None) -> PromptVersion:
    """Carga la versión pedida, o la más alta disponible si version es None.
    Máximo 4 versiones vivas por tarea (regla de S6) — esto no se valida
    aquí sino en el proceso de PR review de PROMPTS.md."""
    versiones = _todas_las_versiones(tarea)
    if version is None:
        return versiones[-1]
    for v in versiones:
        if v.version == version:
            return v
    raise ValueError(f"Versión {version} no encontrada para tarea '{tarea}'")


def listar_tareas_disponibles() -> set[str]:
    """Utilidad de diagnóstico (S6, PROMPTS.md): qué tareas tienen al menos
    un prompt versionado hoy en el repo."""
    tareas = set()
    for path in PROMPTS_DIR.glob("*.md"):
        try:
            tareas.add(_parse_archivo(path).tarea)
        except ValueError:
            continue
    return tareas
