"""
Vridik — tests/support/fakes.py

Contratos mínimos ("fakes") para módulos de negocio que a la fecha de S3
todavía no tienen implementación de producción (Panel admin de usuarios
completo, Mensajes, Generador Word, Panel Vridik Pro) pero sí tienen
Definition of Done escrito en el roadmap (S2, y deuda de "Estado Actual").

Regla de CONTRIBUTING.md aplicada aquí: "bug en producción gana test antes
del fix" — estos fakes materializan el contrato esperado ANTES de que el
código real exista, para que los tests de S3 sean ejecutables desde ya y
sirvan de especificación. Cuando el módulo real se implemente, el fake se
reemplaza por el cliente real sin tocar los tests (misma interfaz).

FakeAnthropicStream sí reemplaza algo real: el client.py de JuliX (S4) no
debe llamarse contra Claude real en CI — se monkeypatch-ea con este fake.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Roles / permisos por módulo (contrato de S2, sección "Actividad" incluida)
# ---------------------------------------------------------------------------
MODULOS = ("usuarios", "casos", "mensajes", "generador", "julix", "panel")

PERMISOS_POR_ROL = {
    "admin":   {"usuarios": {"crear", "leer", "editar", "desactivar"}, "casos": {"leer", "editar"}, "mensajes": {"leer", "escribir"}, "generador": {"leer", "editar"}, "julix": {"leer", "editar"}, "panel": {"leer"}},
    "abogado":  {"usuarios": {"leer"},                                  "casos": {"leer", "editar"}, "mensajes": {"leer", "escribir"}, "generador": {"leer", "editar"}, "julix": {"leer", "editar"}, "panel": {"leer"}},
    "cliente":  {"usuarios": set(),                                      "casos": {"leer"},           "mensajes": {"leer", "escribir"}, "generador": set(),               "julix": set(),               "panel": set()},
}


class FakeRolesService:
    """Contrato de autorización por rol (S2). Implementación real: middleware
    de autorización sobre el JWT resuelto por core.feature_flag_legacy."""

    def puede(self, role: str, modulo: str, accion: str) -> bool:
        if role not in PERMISOS_POR_ROL:
            return False
        if modulo not in PERMISOS_POR_ROL[role]:
            return False
        return accion in PERMISOS_POR_ROL[role][modulo]


# ---------------------------------------------------------------------------
# Mensajes (contrato de S11, mensajería SSE — aquí solo la capa de datos)
# ---------------------------------------------------------------------------
@dataclass
class Mensaje:
    id: str
    conversacion_id: str
    autor_id: str
    texto: str
    adjunto_url: str | None = None
    leido_por: set[str] = field(default_factory=set)
    borrado: bool = False


class FakeMensajesService:
    """Contrato mínimo de Mensajes (deuda 'Mensajes 85%' del roadmap: falta
    polling/tiempo real, ver S11). Esta capa cubre la parte ya estable:
    crear, adjuntar, marcar leído, borrar (soft)."""

    def __init__(self):
        self._mensajes: dict[str, Mensaje] = {}

    def crear_chat(self, *, conversacion_id: str, autor_id: str, texto: str, adjunto_url: str | None = None) -> Mensaje:
        msg = Mensaje(id=str(uuid.uuid4()), conversacion_id=conversacion_id, autor_id=autor_id, texto=texto, adjunto_url=adjunto_url)
        self._mensajes[msg.id] = msg
        return msg

    def marcar_leido(self, mensaje_id: str, user_id: str) -> None:
        self._mensajes[mensaje_id].leido_por.add(user_id)

    def no_leidos_para(self, user_id: str, conversacion_id: str) -> int:
        return sum(
            1 for m in self._mensajes.values()
            if m.conversacion_id == conversacion_id and not m.borrado
            and m.autor_id != user_id and user_id not in m.leido_por
        )

    def borrar(self, mensaje_id: str, actor_id: str) -> bool:
        msg = self._mensajes.get(mensaje_id)
        if msg is None:
            return False
        if msg.autor_id != actor_id:
            return False
        msg.borrado = True
        return True


# ---------------------------------------------------------------------------
# Generador Word (contrato de S10: plantillas UGPP, fuente configurable, PDF)
# ---------------------------------------------------------------------------
class FakeGeneradorService:
    """Contrato del Generador (deuda 'Generador Word 75%': falta PDF, ver S10).
    Cubre la parte estable a hoy: render de plantilla con fuente configurable
    y justificado del texto."""

    PLANTILLAS_VALIDAS = {"ugpp_requerimiento", "ugpp_recurso", "laboral_generico"}
    FUENTES_VALIDAS = {"Arial", "Times New Roman", "Calibri"}

    def renderizar(self, *, plantilla: str, fuente: str, justificado: bool, variables: dict) -> dict:
        if plantilla not in self.PLANTILLAS_VALIDAS:
            raise ValueError(f"Plantilla desconocida: {plantilla}")
        if fuente not in self.FUENTES_VALIDAS:
            raise ValueError(f"Fuente no soportada: {fuente}")
        cuerpo = f"[{plantilla}] " + " ".join(f"{{{k}}}={v}" for k, v in variables.items())
        return {
            "plantilla": plantilla,
            "fuente": fuente,
            "justificado": justificado,
            "cuerpo": cuerpo,
            "formato": "docx",  # PDF llega en S10; aquí solo se valida el contrato docx
        }


# ---------------------------------------------------------------------------
# Panel Vridik Pro (contrato de KPIs; deuda 'vencimientos manuales' del roadmap)
# ---------------------------------------------------------------------------
class FakePanelService:
    """Contrato de KPIs del Panel Vridik Pro (Estado Actual: 90%, 'vencimientos
    manuales, no calculados'). Los vencimientos calculados llegan con el motor
    de términos de Fase 2 — aquí se valida que el panel al menos distinga
    manual vs calculado y no falle si no hay datos."""

    def kpis(self, *, casos_activos: int, casos_con_vencimiento_manual: int, casos_con_vencimiento_calculado: int) -> dict:
        total = casos_activos
        return {
            "casos_activos": total,
            "vencimientos_manuales": casos_con_vencimiento_manual,
            "vencimientos_calculados": casos_con_vencimiento_calculado,
            "porcentaje_calculado": (
                round(100 * casos_con_vencimiento_calculado / total, 1) if total else 0.0
            ),
        }


# ---------------------------------------------------------------------------
# JuliX — fake del stream de Claude (nunca se llama a Anthropic real en CI)
# ---------------------------------------------------------------------------
class FakeAnthropicStream:
    """Sustituye julix.client.JuliXClient.stream_completion en los tests.
    Permite simular: respuesta normal, truncado, 429, 529, formato inválido —
    los 5 modos de fallo domados de S4 (ver julix/errors.py)."""

    def __init__(self, chunks: list[str], *, raise_error: Exception | None = None):
        self._chunks = chunks
        self._raise_error = raise_error

    async def __call__(self, *, tarea: str, system_prompt: str, user_content: str):
        for chunk in self._chunks:
            yield chunk
        if self._raise_error is not None:
            raise self._raise_error


# ---------------------------------------------------------------------------
# JuliX — fake de conexión de BD para probar ledger.py sin PostgreSQL real
# ---------------------------------------------------------------------------
class FakeLedgerDB:
    """Sustituye la conexión asyncpg que julix/ledger.py y julix/service.py
    reciben para registrar_llamada()/gasto_mensual_actual_usd(). Los tests de
    JuliX no requieren PostgreSQL real: el contrato de julix_calls ya se
    valida por separado en julix/sql/ledger_schema.sql (S4)."""

    def __init__(self, *, gasto_mensual_actual: float = 0.0):
        self.llamadas_registradas: list[tuple] = []
        self._gasto_mensual_actual = gasto_mensual_actual

    async def execute(self, query: str, *args):
        self.llamadas_registradas.append((query, args))
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args):
        if "SUM(costo_usd)" in query:
            return (self._gasto_mensual_actual,)
        return None


# ---------------------------------------------------------------------------
# JuliX — fake del stream crudo del SDK de Anthropic (Sprint S4 update)
# ---------------------------------------------------------------------------
class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeFinalMessage:
    def __init__(self, *, stop_reason: str, input_tokens: int, output_tokens: int):
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(input_tokens, output_tokens)


class FakeSDKStream:
    """Sustituye lo que retorna `self._sdk_client.messages.stream(...)` en
    julix/client.py::JuliXClient._abrir_stream_sdk. Se usa como:

        client._abrir_stream_sdk = lambda **kw: FakeSDKStream(["chunk1", "chunk2"])

    Esto permite que el resto de stream_completion (retry, timeout, ledger)
    se ejecute de verdad en los tests, sin llamar nunca a Claude real."""

    def __init__(
        self,
        chunks: list[str],
        *,
        input_tokens: int = 120,
        output_tokens: int = 340,
        stop_reason: str = "end_turn",
        raise_on_enter: Exception | None = None,
    ):
        self._chunks = chunks
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._stop_reason = stop_reason
        self._raise_on_enter = raise_on_enter

    async def __aenter__(self):
        if self._raise_on_enter is not None:
            raise self._raise_on_enter
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def _generador(self):
        for chunk in self._chunks:
            yield chunk

    @property
    def text_stream(self):
        return self._generador()

    async def get_final_message(self):
        return _FakeFinalMessage(
            stop_reason=self._stop_reason,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )


class FakeSDKStreamFactory:
    """Factory reutilizable: `client._abrir_stream_sdk = FakeSDKStreamFactory(stream)`
    — evita tener que escribir un lambda distinto en cada test cuando se
    necesita inspeccionar los kwargs con los que se llamó (model, max_tokens, etc.)."""

    def __init__(self, stream: FakeSDKStream):
        self.stream = stream
        self.llamadas: list[dict] = []

    def __call__(self, **kwargs):
        self.llamadas.append(kwargs)
        return self.stream
