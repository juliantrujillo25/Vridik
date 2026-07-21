"""
Vridik — procesal/alertas_terminos.py
Fase 2 (Copiloto Procesal): alertas proactivas de términos en riesgo --
roadmap: "0 términos vencidos sin alerta en 90 días" y `termino.por_vencer`
(core/events.py, canal SSE genérico de la S11).

Track Forja TF3 (vridik_architecture_v2.json::journey_loop_termino):
escalonado en tres avisos por término (T-5/T-3/T-1, ver
core/terminos.py::DIAS_ESCALONES) en vez de un solo aviso repetido cada
día en riesgo -- el evento pasó de `termino.alerta` a `termino.por_vencer`
(rompe compatibilidad con quien escuchara el tipo viejo a propósito, no
hay otro consumidor además del frontend de este mismo repo, ya
actualizado en el mismo cambio).

El semáforo del dashboard (frontend/src/casos/CasosListPage.tsx) ya avisa
cuando alguien ABRE la app -- esto es el complemento: un aviso aunque
nadie esté mirando en ese momento. "Cero infra nueva" (mismo principio que
core/events.py): en vez de un servicio Railway con cron propio, esto corre
como una tarea de fondo dentro del proceso ya siempre-activo de vridik-api
(ver app/main.py, `_bucle_alertas_terminos`) -- un `asyncio.sleep()` en
loop, no un servicio ni un deploy separado.

Idempotencia: core/terminos.py::listar_terminos_para_alertar() ya filtra
por escalón (`ultimo_escalon_notificado` más flojo que el escalón actual),
así que correr esta ronda más seguido de lo necesario (o dos instancias
del proceso a la vez, aunque hoy numReplicas=1) nunca duplica el mismo
escalón -- cada término recibe como mucho 3 avisos en toda su vida
(T-5, T-3, T-1), no uno por ronda mientras siga en riesgo.
"""

from __future__ import annotations

import logging

from core.events import notificar_evento
from core.health_score import recalcular_health_score_de_casos_abiertos
from core.terminos import listar_terminos_para_alertar, marcar_escalon_notificado

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
    """Una ronda completa: notifica cada término pendiente que alcanzó un
    nuevo escalón (T-5/T-3/T-1) desde el último aviso, y marca ESE escalón
    como notificado (no "hoy", ver core/terminos.py::DIAS_ESCALONES).
    Devuelve cuántos términos se notificaron (0 si no había nada nuevo que
    avisar) -- lo usan tanto el bucle de fondo de app/main.py como los
    tests, sin depender de tiempo real."""
    filas = await listar_terminos_para_alertar(db_connection)
    for fila in filas:
        termino_id = str(fila["id"])
        escalon = fila["escalon"]
        payload = {
            "caso_id": str(fila["caso_id"]),
            "termino_id": termino_id,
            "descripcion": fila["descripcion"],
            "fecha_vencimiento": fila["fecha_vencimiento"].isoformat(),
            "escalon": escalon,
        }
        for user_id in _destinatarios(fila):
            try:
                await notificar_evento(db_connection, user_id=user_id, tipo="termino.por_vencer", payload=payload)
            except Exception:  # noqa: BLE001 — una notificación fallida no debe frenar el resto de la ronda
                logger.warning(
                    "Vridik/alertas_terminos: termino_id=%s no se pudo notificar a user_id=%s",
                    termino_id, user_id,
                )
        await marcar_escalon_notificado(db_connection, termino_id=termino_id, escalon=escalon)
    # TF2: mismo job de 6h recalcula el health-score de todos los casos
    # abiertos -- no hace falta un segundo bucle de fondo separado.
    await recalcular_health_score_de_casos_abiertos(db_connection)
    return len(filas)
