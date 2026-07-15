import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { Caso, MessageNewEvent, Termino, TerminoAlertaEvent } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EstadoPill, fechaCorta, type SemaforoColor } from "../ui";
import { AhorroWidget } from "./AhorroWidget";
import { NotificacionesWidget } from "./NotificacionesWidget";

/** Solo vale la pena mostrar un badge en el dashboard cuando hay algo que
 *  amerita atención (roadmap Fase 2: "semáforo de vencimientos calculados
 *  en el dashboard") -- si todos los términos pendientes están en verde,
 *  no hay nada que el badge deba interrumpir (mismo criterio que el badge
 *  de no-leídos: silencioso en 0). */
function peorSemaforoUrgente(terminos: Termino[]): { color: SemaforoColor; count: number } | null {
  const enRiesgo = terminos.filter((t) => t.estado === "pendiente" && t.dias_restantes <= 3);
  if (enRiesgo.length === 0) return null;
  const color: SemaforoColor = enRiesgo.some((t) => t.dias_restantes <= 0) ? "rojo" : "amarillo";
  return { color, count: enRiesgo.length };
}

export function CasosListPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();
  const [casos, setCasos] = useState<Caso[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noLeidos, setNoLeidos] = useState<Record<string, number>>({});
  const [terminosUrgentes, setTerminosUrgentes] = useState<Record<string, { color: SemaforoColor; count: number } | null>>({});

  const [titulo, setTitulo] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [creando, setCreando] = useState(false);
  const [mostrarForm, setMostrarForm] = useState(false);

  async function cargarNoLeidos(lista: Caso[]) {
    const resultados = await Promise.allSettled(lista.map((c) => api.noLeidos(c.id)));
    setNoLeidos((prev) => {
      const siguiente = { ...prev };
      resultados.forEach((r, i) => {
        if (r.status === "fulfilled") siguiente[lista[i].id] = r.value;
      });
      return siguiente;
    });
  }

  async function cargarTerminos(lista: Caso[]) {
    const resultados = await Promise.allSettled(lista.map((c) => api.listTerminos(c.id)));
    setTerminosUrgentes((prev) => {
      const siguiente = { ...prev };
      resultados.forEach((r, i) => {
        if (r.status === "fulfilled") siguiente[lista[i].id] = peorSemaforoUrgente(r.value);
      });
      return siguiente;
    });
  }

  async function cargar() {
    setError(null);
    try {
      const lista = await api.listCasos();
      setCasos(lista);
      void cargarNoLeidos(lista);
      void cargarTerminos(lista);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudieron cargar los casos.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Actualiza el badge en vivo cuando llega un mensaje nuevo de un caso ya
  // listado -- no incrementa a mano (evita desincronizarse con "marcar
  // leído" de otra pestaña), vuelve a pedir el conteo real de ese caso.
  useEffect(() => {
    const detener = api.streamEvents((ev) => {
      if (ev.type === "message.new") {
        const casoId = (ev as MessageNewEvent).caso_id;
        void api.noLeidos(casoId).then((n) => setNoLeidos((prev) => ({ ...prev, [casoId]: n })));
      }
      // Alerta proactiva de un término (roadmap Fase 2, ver
      // procesal/alertas_terminos.py) -- puede llegar sin que nadie haya
      // recargado el dashboard, así que el badge se actualiza en vivo
      // igual que el de no-leídos.
      if (ev.type === "termino.alerta") {
        const casoId = (ev as TerminoAlertaEvent).caso_id;
        void api.listTerminos(casoId).then((terminos) =>
          setTerminosUrgentes((prev) => ({ ...prev, [casoId]: peorSemaforoUrgente(terminos) })),
        );
      }
    });
    return detener;
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

      {perfil?.role === "cliente" && <AhorroWidget />}
      {perfil && <NotificacionesWidget />}

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
                  {terminosUrgentes[c.id] && (
                    <span
                      className={`badge-termino ${terminosUrgentes[c.id]!.color}`}
                      title={
                        terminosUrgentes[c.id]!.color === "rojo"
                          ? `${terminosUrgentes[c.id]!.count} término(s) vencido(s)`
                          : `${terminosUrgentes[c.id]!.count} término(s) por vencer`
                      }
                    >
                      {terminosUrgentes[c.id]!.count}
                    </span>
                  )}
                  {noLeidos[c.id] > 0 && (
                    <span className="badge-noleidos" title={`${noLeidos[c.id]} mensajes sin leer`}>
                      {noLeidos[c.id]}
                    </span>
                  )}
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
