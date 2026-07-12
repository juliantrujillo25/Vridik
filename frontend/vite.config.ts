import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, el frontend corre en localhost:5173 y la API en Railway.
//
// El proxy se namespacea bajo /api-proxy (con rewrite que le saca ese
// prefijo antes de reenviar) -- a propósito NO se proxean los prefijos
// reales de la API (/auth, /casos, etc.) tal cual, porque esos mismos
// nombres son también rutas del router del frontend (React Router:
// /casos, /casos/:id). Si se proxeara /casos directo, una recarga de
// página estando en /casos/algún-id le pega al proxy en vez de servir
// la SPA, y el navegador termina mostrando el JSON crudo del backend en
// vez de la app -- se encontró este bug al verificar el login por primera
// vez. Con el prefijo /api-proxy no hay colisión posible: ninguna ruta de
// la SPA vive ahí.
//
// src/api/client.ts usa `/api-proxy` como base cuando VITE_API_BASE no
// está seteada (dev); en el build de producción, .env.production fija
// VITE_API_BASE a la URL real de Railway y el cliente llama directo,
// sin pasar por ningún proxy (no hay vite dev server en el build estático).
const API_TARGET =
  process.env.VITE_API_PROXY_TARGET || "https://vridik-api-production.up.railway.app";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api-proxy": {
        target: API_TARGET,
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/api-proxy/, ""),
      },
    },
  },
});
