import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { api, SesionExpiradaError } from "../api/client";
import type { AdjuntoSubido, EventoSSE, MessageNewEvent, Mensaje } from "../api/types";

function esMessageNew(ev: EventoSSE, casoId: string): ev is MessageNewEvent {
  return ev.type === "message.new" && (ev as MessageNewEvent).caso_id === casoId;
}

function horaCorta(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function Mensajes({ casoId, miId }: { casoId: string; miId: string }) {
  const [mensajes, setMensajes] = useState<Mensaje[] | null>(null);
  const [texto, setTexto] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [descargandoId, setDescargandoId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const inputArchivoRef = useRef<HTMLInputElement>(null);

  const cargar = useCallback(async () => {
    try {
      const lista = await api.listMensajes(casoId);
      setMensajes([...lista].reverse()); // la API manda más reciente primero; el chat se lee cronológico
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudieron cargar los mensajes.");
    }
  }, [casoId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  // Marca leído hasta el último mensaje visible -- solo con la pestaña
  // activa (mismo criterio que pide el roadmap S11 para el cursor).
  useEffect(() => {
    if (!mensajes || mensajes.length === 0) return;
    if (document.visibilityState !== "visible") return;
    const ultimo = mensajes[mensajes.length - 1];
    void api.marcarLeido(casoId, ultimo.id).catch(() => {});
  }, [mensajes, casoId]);

  useEffect(() => {
    const detener = api.streamEvents((ev) => {
      if (esMessageNew(ev, casoId)) void cargar();
    });
    return detener;
  }, [casoId, cargar]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [mensajes]);

  function onElegirArchivo(e: ChangeEvent<HTMLInputElement>) {
    setArchivo(e.target.files?.[0] ?? null);
  }

  async function onEnviar(e: FormEvent) {
    e.preventDefault();
    const t = texto.trim();
    if (!t) return;
    setEnviando(true);
    setError(null);
    try {
      let adjuntoSubido: AdjuntoSubido | undefined;
      if (archivo) {
        adjuntoSubido = await api.subirAdjunto(casoId, archivo);
      }
      const nuevo = await api.crearMensaje(casoId, t, adjuntoSubido);
      setTexto("");
      setArchivo(null);
      if (inputArchivoRef.current) inputArchivoRef.current.value = "";
      setMensajes((prev) => (prev ? [...prev, nuevo] : [nuevo]));
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo enviar el mensaje.");
    } finally {
      setEnviando(false);
    }
  }

  async function onBorrar(id: string) {
    const ok = window.confirm("¿Borrar este mensaje?");
    if (!ok) return;
    try {
      await api.borrarMensaje(casoId, id);
      setMensajes((prev) => (prev ? prev.filter((m) => m.id !== id) : prev));
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo borrar el mensaje.");
    }
  }

  /** El adjunto nunca es un link público directo (ver
   *  api/mensajes_endpoint.py::descargar_adjunto_endpoint) -- se pide
   *  autenticado y se abre como blob, mismo patrón que "Abrir PDF" en
   *  CasoDetailPage.tsx. La pestaña se abre síncrona en el click para que
   *  el bloqueador de pop-ups la deje pasar. */
  async function onAbrirAdjunto(mensajeId: string) {
    const pestaña = window.open("", "_blank");
    setDescargandoId(mensajeId);
    try {
      const blob = await api.descargarAdjunto(casoId, mensajeId);
      const url = URL.createObjectURL(blob);
      if (pestaña) pestaña.location.href = url;
    } catch (err) {
      pestaña?.close();
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo abrir el adjunto.");
    } finally {
      setDescargandoId(null);
    }
  }

  return (
    <div className="card mensajes-panel">
      {error && <div className="alert error" role="alert">{error}</div>}

      {mensajes === null ? (
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : mensajes.length === 0 ? (
        <p className="muted mensajes-vacio">Todavía no hay mensajes en este caso.</p>
      ) : (
        <ul className="mensajes-list" ref={listRef}>
          {mensajes.map((m) => {
            const esMio = m.autor_id === miId;
            return (
              <li key={m.id} className={`mensaje-row ${esMio ? "mio" : "otro"}`}>
                <div className="mensaje-bubble">
                  <span className="mensaje-texto">{m.texto}</span>
                  {m.adjunto_url && (
                    <button
                      className="mensaje-adjunto"
                      type="button"
                      disabled={descargandoId === m.id}
                      onClick={() => onAbrirAdjunto(m.id)}
                    >
                      📎 {descargandoId === m.id ? "Abriendo…" : (m.adjunto_nombre ?? "adjunto")}
                    </button>
                  )}
                  <span className="mensaje-meta">
                    <span className="mono faint">{horaCorta(m.created_at)}</span>
                    {esMio && (
                      <button
                        className="mensaje-borrar"
                        type="button"
                        title="Borrar mensaje"
                        onClick={() => onBorrar(m.id)}
                      >
                        ×
                      </button>
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <form className="mensajes-form" onSubmit={onEnviar}>
        <input
          className="input"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Escribí un mensaje…"
          maxLength={4000}
        />
        <input
          ref={inputArchivoRef}
          type="file"
          id="mensaje-adjunto-input"
          className="mensajes-file-input"
          onChange={onElegirArchivo}
          accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.txt"
        />
        <label htmlFor="mensaje-adjunto-input" className="btn btn-ghost btn-sm mensajes-adjuntar" title="Adjuntar archivo">
          📎
        </label>
        <button className="btn btn-primary" type="submit" disabled={enviando || !texto.trim()}>
          {enviando ? <span className="spinner" /> : null}
          {enviando ? "Enviando…" : "Enviar"}
        </button>
      </form>
      {archivo && (
        <p className="faint mensajes-archivo-elegido">
          {archivo.name}
          <button type="button" className="mensajes-quitar-archivo" onClick={() => { setArchivo(null); if (inputArchivoRef.current) inputArchivoRef.current.value = ""; }}>
            Quitar
          </button>
        </p>
      )}
    </div>
  );
}
