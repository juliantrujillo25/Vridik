"""
Vridik / JuliX — rag/context_builder.py
Sprint S6: recuperación semántica real sobre PostgreSQL + pgvector.
Sprint S9: búsqueda mejorada — boost por año (prioriza 2019-2026), boost
por tipo de fuente (ley > decreto > jurisprudencia) y score de similitud
expuesto en la metadata de cada chunk.
Sprint S11: boost/filtro por `fuente` de cliente (metadata JSONB, ver
rag/ingest_desktop.py) — los chunks de expedientes de clientes prioritarios
("Giraldo Velasco", "Marta Arias") suben en el ranking cuando compiten con
chunks del corpus normativo general para la misma pregunta.

Distinto de julix/context_builder.py (que arma el prompt final con
presupuesto de tokens y prioridad normativa a partir de chunks YA
recuperados): este módulo es el que HACE la recuperación. Toma la pregunta
del usuario, la embebe con un modelo local
(sentence-transformers/all-MiniLM-L6-v2, 384 dimensiones — nunca se manda
la pregunta a un proveedor externo de embeddings) y busca los chunks más
cercanos en `rag_chunks` (ver rag/sql/rag_chunks_schema.sql) usando
pgvector (distancia coseno).

Desde S9, `buscar_contexto` no se queda con el ranking puro de pgvector:
trae un pool más grande de candidatos (`top_k * FACTOR_POOL_CANDIDATOS`) y
los reordena en Python por `.score` (similitud ajustada por tipo de fuente
y recencia) antes de truncar a `top_k`. Esto evita que una sentencia de
2015 le gane a un artículo de ley vigente solo por estar marginalmente más
cerca en el espacio de embeddings.

Cada chunk recuperado trae su cita [norma, artículo, párrafo] — esa cita es
la que julix/service.py inyecta en el contexto para que JuliX solo pueda
citar lo que efectivamente está en `rag_chunks`.

NO SE EJECUTA CONTRA UNA BASE DE DATOS NI SE DESCARGA/CORRE EL MODELO REAL
EN ESTE ENTREGABLE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

logger = logging.getLogger("vridik.rag.context_builder")

MODELO_EMBEDDING = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONES_EMBEDDING = 384
TOP_K_POR_DEFECTO = 5

# --- S9: parámetros de re-ranking por tipo de fuente y recencia ---------
# Peso por tipo de fuente: ley > decreto > jurisprudencia (misma jerarquía
# kelseniana que _JERARQUIA_POR_PALABRA_CLAVE, expresada como multiplicador
# de similitud en vez de nivel ordinal).
PESO_POR_TIPO: dict[str, float] = {
    "ley": 1.00,
    "decreto": 0.92,
    "jurisprudencia": 0.85,
}
PESO_POR_TIPO_DEFECTO = 0.90  # chunks legacy sin tipo_fuente (pre-S7)

ANIO_PRIORITARIO_DESDE = 2019
ANIO_PRIORITARIO_HASTA = 2026
BONUS_ANIO_PRIORITARIO = 0.05

# Cuántos candidatos de más trae la consulta SQL antes del re-ranking en
# Python (top_k * FACTOR_POOL_CANDIDATOS) — un pool más grande da margen
# para que el boost por tipo/año cambie el orden sin perder recall.
FACTOR_POOL_CANDIDATOS = 3

# --- S11: boost por fuente de cliente (rag/ingest_desktop.py) -----------
# Expedientes de clientes prioritarios: cuando un chunk de estos clientes
# compite con un chunk del corpus normativo general para la misma
# pregunta, sube en el ranking — casos activos del despacho pesan más que
# jurisprudencia genérica al responder sobre ESE expediente puntual.
FUENTES_CLIENTE_PRIORITARIAS: frozenset[str] = frozenset({"Giraldo Velasco", "Marta Arias"})
BONUS_FUENTE_CLIENTE_PRIORITARIA = 0.08

# Heurística de jerarquía kelseniana a partir del nombre de la norma. Es una
# aproximación para el RAG base de S6 (rag_chunks no tiene columna jerarquia,
# a diferencia de corpus_documents en S7-S9, que sí la modela explícitamente).
_JERARQUIA_POR_PALABRA_CLAVE: list[tuple[str, int]] = [
    ("constitución", 1),
    ("tratado", 2),
    ("ley", 3),
    ("decreto", 4),
    ("resolución", 5),
    ("resolucion", 5),
    ("circular", 5),
    ("concepto", 6),
    ("sentencia", 6),
]


@dataclass
class ChunkRecuperado:
    norma: str
    articulo: str
    parrafo: str | None
    texto: str
    distancia: float
    # --- Campos S9, opcionales: chunks legacy (S6, pre-expansión de
    # corpus) y las construcciones existentes en tests/test_julix.py no
    # los pasan — deben tener default None para no romper compatibilidad.
    anio: int | None = None
    tribunal: str | None = None
    tipo_fuente: str | None = None
    # --- Campo S11, opcional: 'fuente' viene de metadata->>'fuente'
    # (rag/ingest_desktop.py), NULL para chunks del corpus normativo
    # (rag/ingest_corpus.py no puebla la columna metadata todavía).
    fuente_cliente: str | None = None

    @property
    def cita(self) -> str:
        """Cita formateada [norma, artículo, párrafo] pedida en S6."""
        partes = [self.norma, self.articulo]
        if self.parrafo:
            partes.append(self.parrafo)
        return "[" + ", ".join(partes) + "]"

    @property
    def jerarquia(self) -> int:
        # S9: si el chunk ya trae tipo_fuente (ingestado vía S7+
        # rag/ingest_corpus.py), se usa directamente — más confiable que
        # adivinar por palabra clave en el nombre de la norma.
        if self.tipo_fuente == "ley":
            return 3
        if self.tipo_fuente == "decreto":
            return 4
        if self.tipo_fuente == "jurisprudencia":
            return 6

        norma_lower = self.norma.lower()
        for palabra, nivel in _JERARQUIA_POR_PALABRA_CLAVE:
            if palabra in norma_lower:
                return nivel
        return 3  # default conservador: se trata como "ley" si no se reconoce el patrón

    @property
    def tokens_estimados(self) -> int:
        # Aproximación 1 token ~= 0.75 palabras (misma heurística que
        # rag/ingest_ugpp.py cuando no hay tokenizer real disponible).
        return max(1, round(len(self.texto.split()) / 0.75))

    @property
    def similitud(self) -> float:
        """Convierte distancia coseno (0=idéntico, 2=opuesto) a un score de
        similitud en [0, 1] — más intuitivo para exponer en metadata/API
        que la distancia cruda."""
        return max(0.0, min(1.0, 1.0 - self.distancia))

    @property
    def score(self) -> float:
        """Score final de re-ranking S9: similitud ajustada por peso de
        tipo de fuente y bonus de recencia. Es el criterio de orden que
        usa `buscar_contexto` para reordenar el pool de candidatos — NO
        reemplaza `similitud` (que se sigue exponiendo tal cual en la
        metadata para trazabilidad)."""
        peso_tipo = PESO_POR_TIPO.get(self.tipo_fuente or "", PESO_POR_TIPO_DEFECTO)
        bonus_anio = (
            BONUS_ANIO_PRIORITARIO
            if self.anio is not None and ANIO_PRIORITARIO_DESDE <= self.anio <= ANIO_PRIORITARIO_HASTA
            else 0.0
        )
        bonus_fuente_cliente = (
            BONUS_FUENTE_CLIENTE_PRIORITARIA
            if self.fuente_cliente in FUENTES_CLIENTE_PRIORITARIAS
            else 0.0
        )
        return self.similitud * peso_tipo + bonus_anio + bonus_fuente_cliente


@lru_cache(maxsize=1)
def _cargar_modelo_embedding() -> "SentenceTransformer":
    """Carga perezosa y cacheada del modelo local de embeddings. Nunca llama
    a un proveedor externo de embeddings — corre en la misma infraestructura
    de Vridik (a diferencia de julix/client.py, que sí llama a Anthropic)."""
    if SentenceTransformer is None:
        raise RuntimeError(
            "Falta la dependencia 'sentence-transformers' (pip install sentence-transformers)"
        )
    logger.info("Vridik/RAG: cargando modelo de embeddings %s", MODELO_EMBEDDING)
    return SentenceTransformer(MODELO_EMBEDDING)


def embeber_texto(texto: str) -> list[float]:
    """Embebe un texto (pregunta o chunk) con el modelo local. Usado tanto
    por este módulo (para la pregunta) como por rag/ingest_ugpp.py (para los
    chunks del corpus) — mismo modelo, mismo espacio vectorial."""
    modelo = _cargar_modelo_embedding()
    vector = modelo.encode(texto, normalize_embeddings=True)
    return vector.tolist()


def _embedding_a_literal_pgvector(embedding: list[float]) -> str:
    """pgvector acepta el literal de texto '[0.1,0.2,...]' casteado a
    ::vector — evita depender de que el driver tenga el codec de pgvector
    registrado (asyncpg no lo trae por defecto)."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


