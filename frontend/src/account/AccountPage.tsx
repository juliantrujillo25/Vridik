import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { api, SesionExpiradaError } from "../api/client";
import type { Setup2FAResponse } from "../api/types";

type Paso = "cargando" | "inactivo" | "qr" | "codigos" | "activo" | "regenerar";

export function AccountPage() {
  const navigate = useNavigate();
  const { perfil, perfilCargando, perfilError, recargarPerfil, logout } = useAuth();
  const [paso, setPaso] = useState<Paso>("cargando");
  const [error, setError] = useState<string | null>(null);

  const [setup, setSetup] = useState<Setup2FAResponse | null>(null);
  const [code, setCode] = useState("");
  const [verificando, setVerificando] = useState(false);
  const [codigosRespaldo, setCodigosRespaldo] = useState<string[] | null>(null);
  const [confirmoGuardar, setConfirmoGuardar] = useState(false);

  const [passwordActual, setPasswordActual] = useState("");
  const [passwordNueva, setPasswordNueva] = useState("");
  const [passwordConfirmar, setPasswordConfirmar] = useState("");
  const [cambiandoPassword, setCambiandoPassword] = useState(false);
  const [errorPassword, setErrorPassword] = useState<string | null>(null);

  function manejarError(err: unknown, fallback: string) {
    if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
    setError(err instanceof Error ? err.message : fallback);
  }

  useEffect(() => {
    if (perfil) setPaso(perfil.totp_enabled ? "activo" : "inactivo");
  }, [perfil]);

  async function onIniciarSetup() {
    setError(null);
    try {
      setSetup(await api.setup2fa());
      setPaso("qr");
    } catch (err) {
      manejarError(err, "No se pudo generar el código de activación.");
    }
  }

  async function onVerificar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setVerificando(true);
    try {
      const res = await api.verify2fa(code.trim());
      setCodigosRespaldo(res.codigos_respaldo);
      setPaso("codigos");
    } catch (err) {
      manejarError(err, "Código inválido.");
    } finally {
      setVerificando(false);
    }
  }

  async function onRegenerar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setVerificando(true);
    try {
      const res = await api.regenerarCodigosRespaldo(code.trim());
      setCodigosRespaldo(res.codigos_respaldo);
      setPaso("codigos");
    } catch (err) {
      manejarError(err, "Código inválido.");
    } finally {
      setVerificando(false);
    }
  }

  function onTerminar() {
    setCode("");
    setSetup(null);
    setCodigosRespaldo(null);
    setConfirmoGuardar(false);
    void recargarPerfil();
  }

  async function onCambiarPassword(e: FormEvent) {
    e.preventDefault();
    setErrorPassword(null);
    if (passwordNueva !== passwordConfirmar) {
      setErrorPassword("La confirmación no coincide con la contraseña nueva.");
      return;
    }
    setCambiandoPassword(true);
    try {
      await api.cambiarPassword({ password_actual: passwordActual, password_nueva: passwordNueva });
      // El cambio revoca todas las sesiones (incluida esta) del lado del
      // servidor -- cerramos sesión acá también para no dejar la UI en un
      // estado a medias (con un access token que en minutos deja de poder
      // renovarse).
      await logout();
      navigate("/login", { replace: true, state: { mensaje: "Contraseña actualizada. Iniciá sesión de nuevo." } });
    } catch (err) {
      if (err instanceof SesionExpiradaError) return navigate("/login", { replace: true });
      setErrorPassword(err instanceof Error ? err.message : "No se pudo cambiar la contraseña.");
    } finally {
      setCambiandoPassword(false);
    }
  }

  if (perfilCargando || paso === "cargando") {
    return (
      <div className="page">
        <div className="empty muted"><span className="spinner" /> Cargando…</div>
      </div>
    );
  }

  if (!perfil) {
    return (
      <div className="page">
        <div className="alert error" role="alert">{perfilError ?? "No se pudo cargar tu cuenta."}</div>
        <button className="btn btn-ghost btn-sm" onClick={() => void recargarPerfil()}>Reintentar</button>
      </div>
    );
  }

  return (
    <div className="page page-narrow">
      <p className="eyebrow">Cuenta</p>
      <h1 className="page-title">Tu cuenta</h1>

      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="card account-card">
        <div className="account-row">
          <span className="muted">Email</span>
          <span className="mono">{perfil.email}</span>
        </div>
        <div className="account-row">
          <span className="muted">Despacho</span>
          <span className="mono">{perfil.despacho_nombre}</span>
        </div>
        <div className="account-row">
          <span className="muted">Rol</span>
          <span className="mono">{perfil.role}</span>
        </div>
      </div>

      <section className="section">
        <h2 className="section-title">Cambiar contraseña</h2>
        <form className="card twofa-setup" onSubmit={onCambiarPassword}>
          {errorPassword && <div className="alert error" role="alert">{errorPassword}</div>}
          <div className="field">
            <label htmlFor="password-actual">Contraseña actual</label>
            <input
              id="password-actual"
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={passwordActual}
              onChange={(e) => setPasswordActual(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password-nueva">Contraseña nueva</label>
            <input
              id="password-nueva"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={passwordNueva}
              onChange={(e) => setPasswordNueva(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password-confirmar">Confirmar contraseña nueva</label>
            <input
              id="password-confirmar"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={passwordConfirmar}
              onChange={(e) => setPasswordConfirmar(e.target.value)}
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={cambiandoPassword}>
            {cambiandoPassword ? <span className="spinner" /> : null}
            {cambiandoPassword ? "Cambiando…" : "Cambiar contraseña"}
          </button>
        </form>
      </section>

      <section className="section">
        <h2 className="section-title">Verificación en dos pasos</h2>

        {paso === "activo" && (
          <div className="card twofa-status">
            <span className="pill abierto">2FA activo</span>
            <p className="muted twofa-status-note">
              Si perdiste el dispositivo, pedile a un admin que reinicie tu 2FA desde el panel.
              Si lo que te quedaste sin es códigos de respaldo, podés generar un lote nuevo vos mismo.
            </p>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => { setCode(""); setPaso("regenerar"); }}
            >
              Generar nuevos códigos de respaldo
            </button>
          </div>
        )}

        {paso === "regenerar" && (
          <div className="card twofa-setup">
            <p className="twofa-step-label">Confirmá tu identidad</p>
            <p className="muted">
              Ingresá el código de 6 dígitos de tu app de autenticación. Esto invalida los códigos de
              respaldo anteriores y genera 8 nuevos.
            </p>
            <form className="twofa-code-form" onSubmit={onRegenerar}>
              <div className="field">
                <label htmlFor="regen-code">Código de 6 dígitos</label>
                <input
                  id="regen-code"
                  className="input mono"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  maxLength={6}
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))}
                  placeholder="000000"
                />
              </div>
              <div className="twofa-actions">
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setPaso("activo")}>
                  Cancelar
                </button>
                <button className="btn btn-primary" type="submit" disabled={verificando || code.length !== 6}>
                  {verificando ? <span className="spinner" /> : null}
                  {verificando ? "Verificando…" : "Generar códigos nuevos"}
                </button>
              </div>
            </form>
          </div>
        )}

        {paso === "inactivo" && (
          <div className="card twofa-status">
            <span className="pill en_progreso">2FA no activado</span>
            <p className="muted twofa-status-note">
              Agregá un segundo paso de verificación con una app como Google Authenticator o Authy.
            </p>
            <button className="btn btn-primary" onClick={onIniciarSetup}>Activar 2FA</button>
          </div>
        )}

        {paso === "qr" && setup && (
          <div className="card twofa-setup">
            <p className="twofa-step-label">Paso 1 de 2 — Escaneá el código</p>
            <div className="twofa-qr-wrap">
              <img
                className="twofa-qr"
                src={`data:image/png;base64,${setup.qr_code_base64}`}
                alt="Código QR para configurar la verificación en dos pasos"
              />
            </div>
            <details className="twofa-manual">
              <summary>¿No podés escanear? Ingresalo a mano</summary>
              <p className="muted twofa-manual-note">
                En tu app, elegí "ingresar clave manualmente" y pegá esta URI de configuración:
              </p>
              <code className="mono twofa-uri">{setup.otpauth_uri}</code>
            </details>

            <form className="twofa-code-form" onSubmit={onVerificar}>
              <div className="field">
                <label htmlFor="twofa-code">Código de 6 dígitos</label>
                <input
                  id="twofa-code"
                  className="input mono"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))}
                  placeholder="000000"
                />
              </div>
              <div className="twofa-actions">
                <button className="btn btn-ghost btn-sm" type="button" onClick={onTerminar}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={verificando || code.length !== 6}>
                  {verificando ? <span className="spinner" /> : null}
                  {verificando ? "Verificando…" : "Confirmar"}
                </button>
              </div>
            </form>
          </div>
        )}

        {paso === "codigos" && codigosRespaldo && (
          <div className="card twofa-setup">
            <p className="twofa-step-label">
              {setup ? "Paso 2 de 2 — Guardá tus códigos de respaldo" : "Tus códigos de respaldo nuevos"}
            </p>
            <div className="alert warn">
              {setup
                ? "Estos 8 códigos son la única forma de entrar si perdés el teléfono. Se muestran "
                : "Los códigos anteriores ya no sirven. Estos son los nuevos, se muestran "}
              <strong>una sola vez</strong>.
            </div>
            <ul className="backup-codes">
              {codigosRespaldo.map((c) => (
                <li key={c} className="mono">{c}</li>
              ))}
            </ul>
            <label className="check backup-confirm">
              <input
                type="checkbox"
                checked={confirmoGuardar}
                onChange={(e) => setConfirmoGuardar(e.target.checked)}
              />
              Ya guardé estos códigos en un lugar seguro
            </label>
            <button className="btn btn-primary" disabled={!confirmoGuardar} onClick={onTerminar}>
              Listo
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
