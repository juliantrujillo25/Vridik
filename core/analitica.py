"""
Vridik — core/analitica.py
Fase 4 (roadmap: "Analítica de línea decisional UGPP sobre corpus propio,
no perfilamiento de jueces individuales") -- el corpus jurisprudencial
sigue incompleto (85/400+ chunks, ver PROMPTS.md), así que esta pasada
NO analiza jurisprudencia externa. En su lugar, agrega los resultados de
los PROPIOS casos UGPP del despacho: tasa de éxito por tipo de
resolución (`actuaciones.tipo_resolucion_ugpp`, texto libre marcado a
mano por el abogado -- ver core/actuaciones.py::set_resultado_actuacion),
tiempos hasta el fallo, y valor recuperado (core/cobro.py).

Nunca menciona ni agrega por juez -- no hay ningún campo de juez en el
esquema, cumpliendo la advertencia SAMAI del roadmap (Ley 1581: la
disponibilidad pública de datos judiciales no autoriza perfilamiento).

Herramienta de apoyo, no un motor de business intelligence: con pocos
casos, cualquier "tasa de éxito" es poco representativa -- la UI debe
mostrar el tamaño de muestra junto al porcentaje, nunca el porcentaje
solo.
"""

from __future__ import annotations


async def generar_analitica_ugpp(db_connection, *, despacho_id: str) -> dict:
    total_casos_ugpp = await db_connection.fetchval(
        "SELECT count(*) FROM casos WHERE despacho_id = $1 AND materia = 'ugpp'",
        despacho_id,
    )

    fallos = await db_connection.fetch(
        """
        SELECT a.resultado, a.tipo_resolucion_ugpp, a.created_at AS fallo_created_at, c.created_at AS caso_created_at
        FROM actuaciones a
        JOIN casos c ON c.id = a.caso_id
        WHERE c.despacho_id = $1 AND c.materia = 'ugpp' AND a.categoria = 'fallo'
        ORDER BY a.created_at
        """,
        despacho_id,
    )

    con_resultado = [f for f in fallos if f["resultado"] is not None]

    conteo_por_resultado = {"favorable": 0, "desfavorable": 0, "parcial": 0}
    por_tipo: dict[str, dict] = {}
    for f in con_resultado:
        conteo_por_resultado[f["resultado"]] += 1
        tipo = (f["tipo_resolucion_ugpp"] or "").strip() or "(sin especificar)"
        fila_tipo = por_tipo.setdefault(
            tipo, {"tipo_resolucion_ugpp": tipo, "total": 0, "favorable": 0, "desfavorable": 0, "parcial": 0},
        )
        fila_tipo["total"] += 1
        fila_tipo[f["resultado"]] += 1

    tasa_exito = conteo_por_resultado["favorable"] / len(con_resultado) if con_resultado else None

    tiempos_dias = [
        (f["fallo_created_at"] - f["caso_created_at"]).total_seconds() / 86400 for f in con_resultado
    ]
    tiempo_promedio_dias = sum(tiempos_dias) / len(tiempos_dias) if tiempos_dias else None

    cobros = await db_connection.fetch(
        """
        SELECT cb.valor_recuperado
        FROM cobro_caso cb
        JOIN casos c ON c.id = cb.caso_id
        WHERE c.despacho_id = $1 AND c.materia = 'ugpp' AND cb.liquidado_en IS NOT NULL
        """,
        despacho_id,
    )
    valores_recuperados = [float(c["valor_recuperado"]) for c in cobros if c["valor_recuperado"] is not None]

    return {
        "total_casos_ugpp": total_casos_ugpp,
        "total_fallos_registrados": len(fallos),
        "total_con_resultado": len(con_resultado),
        "conteo_por_resultado": conteo_por_resultado,
        "tasa_exito": tasa_exito,
        "por_tipo_resolucion": sorted(por_tipo.values(), key=lambda f: f["total"], reverse=True),
        "tiempo_promedio_dias_hasta_fallo": tiempo_promedio_dias,
        "casos_liquidados": len(valores_recuperados),
        "valor_recuperado_total": sum(valores_recuperados),
        "valor_recuperado_promedio": (
            sum(valores_recuperados) / len(valores_recuperados) if valores_recuperados else None
        ),
    }
