import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Perfil } from "../api/types";

interface AuthState {
  autenticado: boolean;
  /** null mientras carga, si falló, o si no hay sesión; el perfil real una vez resuelto. */
  perfil: Perfil | null;
  /** true mientras hay una carga de perfil en curso (inicial o por recargarPerfil). */
  perfilCargando: boolean;
  /** Mensaje si la última carga de perfil falló por algo que no sea sesión vencida
   *  (esa se resuelve sola: autenticado pasa a false y ProtectedLayout manda a /login). */
  perfilError: string | null;
  logout: () => Promise<void>;
  /** Se llama tras un login/2fa exitoso para reflejar el nuevo estado. */
  sesionActualizada: () => void;
  /** Vuelve a pedir /auth/me (p.ej. después de activar 2FA, o para reintentar tras un error). */
  recargarPerfil: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [autenticado, setAutenticado] = useState(api.autenticado);
  const [perfil, setPerfil] = useState<Perfil | null>(null);
  const [perfilCargando, setPerfilCargando] = useState(api.autenticado);
  const [perfilError, setPerfilError] = useState<string | null>(null);

  async function recargarPerfil() {
    if (!api.autenticado) {
      setPerfil(null);
      setPerfilCargando(false);
      setPerfilError(null);
      return;
    }
    setPerfilCargando(true);
    setPerfilError(null);
    try {
      setPerfil(await api.me());
    } catch (err) {
      setPerfil(null);
      setPerfilError(err instanceof Error ? err.message : "No se pudo cargar tu cuenta.");
    } finally {
      setPerfilCargando(false);
    }
  }

  useEffect(() => {
    // El cliente emite cuando cambian los tokens (incluida la renovación
    // silenciosa y el clear en un refresh inválido).
    return api.onAuthChange(setAutenticado);
  }, []);

  useEffect(() => {
    if (autenticado) {
      void recargarPerfil();
    } else {
      setPerfil(null);
      setPerfilCargando(false);
      setPerfilError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autenticado]);

  const value = useMemo<AuthState>(
    () => ({
      autenticado,
      perfil,
      perfilCargando,
      perfilError,
      logout: () => api.logout(),
      sesionActualizada: () => setAutenticado(api.autenticado),
      recargarPerfil,
    }),
    [autenticado, perfil, perfilCargando, perfilError],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
