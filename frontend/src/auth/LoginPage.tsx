import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { requiere2FA } from "../api/types";
import { useAuth } from "./AuthContext";

type Paso = "credenciales" | "2fa";

export function LoginPage() {
  const navigate = useNavigate();
  const { sesionActualizada } = useAuth();

  const [paso, setPaso] = useState<Paso>("credenciales");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tempToken, setTempToken] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  function entrar() {
    sesionActualizada();
    navigate("/casos", { replace: true });
  }

  async function onCredenciales(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCargando(true);
    try {
      const res = await api.login(email.trim(), password);
      if (requiere2FA(res)) {
        setTempToken(res.temp_token);
        setPaso("2fa");
      } else {
        api.setSession(res);
        entrar();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setCargando(false);
    }
  }

  async function on2fa(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCargando(true);
    try {
      const tokens = await api.login2fa(tempToken, code.trim());
      api.setSession(tokens);
      entrar();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Código inválido.");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card card">
        <p className="eyebrow">Vridik</p>
        <h1 className="login-title">
          {paso === "credenciales" ? "Copiloto legal" : "Verificación en dos pasos"}
        </h1>
        <p className="muted login-sub">
          {paso === "credenciales"
            ? "Ingresá con tu cuenta del despacho."
            : "Ingresá el código de 6 dígitos de tu app de autenticación (o un código de respaldo)."}
        </p>

        {error && <div className="alert error" role="alert">{error}</div>}

        {paso === "credenciales" ? (
          <form className="login-form" onSubmit={onCredenciales}>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                className="input"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="password">Contraseña</label>
              <input
                id="password"
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={cargando}>
              {cargando ? <span className="spinner" /> : null}
              {cargando ? "Entrando…" : "Iniciar sesión"}
            </button>
          </form>
        ) : (
          <form className="login-form" onSubmit={on2fa}>
            <div className="field">
              <label htmlFor="code">Código</label>
              <input
                id="code"
                className="input mono"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                required
                maxLength={8}
                placeholder="000000"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))}
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={cargando}>
              {cargando ? <span className="spinner" /> : null}
              {cargando ? "Verificando…" : "Verificar"}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => { setPaso("credenciales"); setCode(""); setError(null); }}
            >
              Volver
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
