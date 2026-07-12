import { Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";

/** Envuelve las rutas que requieren sesión: si no hay, manda a /login. */
export function ProtectedLayout() {
  const { autenticado, logout } = useAuth();
  const navigate = useNavigate();

  if (!autenticado) return <Navigate to="/login" replace />;

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <a className="brand" href="/casos">
            <span className="brand-mark" aria-hidden="true">§</span>
            Vridik
            <span className="brand-sub">copiloto legal</span>
          </a>
          <button className="btn btn-ghost btn-sm" onClick={onLogout}>Salir</button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
