import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { SignupPage } from "./auth/SignupPage";
import { ProtectedLayout } from "./Layout";
import { CasosListPage } from "./casos/CasosListPage";
import { CasoDetailPage } from "./casos/CasoDetailPage";
import { AccountPage } from "./account/AccountPage";
import { AdminPage } from "./admin/AdminPage";
import { PlatformPage } from "./platform/PlatformPage";
import { ClientesListPage } from "./clientes/ClientesListPage";
import { ClienteDetailPage } from "./clientes/ClienteDetailPage";
import "./index.css";
import "./layout.css";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/registro", element: <SignupPage /> },
  {
    path: "/",
    element: <ProtectedLayout />,
    children: [
      { index: true, element: <Navigate to="/casos" replace /> },
      { path: "casos", element: <CasosListPage /> },
      { path: "casos/:id", element: <CasoDetailPage /> },
      { path: "clientes", element: <ClientesListPage /> },
      { path: "clientes/:id", element: <ClienteDetailPage /> },
      { path: "cuenta", element: <AccountPage /> },
      { path: "admin", element: <AdminPage /> },
      { path: "plataforma", element: <PlatformPage /> },
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
