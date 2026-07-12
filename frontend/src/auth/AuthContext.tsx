import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";

interface AuthState {
  autenticado: boolean;
  logout: () => Promise<void>;
  /** Se llama tras un login/2fa exitoso para reflejar el nuevo estado. */
  sesionActualizada: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [autenticado, setAutenticado] = useState(api.autenticado);

  useEffect(() => {
    // El cliente emite cuando cambian los tokens (incluida la renovación
    // silenciosa y el clear en un refresh inválido).
    return api.onAuthChange(setAutenticado);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      autenticado,
      logout: () => api.logout(),
      sesionActualizada: () => setAutenticado(api.autenticado),
    }),
    [autenticado],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
