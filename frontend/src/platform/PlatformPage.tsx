import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, SesionExpiradaError } from "../api/client";
import type { Despacho, IntegridadBitacora, Plan } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { fechaHora } from "../ui";

const PLAN_LABEL: Record<Plan, string> = { piloto: "Piloto", pagado: "Pagado" };
const PLANES: Plan[] = ["piloto", "pagado"];

/** Fase 4 (pricing por despacho): exclusivo del admin de PLATAFORMA
 *  (perfil.es_superadmin) -- distinto del panel /admin, que es por-despacho.
 *  El backend ya lo exige real (get_current_superadmin); esta página solo
 *  evita mostrarle una pantalla vacía/con 403 a quien no puede usarla. */
export function PlatformPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [despachos, setDespachos] = useState<Despacho[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cambiandoId, setCambiandoId] = useState<string | null>(null);

  const [integridad, setIntegridad] = useState<IntegridadBitacora | null>(null);
  const [verificando, setVerificando] = useState(false);
  const [errorIntegridad, setErrorIntegridad] = useState<string | null>(null);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
    setError(err instanceof Error ? err.message : fallback);
  }

  async function cargar() {
    setError(null);
    try {
      setDespachos(await api.platformListDespachos());
    } catch (err) {
      manejarError(err, "No se pudo cargar la lista de despachos.");
    }
  }

  useEffect(() => {
    if (perfil?.es_superadmin) void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perfil?.es_superadmin]);

  async function onCambiarPlan(d: Despacho, plan: Plan) {
    if (plan === d.plan) return;
    setCambiandoId(d.id);
    try {
      const actualizado = await api.platformCambiarPlan(d.id, plan);
      setDespachos((prev) =>
        prev?.map((x) => (x.id === d.id ? { ...x, plan: actualizado.plan } : x)) ?? prev,
      );
    } catch (err) {
      manejarError(err, "No se pudo cambiar el plan.");
    } finally {
      setCambiandoId(null);
    }
  }

  async function onVerificarIntegridad() {
    setVerificando(true);
    setErrorIntegridad(null);
    try {
      setIntegridad(await api.verificarBitacora());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setErrorIntegridad(err instanceof Error ? err.message : "No se pudo verificar la bitácora.");
    } finally {
      setVerificando(false);
    }
  }

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (!perfil.es_superadmin) {
    return (
      <div className="page">
        <p className="eyebrow">Plataforma</p>
        <h1 className="page-title">Admin de plataforma</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Plataforma</p>
          <h1 className="page-title">Despachos</h1>
        </div>
      </div>

      <div className="card bitacora-widget">
        <div className="bitacora-widget-head">
          <span className="section-title bitacora-widget-title">Bitácora sellada (hash encadenado)</span>
          <button className="btn btn-ghost btn-sm" onClick={onVerificarIntegridad} disabled={verificando}>
            {verificando ? "Verificando…" : "Verificar integridad"}
          </button>
        </div>
        {errorIntegridad && <div className="alert error" role="alert">{errorIntegridad}</div>}
        {integridad && (
          <p className={`bitacora-resultado ${integridad.integra ? "bitacora-ok" : "bitacora-rota"}`}>
            {integridad.integra
              ? `Íntegra -- ${integridad.total_verificados} eventos verificados, sin alteraciones.`
              : `ALTERADA -- la cadena se rompe en el evento #${integridad.primera_ruptura_id}.`}
          </p>
        )}
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      {despachos === null ? (
        error ? (
          <div className="empty muted">
            <button className="btn btn-ghost btn-sm" onClick={() => void cargar()}>Reintentar</button>
          </div>
        ) : (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        )
      ) : (
        <ul className="admin-user-list">
          {despachos.map((d) => (
            <li key={d.id} className="card admin-user-row">
              <div className="admin-user-main">
                <span className="admin-user-email">{d.nombre}</span>
                <span className="faint mono">{fechaHora(d.created_at)}</span>
                <span className="faint mono">
                  {d.cantidad_usuarios} usuario{d.cantidad_usuarios === 1 ? "" : "s"}
                </span>
                <span className="faint mono">${d.gasto_mensual_usd.toFixed(2)} este mes</span>
                {!d.activo && <span className="pill cerrado">Inactivo</span>}
              </div>
              <div className="admin-user-actions">
                <select
                  className="select select-sm"
                  value={d.plan}
                  disabled={cambiandoId === d.id}
                  onChange={(e) => onCambiarPlan(d, e.target.value as Plan)}
                >
                  {PLANES.map((p) => (
                    <option key={p} value={p}>{PLAN_LABEL[p]}</option>
                  ))}
                </select>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
