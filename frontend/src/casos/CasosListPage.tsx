import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { Caso } from "../api/types";
import { EstadoPill, fechaCorta } from "../ui";

export function CasosListPage() {
  const navigate = useNavigate();
  const [casos, setCasos] = useState<Caso[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [titulo, setTitulo] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [creando, setCreando] = useState(false);
  const [mostrarForm, setMostrarForm] = useState(false);

  async function cargar() {
    setError(null);
    try {
      setCasos(await api.listCasos());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudieron cargar los casos.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onCrear(e: FormEvent) {
    e.preventDefault();
    setCreando(true);
    setError(null);
    try {
      const nuevo = await api.crearCaso(titulo.trim(), descripcion.trim() || undefined);
      setTitulo("");
      setDescripcion("");
      setMostrarForm(false);
      navigate(`/casos/${nuevo.id}`);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo crear el caso.");
    } finally {
      setCreando(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Casos</p>
          <h1 className="page-title">Tus casos</h1>
        </div>
        <button className="btn btn-primary" onClick={() => setMostrarForm((v) => !v)}>
          {mostrarForm ? "Cancelar" : "Nuevo caso"}
        </button>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      {mostrarForm && (
        <form className="card create-form" onSubmit={onCrear}>
          <div className="field">
            <label htmlFor="titulo">Título</label>
            <input
              id="titulo"
              className="input"
              required
              autoFocus
              maxLength={200}
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
              placeholder="Ej. Requerimiento UGPP — aportes 2024"
            />
          </div>
          <div className="field">
            <label htmlFor="desc">Descripción <span className="faint">(opcional)</span></label>
            <textarea
              id="desc"
              className="textarea"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Contexto del caso…"
            />
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={creando || !titulo.trim()}>
              {creando ? <span className="spinner" /> : null}
              {creando ? "Creando…" : "Crear caso"}
            </button>
          </div>
        </form>
      )}

      {casos === null ? (
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : casos.length === 0 ? (
        <div className="card empty-state">
          <p className="empty-title">Todavía no hay casos.</p>
          <p className="muted">Creá el primero para empezar a generar documentos con JuliX.</p>
        </div>
      ) : (
        <ul className="caso-list">
          {casos.map((c) => (
            <li key={c.id}>
              <Link className="caso-row card" to={`/casos/${c.id}`}>
                <div className="caso-row-main">
                  <span className="caso-row-title">{c.titulo}</span>
                  {c.descripcion && <span className="caso-row-desc muted">{c.descripcion}</span>}
                </div>
                <div className="caso-row-meta">
                  <EstadoPill estado={c.estado} />
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
