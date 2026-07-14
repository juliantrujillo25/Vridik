"""
Vridik — procesal/calendario_judicial.py
Fase 2 (Copiloto Procesal): motor de cálculo de términos procesales sobre
el calendario judicial colombiano real (festivos + vacancia judicial).
Independiente de cualquier proveedor de monitoreo de procesos -- este
motor no necesita un feed de actuaciones en vivo, solo una fecha de
inicio y una cantidad de días hábiles (ver procesal/__init__.py).

LO QUE ESTE MÓDULO **NO** HACE: no sabe qué término aplica a qué tipo de
actuación bajo CPACA/CPT/CGP -- esa correspondencia (p.ej. "cuántos días
tiene la contestación de una demanda de nulidad y restablecimiento") es
conocimiento jurídico que requiere investigación legal real, no algo que
deba inventarse acá. `sumar_dias_habiles()` es el conteo MECÁNICO de días
hábiles sobre un calendario verificado -- el número de días a sumar lo
decide un abogado (o un catálogo de términos que se construya después,
con la revisión correspondiente), nunca este módulo.

Fuentes de las fechas (verificadas por búsqueda web el 14-jul-2026, NO de
memoria del modelo -- ver cada constante):
  - Festivos 2026/2027: Ley 51 de 1983 (Ley Emiliani) -- 7 fijos + 11
    móviles a lunes, calculados sobre Domingo de Pascua (2026-04-05,
    2027-03-28 -- verificado cruzando cada festivo móvil contra la
    fórmula real de Ley Emiliani, ej. Corpus Christi = Pascua+60 -> lunes
    siguiente, y confirmando que coincide con la fecha publicada).
  - Vacancia judicial de Semana Santa 2026: Consejo Superior de la
    Judicatura (El Tiempo / Asuntos Legales, jul-2026): 28-mar al
    5-abr-2026, retoma 6-abr-2026.
  - Vacancia judicial de fin de año 2025-2026: Consejo Superior de la
    Judicatura, anuncio oficial: 20-dic-2025 al 10-ene-2026, retoma
    13-ene-2026 (rama-judicial.gov.co).

LIMITACIÓN HONESTA: la vacancia judicial de fin de año 2026-2027 todavía
NO estaba anunciada oficialmente al momento de escribir esto (14-jul-2026
-- el Consejo Superior de la Judicatura la anuncia cada año con pocos
meses de anticipación, normalmente en octubre/noviembre). No se adivina
la fecha: `VACANCIA_FIN_DE_ANO_2026_2027` queda vacía y
`vacancia_fin_de_ano_pendiente_de_anuncio()` lo señala explícitamente
para quien use este módulo cerca de fin de 2026. Actualizar apenas se
anuncie (buscar "vacancia judicial" + año en el sitio de la Rama
Judicial).

Este motor NO reemplaza el criterio de un abogado ni un sistema de
gestión de términos certificado -- es un punto de partida verificado
para Fase 2, no algo para confiar ciegamente en un vencimiento real sin
revisión humana.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Festivos oficiales (Ley 51 de 1983 / Ley Emiliani) -- 18 por año.
# ---------------------------------------------------------------------------
FESTIVOS_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),   # Año Nuevo
    date(2026, 1, 12),  # Reyes Magos (móvil)
    date(2026, 3, 23),  # San José (móvil)
    date(2026, 4, 2),   # Jueves Santo
    date(2026, 4, 3),   # Viernes Santo
    date(2026, 5, 1),   # Día del Trabajo
    date(2026, 5, 18),  # Ascensión (móvil)
    date(2026, 6, 8),   # Corpus Christi (móvil)
    date(2026, 6, 15),  # Sagrado Corazón (móvil)
    date(2026, 6, 29),  # San Pedro y San Pablo (móvil)
    date(2026, 7, 20),  # Independencia
    date(2026, 8, 7),   # Batalla de Boyacá
    date(2026, 8, 17),  # Asunción de la Virgen (móvil)
    date(2026, 10, 12), # Día de la Raza (móvil)
    date(2026, 11, 2),  # Todos los Santos (móvil)
    date(2026, 11, 16), # Independencia de Cartagena (móvil)
    date(2026, 12, 8),  # Inmaculada Concepción
    date(2026, 12, 25), # Navidad
})

FESTIVOS_2027: frozenset[date] = frozenset({
    date(2027, 1, 1),   # Año Nuevo
    date(2027, 1, 11),  # Reyes Magos (móvil)
    date(2027, 3, 22),  # San José (móvil)
    date(2027, 3, 25),  # Jueves Santo
    date(2027, 3, 26),  # Viernes Santo
    date(2027, 5, 1),   # Día del Trabajo
    date(2027, 5, 10),  # Ascensión (móvil)
    date(2027, 5, 31),  # Corpus Christi (móvil)
    date(2027, 6, 7),   # Sagrado Corazón (móvil)
    date(2027, 7, 5),   # San Pedro y San Pablo (móvil)
    date(2027, 7, 20),  # Independencia
    date(2027, 8, 7),   # Batalla de Boyacá
    date(2027, 8, 16),  # Asunción de la Virgen (móvil)
    date(2027, 10, 18), # Día de la Raza (móvil)
    date(2027, 11, 1),  # Todos los Santos (móvil)
    date(2027, 11, 15), # Independencia de Cartagena (móvil)
    date(2027, 12, 8),  # Inmaculada Concepción
    date(2027, 12, 25), # Navidad
})

FESTIVOS: frozenset[date] = FESTIVOS_2026 | FESTIVOS_2027


def _rango(inicio: date, fin: date) -> frozenset[date]:
    """Todas las fechas de `inicio` a `fin`, ambos inclusive."""
    dias = (fin - inicio).days
    return frozenset(inicio + timedelta(days=i) for i in range(dias + 1))


# ---------------------------------------------------------------------------
# Vacancia judicial -- suspende términos procesales, distinto de un
# festivo aislado (ver docstring del módulo sobre qué está confirmado y
# qué no).
# ---------------------------------------------------------------------------
VACANCIA_FIN_DE_ANO_2025_2026: frozenset[date] = _rango(date(2025, 12, 20), date(2026, 1, 10))
VACANCIA_SEMANA_SANTA_2026: frozenset[date] = _rango(date(2026, 3, 28), date(2026, 4, 5))

# Todavía no anunciada oficialmente -- ver LIMITACIÓN HONESTA arriba.
VACANCIA_FIN_DE_ANO_2026_2027: frozenset[date] = frozenset()

VACANCIA_JUDICIAL: frozenset[date] = (
    VACANCIA_FIN_DE_ANO_2025_2026 | VACANCIA_SEMANA_SANTA_2026 | VACANCIA_FIN_DE_ANO_2026_2027
)


def vacancia_fin_de_ano_pendiente_de_anuncio(fecha: date) -> bool:
    """True si `fecha` cae en una ventana donde históricamente hay
    vacancia de fin de año (aprox. 20-dic a 10-ene) pero para el
    2026-2027 todavía no hay fecha oficial -- señal para no confiar
    ciegamente en un cálculo de término que cruce esa ventana sin
    verificar el anuncio real primero."""
    if fecha.year == 2026 and fecha.month == 12 and fecha.day >= 15:
        return True
    if fecha.year == 2027 and fecha.month == 1 and fecha.day <= 15:
        return True
    return False


def es_festivo(fecha: date) -> bool:
    return fecha in FESTIVOS


def es_vacancia_judicial(fecha: date) -> bool:
    return fecha in VACANCIA_JUDICIAL


def es_dia_habil(fecha: date) -> bool:
    """Ni fin de semana, ni festivo, ni vacancia judicial."""
    if fecha.weekday() >= 5:  # sábado=5, domingo=6
        return False
    if es_festivo(fecha):
        return False
    if es_vacancia_judicial(fecha):
        return False
    return True


@dataclass
class ResultadoTermino:
    fecha_vencimiento: date
    dias_no_habiles_saltados: list[date] = field(default_factory=list)
    incluye_ventana_sin_confirmar: bool = False


def sumar_dias_habiles(fecha_inicio: date, dias_habiles: int) -> ResultadoTermino:
    """Cuenta `dias_habiles` días hábiles a partir de `fecha_inicio`,
    saltando fines de semana/festivos/vacancia judicial.

    El término empieza a correr el día HÁBIL SIGUIENTE a `fecha_inicio`
    (regla general en CPACA/CGP/CPT: la notificación no cuenta como el
    primer día del término) -- `fecha_inicio` en sí NUNCA se cuenta como
    uno de los `dias_habiles`, sea o no hábil.

    Levanta ValueError si `dias_habiles <= 0` -- no tiene sentido pedir un
    término de cero o negativo días."""
    if dias_habiles <= 0:
        raise ValueError(f"dias_habiles debe ser positivo, se recibió {dias_habiles}")

    saltados: list[date] = []
    incluye_ventana_sin_confirmar = False
    cursor = fecha_inicio
    contados = 0
    while contados < dias_habiles:
        cursor += timedelta(days=1)
        if vacancia_fin_de_ano_pendiente_de_anuncio(cursor):
            incluye_ventana_sin_confirmar = True
        if es_dia_habil(cursor):
            contados += 1
        else:
            saltados.append(cursor)

    return ResultadoTermino(
        fecha_vencimiento=cursor,
        dias_no_habiles_saltados=saltados,
        incluye_ventana_sin_confirmar=incluye_ventana_sin_confirmar,
    )
