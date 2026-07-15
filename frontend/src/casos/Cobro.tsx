import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, SesionExpiradaError } from "../api/client";
import type { Cobro, EsquemaHonorarios, EstadoCaso } from "../api/types";

const ESQUEMA_LABEL: Record<EsquemaHonorarios, string> = {
  fijo: "Fijo",
  cuota_litis: "Cuota litis",
  mixto: "Mixto",
};

function formatoCOP(valor: number | null): string {
  if (valor === null) return "—";
  try {
    return valor.toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
  } catch {
    return String(valor);
  }
}

function fechaCorta(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

interface Props {
  casoId: string;
  casoEstado: EstadoCaso;
  puedeEditar: boolean; // abogado asignado o admin -- nunca el cliente (lo exige el backend igual)
}

export function CobroPanel({ casoId, casoEstado, puedeEditar }: Props) {
  const [cobro, setCobro] = useState<Cobro | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [editando, setEditando] = useState(false);
  const [valorEnDisputa, setValorEnDisputa] = useState("");
  const [esquema, setEsquema] = useState<EsquemaHonorarios | "">("");
  const [montoFijo, setMontoFijo] = useState("");
  const [porcentaje, setPorcentaje] = useState("");
  const [guardando, setGuardando] = useState(false);

  const [valorRecuperado, setValorRecuperado] = useState("");
  const [liquidando, setLiquidando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const c = await api.getCobro(casoId);
      setCobro(c);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo cargar el cobro.");
    }
  }, [casoId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  function iniciarEdicion() {
    setValorEnDisputa(cobro?.valor_en_disputa != null ? String(cobro.valor_en_disputa) : "");
    setEsquema(cobro?.esquema_honorarios ?? "");
    setMontoFijo(cobro?.monto_fijo != null ? String(cobro.monto_fijo) : "");
    setPorcentaje(cobro?.porcentaje_cuota_litis != null ? String(cobro.porcentaje_cuota_litis) : "");
    setEditando(true);
  }

  async function onGuardar(e: FormEvent) {
    e.preventDefault();
    setGuardando(true);
    setError(null);
    try {
      const actualizado = await api.setCobro(casoId, {
        valor_en_disputa: valorEnDisputa ? Number(valorEnDisputa) : null,
        esquema_honorarios: esquema || null,
        monto_fijo: esquema === "fijo" || esquema === "mixto" ? Number(montoFijo || 0) : null,
        porcentaje_cuota_litis: esquema === "cuota_litis" || esquema === "mixto" ? Number(porcentaje || 0) : null,
      });
      setCobro(actualizado);
      setEditando(false);
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo guardar el cobro.");
    } finally {
      setGuardando(false);
    }
  }

  async function onLiquidar(e: FormEvent) {
    e.preventDefault();
    if (!valorRecuperado) return;
    const ok = window.confirm(
      "Liquidar honorarios calcula el monto final a partir del esquema configurado y no se puede deshacer. ¿Continuar?",
    );
    if (!ok) return;
    setLiquidando(true);
    setError(null);
    try {
      const actualizado = await api.liquidarCobro(casoId, Number(valorRecuperado));
      setCobro(actualizado);
      setValorRecuperado("");
    } catch (err) {
      if (err instanceof SesionExpiradaError) return;
      setError(err instanceof Error ? err.message : "No se pudo liquidar el cobro.");
    } finally {
      setLiquidando(false);
    }
  }

  if (!cobro) {
    return (
      <section className="section">
        <h2 className="section-title">Cobro</h2>
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      </section>
    );
  }

  const puedeLiquidar =
    puedeEditar && casoEstado === "cerrado" && cobro.esquema_honorarios !== null && cobro.liquidado_en === null;

  return (
    <section className="section">
      <h2 className="section-title">Cobro</h2>
      {error && <div className="alert error" role="alert">{error}</div>}

      {!editando ? (
        <div className="card cobro-resumen">
          <div className="cobro-fila">
            <span className="faint">Valor en disputa</span>
            <span className="mono">{formatoCOP(cobro.valor_en_disputa)}</span>
          </div>
          <div className="cobro-fila">
            <span className="faint">Esquema de honorarios</span>
            <span>
              {cobro.esquema_honorarios ? ESQUEMA_LABEL[cobro.esquema_honorarios] : "Sin configurar"}
              {cobro.esquema_honorarios === "fijo" && ` — ${formatoCOP(cobro.monto_fijo)}`}
              {cobro.esquema_honorarios === "cuota_litis" && ` — ${cobro.porcentaje_cuota_litis}%`}
              {cobro.esquema_honorarios === "mixto" &&
                ` — ${formatoCOP(cobro.monto_fijo)} + ${cobro.porcentaje_cuota_litis}%`}
            </span>
          </div>
          {cobro.liquidado_en ? (
            <div className="cobro-fila cobro-liquidado">
              <span className="faint">Honorarios liquidados</span>
              <span className="mono cobro-monto-liquidado">
                {formatoCOP(cobro.honorarios_liquidados)}
                <span className="faint"> · {fechaCorta(cobro.liquidado_en)}</span>
              </span>
            </div>
          ) : (
            puedeEditar &&
            casoEstado !== "cerrado" && (
              <p className="faint cobro-nota">La liquidación se habilita cuando el caso pasa a "Cerrado".</p>
            )
          )}
          {puedeEditar && !cobro.liquidado_en && (
            <button className="btn btn-ghost btn-sm" type="button" onClick={iniciarEdicion}>
              {cobro.esquema_honorarios ? "Editar" : "Configurar cobro"}
            </button>
          )}
        </div>
      ) : (
        <form className="card cobro-form" onSubmit={onGuardar}>
          <div className="field">
            <label htmlFor="valor-disputa">Valor en disputa (COP)</label>
            <input
              id="valor-disputa"
              type="number"
              min={0}
              className="input"
              value={valorEnDisputa}
              onChange={(e) => setValorEnDisputa(e.target.value)}
              placeholder="Ej. 50000000"
            />
          </div>
          <div className="field">
            <label htmlFor="esquema">Esquema de honorarios</label>
            <select
              id="esquema"
              className="select"
              value={esquema}
              onChange={(e) => setEsquema(e.target.value as EsquemaHonorarios | "")}
            >
              <option value="">— Elegir esquema —</option>
              <option value="fijo">Fijo</option>
              <option value="cuota_litis">Cuota litis</option>
              <option value="mixto">Mixto (fijo + cuota litis)</option>
            </select>
          </div>
          {(esquema === "fijo" || esquema === "mixto") && (
            <div className="field">
              <label htmlFor="monto-fijo">Monto fijo (COP)</label>
              <input
                id="monto-fijo"
                type="number"
                min={0}
                className="input"
                value={montoFijo}
                onChange={(e) => setMontoFijo(e.target.value)}
              />
            </div>
          )}
          {(esquema === "cuota_litis" || esquema === "mixto") && (
            <div className="field">
              <label htmlFor="porcentaje">Porcentaje de cuota litis (%)</label>
              <input
                id="porcentaje"
                type="number"
                min={0}
                max={100}
                className="input"
                value={porcentaje}
                onChange={(e) => setPorcentaje(e.target.value)}
              />
            </div>
          )}
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

      {puedeLiquidar && (
        <form className="card cobro-form cobro-liquidar-form" onSubmit={onLiquidar}>
          <div className="field">
            <label htmlFor="valor-recuperado">Valor recuperado (COP) — para liquidar honorarios</label>
            <input
              id="valor-recuperado"
              type="number"
              min={0}
              className="input"
              value={valorRecuperado}
              onChange={(e) => setValorRecuperado(e.target.value)}
              placeholder="Resultado real del caso"
            />
          </div>
          <div className="generar-actions">
            <button className="btn btn-primary" type="submit" disabled={liquidando || !valorRecuperado}>
              {liquidando ? <span className="spinner" /> : null}
              {liquidando ? "Liquidando…" : "Liquidar honorarios"}
            </button>
          </div>
          <p className="faint generar-nota">
            El monto se calcula solo con el esquema ya configurado — nunca se ingresa a mano.
          </p>
        </form>
      )}
    </section>
  );
}
