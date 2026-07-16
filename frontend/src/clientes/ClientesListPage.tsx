import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { Cliente } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { fechaCorta } from "../ui";

/** Fase 4 (SAGRILAFT lite): lista de clientes del despacho -- exclusiva de
 *  abogado/admin (lo exige el backend igual). Sin esto no había ninguna
 *  vista de "cliente" independiente del caso: todo colgaba de `casos`. */
export function ClientesListPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();
  const [clientes, setClientes] = useState<Cliente[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function cargar() {
    setError(null);
    try {
      setClientes(await api.listClientes());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudieron cargar los clientes.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (perfil.role !== "admin" && perfil.role !== "abogado") {
    return (
      <div className="page">
        <p className="eyebrow">Clientes</p>
        <h1 className="page-title">Clientes</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Clientes</p>
          <h1 className="page-title">Clientes del despacho</h1>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
          <button className="btn btn-ghost btn-sm" onClick={() => void cargar()}>Reintentar</button>
        </div>
      )}

      {clientes === null ? (
        error ? null : (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        )
      ) : clientes.length === 0 ? (
        <div className="card empty-state">
          <p className="empty-title">Todavía no hay clientes en este despacho.</p>
        </div>
      ) : (
        <ul className="caso-list">
          {clientes.map((c) => (
            <li key={c.id}>
              <Link className="caso-row card" to={`/clientes/${c.id}`}>
                <div className="caso-row-main">
                  <span className="caso-row-title">{c.email}</span>
                </div>
                <div className="caso-row-meta">
                  <span className="faint mono caso-row-date">{fechaCorta(c.created_at)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
