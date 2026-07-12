// Cliente de la API de Vridik.
//
// Estrategia de tokens (roadmap S1): el access token vive SOLO en memoria
// (nunca en localStorage, para reducir superficie de robo vía XSS); el
// refresh token (7 días) sí va a localStorage bajo la clave del roadmap
// `vridik.auth.refresh`, para sobrevivir un reload. En cada 401 se intenta
// una renovación silenciosa vía POST /auth/refresh y se reintenta el
// request original una sola vez.

import type {
  Caso,
  CaseDocument,
  CrearDocumentoInput,
  EstadoCaso,
  LoginResponse,
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

  // --- 2FA (requieren access token) ---------------------------------------
  async setup2fa(): Promise<{ otpauth_uri: string; qr_code_base64: string }> {
    return this.request("/auth/2fa/setup", { method: "POST" });
  }

  async verify2fa(code: string): Promise<Verify2FAResponse> {
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
}

export const api = new ApiClient();
