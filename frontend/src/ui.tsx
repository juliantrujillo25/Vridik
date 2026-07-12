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
