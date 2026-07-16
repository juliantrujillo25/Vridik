import { Link, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";

/** Envuelve las rutas que requieren sesión: si no hay, manda a /login. */
export function ProtectedLayout() {
  const { autenticado, perfil, logout } = useAuth();
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
          <Link className="brand" to="/casos">
            <span className="brand-mark" aria-hidden="true">§</span>
            Vridik
            <span className="brand-sub">copiloto legal</span>
          </Link>
          <nav className="app-nav">
            {(perfil?.role === "admin" || perfil?.role === "abogado") && (
              <Link className="btn btn-ghost btn-sm" to="/clientes">Clientes</Link>
            )}
            {perfil?.role === "admin" && (
              <Link className="btn btn-ghost btn-sm" to="/admin">Admin</Link>
            )}
            {perfil?.es_superadmin && (
              <Link className="btn btn-ghost btn-sm" to="/plataforma">Plataforma</Link>
            )}
            <Link className="btn btn-ghost btn-sm" to="/cuenta">Cuenta</Link>
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>Salir</button>
          </nav>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
