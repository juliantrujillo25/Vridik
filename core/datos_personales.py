"""
Vridik — core/datos_personales.py
Roadmap T7 (Ley 1581 de 2012, derechos ARCO): Acceso -- exportar en un
solo JSON todos los datos personales que Vridik tiene de un usuario, sin
depender de que alguien del equipo arme el export a mano consultando la
base directo.

Rectificación: no tiene función propia acá -- se ejerce con los
endpoints ya existentes (`POST /auth/password`, `PATCH /admin/users/
{id}/role`, etc.), no hace falta un mecanismo nuevo solo para esto.

Supresión: TODAVÍA NO IMPLEMENTADA a propósito. Qué se anonimiza (email,
nombre de despacho si el usuario era su único miembro) vs qué se
conserva por deber legal (actuaciones/términos/documentos del expediente
de un caso, la bitácora de auth_events con hash encadenado -- borrar o
mutar una fila ahí rompe la cadena para todo el que venga después) es una
decisión de producto/legal, no puramente técnica -- queda pendiente de
diseño con el dev lead antes de escribir el DELETE/UPDATE real.

Alcance del export: perfil propio + toda actividad donde el usuario es
DUEÑO del dato (casos donde es cliente/abogado, mensajes que escribió,
actuaciones/términos/documentos que creó, eventos de su propia bitácora
de autenticación). No incluye datos de OTROS usuarios aunque compartan
un caso (p.ej. mensajes que el otro participante del caso escribió) --
ese es el derecho de acceso de esa otra persona, no del que pide este
export.
"""

from __future__ import annotations


async def exportar_datos_de_usuario(db_connection, *, user_id: str) -> dict | None:
    """None si el usuario no existe -- el endpoint lo traduce a 404. Todas
    las queries filtran por columnas de ownership real (cliente_id/
    abogado_id/created_by/autor_id/user_id), nunca por despacho_id solo,
    para no devolver de más ni de menos que lo que es genuinamente del
    usuario que pide su propio export."""
    perfil = await db_connection.fetchrow(
        """
        SELECT u.id, u.email, u.role, u.is_active, u.totp_enabled, u.despacho_id,
               d.nombre AS despacho_nombre, u.es_superadmin, u.created_at
        FROM users u
        LEFT JOIN despachos d ON d.id = u.despacho_id
        WHERE u.id = $1
        """,
        user_id,
    )
    if perfil is None:
        return None

    casos = await db_connection.fetch(
        """
        SELECT id, titulo, descripcion, estado, materia, cliente_id, abogado_id, created_at
        FROM casos
        WHERE cliente_id = $1 OR abogado_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    mensajes = await db_connection.fetch(
        """
        SELECT id, conversacion_id, texto, adjunto_url, borrado, created_at
        FROM mensajes WHERE autor_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    actuaciones = await db_connection.fetch(
        """
        SELECT id, caso_id, texto, categoria, confianza, resultado, tipo_resolucion_ugpp, created_at
        FROM actuaciones WHERE created_by = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    terminos = await db_connection.fetch(
        """
        SELECT id, caso_id, descripcion, fecha_inicio, dias_habiles, fecha_vencimiento, estado, created_at
        FROM terminos WHERE created_by = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    documentos = await db_connection.fetch(
        """
        SELECT id, caso_id, tarea, pregunta, contenido, pdf_url, created_at
        FROM case_documents WHERE created_by = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )
    eventos_de_autenticacion = await db_connection.fetch(
        """
        SELECT id, event_type, metadata, ip_address, user_agent, created_at
        FROM auth_events WHERE user_id = $1
        ORDER BY created_at DESC
        """,
        user_id,
    )

    return {
        "perfil": dict(perfil),
        "casos": [dict(c) for c in casos],
        "mensajes": [dict(m) for m in mensajes],
        "actuaciones": [dict(a) for a in actuaciones],
        "terminos": [dict(t) for t in terminos],
        "documentos_generados": [dict(d) for d in documentos],
        "eventos_de_autenticacion": [dict(e) for e in eventos_de_autenticacion],
    }
