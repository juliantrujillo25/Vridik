import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "./AuthContext";

/** Fase 4 (multi-tenancy): registrarse acá crea un despacho NUEVO -- quien
 *  se registra queda como su primer administrador. Invitar a un cliente o
 *  abogado a un despacho YA existente se hace desde el panel admin
 *  ("Nuevo usuario"), no desde esta pantalla. */
export function SignupPage() {
  const navigate = useNavigate();
  const { sesionActualizada } = useAuth();

  const [nombreDespacho, setNombreDespacho] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCargando(true);
    try {
      const tokens = await api.register(email.trim(), password, nombreDespacho.trim());
      api.setSession(tokens);
      sesionActualizada();
      navigate("/casos", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Ya existe una cuenta con ese email.");
      } else {
        setError(err instanceof Error ? err.message : "No se pudo crear el despacho.");
      }
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card card">
        <p className="eyebrow">Vridik</p>
        <h1 className="login-title">Registrá tu despacho</h1>
        <p className="muted login-sub">
          Creamos un despacho nuevo con estos datos. Vas a ser su primer administrador.
        </p>

        {error && <div className="alert error" role="alert">{error}</div>}

        <form className="login-form" onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="nombre-despacho">Nombre del despacho</label>
            <input
              id="nombre-despacho"
              className="input"
              type="text"
              autoComplete="organization"
              required
              minLength={1}
              value={nombreDespacho}
              onChange={(e) => setNombreDespacho(e.target.value)}
              placeholder="Ej. Trujillo y Asociados"
            />
          </div>
          <div className="field">
            <label htmlFor="signup-email">Email</label>
            <input
              id="signup-email"
              className="input"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="signup-password">Contraseña</label>
            <input
              id="signup-password"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={cargando}>
            {cargando ? <span className="spinner" /> : null}
            {cargando ? "Creando despacho…" : "Crear despacho"}
          </button>
          <p className="muted login-sub-link">
            ¿Ya tenés cuenta? <Link to="/login">Iniciá sesión</Link>
          </p>
        </form>
      </div>
    </div>
  );
}
