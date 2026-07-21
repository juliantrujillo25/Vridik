import { useState } from "react";
import { Link, NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { useTheme } from "./theme";

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrador",
  abogado: "Abogado",
  cliente: "Cliente",
};

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

/** Envuelve las rutas que requieren sesión: si no hay, manda a /login.
 *  TF4 (rediseño "ledger editorial"): sidebar fijo en desktop (>900px),
 *  colapsa a drawer en mobile -- reemplaza el header horizontal simple que
 *  había antes. Misma lista de destinos que el nav anterior, condicionados
 *  por rol igual que hoy; "Casos" se agrega como item explícito (antes solo
 *  se llegaba ahí por la marca). */
export function ProtectedLayout() {
  const { autenticado, perfil, logout } = useAuth();
  const navigate = useNavigate();
  const [sidebarAbierto, setSidebarAbierto] = useState(false);

  if (!autenticado) return <Navigate to="/login" replace />;

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  function cerrarSidebar() {
    setSidebarAbierto(false);
  }

  const linkClase = ({ isActive }: { isActive: boolean }) => `sidebar-link${isActive ? " active" : ""}`;

  const nav = (
    <nav className="sidebar-nav" onClick={cerrarSidebar}>
      <NavLink className={linkClase} to="/casos">Casos</NavLink>
      {(perfil?.role === "admin" || perfil?.role === "abogado") && (
        <NavLink className={linkClase} to="/clientes">Clientes</NavLink>
      )}
      {(perfil?.role === "admin" || perfil?.role === "abogado") && (
        <NavLink className={linkClase} to="/analitica/ugpp">Analítica UGPP</NavLink>
      )}
      {perfil?.role === "admin" && (
        <NavLink className={linkClase} to="/admin">Admin</NavLink>
      )}
      {perfil?.es_superadmin && (
        <NavLink className={linkClase} to="/plataforma">Plataforma</NavLink>
      )}
      {perfil?.es_superadmin && (
        <NavLink className={linkClase} to="/plataforma/corpus">Corpus</NavLink>
      )}
      <NavLink className={linkClase} to="/cuenta">Cuenta</NavLink>
    </nav>
  );

  return (
    <div className="app-shell">
      {sidebarAbierto && <div className="sidebar-backdrop" onClick={cerrarSidebar} aria-hidden="true" />}

      <aside className={`app-sidebar${sidebarAbierto ? " open" : ""}`}>
        <Link className="brand" to="/casos" onClick={cerrarSidebar}>
          <span className="brand-mark" aria-hidden="true">§</span>
          Vridik
          <span className="brand-sub">copiloto legal</span>
        </Link>

        {nav}

        <div className="sidebar-footer">
          {perfil && (
            <div className="sidebar-user">
              <span className="sidebar-user-email">{perfil.email}</span>
              <span className="sidebar-user-role faint">{ROLE_LABEL[perfil.role] ?? perfil.role}</span>
            </div>
          )}
          <div className="sidebar-footer-actions">
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>Salir</button>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="app-content">
        <header className="app-topbar">
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={sidebarAbierto ? "Cerrar menú" : "Abrir menú"}
            aria-expanded={sidebarAbierto}
            onClick={() => setSidebarAbierto((v) => !v)}
          >
            <svg viewBox="0 0 20 16" width="20" height="16" aria-hidden="true">
              <line x1="0" y1="1" x2="20" y2="1" stroke="currentColor" strokeWidth="1.6" />
              <line x1="0" y1="8" x2="20" y2="8" stroke="currentColor" strokeWidth="1.6" />
              <line x1="0" y1="15" x2="20" y2="15" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </button>
          <Link className="brand brand-topbar" to="/casos">
            <span className="brand-mark" aria-hidden="true">§</span>
            Vridik
          </Link>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
