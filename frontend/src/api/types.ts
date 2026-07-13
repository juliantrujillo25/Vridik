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
  borrado: boolean;
  created_at: string;
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
