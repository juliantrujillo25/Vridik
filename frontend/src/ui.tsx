import type { CategoriaActuacion, EstadoCaso, Materia, ResultadoActuacion } from "./api/types";

export const ESTADOS: EstadoCaso[] = ["abierto", "en_progreso", "cerrado"];

export const ESTADO_LABEL: Record<EstadoCaso, string> = {
  abierto: "Abierto",
  en_progreso: "En progreso",
  cerrado: "Cerrado",
};

export function EstadoPill({ estado }: { estado: EstadoCaso }) {
  return <span className={`pill ${estado}`}>{ESTADO_LABEL[estado]}</span>;
}

// Fase 4 (analítica UGPP)
export const MATERIAS: Materia[] = ["ugpp", "laboral", "otro"];

export const MATERIA_LABEL: Record<Materia, string> = {
  ugpp: "UGPP",
  laboral: "Laboral",
  otro: "Otro",
};

export const RESULTADO_LABEL: Record<ResultadoActuacion, string> = {
  favorable: "Favorable",
  desfavorable: "Desfavorable",
  parcial: "Parcial",
};

const RESULTADO_PILL_COLOR: Record<ResultadoActuacion, string> = {
  favorable: "verde",
  desfavorable: "rojo",
  parcial: "amarillo",
};

export function ResultadoPill({ resultado }: { resultado: ResultadoActuacion }) {
  return <span className={`pill ${RESULTADO_PILL_COLOR[resultado]}`}>{RESULTADO_LABEL[resultado]}</span>;
}

export function fechaCorta(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("es-CO", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export function fechaHora(iso: string): string {
  try {
    return new Date(iso).toLocaleString("es-CO", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

const MARCA_REVISAR = "\n\n[revisar]";

/** julix/service.py::validar_citas_post_generacion() incrusta un aviso de
 *  texto plano al final del documento cuando encuentra una cita sin
 *  respaldo en el contexto -- nunca bloquea la generación, así que sin
 *  esto el aviso queda mezclado en la prosa y es fácil pasarlo por alto.
 *  Separa el cuerpo del aviso para poder resaltarlo aparte en la UI. */
export function separarAvisoRevisar(contenido: string): { cuerpo: string; aviso: string | null } {
  const idx = contenido.indexOf(MARCA_REVISAR);
  if (idx === -1) return { cuerpo: contenido, aviso: null };
  return { cuerpo: contenido.slice(0, idx), aviso: contenido.slice(idx + 2).trim() };
}

// --- Fase 2: actuaciones + términos -----------------------------------------
export const CATEGORIA_LABEL: Record<CategoriaActuacion, string> = {
  auto_admisorio: "Auto admisorio",
  requerimiento: "Requerimiento",
  fallo: "Fallo",
  traslado: "Traslado",
  otro: "Otro",
};

/** Semáforo del roadmap ("verde/amarillo/rojo"): el umbral es a criterio de
 *  producto, no del backend (que solo entrega dias_restantes calculado) --
 *  3 días hábiles de margen como corte amarillo/rojo, alineado con el resto
 *  de términos legales cortos de UGPP/procesal que ya maneja el copiloto. */
export type SemaforoColor = "verde" | "amarillo" | "rojo";

export function semaforoTermino(diasRestantes: number, estado: "pendiente" | "cumplido"): SemaforoColor {
  if (estado === "cumplido") return "verde";
  if (diasRestantes <= 0) return "rojo";
  if (diasRestantes <= 3) return "amarillo";
  return "verde";
}
