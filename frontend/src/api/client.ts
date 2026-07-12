// Cliente de la API de Vridik.
//
// Estrategia de tokens (roadmap S1): el access token vive SOLO en memoria
// (nunca en localStorage, para reducir superficie de robo vía XSS); el
// refresh token (7 días) sí va a localStorage bajo la clave del roadmap
// `vridik.auth.refresh`, para sobrevivir un reload. En cada 401 se intenta
// una renovación silenciosa vía POST /auth/refresh y se reintenta el
// request original una sola vez.

import type {
  AdminUser,
  AuthEvent,
  Caso,
  CaseDocument,
  CrearDocumentoInput,
  CrearUsuarioAdminInput,
  EstadoCaso,
  EventoSSE,
  LoginResponse,
  Mensaje,
  Perfil,
  ResetPasswordResult,
  Role,
  Setup2FAResponse,
  TokenPair,
  Verify2FAResponse,
} from "./types";

// Sin VITE_API_BASE (dev): pasa por el proxy de vite.config.ts, namespaceado
// bajo /api-proxy para no chocar con las rutas de la SPA (ver ese archivo).
// Con VITE_API_BASE (build de producción, .env.production): URL real de
// Railway, sin proxy.
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api-proxy";
const REFRESH_KEY = "vridik.auth.refresh";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Se lanza cuando la sesión ya no se puede recuperar (refresh inválido). */
export class SesionExpiradaError extends ApiError {
  constructor() {
    super(401, "Tu sesión expiró. Volvé a iniciar sesión.");
    this.name = "SesionExpiradaError";
  }
}

type Listener = (autenticado: boolean) => void;

class ApiClient {
  private accessToken: string | null = null;
  private listeners = new Set<Listener>();
  private refreshEnCurso: Promise<boolean> | null = null;

