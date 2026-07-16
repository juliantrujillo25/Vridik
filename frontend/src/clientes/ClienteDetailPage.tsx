import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { Canal, ClienteDetalle, MatrizRiesgo, NivelRiesgo, TipoPersona } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EstadoPill, fechaCorta } from "../ui";

const NIVEL_LABEL: Record<NivelRiesgo, string> = { bajo: "Bajo", medio: "Medio", alto: "Alto" };
const NIVEL_PILL_COLOR: Record<NivelRiesgo, string> = { bajo: "verde", medio: "amarillo", alto: "rojo" };
const TIPO_PERSONA_LABEL: Record<TipoPersona, string> = { natural: "Persona natural", juridica: "Persona jurídica" };
const CANAL_LABEL: Record<Canal, string> = { presencial: "Presencial", no_presencial: "No presencial" };

function NivelRiesgoPill({ nivel }: { nivel: NivelRiesgo }) {
  return <span className={`pill ${NIVEL_PILL_COLOR[nivel]}`}>{NIVEL_LABEL[nivel]}</span>;
}

export function ClienteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [cliente, setCliente] = useState<ClienteDetalle | null>(null);
  const [matriz, setMatriz] = useState<MatrizRiesgo | null | undefined>(undefined); // undefined = todavía no cargó
  const [error, setError] = useState<string | null>(null);

  const [editando, setEditando] = useState(false);
  const [tipoPersona, setTipoPersona] = useState<TipoPersona>("natural");
  const [actividadRiesgo, setActividadRiesgo] = useState<NivelRiesgo>("bajo");
  const [jurisdiccionRiesgo, setJurisdiccionRiesgo] = useState<NivelRiesgo>("bajo");
  const [canal, setCanal] = useState<Canal>("presencial");
  const [esPep, setEsPep] = useState(false);
  const [guardando, setGuardando] = useState(false);

  const puedeEditar = perfil?.role === "admin" || perfil?.role === "abogado";

  const cargar = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const [c, m] = await Promise.all([api.getCliente(id), api.getMatrizRiesgo(id)]);
      setCliente(c);
      setMatriz(m);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo cargar el cliente.");
    }
  }, [id, navigate]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  function iniciarEdicion() {
    setTipoPersona(matriz?.tipo_persona ?? "natural");
    setActividadRiesgo(matriz?.actividad_economica_riesgo ?? "bajo");
    setJurisdiccionRiesgo(matriz?.jurisdiccion_riesgo ?? "bajo");
    setCanal(matriz?.canal ?? "presencial");
    setEsPep(matriz?.es_pep ?? false);
    setEditando(true);
  }

  async function onGuardar(e: FormEvent) {
    e.preventDefault();
    if (!id) return;
    setGuardando(true);
    setError(null);
    try {
      const actualizada = await api.setMatrizRiesgo(id, {
        tipo_persona: tipoPersona,
        actividad_economica_riesgo: actividadRiesgo,
        jurisdiccion_riesgo: jurisdiccionRiesgo,
        canal,
        es_pep: esPep,
      });
      setMatriz(actualizada);
      setEditando(false);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo guardar la matriz de riesgo.");
    } finally {
      setGuardando(false);
    }
  }

  if (!perfil || cliente === null) {
    if (error) {
      return (
        <div className="page">
          <div className="alert error" role="alert">{error}</div>
        </div>
      );
    }
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (!cliente) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Cliente</p>
          <h1 className="page-title">{cliente.email}</h1>
        </div>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      <section className="section">
        <h2 className="section-title">Casos</h2>
        {cliente.casos.length === 0 ? (
          <p className="muted">Todavía no tiene casos.</p>
        ) : (
          <ul className="caso-list">
            {cliente.casos.map((c) => (
              <li key={c.id}>
                <Link className="caso-row card" to={`/casos/${c.id}`}>
                  <div className="caso-row-main">
                    <span className="caso-row-title">{c.titulo}</span>
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
      </section>

      <section className="section">
        <h2 className="section-title">Matriz de riesgo (SAGRILAFT lite)</h2>
        <p className="faint">
          Herramienta de apoyo para documentar el criterio del despacho -- no sustituye el juicio
          del oficial de cumplimiento ni es un motor de compliance certificado.
        </p>

        {matriz === undefined ? (
          <div className="empty muted"><span className="spinner" /> Cargando…</div>
        ) : !editando ? (
          <div className="card cobro-resumen">
            {matriz === null ? (
              <p className="muted">Todavía no se evaluó el riesgo de este cliente.</p>
            ) : (
              <>
                <div className="cobro-fila">
                  <span className="faint">Nivel de riesgo</span>
                  <NivelRiesgoPill nivel={matriz.nivel_riesgo_calculado} />
                </div>
                <div className="cobro-fila">
                  <span className="faint">Tipo de persona</span>
                  <span>{TIPO_PERSONA_LABEL[matriz.tipo_persona]}</span>
                </div>
                <div className="cobro-fila">
                  <span className="faint">Actividad económica</span>
                  <span>{NIVEL_LABEL[matriz.actividad_economica_riesgo]}</span>
                </div>
                <div className="cobro-fila">
                  <span className="faint">Jurisdicción</span>
                  <span>{NIVEL_LABEL[matriz.jurisdiccion_riesgo]}</span>
                </div>
                <div className="cobro-fila">
                  <span className="faint">Canal</span>
                  <span>{CANAL_LABEL[matriz.canal]}</span>
                </div>
                <div className="cobro-fila">
                  <span className="faint">Persona expuesta políticamente (PEP)</span>
                  <span>{matriz.es_pep ? "Sí" : "No"}</span>
                </div>
                <p className="faint">Última evaluación: {fechaCorta(matriz.updated_at)}</p>
              </>
            )}
            {puedeEditar && (
              <button className="btn btn-ghost btn-sm" type="button" onClick={iniciarEdicion}>
                {matriz ? "Reevaluar" : "Evaluar riesgo"}
              </button>
            )}
          </div>
        ) : (
          <form className="card cobro-form" onSubmit={onGuardar}>
            <div className="field">
              <label htmlFor="tipo-persona">Tipo de persona</label>
              <select
                id="tipo-persona"
                className="select"
                value={tipoPersona}
                onChange={(e) => setTipoPersona(e.target.value as TipoPersona)}
              >
                <option value="natural">Persona natural</option>
                <option value="juridica">Persona jurídica</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="actividad-riesgo">Riesgo de la actividad económica</label>
              <select
                id="actividad-riesgo"
                className="select"
                value={actividadRiesgo}
                onChange={(e) => setActividadRiesgo(e.target.value as NivelRiesgo)}
              >
                <option value="bajo">Bajo</option>
                <option value="medio">Medio</option>
                <option value="alto">Alto</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="jurisdiccion-riesgo">Riesgo de la jurisdicción</label>
              <select
                id="jurisdiccion-riesgo"
                className="select"
                value={jurisdiccionRiesgo}
                onChange={(e) => setJurisdiccionRiesgo(e.target.value as NivelRiesgo)}
              >
                <option value="bajo">Bajo</option>
                <option value="medio">Medio</option>
                <option value="alto">Alto</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="canal">Canal de vinculación</label>
              <select id="canal" className="select" value={canal} onChange={(e) => setCanal(e.target.value as Canal)}>
                <option value="presencial">Presencial</option>
                <option value="no_presencial">No presencial</option>
              </select>
            </div>
            <label className="check">
              <input type="checkbox" checked={esPep} onChange={(e) => setEsPep(e.target.checked)} />
              Es persona expuesta políticamente (PEP)
            </label>
            <p className="faint">
              Si marcás PEP, el nivel de riesgo calculado va a ser "Alto" sin importar los demás
              factores -- es la regla real de SAGRILAFT, no una decisión de esta herramienta.
            </p>
            <div className="generar-actions">
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setEditando(false)}>
                Cancelar
              </button>
              <button className="btn btn-primary" type="submit" disabled={guardando}>
                {guardando ? <span className="spinner" /> : null}
                {guardando ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
