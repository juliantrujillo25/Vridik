import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Notificacion } from "../api/types";

const EVENT_TYPE_LABEL: Record<string, string> = {
  actuacion_notificada: "Nueva actuación en tu caso",
};

function fechaCorta(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

/** Roadmap Fase 3: "Bitácora sellada de notificaciones con acuse". Cada
 *  fila queda registrada de forma sellada (hash encadenado, ver
 *  core/auth_events.py) apenas se notifica -- esto es lo que el
 *  destinatario ve para confirmar que la recibió. Silencioso si no hay
 *  ninguna pendiente (mismo criterio que el resto de los badges). */
export function NotificacionesWidget() {
  const [notificaciones, setNotificaciones] = useState<Notificacion[] | null>(null);
  const [confirmandoId, setConfirmandoId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.misNotificaciones().then(setNotificaciones, () => setNotificaciones([]));
  }, []);

  async function onConfirmar(id: number) {
    setConfirmandoId(id);
    setError(null);
    try {
      await api.confirmarAcuse(id);
      setNotificaciones((prev) => (prev ? prev.map((n) => (n.id === id ? { ...n, acuse_en: new Date().toISOString() } : n)) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo confirmar la notificación.");
    } finally {
      setConfirmandoId(null);
    }
  }

  if (!notificaciones) return null;
  const pendientes = notificaciones.filter((n) => !n.acuse_en);
  if (pendientes.length === 0) return null;

  return (
    <div className="card notificaciones-widget">
      <span className="section-title notificaciones-widget-title">
        Notificaciones pendientes de confirmar
        <span className="faint mono count"> {pendientes.length}</span>
      </span>
      {error && <div className="alert error" role="alert">{error}</div>}
      <ul className="notificaciones-list">
        {pendientes.map((n) => (
          <li key={n.id} className="notificaciones-row">
            <div className="notificaciones-row-main">
              <span>{EVENT_TYPE_LABEL[n.event_type] ?? n.event_type}</span>
              <span className="faint mono">{fechaCorta(n.created_at)}</span>
            </div>
            <div className="notificaciones-row-actions">
              {n.metadata.caso_id && (
                <Link className="btn btn-ghost btn-sm" to={`/casos/${n.metadata.caso_id}`}>
                  Ver caso
                </Link>
              )}
              <button
                className="btn btn-primary btn-sm"
                type="button"
                disabled={confirmandoId === n.id}
                onClick={() => onConfirmar(n.id)}
              >
                {confirmandoId === n.id ? "Confirmando…" : "Confirmar recepción"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
