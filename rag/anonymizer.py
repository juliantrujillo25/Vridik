#!/usr/bin/env python3
"""
Vridik / JuliX — rag/anonymizer.py
Anonimización de documentos de clientes ANTES de generar cualquier embedding
o guardarlos en rag_chunks (usado por rag/ingest_desktop.py). Nunca se envía
texto sin anonimizar a sentence-transformers ni se persiste en la BD.

Dos mecanismos, en este orden:
  1. Identificadores explícitos (NIT, cédula) por regex — más confiable que
     NER para números, que spaCy no siempre etiqueta de forma consistente.
  2. Personas (PERSON/PER) vía NER de spaCy (es_core_news_sm) si el modelo
     está disponible; si no, un fallback heurístico por mayúsculas (menos
     preciso, documentado explícitamente como tal, nunca silencioso).

Reglas de reemplazo:
  - Persona identificada (nombre propio)  -> [CLIENTE]
  - NIT / cédula (secuencia numérica con formato de identificación)
    -> [ID]

Esto NO es anonimización certificada para fines forenses/regulatorios — es
una primera capa de higiene antes de la ingesta al RAG. La revisión humana
(guardrail "Nota del revisor" de julix/prompts/v3_*.md) sigue siendo la
última línea de defensa contra fugas de PII en las respuestas de JuliX.
"""

from __future__ import annotations

import re
from functools import lru_cache

try:
    import spacy
except ImportError:  # pragma: no cover
    spacy = None  # type: ignore

MODELO_SPACY = "es_core_news_sm"

# --- Identificadores (NIT / cédula) -------------------------------------
# Formatos colombianos comunes: "900.123.456-7", "79.183.546", "CC 79183546",
# "NIT: 900123456-7". Se exige un mínimo de 6 dígitos para no capturar
# números de artículo/ley (p.ej. "Art. 179") por error.
_RE_ID_ETIQUETADO = re.compile(
    r"\b(?:C\.?C\.?|NIT|Nit|Cédula|C[eé]dula de [Cc]iudadan[ií]a)\s*[:\.]?\s*([\d][\d\.\-]{5,})",
    re.IGNORECASE,
)
_RE_ID_FORMATEADO = re.compile(r"\b\d{1,3}(?:\.\d{3}){1,3}-?\d?\b")  # 79.183.546 / 900.123.456-7
_RE_ID_PLANO = re.compile(r"\b\d{7,10}\b")  # cédula/NIT sin puntos, 7-10 dígitos (nunca años: filtrado aparte)

_ANIOS_A_EXCLUIR = re.compile(r"^(19|20)\d{2}$")  # nunca enmascarar un año de 4 dígitos como si fuera ID


def _es_anio(fragmento: str) -> bool:
    return bool(_ANIOS_A_EXCLUIR.match(fragmento.strip()))


def _enmascarar_identificadores(texto: str) -> str:
    texto = _RE_ID_ETIQUETADO.sub("[ID]", texto)
    texto = _RE_ID_FORMATEADO.sub(lambda m: m.group() if _es_anio(m.group()) else "[ID]", texto)
    texto = _RE_ID_PLANO.sub(lambda m: m.group() if _es_anio(m.group()) else "[ID]", texto)
    return texto


# --- Personas (NER spaCy + fallback heurístico) -------------------------
# Palabras que NUNCA deben tratarse como nombre de persona en el fallback
# heurístico (entidades jurídicas/normativas que también van en mayúscula
# inicial y podrían confundirse con nombres propios).
_PALABRAS_EXCLUIDAS_NOMBRE = {
    "Ley", "Decreto", "Sentencia", "Resolución", "Resolucion", "Auto", "Consejo",
    "Estado", "Corte", "Suprema", "Constitucional", "Tribunal", "Superior",
    "Administrativo", "Código", "Codigo", "Sustantivo", "Trabajo", "UGPP",
    "Colombia", "Sección", "Seccion", "Cuarta", "Radicado", "Expediente",
    "Procuraduría", "Procuraduria", "Judicial", "Agencia", "Nacional", "Defensa",
    "Jurídica", "Juridica", "Recurso", "Reconsideración", "Reconsideracion",
    "Requerimiento", "Información", "Informacion", "Constancia", "Notificación",
    "Notificacion", "Anexo", "Balance", "Movimiento", "Auxiliar", "Certificación",
    "Certificacion", "Poder", "Petición", "Peticion", "Acreditación", "Acreditacion",
}

_RE_NOMBRE_HEURISTICO = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})\b"
)


@lru_cache(maxsize=1)
def _cargar_modelo_spacy():
    """Carga perezosa y cacheada del modelo spaCy. Si el paquete o el
    modelo no están instalados, retorna None y anonimizar_texto() cae al
    fallback heurístico — nunca lanza una excepción que bloquee la
    ingesta completa por falta de un modelo de NER."""
    if spacy is None:
        return None
    try:
        return spacy.load(MODELO_SPACY)
    except OSError:
        return None


def _enmascarar_personas_spacy(texto: str, modelo) -> str:
    doc = modelo(texto)
    resultado = texto
    entidades_persona = [ent for ent in doc.ents if ent.label_ in ("PER", "PERSON")]
    # Reemplazo de atrás hacia adelante para no invalidar los offsets de
    # las entidades restantes al cambiar la longitud del texto.
    for ent in sorted(entidades_persona, key=lambda e: e.start_char, reverse=True):
        resultado = resultado[: ent.start_char] + "[CLIENTE]" + resultado[ent.end_char :]
    return resultado


def _enmascarar_personas_heuristico(texto: str) -> str:
    """Fallback SIN spaCy: cualquier secuencia de 2-4 palabras capitalizadas
    consecutivas se trata como nombre propio, salvo que contenga una
    palabra de _PALABRAS_EXCLUIDAS_NOMBRE. Es deliberadamente más agresivo
    (falsos positivos preferibles a fugas de nombres reales) — se marca
    explícitamente como heurístico en los logs de ingest_desktop.py para
    que el equipo sepa que sin spaCy instalado la anonimización es menos
    precisa."""

    def _reemplazar(m: re.Match) -> str:
        candidato = m.group(1)
        palabras = candidato.split()
        if any(p in _PALABRAS_EXCLUIDAS_NOMBRE for p in palabras):
            return candidato
        return "[CLIENTE]"

    return _RE_NOMBRE_HEURISTICO.sub(_reemplazar, texto)


def modo_ner_activo() -> str:
    """Reporta qué mecanismo de detección de personas está activo — usado
    por ingest_desktop.py para dejar constancia en el log/manifest de si la
    anonimización de esta corrida usó spaCy real o el fallback heurístico."""
    return "spacy" if _cargar_modelo_spacy() is not None else "heuristico_mayusculas"


def anonimizar_texto(texto: str) -> str:
    """Punto de entrada único usado por rag/ingest_desktop.py. Aplica
    primero identificadores (regex, no depende de spaCy) y luego personas
    (spaCy si está disponible, si no heurística)."""
    texto = _enmascarar_identificadores(texto)
    modelo = _cargar_modelo_spacy()
    if modelo is not None:
        texto = _enmascarar_personas_spacy(texto, modelo)
    else:
        texto = _enmascarar_personas_heuristico(texto)
    return texto


def is_duplicate(hash_valor: str, conocidos: set[str]) -> bool:
    """Chequeo de duplicado O(1) contra un set de hashes ya vistos (nivel
    archivo o nivel chunk, según quién lo llame). Separado en su propia
    función para que rag/ingest_desktop.py pueda testear/mockear la lógica
    de dedup sin depender de si hay o no conexión a BD."""
    return hash_valor in conocidos
