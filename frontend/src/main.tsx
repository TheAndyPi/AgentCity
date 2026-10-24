import React, { Suspense, lazy, Component, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  RouterProvider,
  Outlet,
  Link,
  useLocation,
} from "react-router-dom";
import { AgentCityClient, LiveTransport } from "./api/client";
import { AppProvider } from "./state/app";
import { Busy } from "./components/ui";
import Landing from "./pages/Landing";
import "./styles.css";
const Setup = lazy(() => import("./pages/Setup")),
  Loading = lazy(() => import("./pages/Loading")),
  Simulation = lazy(() => import("./pages/Simulation")),
  History = lazy(() => import("./pages/History")),
  Settings = lazy(() => import("./pages/Settings")),
  Templates = lazy(() => import("./pages/Templates")),
  About = lazy(() => import("./pages/About"));
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  state: { error: string | null } = { error: null };
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  render() {
    return this.state.error ? (
      <div className="city-connecting">
        <h1>This view needs a fresh start.</h1>
        <p>{this.state.error}</p>
        <a href="/" className="button primary">
          Return home
        </a>
      </div>
    ) : (
      this.props.children
    );
  }
}
function ScrollReset() {
  const location = useLocation();
  React.useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return null;
}
const root = createRoot(document.getElementById("root")!);
let disposed = false;
if (import.meta.hot)
  import.meta.hot.dispose(() => {
    disposed = true;
    root.unmount();
  });
async function start() {
  const mode = import.meta.env.VITE_DATA_MODE ?? "live";
  const transport =
    mode === "mock"
      ? new (await import("./api/mock")).MockTransport()
      : new LiveTransport();
  if (disposed) return;
  const client = new AgentCityClient(transport);
  const router = createBrowserRouter([
    {
      element: (
        <>
          <ScrollReset />
          <Suspense
            fallback={
              <div className="city-connecting">
                <Busy text="Opening AgentCity…" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </>
      ),
      children: [
        { path: "/", element: <Landing /> },
        { path: "/simulations/new", element: <Setup /> },
        { path: "/simulations/:id/loading", element: <Loading /> },
        { path: "/simulations/:id", element: <Simulation /> },
        { path: "/simulations", element: <History /> },
        { path: "/settings", element: <Settings /> },
        { path: "/templates", element: <Templates /> },
        { path: "/about", element: <About /> },
        {
          path: "*",
          element: (
            <div className="city-connecting">
              <h1>This street doesn’t exist yet.</h1>
              <Link to="/" className="button primary">
                Return home
              </Link>
            </div>
          ),
        },
      ],
    },
  ]);
  root.render(
    <ErrorBoundary>
      <AppProvider client={client}>
        <RouterProvider router={router} />
      </AppProvider>
    </ErrorBoundary>,
  );
}
void start();
