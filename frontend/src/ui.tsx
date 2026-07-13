import type { EstadoCaso } from "./api/types";

export const ESTADOS: EstadoCaso[] = ["abierto", "en_progreso", "cerrado"];

export const ESTADO_LABEL: Record<EstadoCaso, string> = {
  abierto: "Abierto",
  en_progreso: "En progreso",
  cerrado: "Cerrado",
};

export function EstadoPill({ estado }: { estado: EstadoCaso }) {
  return <span className={`pill ${estado}`}>{ESTADO_LABEL[estado]}</span>;
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
