import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, SesionExpiradaError } from "../api/client";
import type { Actuacion, ActuacionNuevaEvent, EventoSSE, Termino, TerminoAlertaEvent } from "../api/types";
import { CATEGORIA_LABEL, fechaCorta, fechaHora, semaforoTermino } from "../ui";

function esActuacionNueva(ev: EventoSSE, casoId: string): ev is ActuacionNuevaEvent {
  return ev.type === "actuacion.nueva" && (ev as ActuacionNuevaEvent).caso_id === casoId;
}

function esTerminoAlerta(ev: EventoSSE, casoId: string): ev is TerminoAlertaEvent {
  return ev.type === "termino.alerta" && (ev as TerminoAlertaEvent).caso_id === casoId;
}

function etiquetaDiasRestantes(t: Termino): string {
  if (t.estado === "cumplido") return "Cumplido";
  if (t.dias_restantes < 0) return `Vencido hace ${-t.dias_restantes}d`;
  if (t.dias_restantes === 0) return "Vence hoy";
  return `${t.dias_restantes}d restantes`;
}

function sugerenciaBorrador(a: Actuacion): string {
  return `Redactá una respuesta a la siguiente actuación (${CATEGORIA_LABEL[a.categoria]}):\n\n${a.texto}`;
}

interface Props {
  casoId: string;
  /** Roadmap Fase 2: "Borrador automático vía JuliX con el expediente del
   *  caso" -- no dispara la generación acá (eso sigue siendo una llamada
   *  paga que el usuario confirma en el formulario existente), solo le
   *  pasa al padre una pregunta sugerida a partir de la actuación para
   *  precargar ese formulario. */
  onGenerarBorrador?: (preguntaSugerida: string) => void;
}

