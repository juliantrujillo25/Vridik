#!/usr/bin/env python3
"""
Vridik / JuliX — rag/cache.py
Cache local de respuestas de JuliX sobre SQLite (data/rag_cache.db), pensada
para evitar llamadas repetidas a Anthropic cuando la misma pregunta (o una
equivalente tras normalizar) ya se resolvió recientemente.

Esquema de la tabla `rag_cache` (exactamente el pedido):
    query_hash TEXT PRIMARY KEY,
    respuesta  TEXT NOT NULL,
    fuentes    JSON NOT NULL,   -- lista de citas, serializada con json.dumps
    tokens     INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL

TTL diferenciado (requisito 4): la tabla NO guarda el TTL por fila (no se
pidió esa columna) — en su lugar, `get()` recibe el TTL a aplicar como
parámetro opcional (default 24h). Quien integra la cache (ver
julix/context_builder.py) es quien clasifica la pregunta con
`ttl_horas_para_query()` y pasa el mismo TTL tanto al `get()` como al
`set()` de una pregunta dada — así una pregunta de definición ("¿qué es el
IBC?") usa 7 días, y el resto (UGPP puntual/expediente) usa 24h, sin
necesitar una columna extra en la tabla.

NO SE EJECUTA CONTRA ANTHROPIC NI CONTRA EL PIPELINE DE RAG REAL EN ESTE
ENTREGABLE — es una utilidad de cache pura sobre SQLite local.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH_POR_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "rag_cache.db"

TTL_HORAS_DEFECTO = 24            # preguntas UGPP / consultas de expediente puntuales
TTL_HORAS_DEFINICION = 24 * 7     # 7 días — preguntas de definición ("¿qué es el IBC?")

_RE_ESPACIOS = re.compile(r"\s+")
_RE_PREGUNTA_DEFINICION = re.compile(
    r"^\s*(qu[eé]\s+es|qu[eé]\s+significa|definici[oó]n\s+de)\b", re.IGNORECASE
)


def normalizar_query(query: str) -> str:
    """lower + sin acentos (NFKD, se descartan las marcas diacríticas) +
    espacios múltiples colapsados a uno solo + recorte de extremos. Así
    '¿Qué   es el IBC?' y 'que es el ibc?' producen el mismo hash."""
    texto = query.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = _RE_ESPACIOS.sub(" ", texto).strip()
    return texto


def hash_query(query: str) -> str:
    """SHA256 (hex) de la query normalizada — clave primaria de la tabla."""
    return hashlib.sha256(normalizar_query(query).encode("utf-8")).hexdigest()


def es_pregunta_definicion(query: str) -> bool:
    """Heurística para el requisito 4: preguntas que piden una definición
    ('¿qué es el IBC?', 'definición de mora presunta', '¿qué significa
    UGPP?') usan el TTL largo. Cualquier otra pregunta (consulta puntual de
    expediente/UGPP) usa el TTL corto. Se evalúa sobre la query original
    (antes de normalizar) para no perder los signos de interrogación con
    los que suele empezar este tipo de pregunta en español."""
    return bool(_RE_PREGUNTA_DEFINICION.match(query.strip().lstrip("¿")))


def ttl_horas_para_query(query: str) -> int:
    """TTL en horas a aplicar para esta pregunta: 7 días si es una pregunta
    de definición, 24h en cualquier otro caso (UGPP / expediente)."""
    return TTL_HORAS_DEFINICION if es_pregunta_definicion(query) else TTL_HORAS_DEFECTO


class RAGCache:
    """Cache SQLite de respuestas de JuliX. Cada instancia abre su propia
    conexión (SQLite no soporta bien conexiones compartidas entre threads
    sin cuidado extra); pensada para usarse como un objeto de vida corta por
    request, o cacheada a nivel de proceso si el caller lo prefiere."""

    def __init__(self, db_path: Path | str = DB_PATH_POR_DEFECTO):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        # journal_mode=MEMORY (en vez del rollback journal por defecto, que
        # crea un archivo -journal aparte y depende de locks a nivel de
        # filesystem): necesario cuando data/ vive sobre un volumen
        # montado en red/FUSE, donde esos locks no siempre están
        # soportados y el journal por defecto falla con "disk I/O error"
        # incluso en el CREATE TABLE inicial. En un filesystem local normal
        # (Railway, disco local) este modo también funciona sin problema.
        self._conn.execute("PRAGMA journal_mode=MEMORY")
        self._crear_tabla()

    def _crear_tabla(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_cache (
                query_hash TEXT PRIMARY KEY,
                respuesta TEXT NOT NULL,
                fuentes JSON NOT NULL,
                tokens INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def hash_query(query: str) -> str:
        """Atajo — misma lógica que el `hash_query()` de módulo, expuesto
        también como método estático para quien ya tiene una instancia."""
        return hash_query(query)

    def get(
        self, query_hash: str, *, ttl_horas: int = TTL_HORAS_DEFECTO
    ) -> tuple[str, list, int] | None:
        """Retorna (respuesta, fuentes, tokens) si existe una entrada cuyo
        `created_at` sigue vigente dentro de `ttl_horas` (por defecto 24h,
        el requisito 1 literal: "devuelve respuesta si existe y tiene
        <24h"). Retorna None si no existe la entrada, o si expiró según el
        `ttl_horas` pasado — quien llama debe pasar
        `ttl_horas_para_query(query)` para que una pregunta de definición
        respete su TTL de 7 días en vez del de 24h por defecto (requisito 4).
        Una entrada expirada NO se borra aquí; se sobreescribe sola en el
        siguiente `set()` con la misma `query_hash`."""
        fila = self._conn.execute(
            "SELECT respuesta, fuentes, tokens, created_at FROM rag_cache WHERE query_hash = ?",
            (query_hash,),
        ).fetchone()
        if fila is None:
            return None

        created_at = datetime.fromisoformat(fila["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        vencimiento = created_at + timedelta(hours=ttl_horas)
        if datetime.now(timezone.utc) >= vencimiento:
            return None  # expiró

        return fila["respuesta"], json.loads(fila["fuentes"]), fila["tokens"]

    def set(self, query_hash: str, respuesta: str, fuentes: list, tokens: int) -> None:
        """Guarda/reemplaza la entrada de `query_hash` con `created_at` =
        ahora (UTC). El TTL no se guarda en la tabla (ver docstring del
        módulo) — se decide en cada `get()`."""
        self._conn.execute(
            """
            INSERT INTO rag_cache (query_hash, respuesta, fuentes, tokens, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                respuesta=excluded.respuesta,
                fuentes=excluded.fuentes,
                tokens=excluded.tokens,
                created_at=excluded.created_at
            """,
            (
                query_hash,
                respuesta,
                json.dumps(fuentes, ensure_ascii=False),
                tokens,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RAGCache":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
