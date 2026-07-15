// Tipos que reflejan el contrato de la API de Vridik (FastAPI). Se mantienen
// a mano en sincronía con los endpoints — no hay generación automática de
// esquema todavía.

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

// POST /auth/login devuelve TokenPair (sin 2FA) o esto (con 2FA):
export interface Requires2FA {
  requires_2fa: true;
  temp_token: string;
}

export type LoginResponse = TokenPair | Requires2FA;

export function requiere2FA(r: LoginResponse): r is Requires2FA {
  return (r as Requires2FA).requires_2fa === true;
}

export interface Verify2FAResponse {
  two_factor_enabled: boolean;
  codigos_respaldo: string[];
}

export interface Setup2FAResponse {
  otpauth_uri: string;
  qr_code_base64: string;
}

// POST /auth/2fa/backup-codes/regenerate
export interface RegenerarCodigosResponse {
  codigos_respaldo: string[];
}

export type Role = "admin" | "abogado" | "cliente";

// GET /auth/me
export interface Perfil {
  id: string;
  email: string;
  role: Role;
  totp_enabled: boolean;
}

export type EstadoCaso = "abierto" | "en_progreso" | "cerrado";

export interface Caso {
  id: string;
  cliente_id: string;
  abogado_id: string | null;
  titulo: string;
  descripcion: string | null;
  estado: EstadoCaso;
  created_at: string;
  updated_at: string;
}

export interface CaseDocument {
  id: string;
  caso_id: string;
  created_by: string;
  tarea: string;
  pregunta: string;
  contenido?: string; // el listado liviano no lo trae; el detalle sí
  pdf_url: string | null;
  created_at: string;
}

export interface CrearDocumentoInput {
  pregunta: string;
  tarea?: string;
  generar_pdf?: boolean;
}

export interface Mensaje {
  id: string;
  conversacion_id: string;
  autor_id: string;
  texto: string;
  adjunto_url: string | null;
  adjunto_nombre: string | null;
  borrado: boolean;
  created_at: string;
}

// POST /casos/{id}/mensajes/adjuntos -- adjunto_url NUNCA es un link
// público (ver api/mensajes_endpoint.py::descargar_adjunto_endpoint), se
// pasa tal cual a POST /mensajes y se descarga autenticado después.
export interface AdjuntoSubido {
  adjunto_url: string;
  adjunto_nombre: string;
}

// GET /api/events/stream (SSE) -- cada evento trae al menos id/type; el
// resto del payload depende de `type` (para "message.new":
// caso_id/conversacion_id/mensaje_id, ver api/mensajes_endpoint.py).
export interface EventoSSE {
  id: number;
  type: string;
  [key: string]: unknown;
}

export interface MessageNewEvent extends EventoSSE {
  type: "message.new";
  caso_id: string;
  conversacion_id: string;
  mensaje_id: string;
}

export interface ActuacionNuevaEvent extends EventoSSE {
  type: "actuacion.nueva";
  caso_id: string;
  actuacion_id: string;
  categoria: CategoriaActuacion;
}

// Alerta proactiva de un término en riesgo (roadmap Fase 2, ver
// procesal/alertas_terminos.py) -- llega aunque nadie haya abierto el caso.
export interface TerminoAlertaEvent extends EventoSSE {
  type: "termino.alerta";
  caso_id: string;
  termino_id: string;
  descripcion: string;
  fecha_vencimiento: string;
}

// --- panel admin (roadmap S2) ----------------------------------------------
export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface CrearUsuarioAdminInput {
  email: string;
  password: string;
  role: Role;
}

export interface AuthEvent {
  id: string;
  event_type: string;
  metadata: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface ResetPasswordResult {
  user_id: string;
  password_temporal: string;
}

// GET /admin/costos
export interface CostosResponse {
  gasto_mensual_usd: number;
  limite_mensual_usd: number;
  aviso_80: boolean;
  confirmacion_100: boolean;
}

// --- Fase 2: actuaciones + términos (procesal/) ----------------------------
export type CategoriaActuacion = "auto_admisorio" | "requerimiento" | "fallo" | "traslado" | "otro";

// POST/GET /casos/{id}/actuaciones
export interface Actuacion {
  id: string;
  caso_id: string;
  created_by: string;
  texto: string;
  categoria: CategoriaActuacion;
  confianza: number;
  texto_bruto_clasificacion: string;
  created_at: string;
}

export type EstadoTermino = "pendiente" | "cumplido";

// POST/GET /casos/{id}/terminos -- fecha_vencimiento y dias_restantes los
// calcula siempre el backend (ver core/terminos.py); nunca se proponen a mano.
export interface Termino {
  id: string;
  caso_id: string;
  created_by: string;
  descripcion: string;
  fecha_inicio: string;
  dias_habiles: number;
  fecha_vencimiento: string;
  incluye_ventana_sin_confirmar: boolean;
  actuacion_id: string | null;
  estado: EstadoTermino;
  created_at: string;
  dias_restantes: number;
}

export interface CrearTerminoInput {
  descripcion: string;
  fecha_inicio: string;
  dias_habiles: number;
  actuacion_id?: string | null;
}

// --- Fase 3: cobro inteligente (valor en disputa + honorarios) -----------
export type EsquemaHonorarios = "fijo" | "cuota_litis" | "mixto";

// GET/POST /casos/{id}/cobro -- honorarios_liquidados SIEMPRE lo calcula el
// backend (core/cobro.py), nunca se propone desde acá.
export interface Cobro {
  caso_id: string;
  valor_en_disputa: number | null;
  esquema_honorarios: EsquemaHonorarios | null;
  monto_fijo: number | null;
  porcentaje_cuota_litis: number | null;
  valor_recuperado: number | null;
  honorarios_liquidados: number | null;
  liquidado_en: string | null;
}

export interface SetCobroInput {
  valor_en_disputa?: number | null;
  esquema_honorarios?: EsquemaHonorarios | null;
  monto_fijo?: number | null;
  porcentaje_cuota_litis?: number | null;
}

// GET /cobro/ahorro -- exclusivo del rol cliente, siempre sobre sus
// propios casos liquidados (roadmap: "Panel 'ahorro generado' en Portal
// Cliente Vridik").
export interface ResumenAhorro {
  casos_liquidados: number;
  total_valor_recuperado: number;
  total_honorarios_liquidados: number;
  ahorro_generado: number;
}
