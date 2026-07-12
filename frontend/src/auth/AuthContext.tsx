import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Perfil } from "../api/types";

interface AuthState {
  autenticado: boolean;
  /** null mientras carga o si no hay sesión; el perfil real una vez resuelto. */
  perfil: Perfil | null;
  logout: () => Promise<void>;
  /** Se llama tras un login/2fa exitoso para reflejar el nuevo estado. */
  sesionActualizada: () => void;
  /** Vuelve a pedir /auth/me (p.ej. después de activar 2FA). */
  recargarPerfil: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [autenticado, setAutenticado] = useState(api.autenticado);
  const [perfil, setPerfil] = useState<Perfil | null>(null);

  async function recargarPerfil() {
    if (!api.autenticado) {
      setPerfil(null);
      return;
    }
    try {
      setPerfil(await api.me());
    } catch {
      setPerfil(null);
    }
  }

  useEffect(() => {
    // El cliente emite cuando cambian los tokens (incluida la renovación
    // silenciosa y el clear en un refresh inválido).
    return api.onAuthChange(setAutenticado);
  }, []);

  useEffect(() => {
    if (autenticado) void recargarPerfil();
    else setPerfil(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autenticado]);

  const value = useMemo<AuthState>(
    () => ({
      autenticado,
      perfil,
      logout: () => api.logout(),
      sesionActualizada: () => setAutenticado(api.autenticado),
      recargarPerfil,
    }),
    [autenticado, perfil],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