  // --- sesión -------------------------------------------------------------
  get refreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  }

  get autenticado(): boolean {
    return this.accessToken !== null || this.refreshToken !== null;
  }

  setSession(tokens: TokenPair): void {
    this.accessToken = tokens.access_token;
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    this.emit();
  }

  clearSession(): void {
    this.accessToken = null;
    localStorage.removeItem(REFRESH_KEY);
    this.emit();
  }

  onAuthChange(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private emit(): void {
    for (const l of this.listeners) l(this.autenticado);
  }

  // --- núcleo de fetch ----------------------------------------------------
  private async raw(path: string, init: RequestInit, conAuth: boolean): Promise<Response> {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (conAuth && this.accessToken) {
      headers.set("Authorization", `Bearer ${this.accessToken}`);
    }
    return fetch(`${API_BASE}${path}`, { ...init, headers });
  }

  private async parse<T>(resp: Response): Promise<T> {
    if (resp.status === 204) return undefined as T;
    const texto = await resp.text();
    const data = texto ? JSON.parse(texto) : undefined;
    if (!resp.ok) {
      const detalle =
        (data && (data.detail ?? data.message)) || `Error ${resp.status}`;
      throw new ApiError(resp.status, typeof detalle === "string" ? detalle : JSON.stringify(detalle));
    }
    return data as T;
  }

  /** Request autenticado con renovación silenciosa en 401. */
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let resp = await this.raw(path, init, true);
    if (resp.status === 401 && this.refreshToken) {
      const ok = await this.renovar();
      if (!ok) throw new SesionExpiradaError();
      resp = await this.raw(path, init, true);
    }
    return this.parse<T>(resp);
  }

  /** Comparte una única renovación entre requests concurrentes que fallen 401. */
  private async renovar(): Promise<boolean> {
    if (!this.refreshEnCurso) {
      this.refreshEnCurso = (async () => {
        const rt = this.refreshToken;
        if (!rt) return false;
        const resp = await this.raw(
          "/auth/refresh",
          { method: "POST", body: JSON.stringify({ refresh_token: rt }) },
          false,
        );
        if (!resp.ok) {
          this.clearSession();
          return false;
        }
        const tokens = (await resp.json()) as TokenPair;
        this.setSession(tokens);
        return true;
      })().finally(() => {
        this.refreshEnCurso = null;
      });
    }
    return this.refreshEnCurso;
  }

  // --- auth (sin token previo) --------------------------------------------
  async login(email: string, password: string): Promise<LoginResponse> {
    const resp = await this.raw(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    );
    return this.parse<LoginResponse>(resp);
  }

  async login2fa(temp_token: string, code: string): Promise<TokenPair> {
    const resp = await this.raw(
      "/auth/2fa/login",
      { method: "POST", body: JSON.stringify({ temp_token, code }) },
      false,
    );
    return this.parse<TokenPair>(resp);
  }

  async register(email: string, password: string): Promise<TokenPair> {
    const resp = await this.raw(
      "/auth/register",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    );
    return this.parse<TokenPair>(resp);
  }

  async logout(): Promise<void> {
    const rt = this.refreshToken;
    if (rt) {
      try {
        await this.raw("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: rt }) }, false);
      } catch {
        // logout es best-effort: aunque el server no responda, limpiamos local.
      }
    }
    this.clearSession();
  }

  // --- perfil / 2FA (requieren access token) -------------------------------
  me(): Promise<Perfil> {
    return this.request("/auth/me");
  }

  setup2fa(): Promise<Setup2FAResponse> {
    return this.request("/auth/2fa/setup", { method: "POST" });
  }

  verify2fa(code: string): Promise<Verify2FAResponse> {
    return this.request("/auth/2fa/verify", { method: "POST", body: JSON.stringify({ code }) });
  }

  // --- casos --------------------------------------------------------------
  listCasos(): Promise<Caso[]> {
    return this.request("/casos");
  }

  getCaso(id: string): Promise<Caso> {
    return this.request(`/casos/${id}`);
  }

  crearCaso(titulo: string, descripcion?: string): Promise<Caso> {
    return this.request("/casos", {
      method: "POST",
      body: JSON.stringify({ titulo, descripcion: descripcion || null }),
    });
  }

  cambiarEstado(id: string, estado: EstadoCaso): Promise<Caso> {
    return this.request(`/casos/${id}/estado`, { method: "PATCH", body: JSON.stringify({ estado }) });
  }

  // --- documentos generados por JuliX -------------------------------------
  listDocumentos(casoId: string): Promise<CaseDocument[]> {
    return this.request(`/casos/${casoId}/documents`);
  }

  getDocumento(casoId: string, docId: string): Promise<CaseDocument> {
    return this.request(`/casos/${casoId}/documents/${docId}`);
  }

  /** OJO: dispara una llamada real a Anthropic (cuesta dinero) y puede
   *  tardar decenas de segundos mientras JuliX genera el documento. */
  crearDocumento(casoId: string, input: CrearDocumentoInput): Promise<CaseDocument> {
    return this.request(`/casos/${casoId}/documents`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  // --- mensajería (roadmap S11) --------------------------------------------
  listMensajes(casoId: string, limit = 50): Promise<Mensaje[]> {
    return this.request(`/casos/${casoId}/mensajes?limit=${limit}`);
  }

  crearMensaje(casoId: string, texto: string, adjuntoUrl?: string): Promise<Mensaje> {
    return this.request(`/casos/${casoId}/mensajes`, {
      method: "POST",
      body: JSON.stringify({ texto, adjunto_url: adjuntoUrl ?? null }),
    });
  }

  marcarLeido(casoId: string, mensajeId: string): Promise<void> {
    return this.request(`/casos/${casoId}/mensajes/${mensajeId}/leido`, { method: "POST" });
  }

  borrarMensaje(casoId: string, mensajeId: string): Promise<void> {
    return this.request(`/casos/${casoId}/mensajes/${mensajeId}`, { method: "DELETE" });
  }

  // --- panel admin (roadmap S2) --------------------------------------------
  adminListUsers(skip = 0, limit = 20): Promise<AdminUser[]> {
    return this.request(`/admin/users?skip=${skip}&limit=${limit}`);
  }

  adminCrearUsuario(input: CrearUsuarioAdminInput): Promise<AdminUser> {
    return this.request("/admin/users", { method: "POST", body: JSON.stringify(input) });
  }

  adminCambiarRol(userId: string, role: Role): Promise<AdminUser> {
    return this.request(`/admin/users/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  }

  adminActividad(userId: string, limite = 50): Promise<AuthEvent[]> {
    return this.request(`/admin/users/${userId}/actividad?limite=${limite}`);
  }

  adminResetPassword(userId: string): Promise<ResetPasswordResult> {
    return this.request(`/admin/users/${userId}/reset-password`, { method: "POST" });
  }

  adminReset2FA(userId: string): Promise<{ user_id: string; two_factor_enabled: boolean }> {
    return this.request(`/admin/users/${userId}/reset-2fa`, { method: "POST" });
  }

  // --- eventos en vivo (SSE, roadmap S11 Fase C) ---------------------------
  //
  // El navegador no puede usar EventSource nativo porque necesita mandar el
  // header Authorization (el backend lo exige explícitamente, ver
  // api/events_endpoint.py) -- se arma el parseo de SSE a mano sobre
  // fetch + ReadableStream. Reconecta solo (con Last-Event-ID) si el stream
  // se corta; devuelve una función para cerrar la conexión.
  streamEvents(onEvento: (ev: EventoSSE) => void, onResync?: () => void): () => void {
    const controller = new AbortController();
    let lastEventId: number | null = null;

    const bucle = async () => {
      while (!controller.signal.aborted) {
        try {
          await this.conectarStreamUnaVez(controller.signal, lastEventId, (id) => {
            lastEventId = id;
          }, onEvento, onResync);
        } catch {
          // red caída, 401 sin refresh posible, etc. -- se reintenta abajo.
        }
        if (controller.signal.aborted) return;
        await new Promise((r) => setTimeout(r, 2000));
      }
    };
    void bucle();

    return () => controller.abort();
  }

  private async conectarStreamUnaVez(
    signal: AbortSignal,
    lastEventId: number | null,
    setLastEventId: (id: number) => void,
    onEvento: (ev: EventoSSE) => void,
    onResync?: () => void,
  ): Promise<void> {
    if (!this.accessToken) {
      const ok = await this.renovar();
      if (!ok) throw new SesionExpiradaError();
    }
    const headers = new Headers({ Authorization: `Bearer ${this.accessToken}` });
    if (lastEventId !== null) headers.set("Last-Event-ID", String(lastEventId));

    const resp = await fetch(`${API_BASE}/api/events/stream`, { headers, signal });
    if (!resp.ok || !resp.body) throw new Error(`stream ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const bloque = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        this.procesarBloqueSSE(bloque, setLastEventId, onEvento, onResync);
      }
    }
  }

  private procesarBloqueSSE(
    bloque: string,
    setLastEventId: (id: number) => void,
    onEvento: (ev: EventoSSE) => void,
    onResync?: () => void,
  ): void {
    let tipo: string | null = null;
    let dataLine: string | null = null;
    for (const linea of bloque.split("\n")) {
      if (linea.startsWith("event:")) tipo = linea.slice(6).trim();
      else if (linea.startsWith("data:")) dataLine = linea.slice(5).trim();
    }
    if (tipo === "resync") {
      onResync?.();
      return;
    }
    if (!dataLine) return;
    const data = JSON.parse(dataLine) as EventoSSE;
    setLastEventId(data.id);
    onEvento(data);
  }
}

export const api = new ApiClient();
