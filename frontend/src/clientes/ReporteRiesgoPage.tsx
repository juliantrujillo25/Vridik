import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SesionExpiradaError } from "../api/client";
import type { NivelRiesgo, ReporteRiesgo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { fechaCorta } from "../ui";

const NIVEL_LABEL: Record<NivelRiesgo, string> = { bajo: "Bajo", medio: "Medio", alto: "Alto" };
const NIVEL_PILL_COLOR: Record<NivelRiesgo, string> = { bajo: "verde", medio: "amarillo", alto: "rojo" };

function NivelRiesgoPill({ nivel }: { nivel: NivelRiesgo }) {
  return <span className={`pill ${NIVEL_PILL_COLOR[nivel]}`}>{NIVEL_LABEL[nivel]}</span>;
}

/** Fase 4 (SAGRILAFT lite: "reportes Supersociedades") -- resumen + detalle
 *  de la matriz de riesgo del despacho, insumo del informe del oficial de
 *  cumplimiento. NO es el formato oficial exacto que exige la
 *  Superintendencia (ver core/cumplimiento.py::generar_reporte_riesgo). */
export function ReporteRiesgoPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();
  const [reporte, setReporte] = useState<ReporteRiesgo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [descargando, setDescargando] = useState(false);

  async function cargar() {
    setError(null);
    try {
      setReporte(await api.reporteRiesgo());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo cargar el reporte.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onDescargarCsv() {
    setDescargando(true);
    try {
      const blob = await api.descargarReporteRiesgoCsv();
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = "reporte_riesgo.csv";
      enlace.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo descargar el reporte.");
    } finally {
      setDescargando(false);
    }
  }

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (perfil.role !== "admin" && perfil.role !== "abogado") {
    return (
      <div className="page">
        <p className="eyebrow">Clientes</p>
        <h1 className="page-title">Reporte de riesgo</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow"><Link to="/clientes">Clientes</Link> / Reporte de riesgo</p>
          <h1 className="page-title">Reporte de riesgo (SAGRILAFT lite)</h1>
        </div>
      </div>

      <p className="faint">
        Insumo para el informe periódico del oficial de cumplimiento -- no es el formato oficial
        exacto que exige la Superintendencia de Sociedades, es la documentación de respaldo para
        prepararlo. Herramienta de apoyo, no sustituye el criterio del oficial de cumplimiento.
      </p>

      {error && (
        <div className="alert error" role="alert">
          {error}
          <button className="btn btn-ghost btn-sm" onClick={() => void cargar()}>Reintentar</button>
        </div>
      )}

      {reporte === null ? (
        error ? null : <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : (
        <>
          <div className="card cobro-resumen">
            <div className="cobro-fila">
              <span className="faint">Clientes del despacho</span>
              <span>{reporte.total_clientes}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Evaluados</span>
              <span>{reporte.total_evaluados}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Sin evaluar</span>
              <span>{reporte.total_sin_evaluar}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Riesgo alto</span>
              <NivelRiesgoPill nivel="alto" />
              <span>{reporte.conteo_por_nivel.alto}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Riesgo medio</span>
              <NivelRiesgoPill nivel="medio" />
              <span>{reporte.conteo_por_nivel.medio}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Riesgo bajo</span>
              <NivelRiesgoPill nivel="bajo" />
              <span>{reporte.conteo_por_nivel.bajo}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Personas expuestas políticamente (PEP)</span>
              <span>{reporte.total_pep}</span>
            </div>
            <p className="faint">Generado: {fechaCorta(reporte.generado_en)}</p>
            <button className="btn btn-primary" type="button" onClick={() => void onDescargarCsv()} disabled={descargando}>
              {descargando ? <span className="spinner" /> : null}
              {descargando ? "Descargando…" : "Descargar CSV"}
            </button>
          </div>

          {reporte.clientes.length === 0 ? (
            <div className="card empty-state">
              <p className="empty-title">Todavía no hay clientes evaluados.</p>
            </div>
          ) : (
            <ul className="caso-list">
              {reporte.clientes.map((c) => (
                <li key={c.cliente_id}>
                  <Link className="caso-row card" to={`/clientes/${c.cliente_id}`}>
                    <div className="caso-row-main">
                      <span className="caso-row-title">{c.email}</span>
                    </div>
                    <div className="caso-row-meta">
                      {c.es_pep && <span className="pill rojo">PEP</span>}
                      <NivelRiesgoPill nivel={c.nivel_riesgo_calculado} />
                      <span className="faint mono caso-row-date">{fechaCorta(c.updated_at)}</span>
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
