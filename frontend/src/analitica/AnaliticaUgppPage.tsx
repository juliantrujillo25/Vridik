import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, SesionExpiradaError } from "../api/client";
import type { AnaliticaUgpp } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { RESULTADO_LABEL } from "../ui";

function formatoMoneda(valor: number): string {
  return valor.toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
}

function formatoPorcentaje(valor: number): string {
  return `${Math.round(valor * 100)}%`;
}

/** Fase 4 (roadmap: "línea decisional UGPP") -- el corpus jurisprudencial
 *  sigue incompleto, así que esto NO analiza jurisprudencia externa ni
 *  perfila jueces (advertencia SAMAI del roadmap): agrega los resultados
 *  que el propio despacho registra sobre sus propios casos UGPP. */
export function AnaliticaUgppPage() {
  const navigate = useNavigate();
  const { perfil } = useAuth();
  const [datos, setDatos] = useState<AnaliticaUgpp | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function cargar() {
    setError(null);
    try {
      setDatos(await api.analiticaUgpp());
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setError(err instanceof Error ? err.message : "No se pudo cargar la analítica.");
    }
  }

  useEffect(() => {
    void cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!perfil) {
    return <div className="page"><div className="empty muted"><span className="spinner" /> Cargando…</div></div>;
  }

  if (perfil.role !== "admin" && perfil.role !== "abogado") {
    return (
      <div className="page">
        <p className="eyebrow">Analítica</p>
        <h1 className="page-title">Analítica UGPP</h1>
        <div className="alert error" role="alert">No tenés acceso a esta sección.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Analítica</p>
          <h1 className="page-title">Línea decisional UGPP</h1>
        </div>
      </div>

      <p className="faint">
        Resultados de los casos UGPP propios del despacho -- no analiza jurisprudencia externa (el
        corpus todavía está incompleto) ni perfila jueces. Con pocas muestras, un porcentaje solo es
        poco representativo: mirá siempre el número de casos junto al porcentaje.
      </p>

      {error && (
        <div className="alert error" role="alert">
          {error}
          <button className="btn btn-ghost btn-sm" onClick={() => void cargar()}>Reintentar</button>
        </div>
      )}

      {datos === null ? (
        error ? null : <div className="empty muted"><span className="spinner" /> Cargando…</div>
      ) : datos.total_casos_ugpp === 0 ? (
        <div className="card empty-state">
          <p className="empty-title">Todavía no hay casos marcados con materia "UGPP".</p>
          <p className="muted">Marcá la materia de un caso desde su detalle para que aparezca acá.</p>
        </div>
      ) : (
        <>
          <div className="card cobro-resumen">
            <div className="cobro-fila">
              <span className="faint">Casos UGPP</span>
              <span>{datos.total_casos_ugpp}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Fallos registrados</span>
              <span>{datos.total_fallos_registrados}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Fallos con resultado</span>
              <span>{datos.total_con_resultado}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Tasa de éxito</span>
              <span>
                {datos.tasa_exito === null ? "—" : formatoPorcentaje(datos.tasa_exito)}
                {" "}
                <span className="faint mono">(n={datos.total_con_resultado})</span>
              </span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Días promedio hasta el fallo</span>
              <span>
                {datos.tiempo_promedio_dias_hasta_fallo === null
                  ? "—"
                  : Math.round(datos.tiempo_promedio_dias_hasta_fallo)}
              </span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Casos liquidados</span>
              <span>{datos.casos_liquidados}</span>
            </div>
            <div className="cobro-fila">
              <span className="faint">Valor recuperado total</span>
              <span>{formatoMoneda(datos.valor_recuperado_total)}</span>
            </div>
            {datos.valor_recuperado_promedio !== null && (
              <div className="cobro-fila">
                <span className="faint">Valor recuperado promedio</span>
                <span>{formatoMoneda(datos.valor_recuperado_promedio)}</span>
              </div>
            )}
          </div>

          <section className="section">
            <h2 className="section-title">Por tipo de resolución</h2>
            {datos.por_tipo_resolucion.length === 0 ? (
              <p className="muted">Todavía no hay fallos con resultado registrado.</p>
            ) : (
              <ul className="caso-list">
                {datos.por_tipo_resolucion.map((t) => (
                  <li key={t.tipo_resolucion_ugpp}>
                    <div className="card caso-row">
                      <div className="caso-row-main">
                        <span className="caso-row-title">{t.tipo_resolucion_ugpp}</span>
                        <span className="faint mono">n={t.total}</span>
                      </div>
                      <div className="caso-row-meta">
                        <span className="pill verde">{RESULTADO_LABEL.favorable} {t.favorable}</span>
                        <span className="pill amarillo">{RESULTADO_LABEL.parcial} {t.parcial}</span>
                        <span className="pill rojo">{RESULTADO_LABEL.desfavorable} {t.desfavorable}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
