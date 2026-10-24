import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { AgentCityClient, ApiError } from "../api/client";
import type { Capabilities, Settings } from "../api/types";
import { defaultSettings } from "../api/defaults";
import { Modal, Field, Button, ErrorBox } from "../components/ui";
type AppState = {
  client: AgentCityClient;
  settings: Settings;
  setSettings: (s: Settings) => void;
  capabilities: Capabilities | null;
  notice: (text: string) => void;
  notifyError: (error: unknown) => void;
};
const Context = createContext<AppState>(null!);
export function AppProvider({
  client,
  children,
}: {
  client: AgentCityClient;
  children: ReactNode;
}) {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [message, setMessage] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false),
    [passphrase, setPassphrase] = useState(""),
    [signingIn, setSigningIn] = useState(false),
    [loginError, setLoginError] = useState("");
  const notice = useCallback((text: string) => setMessage(text), []);
  const notifyError = useCallback(
    (e: unknown) => setMessage(e instanceof Error ? e.message : String(e)),
    [],
  );
  useEffect(() => {
    void client
      .capabilities()
      .then(setCapabilities)
      .then(() => client.session())
      .then((session) => {
        if (!session.authenticated) {
          setNeedsLogin(true);
          return null;
        }
        return client.settings();
      })
      .then((s) => {
        if (s) setSettings(s);
      })
      .catch(notifyError);
  }, [client, notifyError]);
  useEffect(() => {
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.motion = settings.reduce_motion
      ? "reduced"
      : "full";
  }, [settings]);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(""), 7000);
    return () => clearTimeout(t);
  }, [message]);
  return (
    <Context.Provider
      value={{
        client,
        settings,
        setSettings,
        capabilities,
        notice,
        notifyError,
      }}
    >
      {children}
      {needsLogin && (
        <Modal
          title="Welcome to your private city."
          eyebrow="OWNER SESSION"
          dismissible={false}
          busy={signingIn}
          onClose={() => {}}
        >
          <p className="muted">
            Enter the demo passphrase configured on your AgentCity server.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setSigningIn(true);
              setLoginError("");
              void client
                .login(passphrase)
                .then(() => client.settings())
                .then((s) => {
                  setSettings(s);
                  setPassphrase("");
                  setNeedsLogin(false);
                  window.location.reload();
                })
                .catch((e) => setLoginError(messageOf(e)))
                .finally(() => setSigningIn(false));
            }}
          >
            <Field label="Demo passphrase">
              <input
                type="password"
                autoComplete="current-password"
                required
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
              />
            </Field>
            {loginError && <ErrorBox error={loginError} />}
            <Button type="submit" disabled={signingIn}>
              Open your worlds
            </Button>
          </form>
        </Modal>
      )}

      {client.mode === "mock" && (
        <div className="mock-badge">
          <span /> MOCK MODE{" "}
          <span className="mock-extra">· Recorded review fixtures</span>
        </div>
      )}
      {message && (
        <div className="toast" role="status">
          {message}
          <button
            aria-label="Dismiss notification"
            onClick={() => setMessage("")}
          >
            ×
          </button>
        </div>
      )}
    </Context.Provider>
  );
}
export const useApp = () => useContext(Context);
export const messageOf = (e: unknown) =>
  e instanceof ApiError
    ? `${e.code}: ${e.message}`
    : e instanceof Error
      ? e.message
      : String(e);
export function useQuery<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    load()
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) setError(messageOf(e));
      });
    return () => {
      active = false;
    };
  }, [...deps, refresh]);
  return { data, error, reload: () => setRefresh((n) => n + 1) };
}
