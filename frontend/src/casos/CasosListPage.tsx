import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { Caso, MessageNewEvent, Termino, TerminoPorVencerEvent } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EstadoPill, fechaCorta, semaforoHealthScore, type SemaforoColor } from "../ui";
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

/** TF4, punto 1: el caso con health_score más alto (por encima del umbral
 *  ya usado en el badge, >30 -- "no limpiamente verde") se promueve a fila
 *  hero; si ninguno tiene un health_score que amerite atención, se usa el
 *  caso con el término más urgente (rojo antes que amarillo). Sin ninguna
 *  señal real, no se fuerza un hero -- la lista queda plana. */
function elegirHeroId(
  lista: Caso[],
  terminosUrgentes: Record<string, { color: SemaforoColor; count: number } | null>,
): string | null {
  const conScore = lista.filter((c) => c.health_score !== null && c.health_score > 30);
  if (conScore.length > 0) {
    return conScore.reduce((peor, c) => (c.health_score! > peor.health_score! ? c : peor)).id;
  }
  const rojo = lista.find((c) => terminosUrgentes[c.id]?.color === "rojo");
  if (rojo) return rojo.id;
  const amarillo = lista.find((c) => terminosUrgentes[c.id]?.color === "amarillo");
  if (amarillo) return amarillo.id;
  return null;
}

export function CasosListPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();
  const [casos, setCasos] = useState<Caso[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noLeidos, setNoLeidos] = useState<Record<string, number>>({});
  const [terminosUrgentes, setTerminosUrgentes] = useState<Record<string, { color: SemaforoColor; count: number } | null>>({});
  const [documentCounts, setDocumentCounts] = useState<Record<string, number>>({});

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

  /** KPI "documentos generados por JuliX" (TF4, punto 6) -- no hay endpoint
   *  agregado, así que se reusa GET /casos/{id}/documents por caso, mismo
   *  patrón N+1 que ya usan cargarNoLeidos/cargarTerminos arriba. */
  async function cargarDocumentos(lista: Caso[]) {
    const resultados = await Promise.allSettled(lista.map((c) => api.listDocumentos(c.id)));
    setDocumentCounts((prev) => {
      const siguiente = { ...prev };
      resultados.forEach((r, i) => {
        if (r.status === "fulfilled") siguiente[lista[i].id] = r.value.length;
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
      void cargarDocumentos(lista);
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
      if (ev.type === "termino.por_vencer") {
        const casoId = (ev as TerminoPorVencerEvent).caso_id;
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

  /** Único badge de riesgo por fila (TF4, punto 4): el término urgente manda
   *  sobre el health-score cuando ambos aplican -- es la señal más accionable
   *  (tiene una fecha límite real), el health-score es una medida más
   *  general. Nunca se muestran los dos badges juntos. */
  function riesgoBadge(c: Caso): ReactNode {
    const t = terminosUrgentes[c.id];
    if (t) {
      return (
        <span
          className={`badge-termino ${t.color}`}
          title={t.color === "rojo" ? `${t.count} término(s) vencido(s)` : `${t.count} término(s) por vencer`}
        >
          {t.count}
        </span>
      );
    }
    if (c.health_score !== null && c.health_score > 30) {
      return (
        <span className={`badge-termino ${semaforoHealthScore(c.health_score)}`} title={`Health-score de riesgo: ${c.health_score}/100`}>
          {c.health_score}
        </span>
      );
    }
    return null;
  }

  function noLeidosIndicador(c: Caso): ReactNode {
    const n = noLeidos[c.id];
    if (!n) return null;
    return (
      <span className="indicador-noleidos" title={`${n} mensaje(s) sin leer`}>
        <span className="indicador-noleidos-dot" aria-hidden="true" />
        {n}
      </span>
    );
  }

  const heroId = casos ? elegirHeroId(casos, terminosUrgentes) : null;
  const heroCaso = casos?.find((c) => c.id === heroId) ?? null;
  const restCasos = casos?.filter((c) => c.id !== heroId) ?? [];
  const heroEsRiesgo =
    !!heroCaso &&
    ((heroCaso.health_score !== null && heroCaso.health_score > 70) || terminosUrgentes[heroCaso.id]?.color === "rojo");

  const casosEnRiesgo = casos
    ? casos.filter((c) => (c.health_score !== null && c.health_score > 70) || !!terminosUrgentes[c.id]).length
    : 0;
  const totalDocumentos = Object.values(documentCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Casos</p>
          <h1 className="page-title page-title-serif">Tus casos</h1>
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
        <>
          <div className="kpi-row">
            <div className="kpi-card">
              <span className="kpi-label">Casos</span>
              <span className="kpi-value">{casos.length}</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">En riesgo</span>
              <span className={`kpi-value${casosEnRiesgo > 0 ? " riesgo" : ""}`}>{casosEnRiesgo}</span>
            </div>
            <div className="kpi-card">
              <span className="kpi-label">Documentos JuliX</span>
              <span className="kpi-value">{totalDocumentos}</span>
            </div>
          </div>

          {heroCaso && (
            <Link className={`card caso-row-hero${heroEsRiesgo ? " es-riesgo" : ""}`} to={`/casos/${heroCaso.id}`}>
              <div className="caso-row-hero-head">
                <h2 className="caso-row-hero-titulo">{heroCaso.titulo}</h2>
                <div className="caso-row-hero-meta">
                  {riesgoBadge(heroCaso)}
                  {noLeidosIndicador(heroCaso)}
                  <EstadoPill estado={heroCaso.estado} />
                </div>
              </div>
              {heroCaso.descripcion && <p className="caso-row-hero-desc muted">{heroCaso.descripcion}</p>}
              <span className="faint mono caso-row-date">{fechaCorta(heroCaso.created_at)}</span>
            </Link>
          )}

          {restCasos.length > 0 && (
            <ul className="card caso-dense-list">
              {restCasos.map((c) => (
                <li key={c.id}>
                  <Link className="caso-row-compact" to={`/casos/${c.id}`}>
                    <span className="caso-row-compact-title">{c.titulo}</span>
                    <div className="caso-row-compact-meta">
                      {riesgoBadge(c)}
                      {noLeidosIndicador(c)}
                      <EstadoPill estado={c.estado} />
                      <span className="faint mono caso-row-date">{fechaCorta(c.created_at)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