async def buscar_contexto(
    db_connection,
    pregunta: str,
    *,
    top_k: int = TOP_K_POR_DEFECTO,
    solo_fuentes: list[str] | None = None,
) -> list[ChunkRecuperado]:
    """Embebe la pregunta, trae un pool de `top_k * FACTOR_POOL_CANDIDATOS`
    chunks candidatos ordenados por distancia pgvector (coseno, `<=>`), y
    los reordena en Python por `.score` (similitud + boost por tipo de
    fuente + boost por recencia + boost por fuente de cliente, ver S9/S11)
    antes de truncar a `top_k`.

    `solo_fuentes` (S11, opcional): si se pasa una lista de nombres de
    fuente (p.ej. ["Giraldo Velasco"]), la búsqueda se restringe a chunks
    de esas fuentes (filtro duro vía metadata->>'fuente', útil cuando un
    abogado quiere acotar la respuesta a UN expediente de cliente). Si es
    None (caso normal), no hay filtro duro — el boost de
    FUENTES_CLIENTE_PRIORITARIAS sigue aplicando igual sobre todo el pool.

    Retorna lista vacía si no hay chunks — nunca inventa contexto; es
    justamente ese caso (lista vacía) el que dispara la directiva de
    "No tengo fuente suficiente" en julix/service.py."""
    if db_connection is None:
        logger.warning("Vridik/RAG: buscar_contexto llamado sin db_connection — se retorna vacío")
        return []

    embedding = embeber_texto(pregunta)
    literal = _embedding_a_literal_pgvector(embedding)
    tamanio_pool = max(top_k, top_k * FACTOR_POOL_CANDIDATOS)

    if solo_fuentes:
        query = """
            SELECT norma, articulo, parrafo, texto, anio, tribunal, tipo_fuente,
                   metadata ->> 'fuente' AS fuente_cliente,
                   embedding <=> $1::vector AS distancia
            FROM rag_chunks
            WHERE metadata ->> 'fuente' = ANY($3::text[])
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """
        filas = await db_connection.fetch(query, literal, tamanio_pool, solo_fuentes)
    else:
        query = """
            SELECT norma, articulo, parrafo, texto, anio, tribunal, tipo_fuente,
                   metadata ->> 'fuente' AS fuente_cliente,
                   embedding <=> $1::vector AS distancia
            FROM rag_chunks
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """
        filas = await db_connection.fetch(query, literal, tamanio_pool)

    candidatos = [
        ChunkRecuperado(
            norma=fila["norma"], articulo=fila["articulo"], parrafo=fila["parrafo"],
            texto=fila["texto"], distancia=float(fila["distancia"]),
            anio=fila["anio"], tribunal=fila["tribunal"], tipo_fuente=fila["tipo_fuente"],
            fuente_cliente=fila["fuente_cliente"],
        )
        for fila in filas
    ]
    # Re-ranking S9/S11: pgvector nos da el pool por cercanía pura; el
    # orden final que ve JuliX prioriza tipo de fuente, recencia y fuente
    # de cliente prioritaria sobre cercanía marginal en el espacio de
    # embeddings.
    candidatos.sort(key=lambda c: c.score, reverse=True)
    seleccionados = candidatos[:top_k]

    # Sin esto, la única forma de ver qué (si algo) se recuperó para una
    # pregunta dada era la caché SQLite local (rag/cache.py), no los logs
    # de Railway -- no hay umbral de similitud acá (buscar_contexto SIEMPRE
    # devuelve los top_k más cercanos que haya, por débil que sea la
    # coincidencia), así que "0 candidatos" solo pasa con la tabla vacía o
    # sin conexión; un "No tengo fuente suficiente" con candidatos > 0 es
    # el prompt de JuliX rechazando fuentes topicamente insuficientes, no
    # un fallo de recuperación -- este log distingue los dos casos en
    # producción sin tener que inspeccionar la caché.
    if seleccionados:
        logger.info(
            "Vridik/RAG: %s candidato(s) recuperados para %r — top: %s art. %s (score=%.3f, distancia=%.3f)",
            len(seleccionados), pregunta[:80],
            seleccionados[0].norma, seleccionados[0].articulo,
            seleccionados[0].score, seleccionados[0].distancia,
        )
    else:
        logger.info("Vridik/RAG: 0 candidatos recuperados para %r — tabla rag_chunks vacía", pregunta[:80])

    return seleccionados


def a_ranked_chunks(chunks: list[ChunkRecuperado]):
    """Convierte los chunks recuperados al formato que espera
    julix/context_builder.py (RankedChunk), para que julix/service.py pueda
    reutilizar la lógica ya existente de priorización/truncado por
    presupuesto de tokens sin duplicar código."""
    from julix.context_builder import RankedChunk  # import local: evita ciclo en tiempo de import

    return [
        RankedChunk(
            referencia=chunk.cita,
            jerarquia=chunk.jerarquia,
            vigente=True,  # rag_chunks no modela vigencia todavía (llega con corpus_documents en S7-S9)
            tokens=chunk.tokens_estimados,
            contenido=chunk.texto,
        )
        for chunk in chunks
    ]