export function ActuacionesYTerminos({ casoId, onGenerarBorrador }: Props) {
  const [actuaciones, setActuaciones] = useState<Actuacion[] | null>(null);
  const [terminos, setTerminos] = useState<Termino[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [textoActuacion, setTextoActuacion] = useState("");
  const [clasificando, setClasificando] = useState(false);

  const [descripcion, setDescripcion] = useState("");
  const [fechaInicio, setFechaInicio] = useState("");
  const [diasHabiles, setDiasHabiles] = useState("");
  const [actuacionVinculada, setActuacionVinculada] = useState("");
  const [creandoTermino, setCreandoTermino] = useState(false);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) return;
    setError(err instanceof Error ? err.message : fallback);
  }

  const cargarActuaciones = useCallback(async () => {
    try {
      setActuaciones(await api.listActuaciones(casoId));
    } catch (err) {
      manejarError(err, "No se pudieron cargar las actuaciones.");
    }
  }, [casoId]);

  const cargarTerminos = useCallback(async () => {
    try {
      setTerminos(await api.listTerminos(casoId));
    } catch (err) {
      manejarError(err, "No se pudieron cargar los términos.");
    }
  }, [casoId]);

  useEffect(() => {
    void cargarActuaciones();
    void cargarTerminos();
  }, [cargarActuaciones, cargarTerminos]);

  useEffect(() => {
    const detener = api.streamEvents((ev) => {
      if (esActuacionNueva(ev, casoId)) void cargarActuaciones();
      if (esTerminoAlerta(ev, casoId)) void cargarTerminos();
    });
    return detener;
  }, [casoId, cargarActuaciones, cargarTerminos]);

  async function onCrearActuacion(e: FormEvent) {
    e.preventDefault();
    const texto = textoActuacion.trim();
    if (!texto) return;
    const ok = window.confirm(
      "Clasificar la actuación usa JuliX (Claude) con una llamada real que tiene costo. ¿Continuar?",
    );
    if (!ok) return;

    setClasificando(true);
    setError(null);
    try {
      const nueva = await api.crearActuacion(casoId, texto);
      setTextoActuacion("");
      setActuaciones((prev) => (prev ? [nueva, ...prev] : [nueva]));
    } catch (err) {
      manejarError(err, "No se pudo clasificar la actuación.");
    } finally {
      setClasificando(false);
    }
  }

  async function onCrearTermino(e: FormEvent) {
    e.preventDefault();
    const dias = Number(diasHabiles);
    if (!descripcion.trim() || !fechaInicio || !dias || dias <= 0) return;

    setCreandoTermino(true);
    setError(null);
    try {
      const nuevo = await api.crearTermino(casoId, {
        descripcion: descripcion.trim(),
        fecha_inicio: fechaInicio,
        dias_habiles: dias,
        actuacion_id: actuacionVinculada || null,
      });
      setDescripcion("");
      setFechaInicio("");
      setDiasHabiles("");
      setActuacionVinculada("");
      setTerminos((prev) => {
        const lista = prev ? [...prev, nuevo] : [nuevo];
        return lista.sort((a, b) => a.fecha_vencimiento.localeCompare(b.fecha_vencimiento));
      });
    } catch (err) {
      manejarError(err, "No se pudo crear el término.");
    } finally {
      setCreandoTermino(false);
    }
  }

  async function onMarcarCumplido(termino: Termino) {
    try {
      const actualizado = await api.cambiarEstadoTermino(casoId, termino.id, "cumplido");
      setTerminos((prev) => prev?.map((t) => (t.id === termino.id ? actualizado : t)) ?? prev);
    } catch (err) {
      manejarError(err, "No se pudo actualizar el término.");
    }
  }

  return (
    <>
      {error && <div className="alert error" role="alert">{error}</div>}

      <section className="section">
        <h2 className="section-title">
          Términos
          {terminos && <span className="faint mono count"> {terminos.length}</span>}
        </h2>

        <form className="card termino-form" onSubmit={onCrearTermino}>
          <div className="termino-form-grid">
            <div className="field">
              <label htmlFor="termino-desc">Descripción</label>
              <input
                id="termino-desc"
                className="input"
                required
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
                placeholder="Ej. Contestar requerimiento UGPP"
              />
            </div>
            <div className="field">
              <label htmlFor="termino-fecha">Fecha de inicio</label>
              <input
                id="termino-fecha"
                type="date"
                className="input"
                required
                value={fechaInicio}
                onChange={(e) => setFechaInicio(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="termino-dias">Días hábiles</label>
              <input
                id="termino-dias"
                type="number"
                min={1}
                className="input"
                required
                value={diasHabiles}
                onChange={(e) => setDiasHabiles(e.target.value)}
              />
            </div>
            {actuaciones && actuaciones.length > 0 && (
              <div className="field">
                <label htmlFor="termino-actuacion">Actuación vinculada (opcional)</label>
                <select
                  id="termino-actuacion"
                  className="select"
                  value={actuacionVinculada}
                  onChange={(e) => setActuacionVinculada(e.target.value)}
                >
                  <option value="">— Ninguna —</option>
                  {actuaciones.map((a) => (
                    <option key={a.id} value={a.id}>
                      {CATEGORIA_LABEL[a.categoria]} · {fechaCorta(a.created_at)}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <div className="generar-actions">
            <button
              className="btn btn-primary"
              type="submit"
              disabled={creandoTermino || !descripcion.trim() || !fechaInicio || !diasHabiles}
            >
              {creandoTermino ? <span className="spinner" /> : null}
              {creandoTermino ? "Calculando…" : "Calcular vencimiento y guardar"}
            </button>
          </div>
          <p className="faint generar-nota">
            El vencimiento se calcula solo (festivos y vacancia judicial 2026/2027) — nunca se ingresa a mano.
          </p>
        </form>

        {terminos === null ? (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        ) : terminos.length === 0 ? (
          <p className="muted">Todavía no hay términos en este caso.</p>
        ) : (
          <ul className="termino-list">
            {terminos.map((t) => {
              const color = semaforoTermino(t.dias_restantes, t.estado);
              return (
                <li key={t.id} className="card termino-row">
                  <div className="termino-row-main">
                    <span className={`semaforo-dot ${color}`} aria-hidden="true" />
                    <span className="termino-desc">{t.descripcion}</span>
                    {t.incluye_ventana_sin_confirmar && (
                      <span
                        className="pill amarillo"
                        title="Incluye una fecha de vacancia judicial todavía no anunciada oficialmente -- verificar antes de confiar en este vencimiento"
                      >
                        fecha por confirmar
                      </span>
                    )}
                  </div>
                  <div className="termino-row-meta">
                    <span className="mono">{fechaCorta(t.fecha_vencimiento)}</span>
                    <span className={`termino-dias ${color}`}>{etiquetaDiasRestantes(t)}</span>
                    {t.estado === "pendiente" && (
                      <button className="btn btn-ghost btn-sm" onClick={() => onMarcarCumplido(t)}>
                        Marcar cumplido
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="section">
        <h2 className="section-title">
          Actuaciones
          {actuaciones && <span className="faint mono count"> {actuaciones.length}</span>}
        </h2>

        <form className="card actuacion-form" onSubmit={onCrearActuacion}>
          <div className="field">
            <label htmlFor="texto-actuacion">Pegar el texto de la actuación</label>
            <textarea
              id="texto-actuacion"
              className="textarea"
              required
              rows={4}
              value={textoActuacion}
              onChange={(e) => setTextoActuacion(e.target.value)}
              placeholder="Ej. Por medio del presente auto se admite la demanda…"
            />
          </div>
          <div className="generar-actions">
            <button className="btn btn-primary" type="submit" disabled={clasificando || !textoActuacion.trim()}>
              {clasificando ? <span className="spinner" /> : null}
              {clasificando ? "Clasificando…" : "Clasificar y guardar"}
            </button>
          </div>
          <p className="faint generar-nota">Usa una llamada real a Claude (tiene costo).</p>
        </form>

        {actuaciones === null ? (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        ) : actuaciones.length === 0 ? (
          <p className="muted">Todavía no hay actuaciones registradas en este caso.</p>
        ) : (
          <ul className="doc-list">
            {actuaciones.map((a) => (
              <li key={a.id}>
                <div className="doc-row card actuacion-row">
                  <div className="doc-row-main">
                    <span className="pill abierto">{CATEGORIA_LABEL[a.categoria]}</span>
                    <span className="doc-row-pregunta muted">{a.texto}</span>
                  </div>
                  <div className="doc-row-meta">
                    <span className="faint mono">{Math.round(a.confianza * 100)}%</span>
                    <span className="faint mono">{fechaHora(a.created_at)}</span>
                    {onGenerarBorrador && (
                      <button
                        className="btn btn-ghost btn-sm"
                        type="button"
                        onClick={() => onGenerarBorrador(sugerenciaBorrador(a))}
                      >
                        Generar borrador
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
