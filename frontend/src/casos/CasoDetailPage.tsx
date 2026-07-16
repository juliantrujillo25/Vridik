import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, SesionExpiradaError } from "../api/client";
import type { AdminUser, Caso, CaseDocument, EstadoCaso, Materia } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ESTADOS, ESTADO_LABEL, EstadoPill, fechaHora, MATERIA_LABEL, MATERIAS, separarAvisoRevisar } from "../ui";
import { ActuacionesYTerminos } from "./ActuacionesYTerminos";
import { CobroPanel } from "./Cobro";
import { Mensajes } from "./Mensajes";

export function CasoDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [caso, setCaso] = useState<Caso | null>(null);
  const [docs, setDocs] = useState<CaseDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // asignación de abogado (solo admin -- lo exige el backend)
  const [abogados, setAbogados] = useState<AdminUser[] | null>(null);
  const [asignando, setAsignando] = useState(false);

  // generación
  const [pregunta, setPregunta] = useState("");
  const [generarPdf, setGenerarPdf] = useState(false);
  const [generando, setGenerando] = useState(false);

  // visor de documento
  const [docAbierto, setDocAbierto] = useState<CaseDocument | null>(null);
  const [cargandoDoc, setCargandoDoc] = useState(false);
  const [descargandoPdf, setDescargandoPdf] = useState(false);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) {
      navigate("/login", { replace: true });
      return;
    }
    setError(err instanceof Error ? err.message : fallback);
  }

  async function cargar() {
    setError(null);
    try {
      const [c, d] = await Promise.all([api.getCaso(id), api.listDocumentos(id)]);
      setCaso(c);
      setDocs(d);
    } catch (err) {
      manejarError(err, "No se pudo cargar el caso.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (perfil?.role !== "admin") return;
    api.adminListUsers(0, 100).then(
      (usuarios) => setAbogados(usuarios.filter((u) => u.role === "abogado")),
      () => setAbogados([]),
    );
  }, [perfil?.role]);

  async function onCambiarEstado(estado: EstadoCaso) {
    if (!caso || estado === caso.estado) return;
    try {
      setCaso(await api.cambiarEstado(caso.id, estado));
    } catch (err) {
      manejarError(err, "No se pudo cambiar el estado.");
    }
  }

  async function onCambiarMateria(materia: Materia) {
    if (!caso || materia === caso.materia) return;
    try {
      setCaso(await api.cambiarMateria(caso.id, materia));
    } catch (err) {
      manejarError(err, "No se pudo cambiar la materia.");
    }
  }

  async function onAsignarAbogado(abogadoId: string) {
    if (!caso || abogadoId === caso.abogado_id) return;
    setAsignando(true);
    try {
      setCaso(await api.asignarAbogado(caso.id, abogadoId));
    } catch (err) {
      manejarError(err, "No se pudo asignar el abogado.");
    } finally {
      setAsignando(false);
    }
  }

  async function onGenerar(e: FormEvent) {
    e.preventDefault();
    if (!pregunta.trim()) return;
    const ok = window.confirm(
      "Generar el documento usa JuliX (Claude) con una llamada real que tiene costo y puede tardar. ¿Continuar?",
    );
    if (!ok) return;

    setGenerando(true);
    setError(null);
    try {
      const doc = await api.crearDocumento(id, {
        pregunta: pregunta.trim(),
        generar_pdf: generarPdf,
      });
      setPregunta("");
      setGenerarPdf(false);
      setDocs((prev) => (prev ? [doc, ...prev] : [doc]));
      setDocAbierto(doc);
    } catch (err) {
      manejarError(err, "No se pudo generar el documento.");
    } finally {
      setGenerando(false);
    }
  }

  function onGenerarBorrador(preguntaSugerida: string) {
    setPregunta(preguntaSugerida);
    const campo = document.getElementById("pregunta");
    campo?.scrollIntoView({ behavior: "smooth", block: "center" });
    (campo as HTMLTextAreaElement | null)?.focus();
  }

  async function abrirDoc(docId: string) {
    setCargandoDoc(true);
    try {
      setDocAbierto(await api.getDocumento(id, docId));
    } catch (err) {
      manejarError(err, "No se pudo abrir el documento.");
    } finally {
      setCargandoDoc(false);
    }
  }

  /** El PDF nunca es un link público directo (ver
   *  api/case_documents_endpoint.py::descargar_pdf_de_documento) -- hay que
   *  pedirlo autenticado y abrirlo como blob. Se abre una pestaña en blanco
   *  DE FORMA SÍNCRONA en el click (antes del await) porque los bloqueadores
   *  de pop-ups dejan pasar `window.open` solo si ocurre directo en el gesto
   *  del usuario; recién cuando el blob está listo se le asigna la URL. */
  async function onAbrirPdf(docId: string) {
    const pestaña = window.open("", "_blank");
    setDescargandoPdf(true);
    try {
      const blob = await api.descargarPdf(id, docId);
      const url = URL.createObjectURL(blob);
      if (pestaña) pestaña.location.href = url;
    } catch (err) {
      pestaña?.close();
      manejarError(err, "No se pudo abrir el PDF.");
    } finally {
      setDescargandoPdf(false);
    }
  }

  if (error && !caso) {
    return (
      <div className="page">
        <Link className="back-link" to="/casos">← Casos</Link>
        <div className="alert error" role="alert">{error}</div>
      </div>
    );
  }

  if (!caso) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  return (
    <div className="page">
      <Link className="back-link" to="/casos">← Casos</Link>

      <div className="page-head">
        <div>
          <p className="eyebrow">Caso</p>
          <h1 className="page-title">{caso.titulo}</h1>
        </div>
        <EstadoPill estado={caso.estado} />
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      {caso.descripcion && <p className="caso-desc muted">{caso.descripcion}</p>}

      <div className="caso-meta-row">
        <div className="field estado-field">
          <label htmlFor="estado">Estado</label>
          <select
            id="estado"
            className="select"
            value={caso.estado}
            onChange={(e) => onCambiarEstado(e.target.value as EstadoCaso)}
          >
            {ESTADOS.map((e) => (
              <option key={e} value={e}>{ESTADO_LABEL[e]}</option>
            ))}
          </select>
        </div>
        <div className="field estado-field">
          <label htmlFor="materia">Materia</label>
          <select
            id="materia"
            className="select"
            value={caso.materia ?? ""}
            onChange={(e) => { if (e.target.value) void onCambiarMateria(e.target.value as Materia); }}
          >
            <option value="" disabled>— Sin clasificar —</option>
            {MATERIAS.map((m) => (
              <option key={m} value={m}>{MATERIA_LABEL[m]}</option>
            ))}
          </select>
        </div>
        {perfil?.role === "admin" && (
          <div className="field estado-field">
            <label htmlFor="abogado">Abogado asignado</label>
            <select
              id="abogado"
              className="select"
              value={caso.abogado_id ?? ""}
              disabled={asignando || abogados === null}
              onChange={(e) => { if (e.target.value) void onAsignarAbogado(e.target.value); }}
            >
              <option value="" disabled>
                {abogados === null ? "Cargando…" : "— Elegir abogado —"}
              </option>
              {abogados?.map((a) => (
                <option key={a.id} value={a.id}>{a.email}</option>
              ))}
            </select>
          </div>
        )}
        <span className="faint mono caso-created">Creado {fechaHora(caso.created_at)}</span>
      </div>

      <section className="section">
        <h2 className="section-title">Mensajes</h2>
        {perfil && <Mensajes casoId={id} miId={perfil.id} />}
      </section>

      <ActuacionesYTerminos casoId={id} onGenerarBorrador={onGenerarBorrador} />

      <CobroPanel
        casoId={id}
        casoEstado={caso.estado}
        puedeEditar={perfil?.role === "admin" || (perfil?.role === "abogado" && perfil.id === caso.abogado_id)}
      />

      <section className="section">
        <h2 className="section-title">Generar documento con JuliX</h2>
        <form className="card generar-form" onSubmit={onGenerar}>
          <div className="field">
            <label htmlFor="pregunta">Consulta / expediente</label>
            <textarea
              id="pregunta"
              className="textarea"
              required
              rows={4}
              value={pregunta}
              onChange={(e) => setPregunta(e.target.value)}
              placeholder="Ej. Redactá la respuesta al requerimiento de la UGPP sobre aportes de 2024…"
            />
          </div>
          <div className="generar-actions">
            <label className="check">
              <input type="checkbox" checked={generarPdf} onChange={(e) => setGenerarPdf(e.target.checked)} />
              Generar también el PDF
            </label>
            <button className="btn btn-primary" type="submit" disabled={generando || !pregunta.trim()}>
              {generando ? <span className="spinner" /> : null}
              {generando ? "JuliX está redactando…" : "Generar documento"}
            </button>
          </div>
          <p className="faint generar-nota">Usa una llamada real a Claude (tiene costo y puede tardar).</p>
        </form>
      </section>

      <section className="section">
        <h2 className="section-title">
          Documentos
          {docs && <span className="faint mono count"> {docs.length}</span>}
        </h2>
        {docs === null ? (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        ) : docs.length === 0 ? (
          <p className="muted">Todavía no hay documentos en este caso.</p>
        ) : (
          <ul className="doc-list">
            {docs.map((d) => (
              <li key={d.id}>
                <button className="doc-row card" onClick={() => abrirDoc(d.id)}>
                  <div className="doc-row-main">
                    <span className="doc-row-tarea mono">{d.tarea}</span>
                    <span className="doc-row-pregunta muted">{d.pregunta}</span>
                  </div>
                  <div className="doc-row-meta">
                    {d.pdf_url && <span className="pill abierto">PDF</span>}
                    <span className="faint mono">{fechaHora(d.created_at)}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {docAbierto && (
        <div className="doc-modal-backdrop" onClick={() => setDocAbierto(null)}>
          <div className="doc-modal card" onClick={(e) => e.stopPropagation()}>
            <div className="doc-modal-head">
              <div>
                <span className="mono faint">{docAbierto.tarea}</span>
                <h3 className="doc-modal-title">{docAbierto.pregunta}</h3>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setDocAbierto(null)}>Cerrar</button>
            </div>
            {cargandoDoc ? (
              <div className="empty muted"><span className="spinner" /> Cargando…</div>
            ) : (
              (() => {
                const { cuerpo, aviso } = separarAvisoRevisar(docAbierto.contenido ?? "(sin contenido)");
                return (
                  <>
                    {aviso && <div className="alert warn doc-aviso-revisar" role="alert">{aviso}</div>}
                    <div className="doc-content">{cuerpo}</div>
                  </>
                );
              })()
            )}
            {docAbierto.pdf_url && (
              <button
                className="btn btn-ghost btn-sm doc-pdf-link"
                type="button"
                disabled={descargandoPdf}
                onClick={() => onAbrirPdf(docAbierto.id)}
              >
                {descargandoPdf ? <span className="spinner" /> : null}
                {descargandoPdf ? "Abriendo…" : "Abrir PDF"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
