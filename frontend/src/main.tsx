import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { ProtectedLayout } from "./Layout";
import { CasosListPage } from "./casos/CasosListPage";
import { CasoDetailPage } from "./casos/CasoDetailPage";
import "./index.css";
import "./layout.css";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <ProtectedLayout />,
    children: [
      { index: true, element: <Navigate to="/casos" replace /> },
      { path: "casos", element: <CasosListPage /> },
      { path: "casos/:id", element: <CasoDetailPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/casos" replace /> },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>,
);
