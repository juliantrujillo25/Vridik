"""
Vridik / JuliX — julix/service.py
Orquestador de alto nivel: recibe la petición del frontend (caso + tarea),
recupera contexto real (rag/context_builder.py), lo arma con presupuesto de
tokens (julix/context_builder.py) y llama al modelo con streaming (client),
traduciendo los errores domados (errors.py) a una respuesta honesta.

Actualización S4: el registro en `julix_calls` vive en julix/client.py, no
aquí (ver JuliXClient.stream_completion).

Actualización S6 (RAG base): antes de llamar a Sonnet 5, este servicio
recupera contexto real desde `rag_chunks` (pgvector) vía
rag/context_builder.py — ya no depende únicamente de que el llamador pase
`chunks_candidatos` a mano. Si no se pasan chunks explícitos, se recuperan
automáticamente a partir de la pregunta/expediente. Además, se agrega una
directiva obligatoria al final de cada system prompt: responder SOLO con
normas citadas en el contexto, y decir explícitamente "No tengo fuente
suficiente" cuando no hay contexto que respalde la respuesta — así se cierre
la puerta a que JuliX complete de memoria cuando el RAG no encuentra nada.

Actualización S11-extra (cache): antes de llamar al modelo (y antes de
recuperar contexto del RAG), se revisa `rag/cache.py` (SQLite,
`data/rag_cache.db`) con el hash de la pregunta normalizada. Si hay un hit
vigente, se devuelve la respuesta cacheada sin gastar ni un token de
Anthropic — por eso el chequeo va incluso antes del límite blando mensual
(un hit no debe contar contra ese límite). Si hay miss, el flujo sigue
igual que antes y, al terminar el streaming con éxito, la respuesta
completa se guarda en cache con `RAGCache.set()`.

NO SE EJECUTA EN ESTE ENTREGABLE — esqueleto de referencia.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from . import prompts
from .client import JuliXClient
from .context_builder import ContextBudget, RankedChunk, construir_contexto
from .errors import JuliXError
from .ledger import requiere_confirmacion
from rag.cache import RAGCache, hash_query, ttl_horas_para_query
from rag.context_builder import a_ranked_chunks as rag_a_ranked_chunks
from rag.context_builder import buscar_contexto as rag_buscar_contexto


def _query_hash(query: str) -> str:
    """Helper de wiring (S11-extra): query_hash = sha256(normaliza(query)).
    Delega en rag.cache.hash_query() en vez de reimplementar la
    normalización aquí, para que el hash que calcula service.py al leer sea
    IDÉNTICO, byte a byte, al que calculó quien escribió la entrada — dos
    implementaciones separadas de "normaliza" divergerían con el tiempo y
    romperían la cache en silencio (todo sería miss)."""
    return hash_query(query)

# Directiva obligatoria de fuente (Sprint S6, pedida explícitamente por el
# dev lead). Se agrega al final de CUALQUIER prompt de tarea versionado,
# como último recurso de seguridad además de las reglas propias de cada
# prompt (ver julix/prompts/*.md) — nunca se confía solo en que el prompt de
# la tarea la mencione, porque S6 exige que esta regla sea innegociable.
DIRECTIVA_FUENTE_OBLIGATORIA = (
    "\n\n## Regla obligatoria de fuente (S6, no negociable)\n"
    "Responde SOLO con normas colombianas citadas explícitamente en el contexto "
    "que se te entrega en este mensaje. Nunca completes con normas, artículos o "
    "cifras que no estén en ese contexto, aunque te parezcan correctos de memoria. "
    "Si el contexto no trae fuente suficiente para responder la pregunta, responde "
    "exactamente: \"No tengo fuente suficiente\"."
)


class JuliXService:
    def __init__(self, client: JuliXClient, db_connection):
        self.client = client
        self.db = db_connection
        # Si el client no trae su propia conexión de ledger, usa la del
        # service — así el registro en julix_calls ocurre una sola vez,
        # dentro de client.stream_completion (ver julix/client.py, S4).
        if getattr(self.client, "db_connection", None) is None:
            self.client.db_connection = self.db

    async def generar_documento(
        self,
        *,
        user_id: str,
        caso_id: str,
        tarea: str,
        expediente_texto: str,
        chunks_candidatos: list[RankedChunk] | None = None,
        pregunta: str | None = None,
        prompt_version: int | None = None,
    ) -> AsyncIterator[str]:
        """Punto de entrada usado por el endpoint HTTP/SSE del backend
        (ver api/julix_endpoint.py). Yields chunks de texto; el registro en
        julix_calls ocurre dentro de client.stream_completion al finalizar.

        `chunks_candidatos`: si se pasa explícitamente (p.ej. desde tests o
        desde un flujo que ya trae contexto propio), se usa tal cual y NO se
        consulta el RAG. Si es None (caso normal en producción), el servicio
        recupera contexto real desde rag_chunks usando `pregunta` (o
        `expediente_texto` como respaldo) antes de llamar a Sonnet 5.
        """

        # 0. Cache (S11-extra, wiring): antes de llamar a Anthropic (y antes
        #    de recuperar contexto del RAG), revisa si esta misma pregunta ya
        #    se resolvió y sigue vigente. Un hit no cuesta ni un token, así
        #    que se revisa incluso antes del límite blando mensual — un hit
        #    nunca debe contar contra ese límite.
        texto_busqueda = pregunta or expediente_texto
        query_hash = _query_hash(texto_busqueda)
        cache = RAGCache()
        cached = cache.get(query_hash, ttl_horas=ttl_horas_para_query(texto_busqueda))
        if cached:
            respuesta_cacheada, _fuentes_cacheadas, _tokens_cacheados = cached
            yield respuesta_cacheada
            return

        # 1. Límite blando mensual — nunca bloqueo duro, solo aviso/confirmación
        mostrar_aviso, requiere_confirm = await requiere_confirmacion(self.db)
        if requiere_confirm:
            yield "__JULIX_REQUIERE_CONFIRMACION__"  # el frontend intercepta este marcador
            return
        if mostrar_aviso:
            yield "__JULIX_AVISO_80_PORCIENTO__"

        # 2. Cargar prompt versionado (nunca prompt en código) + directiva de fuente
        prompt = prompts.load_prompt(tarea, version=prompt_version)
        system_prompt = prompt.contenido + DIRECTIVA_FUENTE_OBLIGATORIA

        # 3. Recuperar contexto real (RAG, S6) si no vino explícito
        if chunks_candidatos is None:
            chunks_recuperados = await rag_buscar_contexto(self.db, texto_busqueda)
            chunks_candidatos = rag_a_ranked_chunks(chunks_recuperados)

        # 4. Construir contexto con presupuesto de tokens (vacío es válido:
        #    si el RAG no encontró nada, el contexto queda sin fuentes y la
        #    directiva de arriba obliga a decir "No tengo fuente suficiente")
        contexto = construir_contexto(
            instrucciones=system_prompt,
            expediente_texto=expediente_texto,
            chunks_candidatos=chunks_candidatos,
            presupuesto=ContextBudget(),
        )

        # 5. Streaming con manejo de los 5 modos de fallo domados. El ledger
        #    (julix_calls) se registra dentro del propio client. Se acumula
        #    el texto completo (S11-extra) para poder guardarlo en cache al
        #    finalizar sin alterar el streaming que ve el frontend.
        respuesta_completa = ""
        try:
            async for chunk in self.client.stream_completion(
                tarea=tarea,
                system_prompt=contexto.system_prompt,
                user_content=contexto.user_content,
                user_id=user_id,
                caso_id=caso_id,
                prompt_version=prompt.version,
                prompt_hash=prompt.hash,
            ):
                respuesta_completa += chunk
                yield chunk
        except JuliXError as exc:
            if exc.partial_text:
                yield f"\n\n[JULIX_PARCIAL_RECUPERABLE: {exc.partial_text}]"
            yield f"\n\n[JULIX_ERROR:{exc.status}] {exc}"
            return  # una respuesta con error nunca se cachea

        # 6. Cache (S11-extra): guarda la respuesta real completa. Las
        #    "fuentes" son las referencias citables ya calculadas por
        #    construir_contexto() (contexto.chunks_incluidos); los "tokens"
        #    son el estimado del propio contexto — el conteo real de
        #    Anthropic se registra aparte en julix_calls (julix/client.py) y
        #    no llega hasta aquí sin duplicar esa lógica de ledger.
        cache.set(query_hash, respuesta_completa, contexto.chunks_incluidos, contexto.tokens_estimados)

    async def clasificar_actuacion(self, *, texto_actuacion: str) -> dict:
        """Preparado para Fase 2 (Copiloto Procesal): clasificación con Haiku.
        Esqueleto S4 — implementación real en Fase 2, Sprint correspondiente."""
        raise NotImplementedError("Clasificador de actuaciones: Fase 2")
