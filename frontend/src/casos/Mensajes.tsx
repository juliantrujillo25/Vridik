import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, SesionExpiradaError } from "../api/client";
import type { EventoSSE, MessageNewEvent, Mensaje } from "../api/types";

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
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);

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

  async function onEnviar(e: FormEvent) {
    e.preventDefault();
    const t = texto.trim();
    if (!t) return;
    setEnviando(true);
    setError(null);
    try {
      const nuevo = await api.crearMensaje(casoId, t);
      setTexto("");
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

  return (
    <div className="card mensajes-panel">
      {error && <div className="alert error" role="alert">{error}</div>}

      <ul className="mensajes-list" ref={listRef}>
        {mensajes === null ? (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        ) : mensajes.length === 0 ? (
          <p className="muted mensajes-vacio">Todavía no hay mensajes en este caso.</p>
        ) : (
          mensajes.map((m) => {
            const esMio = m.autor_id === miId;
            return (
              <li key={m.id} className={`mensaje-row ${esMio ? "mio" : "otro"}`}>
                <div className="mensaje-bubble">
                  <span className="mensaje-texto">{m.texto}</span>
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
          })
        )}
      </ul>

      <form className="mensajes-form" onSubmit={onEnviar}>
        <input
          className="input"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Escribí un mensaje…"
          maxLength={4000}
        />
        <button className="btn btn-primary" type="submit" disabled={enviando || !texto.trim()}>
          Enviar
        </button>
      </form>
    </div>
  );
}
