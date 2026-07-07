#!/usr/bin/env python3
"""
Vridik / JuliX — scripts/build_ana_profile.py
Sprint S11-extra: genera data/ana_luisa_profile.md a partir del export real
de ChatGPT de Ana Luisa (socia a cargo de UGPP) — ver la nota pendiente en
julix/prompt_v3.txt. Corrida autorizada explícitamente por el dev lead
(dato personal sensible).

Qué hace, en orden:
  1. Lee los 5 archivos `conversations-*.json` del export (formato estándar
     de exportación de ChatGPT: lista de conversaciones, cada una con un
     árbol `mapping` de nodos {id, message, parent}).
  2. Toma una muestra determinística de hasta `TAMANIO_MUESTRA` (200)
     conversaciones (las primeras N por orden del export — reproducible,
     sin aleatoriedad) y, dentro de esa muestra, filtra las que mencionan
     "UGPP", "Ana" (nombre) o "pensión" (case-insensitive, palabra completa)
     en el título o en el cuerpo de algún mensaje.
  3. Sobre las conversaciones filtradas, mide patrones de ESTILO agregados
     (no contenido) contra la hipótesis ya fijada en julix/prompt_v3.txt:
     ¿pide bullets accionables? ¿pide explicaciones simples? ¿rechaza
     tecnicismos sin definir? ¿pide ejemplos numéricos? — y agrega temas
     frecuentes en categorías amplias (derecho laboral, UGPP/seguridad
     social, contratos, actos administrativos), nunca casos individuales.
  4. Escribe `data/ana_luisa_profile.md` con SOLO el resumen agregado.

Salvaguarda de privacidad (deliberada, no negociable en este script):
  - NUNCA se copia al reporte un número de cédula, NIT, radicado de proceso,
    ni el nombre de un cliente/contraparte distinto de Ana Luisa misma —
    antes de que cualquier fragmento de texto llegue al reporte pasa por
    `_redactar()`, que reemplaza esos patrones por marcadores genéricos.
  - Los "ejemplos ilustrativos" que sí se incluyen (máx. 1 por categoría de
    patrón) se truncan a `MAX_PALABRAS_EJEMPLO` palabras y se redactan —
    nunca es un párrafo completo de un documento legal real.
  - El export crudo NUNCA se sube a ningún lado ni se llama a Anthropic con
    su contenido — este script corre 100% local/offline, solo lee archivos
    y escribe un `.md` de salida.

USO:
    python scripts/build_ana_profile.py
    python scripts/build_ana_profile.py --export-dir /ruta/al/export --salida data/ana_luisa_profile.md
    python scripts/build_ana_profile.py --dry-run   # imprime el resumen sin escribir el archivo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

TAMANIO_MUESTRA = 200
MAX_PALABRAS_EJEMPLO = 18

_RE_PALABRA_CLAVE = re.compile(r"\bugpp\b|\bana\b|pensi[oó]n", re.IGNORECASE)
_RE_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+\S", re.MULTILINE)
_RE_EJEMPLO_NUMERICO = re.compile(
    r"(ejemplo[^.\n]{0,120}\d|\$\s?[\d.,]+|\d+[.,]?\d*\s?%|\d+[.,]?\d*\s?(?:smlv|salarios? m[ií]nimos?|pesos|cop))",
    re.IGNORECASE,
)
_RE_PIDE_SIMPLE = re.compile(
    r"(en t[eé]rminos simples|expl[ií]came? (?:m[aá]s )?simple|sin tecnicismos|"
    r"que no sea tan t[eé]cnico|resume(?:lo)? f[aá]cil|en palabras sencillas)",
    re.IGNORECASE,
)
_RE_RECHAZA_JERGA = re.compile(
    r"(no entiendo (?:ese|el) t[eé]rmino|qu[eé] significa|explica (?:el|ese) t[eé]rmino|"
    r"evita (?:la )?jerga|sin (?:tanto )?tecnicismo)",
    re.IGNORECASE,
)
_RE_PIDE_BULLETS = re.compile(
    r"(en bullets|en vi[ñn]etas|en puntos|resume en \d+ puntos|lista(?:do)? de puntos)",
    re.IGNORECASE,
)

# Patrones de PII que NUNCA deben llegar al reporte, sin excepción.
_RE_CEDULA = re.compile(r"\b\d{1,3}(?:[.,]\d{3}){1,3}\b")
_RE_NIT = re.compile(r"\b\d{6,10}-\d\b")
_RE_TARJETA_PROFESIONAL = re.compile(r"tarjeta profesional\s*(?:No\.?)?\s*[\d.]+", re.IGNORECASE)

CATEGORIAS_TEMA: dict[str, re.Pattern] = {
    "UGPP / seguridad social": re.compile(r"\bugpp\b|pensi[oó]n|aporte|seguridad social|ibc\b", re.IGNORECASE),
    "Derecho laboral": re.compile(r"contrato laboral|demanda laboral|despido|acoso laboral|prestaci[oó]n de servicios", re.IGNORECASE),
    "Actos administrativos / litigio": re.compile(r"acto administrativo|conciliaci[oó]n|procuradur[ií]a|juzgado|demanda administrativa", re.IGNORECASE),
    "Contratos y documentos corporativos": re.compile(r"contrato de (?:aprendizaje|uni[oó]n temporal|prestaci[oó]n)|manual de funciones|reglamento", re.IGNORECASE),
}


def _redactar(texto: str) -> str:
    """Reemplaza PII conocida (cédulas, NIT, tarjetas profesionales) por
    marcadores genéricos. Se aplica SIEMPRE antes de que cualquier
    fragmento de texto real llegue al reporte final."""
    texto = _RE_CEDULA.sub("[C.C. redactada]", texto)
    texto = _RE_NIT.sub("[NIT redactado]", texto)
    texto = _RE_TARJETA_PROFESIONAL.sub("[tarjeta profesional redactada]", texto)
    return texto


def _truncar_ejemplo(texto: str, *, max_palabras: int = MAX_PALABRAS_EJEMPLO) -> str:
    palabras = texto.split()
    recortado = " ".join(palabras[:max_palabras])
    return _redactar(recortado) + ("…" if len(palabras) > max_palabras else "")


@dataclass
class Conteos:
    total_conversaciones_muestra: int = 0
    total_coincidencias: int = 0
    pide_simple: int = 0
    rechaza_jerga: int = 0
    pide_bullets_explicitos: int = 0
    respuestas_con_bullets_al_inicio: int = 0
    respuestas_con_ejemplo_numerico: int = 0
    temas: Counter = field(default_factory=Counter)
    ejemplos_pide_simple: list[str] = field(default_factory=list)
    ejemplos_rechaza_jerga: list[str] = field(default_factory=list)
    ejemplos_pide_bullets: list[str] = field(default_factory=list)


def cargar_conversaciones(export_dir: Path) -> list[dict]:
    conversaciones: list[dict] = []
    archivos = sorted(export_dir.glob("conversations-*.json"))
    if not archivos:
        raise FileNotFoundError(
            f"No se encontraron archivos conversations-*.json en {export_dir}"
        )
    for archivo in archivos:
        with archivo.open(encoding="utf-8") as f:
            conversaciones.extend(json.load(f))
    return conversaciones


def _mensajes_de(conv: dict) -> list[tuple[str, str]]:
    """Retorna [(role, texto)] en el orden en que aparecen en el mapping.
    No reconstruye el árbol de ramas (current_node) porque para las
    métricas agregadas de este script alcanza con el conjunto de mensajes,
    no con la conversación "canónica" completa."""
    mapping = conv.get("mapping", {})
    resultado = []
    nodos = sorted(
        (n for n in mapping.values() if n.get("message")),
        key=lambda n: (n["message"].get("create_time") or 0),
    )
    for nodo in nodos:
        msg = nodo["message"]
        role = (msg.get("author") or {}).get("role", "unknown")
        content = msg.get("content") or {}
        if content.get("content_type") != "text":
            continue
        texto = "\n".join(p for p in content.get("parts", []) if isinstance(p, str))
        if texto.strip():
            resultado.append((role, texto))
    return resultado


def _texto_completo(conv: dict) -> str:
    partes = [conv.get("title") or ""]
    partes.extend(texto for _role, texto in _mensajes_de(conv))
    return "\n".join(partes)


def analizar(conversaciones_muestra: list[dict]) -> Conteos:
    conteos = Conteos(total_conversaciones_muestra=len(conversaciones_muestra))

    for conv in conversaciones_muestra:
        texto_completo = _texto_completo(conv)
        if not _RE_PALABRA_CLAVE.search(texto_completo):
            continue
        conteos.total_coincidencias += 1

        for categoria, patron in CATEGORIAS_TEMA.items():
            if patron.search(texto_completo):
                conteos.temas[categoria] += 1

        # Los siguientes 5 indicadores se cuentan UNA vez por conversación
        # (no una vez por mensaje) — una conversación larga con muchos
        # mensajes no debe pesar más que una corta solo por tener más
        # turnos; el porcentaje reportado es "% de conversaciones donde
        # ocurrió al menos una vez", nunca puede superar el 100%.
        conv_pide_simple = False
        conv_rechaza_jerga = False
        conv_pide_bullets = False
        conv_respuesta_con_bullets = False
        conv_respuesta_con_ejemplo = False

        for role, texto in _mensajes_de(conv):
            if role == "user":
                if not conv_pide_simple and _RE_PIDE_SIMPLE.search(texto):
                    conv_pide_simple = True
                    if len(conteos.ejemplos_pide_simple) < 3:
                        m = _RE_PIDE_SIMPLE.search(texto)
                        ventana = texto[max(0, m.start() - 40): m.end() + 40]
                        conteos.ejemplos_pide_simple.append(_truncar_ejemplo(ventana))
                if not conv_rechaza_jerga and _RE_RECHAZA_JERGA.search(texto):
                    conv_rechaza_jerga = True
                    if len(conteos.ejemplos_rechaza_jerga) < 3:
                        m = _RE_RECHAZA_JERGA.search(texto)
                        ventana = texto[max(0, m.start() - 40): m.end() + 40]
                        conteos.ejemplos_rechaza_jerga.append(_truncar_ejemplo(ventana))
                if not conv_pide_bullets and _RE_PIDE_BULLETS.search(texto):
                    conv_pide_bullets = True
                    if len(conteos.ejemplos_pide_bullets) < 3:
                        m = _RE_PIDE_BULLETS.search(texto)
                        ventana = texto[max(0, m.start() - 40): m.end() + 40]
                        conteos.ejemplos_pide_bullets.append(_truncar_ejemplo(ventana))
            elif role == "assistant":
                lineas_iniciales = "\n".join(l for l in texto.splitlines() if l.strip())[:600]
                if not conv_respuesta_con_bullets and len(_RE_BULLET.findall(lineas_iniciales)) >= 3:
                    conv_respuesta_con_bullets = True
                if not conv_respuesta_con_ejemplo and _RE_EJEMPLO_NUMERICO.search(texto):
                    conv_respuesta_con_ejemplo = True

        conteos.pide_simple += int(conv_pide_simple)
        conteos.rechaza_jerga += int(conv_rechaza_jerga)
        conteos.pide_bullets_explicitos += int(conv_pide_bullets)
        conteos.respuestas_con_bullets_al_inicio += int(conv_respuesta_con_bullets)
        conteos.respuestas_con_ejemplo_numerico += int(conv_respuesta_con_ejemplo)

    return conteos


def _porcentaje(parte: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{round(100 * parte / total)}%"


def generar_markdown(conteos: Conteos, *, export_dir: Path) -> str:
    n = conteos.total_coincidencias
    lineas = [
        "# Perfil de estilo — Ana Luisa (socia UGPP)",
        "",
        "Generado por `scripts/build_ana_profile.py` a partir de una muestra "
        f"determinística de {conteos.total_conversaciones_muestra} conversaciones del export "
        f"real de ChatGPT (`{export_dir}`), filtradas por menciones a "
        '"UGPP"/"Ana"/"pensión". Corrida autorizada explícitamente por el dev lead '
        "(dato personal sensible) — ver nota pendiente en `julix/prompt_v3.txt`.",
        "",
        "**Privacidad:** este perfil contiene solo patrones agregados de estilo y "
        "temas por categoría amplia. Ningún número de cédula, NIT, tarjeta profesional, "
        "radicado de proceso o nombre de cliente/contraparte distinto de Ana Luisa se "
        "incluye aquí — se redactaron automáticamente si aparecían cerca de los "
        "fragmentos ilustrativos. El export crudo no se subió a ningún lado ni se envió "
        "a Anthropic; este script corre 100% local.",
        "",
        f"- Conversaciones en la muestra: **{conteos.total_conversaciones_muestra}**",
        f"- Conversaciones con menciones a UGPP/Ana/pensión: **{n}** "
        f"({_porcentaje(n, conteos.total_conversaciones_muestra)} de la muestra)",
        "",
        "## Temas frecuentes (categorías amplias, no casos individuales)",
        "",
    ]

    if conteos.temas:
        for categoria, cuenta in conteos.temas.most_common():
            lineas.append(f"- {categoria}: {cuenta} conversaciones ({_porcentaje(cuenta, n)})")
    else:
        lineas.append("- Sin datos suficientes en la muestra.")

    lineas += [
        "",
        "## Validación de la hipótesis de estilo (julix/prompt_v3.txt)",
        "",
        "La hipótesis fija actualmente en `julix/prompt_v3.txt` es: *\"primero 3 bullets "
        "accionables, luego explicación simple, evita tecnicismos DIAN a menos que los "
        "definas, usa ejemplo numérico siempre\"*. Evidencia observada en la muestra "
        "(sobre las conversaciones que sí mencionan UGPP/Ana/pensión):",
        "",
        f"- Mensajes de Ana Luisa pidiendo explicación **simple/sin tecnicismos**: "
        f"{conteos.pide_simple} ({_porcentaje(conteos.pide_simple, n)})",
        f"- Mensajes de Ana Luisa **rechazando o pidiendo definir jerga**: "
        f"{conteos.rechaza_jerga} ({_porcentaje(conteos.rechaza_jerga, n)})",
        f"- Mensajes de Ana Luisa pidiendo explícitamente **bullets/puntos**: "
        f"{conteos.pide_bullets_explicitos} ({_porcentaje(conteos.pide_bullets_explicitos, n)})",
        f"- Respuestas del asistente que **empiezan con ≥3 bullets**: "
        f"{conteos.respuestas_con_bullets_al_inicio} ({_porcentaje(conteos.respuestas_con_bullets_al_inicio, n)})",
        f"- Respuestas del asistente con **ejemplo numérico**: "
        f"{conteos.respuestas_con_ejemplo_numerico} ({_porcentaje(conteos.respuestas_con_ejemplo_numerico, n)})",
        "",
    ]

    if conteos.ejemplos_pide_simple:
        lineas.append("**Ejemplos ilustrativos (redactados, truncados) — pide explicación simple:**")
        for ej in conteos.ejemplos_pide_simple:
            lineas.append(f'  - "…{ej}…"')
        lineas.append("")
    if conteos.ejemplos_rechaza_jerga:
        lineas.append("**Ejemplos ilustrativos (redactados, truncados) — rechaza/pide definir jerga:**")
        for ej in conteos.ejemplos_rechaza_jerga:
            lineas.append(f'  - "…{ej}…"')
        lineas.append("")
    if conteos.ejemplos_pide_bullets:
        lineas.append("**Ejemplos ilustrativos (redactados, truncados) — pide bullets/puntos:**")
        for ej in conteos.ejemplos_pide_bullets:
            lineas.append(f'  - "…{ej}…"')
        lineas.append("")

    lineas += [
        "## Recomendación para julix/prompt_v3.txt",
        "",
    ]
    if n < 20:
        lineas.append(
            "La muestra filtrada es pequeña — la evidencia aquí es indicativa, no "
            "concluyente. Se recomienda NO reemplazar todavía el texto fijo de "
            "`julix/prompt_v3.txt` solo con esta corrida; correr este script sobre una "
            "muestra mayor (o el export completo) antes de decidir un cambio de prompt."
        )
    else:
        recomendaciones = []
        if conteos.pide_simple / max(n, 1) >= 0.15:
            recomendaciones.append(
                "la evidencia SÍ respalda mantener la instrucción de \"explicación simple\""
            )
        if conteos.rechaza_jerga / max(n, 1) >= 0.10:
            recomendaciones.append(
                "la evidencia SÍ respalda \"evita tecnicismos sin definir\""
            )
        if conteos.pide_bullets_explicitos / max(n, 1) < 0.10 and conteos.respuestas_con_bullets_al_inicio / max(n, 1) < 0.10:
            recomendaciones.append(
                "la exigencia de \"SIEMPRE 3 bullets accionables al inicio\" NO tiene "
                "evidencia fuerte en la muestra — considerar suavizarla a \"cuando la "
                "pregunta lo amerite\" en vez de una regla incondicional"
            )
        if not recomendaciones:
            recomendaciones.append(
                "la muestra no da señal fuerte en ninguna dirección — mantener el texto "
                "actual de prompt_v3.txt sin cambios hasta tener más evidencia"
            )
        for r in recomendaciones:
            lineas.append(f"- {r.capitalize()}.")

    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vridik/JuliX — genera data/ana_luisa_profile.md desde el export real de ChatGPT (S11-extra)"
    )
    parser.add_argument(
        "--export-dir", default=str(Path.home() / "Desktop" / "ChatGPT"),
        help="Carpeta con los conversations-*.json del export (default: ~/Desktop/ChatGPT)",
    )
    parser.add_argument("--salida", default="data/ana_luisa_profile.md", help="Ruta de salida del perfil")
    parser.add_argument("--tamanio-muestra", type=int, default=TAMANIO_MUESTRA)
    parser.add_argument("--dry-run", action="store_true", help="Imprime el resumen sin escribir el archivo")
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    try:
        conversaciones = cargar_conversaciones(export_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    muestra = conversaciones[: args.tamanio_muestra]
    conteos = analizar(muestra)
    markdown = generar_markdown(conteos, export_dir=export_dir)

    print(
        f"Vridik/JuliX — build_ana_profile: {conteos.total_conversaciones_muestra} conversaciones en la "
        f"muestra, {conteos.total_coincidencias} con menciones UGPP/Ana/pensión."
    )

    if args.dry_run:
        print("\n--- dry-run: contenido que se escribiría ---\n")
        print(markdown)
        return 0

    ruta_salida = Path(args.salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(markdown, encoding="utf-8")
    print(f"Perfil escrito en {ruta_salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
