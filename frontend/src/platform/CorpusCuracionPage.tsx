import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, SesionExpiradaError } from "../api/client";
import type {
  BorradorCorpus, BorradorCorpusResumen, PrioridadCorpus, TipoFuenteCorpus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { fechaHora } from "../ui";

const TIPO_FUENTE_LABEL: Record<TipoFuenteCorpus, string> = {
  ley: "Ley", decreto: "Decreto", jurisprudencia: "Jurisprudencia",
};
const PRIORIDAD_LABEL: Record<PrioridadCorpus, string> = { alta: "Alta", media: "Media", baja: "Baja" };

/** Roadmap S7: "mini-herramienta de 3 pasos en una vista: carga con texto
 *  extraído siempre visible -> chunks propuestos editables -> metadatos con
 *  selects preseleccionados por heurística." Exclusiva del admin de
 *  plataforma -- rag_chunks es corpus compartido de toda la plataforma, sin
 *  despacho_id (ver core/corpus_curation.py). Nada de lo que se ve acá se
 *  publica hasta apretar "Publicar en el corpus" en el paso 3. */
export function CorpusCuracionPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [borradores, setBorradores] = useState<BorradorCorpusResumen[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [activo, setActivo] = useState<BorradorCorpus | null>(null);
  const [cargandoActivo, setCargandoActivo] = useState(false);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
    setError(err instanceof Error ? err.message : fallback);
  }

  const cargarLista = useCallback(async () => {
    setError(null);
    try {
      setBorradores(await api.listarBorradoresCorpus());
    } catch (err) {
      manejarError(err, "No se pudo cargar la lista de borradores.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (perfil?.es_superadmin) void cargarLista();
  }, [perfil?.es_superadmin, cargarLista]);

  async function abrirBorrador(id: string) {
    setCargandoActivo(true);
    setError(null);
    try {
      setActivo(await api.obtenerBorradorCorpus(id));
    } catch (err) {
      manejarError(err, "No se pudo abrir el borrador.");
    } finally {
      setCargandoActivo(false);
    }
  }

  function cerrarEditor() {
    setActivo(null);
    void cargarLista();
  }

  async function onDescartar(id: string, ev: React.MouseEvent) {
    ev.stopPropagation();
    if (!window.confirm("¿Descartar este borrador? No se puede deshacer.")) return;
    try {
      await api.descartarBorradorCorpus(id);
      void cargarLista();
    } catch (err) {
      manejarError(err, "No se pudo descartar el borrador.");
    }
  }

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (!perfil.es_superadmin) {
    return (
      <div className="page">
        <p className="eyebrow">Plataforma</p>
        <h1 className="page-title">Curaduría del corpus</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  if (cargandoActivo) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (activo) {
    return <EditorBorrador borrador={activo} onCerrar={cerrarEditor} onError={(e) => manejarError(e, "Error inesperado.")} />;
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Plataforma</p>
          <h1 className="page-title">Curaduría del corpus</h1>
        </div>
      </div>
      <p className="muted" style={{ marginBottom: "1.25rem" }}>
        Cargar un documento al corpus legal en 3 pasos: pegar el texto (o subir un PDF), revisar/editar los
        fragmentos propuestos, completar la metadata y publicar. Nada se publica hasta el paso final.
      </p>

      <NuevoBorradorForm onCreado={(b) => setActivo(b)} onError={(e) => manejarError(e, "No se pudo crear el borrador.")} />

      {error && <div className="alert error" role="alert">{error}</div>}

      <h2 className="section-title" style={{ marginTop: "2rem" }}>Borradores</h2>
      {borradores === null ? (
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : borradores.length === 0 ? (
        <div className="empty muted">Todavía no hay borradores.</div>
      ) : (
        <ul className="admin-user-list">
          {borradores.map((b) => (
            <li key={b.id} className="card admin-user-row" onClick={() => void abrirBorrador(b.id)} style={{ cursor: "pointer" }}>
              <div className="admin-user-main">
                <span className="admin-user-email">{b.nombre_fuente}</span>
                <span className="faint mono">{b.cantidad_chunks} fragmento{b.cantidad_chunks === 1 ? "" : "s"}</span>
                {b.norma && <span className="faint mono">{b.norma}</span>}
                <span className="faint mono">{fechaHora(b.actualizado_en)}</span>
                <span className={`pill ${b.estado === "publicado" ? "verde" : "amarillo"}`}>
                  {b.estado === "publicado" ? "Publicado" : "Borrador"}
                </span>
              </div>
              {b.estado === "borrador" && (
                <div className="admin-user-actions">
                  <button className="btn btn-ghost btn-sm" onClick={(ev) => void onDescartar(b.id, ev)}>Descartar</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- Paso 1: crear el borrador (pegar texto o subir PDF) -------------------

function NuevoBorradorForm({ onCreado, onError }: { onCreado: (b: BorradorCorpus) => void; onError: (e: unknown) => void }) {
  const [abierto, setAbierto] = useState(false);
  const [nombreFuente, setNombreFuente] = useState("");
  const [texto, setTexto] = useState("");
  const [extrayendo, setExtrayendo] = useState(false);
  const [creando, setCreando] = useState(false);

  async function onArchivo(ev: React.ChangeEvent<HTMLInputElement>) {
    const archivo = ev.target.files?.[0];
    if (!archivo) return;
    if (!nombreFuente) setNombreFuente(archivo.name);
    setExtrayendo(true);
    try {
      const { texto: extraido } = await api.extraerTextoPdf(archivo);
      setTexto(extraido);
    } catch (err) {
      onError(err);
    } finally {
      setExtrayendo(false);
      ev.target.value = "";
    }
  }

  async function onCrear() {
    if (!nombreFuente.trim() || !texto.trim()) return;
    setCreando(true);
    try {
      const borrador = await api.crearBorradorCorpus(nombreFuente.trim(), texto);
      setAbierto(false);
      setNombreFuente("");
      setTexto("");
      onCreado(borrador);
    } catch (err) {
      onError(err);
    } finally {
      setCreando(false);
    }
  }

  if (!abierto) {
    return <button className="btn btn-primary" onClick={() => setAbierto(true)}>Nuevo borrador</button>;
  }

  return (
    <div className="card" style={{ padding: "1.25rem", marginBottom: "1rem" }}>
      <h2 className="section-title">Paso 1 — Fuente</h2>
      <div className="field">
        <label htmlFor="nombre-fuente">Nombre de la fuente</label>
        <input
          id="nombre-fuente" className="input" value={nombreFuente}
          onChange={(e) => setNombreFuente(e.target.value)}
          placeholder="p. ej. Ley 1607 de 2012, o SL17063-2017 Corte Suprema de Justicia"
        />
      </div>
      <div className="field">
        <label htmlFor="pdf-fuente">Subir PDF (opcional -- extrae el texto automáticamente)</label>
        <input id="pdf-fuente" type="file" accept=".pdf" onChange={(e) => void onArchivo(e)} disabled={extrayendo} />
      </div>
      <div className="field">
        <label htmlFor="texto-fuente">Texto extraído (siempre editable)</label>
        <textarea
          id="texto-fuente" className="textarea" rows={10} value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Pegá el texto acá, o subí un PDF arriba para extraerlo automáticamente."
          disabled={extrayendo}
        />
      </div>
      <div className="form-actions">
        <button className="btn btn-ghost btn-sm" onClick={() => setAbierto(false)} disabled={creando}>Cancelar</button>
        <button className="btn btn-primary btn-sm" onClick={() => void onCrear()} disabled={creando || extrayendo || !nombreFuente.trim() || !texto.trim()}>
          {creando ? "Generando…" : extrayendo ? "Extrayendo…" : "Generar fragmentos propuestos →"}
        </button>
      </div>
    </div>
  );
}

// --- Pasos 2 y 3: editar chunks + metadata, publicar ------------------------

function EditorBorrador({
  borrador, onCerrar, onError,
}: { borrador: BorradorCorpus; onCerrar: () => void; onError: (e: unknown) => void }) {
  const soloLectura = borrador.estado === "publicado";

  const [chunks, setChunks] = useState<string[]>(borrador.chunks);
  const [norma, setNorma] = useState(borrador.norma ?? "");
  const [articulo, setArticulo] = useState(borrador.articulo ?? "");
  const [tipoFuente, setTipoFuente] = useState<TipoFuenteCorpus | "">(borrador.tipo_fuente ?? "");
  const [prioridad, setPrioridad] = useState<PrioridadCorpus | "">(borrador.prioridad ?? "");
  const [anio, setAnio] = useState(borrador.anio?.toString() ?? "");
  const [tribunal, setTribunal] = useState(borrador.tribunal ?? "");

  const [guardando, setGuardando] = useState(false);
  const [publicando, setPublicando] = useState(false);
  const [resultado, setResultado] = useState<BorradorCorpus | null>(soloLectura ? borrador : null);

  function unirConSiguiente(idx: number) {
    setChunks((prev) => {
      if (idx >= prev.length - 1) return prev;
      const copia = [...prev];
      copia[idx] = `${copia[idx]}\n\n${copia[idx + 1]}`;
      copia.splice(idx + 1, 1);
      return copia;
    });
  }

  function dividirALaMitad(idx: number) {
    setChunks((prev) => {
      const texto = prev[idx];
      const mitad = Math.floor(texto.length / 2);
      const corte = texto.indexOf(" ", mitad) === -1 ? mitad : texto.indexOf(" ", mitad);
      const copia = [...prev];
      copia.splice(idx, 1, texto.slice(0, corte).trim(), texto.slice(corte).trim());
      return copia;
    });
  }

  function eliminarChunk(idx: number) {
    setChunks((prev) => prev.filter((_, i) => i !== idx));
  }

  function editarChunk(idx: number, valor: string) {
    setChunks((prev) => prev.map((c, i) => (i === idx ? valor : c)));
  }

  async function onGuardar() {
    setGuardando(true);
    try {
      await api.actualizarBorradorCorpus(borrador.id, {
        chunks,
        norma: norma.trim() || undefined,
        articulo: articulo.trim() || undefined,
        tipo_fuente: tipoFuente || undefined,
        prioridad: prioridad || undefined,
        anio: anio ? Number(anio) : undefined,
        tribunal: tribunal.trim() || undefined,
      });
    } catch (err) {
      onError(err);
    } finally {
      setGuardando(false);
    }
  }

  const metadataCompleta = norma.trim() && articulo.trim() && tipoFuente && prioridad && chunks.length > 0;

  async function onPublicar() {
    if (!metadataCompleta) return;
    if (!window.confirm(`¿Publicar ${chunks.length} fragmento(s) en el corpus? No se puede deshacer.`)) return;
    setPublicando(true);
    try {
      await onGuardar();
      setResultado(await api.publicarBorradorCorpus(borrador.id));
    } catch (err) {
      onError(err);
    } finally {
      setPublicando(false);
    }
  }

  if (resultado) {
    return (
      <div className="page">
        <p className="eyebrow">Plataforma</p>
        <h1 className="page-title">Publicado</h1>
        <div className="alert" role="status">
          {resultado.chunks_publicados} fragmento(s) nuevo(s) insertado(s) en el corpus,{" "}
          {resultado.chunks_duplicados} ya existían (mismo contenido, se omitieron).
        </div>
        <button className="btn btn-primary" onClick={onCerrar}>Volver a la lista</button>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Plataforma</p>
          <h1 className="page-title">{borrador.nombre_fuente}</h1>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onCerrar}>← Volver a la lista</button>
      </div>

      {soloLectura && <div className="alert" role="status">Este borrador ya fue publicado -- queda como historial, no se puede editar.</div>}

      <section style={{ marginBottom: "1.5rem" }}>
        <h2 className="section-title">Texto extraído</h2>
        <div className="card" style={{ padding: "1rem", maxHeight: "220px", overflowY: "auto", whiteSpace: "pre-wrap" }}>
          {borrador.texto_extraido}
        </div>
      </section>

      <section style={{ marginBottom: "1.5rem" }}>
        <h2 className="section-title">Paso 2 — Fragmentos ({chunks.length})</h2>
        {chunks.map((c, idx) => (
          <div key={idx} className="card" style={{ padding: "0.85rem", marginBottom: "0.6rem" }}>
            <textarea
              className="textarea" rows={4} value={c} disabled={soloLectura}
              onChange={(e) => editarChunk(idx, e.target.value)}
            />
            {!soloLectura && (
              <div className="form-actions" style={{ marginTop: "0.4rem" }}>
                <button className="btn btn-ghost btn-sm" onClick={() => dividirALaMitad(idx)}>Dividir</button>
                <button className="btn btn-ghost btn-sm" onClick={() => unirConSiguiente(idx)} disabled={idx >= chunks.length - 1}>
                  Unir con el siguiente
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => eliminarChunk(idx)}>Eliminar</button>
              </div>
            )}
          </div>
        ))}
        {chunks.length === 0 && <div className="empty muted">Sin fragmentos -- no se puede publicar así.</div>}
      </section>

      <section style={{ marginBottom: "1.5rem" }}>
        <h2 className="section-title">Paso 3 — Metadata</h2>
        <div className="field">
          <label htmlFor="norma">Norma / sentencia</label>
          <input id="norma" className="input" value={norma} onChange={(e) => setNorma(e.target.value)} disabled={soloLectura} placeholder="p. ej. Ley 1607 de 2012" />
        </div>
        <div className="field">
          <label htmlFor="articulo">Artículo(s) clave</label>
          <input id="articulo" className="input" value={articulo} onChange={(e) => setArticulo(e.target.value)} disabled={soloLectura} placeholder="p. ej. Art. 178-180" />
        </div>
        <div className="field">
          <label htmlFor="tipo-fuente">Tipo de fuente</label>
          <select id="tipo-fuente" className="select" value={tipoFuente} onChange={(e) => setTipoFuente(e.target.value as TipoFuenteCorpus)} disabled={soloLectura}>
            <option value="">Elegir…</option>
            {(Object.keys(TIPO_FUENTE_LABEL) as TipoFuenteCorpus[]).map((t) => (
              <option key={t} value={t}>{TIPO_FUENTE_LABEL[t]}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="prioridad">Prioridad</label>
          <select id="prioridad" className="select" value={prioridad} onChange={(e) => setPrioridad(e.target.value as PrioridadCorpus)} disabled={soloLectura}>
            <option value="">Elegir…</option>
            {(Object.keys(PRIORIDAD_LABEL) as PrioridadCorpus[]).map((p) => (
              <option key={p} value={p}>{PRIORIDAD_LABEL[p]}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="anio">Año (preseleccionado por heurística, revisar)</label>
          <input id="anio" className="input" type="number" value={anio} onChange={(e) => setAnio(e.target.value)} disabled={soloLectura} />
        </div>
        <div className="field">
          <label htmlFor="tribunal">Tribunal (si aplica, preseleccionado por heurística)</label>
          <input id="tribunal" className="input" value={tribunal} onChange={(e) => setTribunal(e.target.value)} disabled={soloLectura} />
        </div>
      </section>

      {!soloLectura && (
        <div className="form-actions">
          <button className="btn btn-ghost btn-sm" onClick={() => void onGuardar()} disabled={guardando || publicando}>
            {guardando ? "Guardando…" : "Guardar borrador"}
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => void onPublicar()} disabled={!metadataCompleta || guardando || publicando}>
            {publicando ? "Publicando…" : "Publicar en el corpus"}
          </button>
        </div>
      )}
    </div>
  );
}
