import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, SesionExpiradaError } from "../api/client";
import type { AdminUser, AuthEvent, CostosResponse, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { fechaHora } from "../ui";

const ROLES: Role[] = ["cliente", "abogado", "admin"];
const ROLE_LABEL: Record<Role, string> = { cliente: "Cliente", abogado: "Abogado", admin: "Admin" };
const LIMITE_PAGINA = 20;

export function AdminPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [usuarios, setUsuarios] = useState<AdminUser[] | null>(null);
  const [hayMas, setHayMas] = useState(true);
  const [cargandoMas, setCargandoMas] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mostrarCrear, setMostrarCrear] = useState(false);
  const [nuevoEmail, setNuevoEmail] = useState("");
  const [nuevoPassword, setNuevoPassword] = useState("");
  const [nuevoRol, setNuevoRol] = useState<Role>("cliente");
  const [creando, setCreando] = useState(false);

  const [actividadDe, setActividadDe] = useState<AdminUser | null>(null);
  const [actividad, setActividad] = useState<AuthEvent[] | null>(null);

  const [passwordTemporal, setPasswordTemporal] = useState<{ userId: string; valor: string } | null>(null);

  const [costos, setCostos] = useState<CostosResponse | null>(null);
  const [errorCostos, setErrorCostos] = useState<string | null>(null);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
    setError(err instanceof Error ? err.message : fallback);
  }

  async function cargar(reset: boolean) {
    setError(null);
    try {
      const skip = reset ? 0 : usuarios?.length ?? 0;
      const pagina = await api.adminListUsers(skip, LIMITE_PAGINA);
      setUsuarios((prev) => (reset || !prev ? pagina : [...prev, ...pagina]));
      setHayMas(pagina.length === LIMITE_PAGINA);
    } catch (err) {
      manejarError(err, "No se pudo cargar la lista de usuarios.");
    }
  }

  async function cargarCostos() {
    setErrorCostos(null);
    try {
      setCostos(await api.adminCostos());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setErrorCostos(err instanceof Error ? err.message : "No se pudo cargar el gasto de JuliX.");
    }
  }

  useEffect(() => {
    if (perfil?.role === "admin") {
      void cargar(true);
      void cargarCostos();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perfil?.role]);

  async function onCargarMas() {
    setCargandoMas(true);
    await cargar(false);
    setCargandoMas(false);
  }

  async function onCrear(e: FormEvent) {
    e.preventDefault();
    setCreando(true);
    setError(null);
    try {
      const creado = await api.adminCrearUsuario({ email: nuevoEmail.trim(), password: nuevoPassword, role: nuevoRol });
      setUsuarios((prev) => (prev ? [creado, ...prev] : [creado]));
      setNuevoEmail("");
      setNuevoPassword("");
      setNuevoRol("cliente");
      setMostrarCrear(false);
    } catch (err) {
      manejarError(err, "No se pudo crear el usuario.");
    } finally {
      setCreando(false);
    }
  }

  async function onCambiarRol(u: AdminUser, role: Role) {
    if (role === u.role) return;
    try {
      const actualizado = await api.adminCambiarRol(u.id, role);
      setUsuarios((prev) => prev?.map((x) => (x.id === actualizado.id ? actualizado : x)) ?? prev);
    } catch (err) {
      manejarError(err, "No se pudo cambiar el rol.");
    }
  }

  async function onVerActividad(u: AdminUser) {
    setActividadDe(u);
    setActividad(null);
    try {
      setActividad(await api.adminActividad(u.id));
    } catch (err) {
      manejarError(err, "No se pudo cargar la actividad.");
    }
  }

  async function onResetPassword(u: AdminUser) {
    const ok = window.confirm(`¿Generar una contraseña temporal nueva para ${u.email}? Esto cierra sus sesiones activas.`);
    if (!ok) return;
    try {
      const res = await api.adminResetPassword(u.id);
      setPasswordTemporal({ userId: u.id, valor: res.password_temporal });
    } catch (err) {
      manejarError(err, "No se pudo resetear la contraseña.");
    }
  }

  async function onReset2FA(u: AdminUser) {
    const ok = window.confirm(`¿Desactivar el 2FA de ${u.email}? Va a poder entrar solo con contraseña hasta que lo reactive.`);
    if (!ok) return;
    try {
      await api.adminReset2FA(u.id);
      window.alert(`2FA desactivado para ${u.email}.`);
    } catch (err) {
      manejarError(err, "No se pudo resetear el 2FA.");
    }
  }

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (perfil.role !== "admin") {
    return (
      <div className="page">
        <p className="eyebrow">Admin</p>
        <h1 className="page-title">Panel de administración</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  const ratioCostos = costos ? Math.min(costos.gasto_mensual_usd / costos.limite_mensual_usd, 1) : 0;
  const estadoCostos = costos?.confirmacion_100 ? "critico" : costos?.aviso_80 ? "aviso" : "normal";

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Admin</p>
          <h1 className="page-title">Usuarios</h1>
        </div>
        <button className="btn btn-primary" onClick={() => setMostrarCrear((v) => !v)}>
          {mostrarCrear ? "Cancelar" : "Nuevo usuario"}
        </button>
      </div>

      {errorCostos && <div className="alert error" role="alert">{errorCostos}</div>}

      {costos && (
        <div className={`card costos-widget costos-${estadoCostos}`}>
          <div className="costos-widget-head">
            <span className="section-title costos-widget-title">Gasto de JuliX este mes</span>
            <span className="mono costos-widget-monto">
              ${costos.gasto_mensual_usd.toFixed(2)} <span className="faint">/ ${costos.limite_mensual_usd.toFixed(2)} USD</span>
            </span>
          </div>
          <div className="costos-bar-track">
            <div className="costos-bar-fill" style={{ width: `${ratioCostos * 100}%` }} />
          </div>
          {costos.confirmacion_100 && (
            <p className="costos-nota costos-nota-critico">
              Por encima del límite blando mensual. No bloquea nada, pero cada documento nuevo debería confirmarse a conciencia.
            </p>
          )}
          {!costos.confirmacion_100 && costos.aviso_80 && (
            <p className="costos-nota costos-nota-aviso">Ya pasó el 80% del límite blando mensual.</p>
          )}
        </div>
      )}

      {error && <div className="alert error" role="alert">{error}</div>}

      {mostrarCrear && (
        <form className="card create-form" onSubmit={onCrear}>
          <div className="field">
            <label htmlFor="nuevo-email">Email</label>
            <input
              id="nuevo-email"
              className="input"
              type="email"
              required
              value={nuevoEmail}
              onChange={(e) => setNuevoEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="nuevo-password">Contraseña inicial</label>
            <input
              id="nuevo-password"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={nuevoPassword}
              onChange={(e) => setNuevoPassword(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="nuevo-rol">Rol</label>
            <select id="nuevo-rol" className="select" value={nuevoRol} onChange={(e) => setNuevoRol(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_LABEL[r]}</option>
              ))}
            </select>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={creando}>
              {creando ? "Creando…" : "Crear usuario"}
            </button>
          </div>
        </form>
      )}

      {usuarios === null ? (
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : (
        <>
          <ul className="admin-user-list">
            {usuarios.map((u) => (
              <li key={u.id} className="card admin-user-row">
                <div className="admin-user-main">
                  <span className="admin-user-email">{u.email}</span>
                  <span className="faint mono">{fechaHora(u.created_at)}</span>
                  {!u.is_active && <span className="pill cerrado">Inactivo</span>}
                </div>

                {passwordTemporal?.userId === u.id && (
                  <div className="alert warn admin-password-reveal">
                    Contraseña temporal (se muestra una sola vez):{" "}
                    <code className="mono">{passwordTemporal.valor}</code>
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      onClick={() => setPasswordTemporal(null)}
                    >
                      Ya la copié
                    </button>
                  </div>
                )}

                <div className="admin-user-actions">
                  <select
                    className="select select-sm"
                    value={u.role}
                    disabled={u.id === perfil.id}
                    title={u.id === perfil.id ? "No podés cambiar tu propio rol" : undefined}
                    onChange={(e) => onCambiarRol(u, e.target.value as Role)}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                    ))}
                  </select>
                  <button className="btn btn-ghost btn-sm" onClick={() => onVerActividad(u)}>Actividad</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => onResetPassword(u)}>Resetear contraseña</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => onReset2FA(u)}>Resetear 2FA</button>
                </div>
              </li>
            ))}
          </ul>

          {hayMas && (
            <div className="form-actions">
              <button className="btn btn-ghost" onClick={onCargarMas} disabled={cargandoMas}>
                {cargandoMas ? "Cargando…" : "Cargar más"}
              </button>
            </div>
          )}
        </>
      )}

      {actividadDe && (
        <div className="doc-modal-backdrop" onClick={() => setActividadDe(null)}>
          <div className="doc-modal card" onClick={(e) => e.stopPropagation()}>
            <div className="doc-modal-head">
              <div>
                <span className="mono faint">Actividad</span>
                <h3 className="doc-modal-title">{actividadDe.email}</h3>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setActividadDe(null)}>Cerrar</button>
            </div>
            {actividad === null ? (
              <div className="empty muted"><span className="spinner" /> Cargando…</div>
            ) : actividad.length === 0 ? (
              <p className="muted">Sin eventos registrados.</p>
            ) : (
              <ul className="admin-activity-list">
                {actividad.map((ev) => (
                  <li key={ev.id} className="admin-activity-row">
                    <span className="mono">{ev.event_type}</span>
                    <span className="faint mono">{fechaHora(ev.created_at)}</span>
                    {ev.ip_address && <span className="faint mono">{ev.ip_address}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
