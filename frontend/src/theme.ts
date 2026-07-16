import { useCallback, useEffect, useState } from "react";

// Toggle de tema manual -- frontend/src/index.css ya soportaba
// :root[data-theme="light"|"dark"] desde el principio (además de
// @media(prefers-color-scheme)), pero nada en la app lo usaba todavía:
// hasta ahora Vridik solo seguía la preferencia del sistema operativo.
type Tema = "light" | "dark";

const CLAVE_STORAGE = "vridik.theme";

function temaGuardado(): Tema | null {
  const valor = localStorage.getItem(CLAVE_STORAGE);
  return valor === "light" || valor === "dark" ? valor : null;
}

function temaDelSistema(): Tema {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function aplicarTema(tema: Tema | null): void {
  if (tema) {
    document.documentElement.dataset.theme = tema;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

/** `null` = sin preferencia guardada, sigue al sistema operativo (el
 *  comportamiento de siempre). Elegir un tema a mano lo persiste y deja
 *  de seguir al sistema hasta que el usuario lo reinicie. */
export function useTheme(): { tema: Tema; toggleTheme: () => void } {
  const [temaElegido, setTemaElegido] = useState<Tema | null>(() => temaGuardado());

  useEffect(() => {
    aplicarTema(temaElegido);
  }, [temaElegido]);

  const toggleTheme = useCallback(() => {
    setTemaElegido((actual) => {
      const base = actual ?? temaDelSistema();
      const nuevo: Tema = base === "dark" ? "light" : "dark";
      localStorage.setItem(CLAVE_STORAGE, nuevo);
      return nuevo;
    });
  }, []);

  return { tema: temaElegido ?? temaDelSistema(), toggleTheme };
}
