import { Link, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { useTheme } from "./theme";

function ThemeToggle() {
  const { tema, toggleTheme } = useTheme();
  const esOscuro = tema === "dark";
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={esOscuro ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
      title={esOscuro ? "Tema claro" : "Tema oscuro"}
    >
      {esOscuro ? (
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M8 3 A5 5 0 0 0 8 13 Z" fill="currentColor" />
        </svg>
      ) : (
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <line x1="8" y1="0.5" x2="8" y2="2.5" stroke="currentColor" strokeWidth="1.2" />
          <line x1="8" y1="13.5" x2="8" y2="15.5" stroke="currentColor" strokeWidth="1.2" />
          <line x1="0.5" y1="8" x2="2.5" y2="8" stroke="currentColor" strokeWidth="1.2" />
          <line x1="13.5" y1="8" x2="15.5" y2="8" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      )}
    </button>
  );
}

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
            {(perfil?.role === "admin" || perfil?.role === "abogado") && (
              <Link className="btn btn-ghost btn-sm" to="/analitica/ugpp">Analítica UGPP</Link>
            )}
            {perfil?.role === "admin" && (
              <Link className="btn btn-ghost btn-sm" to="/admin">Admin</Link>
            )}
            {perfil?.es_superadmin && (
              <Link className="btn btn-ghost btn-sm" to="/plataforma">Plataforma</Link>
            )}
            {perfil?.es_superadmin && (
              <Link className="btn btn-ghost btn-sm" to="/plataforma/corpus">Corpus</Link>
            )}
            <Link className="btn btn-ghost btn-sm" to="/cuenta">Cuenta</Link>
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>Salir</button>
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
