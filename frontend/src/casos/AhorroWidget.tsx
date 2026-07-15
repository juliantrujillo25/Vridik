import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ResumenAhorro } from "../api/types";

function formatoCOP(valor: number): string {
  try {
    return valor.toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  } catch {
    return String(valor);
  }
}

/** Roadmap Fase 3: "Panel 'ahorro generado' en Portal Cliente Vridik
 *  (55% → 90%)". Solo se monta para el rol cliente (CasosListPage.tsx
 *  decide eso) -- el backend igual lo exige (403 para abogado/admin). */
export function AhorroWidget() {
  const [resumen, setResumen] = useState<ResumenAhorro | null>(null);

  useEffect(() => {
    api.resumenAhorro().then(setResumen, () => setResumen(null));
  }, []);

  // Silencioso si todavía no hay ningún caso liquidado -- no hay nada que
  // mostrarle al cliente hasta que exista un resultado real (mismo
  // criterio que los badges de términos/no-leídos: silencioso en 0).
  if (!resumen || resumen.casos_liquidados === 0) return null;

  return (
    <div className="card ahorro-widget">
      <span className="section-title ahorro-widget-title">Ahorro generado</span>
      <span className="mono ahorro-widget-monto">{formatoCOP(resumen.ahorro_generado)}</span>
      <p className="faint ahorro-widget-nota">
        {formatoCOP(resumen.total_valor_recuperado)} recuperados en {resumen.casos_liquidados}{" "}
        {resumen.casos_liquidados === 1 ? "caso cerrado" : "casos cerrados"}, después de{" "}
        {formatoCOP(resumen.total_honorarios_liquidados)} en honorarios.
      </p>
    </div>
  );
}
