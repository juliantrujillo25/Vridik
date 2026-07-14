"""
Vridik — procesal/alertas_terminos.py
Fase 2 (Copiloto Procesal): alertas proactivas de términos en riesgo --
roadmap: "0 términos vencidos sin alerta en 90 días" y `termino.alerta`
(core/events.py, canal SSE genérico de la S11).

El semáforo del dashboard (frontend/src/casos/CasosListPage.tsx) ya avisa
cuando alguien ABRE la app -- esto es el complemento: un aviso aunque
nadie esté mirando en ese momento. "Cero infra nueva" (mismo principio que
core/events.py): en vez de un servicio Railway con cron propio, esto corre
como una tarea de fondo dentro del proceso ya siempre-activo de vridik-api
(ver app/main.py, `_bucle_alertas_terminos`) -- un `asyncio.sleep()` en
loop, no un servicio ni un deploy separado.

Idempotencia: core/terminos.py::listar_terminos_para_alertar() ya filtra
por `ultima_alerta_enviada <> hoy`, así que correr esta ronda más seguido
de lo necesario (o dos instancias del proceso a la vez, aunque hoy
numReplicas=1) nunca duplica una alerta el mismo día -- como mucho, una
notificación de más por término por día en riesgo, nunca cero.
"""

from __future__ import annotations

import logging

from core.events import notificar_evento
from core.terminos import listar_terminos_para_alertar, marcar_alerta_enviada

logger = logging.getLogger("vridik.procesal.alertas_terminos")


def _destinatarios(fila: dict) -> set[str]:
    """A diferencia de actuacion.nueva (que excluye a quien generó el
    evento), acá no hay "autor" -- el aviso es "se acerca/pasó una fecha",
    le importa a cualquiera con acceso al caso."""
    destinatarios = {str(fila["cliente_id"])}
    if fila["abogado_id"] is not None:
        destinatarios.add(str(fila["abogado_id"]))
    return destinatarios


async def ejecutar_ronda_de_alertas(db_connection) -> int:
    """Una ronda completa: notifica cada término pendiente en riesgo que
    todavía no se avisó hoy, y lo marca como avisado. Devuelve cuántos
    términos se notificaron (0 si no había nada nuevo que avisar) -- lo
    usan tanto el bucle de fondo de app/main.py como los tests, sin
    depender de tiempo real."""
    filas = await listar_terminos_para_alertar(db_connection)
    for fila in filas:
        termino_id = str(fila["id"])
        payload = {
            "caso_id": str(fila["caso_id"]),
            "termino_id": termino_id,
            "descripcion": fila["descripcion"],
            "fecha_vencimiento": fila["fecha_vencimiento"].isoformat(),
        }
        for user_id in _destinatarios(fila):
            try:
                await notificar_evento(db_connection, user_id=user_id, tipo="termino.alerta", payload=payload)
            except Exception:  # noqa: BLE001 — una notificación fallida no debe frenar el resto de la ronda
                logger.warning(
                    "Vridik/alertas_terminos: termino_id=%s no se pudo notificar a user_id=%s",
                    termino_id, user_id,
                )
        await marcar_alerta_enviada(db_connection, termino_id=termino_id)
    return len(filas)
