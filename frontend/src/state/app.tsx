import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AgentCityClient, ApiError } from "../api/client";
import type { Capabilities, Settings } from "../api/types";
import { defaultSettings } from "../api/defaults";
import { Modal, Field, Button, ErrorBox } from "../components/ui";
import { MouseTrail } from "../components/MouseTrail";
import { CityZoom, type CityShot } from "../components/CityStrip";
type AppState = {
  client: AgentCityClient;
  settings: Settings;
  setSettings: (s: Settings) => void;
  capabilities: Capabilities | null;
  notice: (text: string) => void;
  notifyError: (error: unknown) => void;
  zoomCity: (shot: CityShot, onCovered: () => void) => void;
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
  const [zoom, setZoom] = useState<{
    shot: CityShot;
    onCovered: () => void;
  } | null>(null);
  const zoomCity = useCallback(
    (shot: CityShot, onCovered: () => void) => setZoom({ shot, onCovered }),
    [],
  );
  const notice = useCallback((text: string) => setMessage(text), []);
  const notifyError = useCallback(
    (e: unknown) => setMessage(e instanceof Error ? e.message : String(e)),
    [],
  );
  useEffect(() => {
    const expired = () => setNeedsLogin(true);
    window.addEventListener("agentcity:session-expired", expired);
    return () =>
      window.removeEventListener("agentcity:session-expired", expired);
  }, []);
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
        if (s)
          setSettings({
            ...s,
            reduce_motion:
              s.version === 0 ? defaultSettings.reduce_motion : s.reduce_motion,
          });
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
        zoomCity,
      }}
    >
      {children}
      {zoom && (
        <CityZoom
          shot={zoom.shot}
          onCovered={zoom.onCovered}
          onDone={() => setZoom(null)}
        />
      )}
      <MouseTrail enabled={!settings.reduce_motion} />
      {needsLogin && (
        <Modal
          title="Sign in to AgentCity"
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
export function useQuery<T>(
  load: () => Promise<T>,
  deps: unknown[],
  retainKey?: string,
) {
  const scope = useMemo(() => ({ active: true }), [retainKey]);
  const sequence = useRef(0);
  const [result, setResult] = useState({
    scope,
    data: null as T | null,
    error: "",
    sequence: 0,
  });
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    scope.active = true;
    return () => {
      scope.active = false;
    };
  }, [scope]);
  useEffect(() => {
    let active = true;
    const request = ++sequence.current;
    setResult((current) => ({
      scope,
      data:
        retainKey !== undefined && current.scope === scope
          ? current.data
          : null,
      error: "",
      sequence: current.scope === scope ? current.sequence : 0,
    }));
    const settle = (data: T | null, error: string) => {
      if (!scope.active || (!active && retainKey === undefined)) return;
      setResult((current) => {
        // Slow refreshes may finish after the next tick, but must never rewind data.
        if (current.scope === scope && current.sequence > request)
          return current;
        return {
          scope,
          data: error && current.scope === scope ? current.data : data,
          error,
          sequence: request,
        };
      });
    };
    load()
      .then((data) => settle(data, ""))
      .catch((error) => settle(null, messageOf(error)));
    return () => {
      active = false;
    };
  }, [...deps, refresh, scope]);
  return {
    data: result.scope === scope ? result.data : null,
    error: result.scope === scope ? result.error : "",
    reload: () => setRefresh((n) => n + 1),
  };
}
