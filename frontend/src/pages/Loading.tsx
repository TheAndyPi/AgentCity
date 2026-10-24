import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Check, Settings2 } from "lucide-react";
import { Ambient, Brand, Button, ErrorBox } from "../components/ui";
import gearImage from "../assets/gear.png";
import { useApp, messageOf } from "../state/app";
import type { Simulation } from "../api/types";
export default function Loading() {
  const { id } = useParams();
  const { client } = useApp();
  const navigate = useNavigate();
  const [s, setS] = useState<Simulation | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const sim = await client.simulation(id!);
        if (!active) return;
        setS(sim);
        if (sim.status === "failed") return;
        if (sim.status !== "initializing") {
          navigate(`/simulations/${id}`, { replace: true });
          return;
        }
        timer = setTimeout(poll, client.mode === "mock" ? 650 : 1000);
      } catch (e) {
        if (active) setError(messageOf(e));
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [client, id, navigate]);
  const progress = s?.initialization.progress ?? 0;
  return (
    <div className="loading-page">
      <Ambient />
      <Link to="/" aria-label="AgentCity home" className="loading-brand">
        <Brand />
      </Link>
      <main>
        <div className="loading-gears" aria-hidden="true">
          <img src={gearImage} alt="" />
          <img src={gearImage} alt="" />
          <img src={gearImage} alt="" />
        </div>
        <h1>
          {progress < 10
            ? "Getting your simulation ready…"
            : progress < 80
              ? (s?.initialization.message ?? "Initializing…")
              : "Almost there!"}
        </h1>
        <div className="progress-meta">
          <span>{s?.name ?? "Your simulation"}</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <progress
          aria-label="Initialization progress"
          max={100}
          value={progress}
        />
        <div className="loading-stages">
          {["map", "population", "relationships", "persistence"].map(
            (stage, i) => (
              <span
                key={stage}
                className={progress > [20, 45, 65, 90][i] ? "done" : ""}
              >
                {progress > [20, 45, 65, 90][i] ? (
                  <Check size={13} />
                ) : (
                  <Settings2 size={13} />
                )}{" "}
                {stage}
              </span>
            ),
          )}
        </div>
        {(error || s?.status === "failed") && (
          <>
            <ErrorBox
              error={
                error ||
                s?.initialization.error?.message ||
                "Initialization failed."
              }
            />
            <Button
              onClick={() =>
                navigate("/simulations/new", { state: { config: s?.config } })
              }
            >
              Return to retained configuration
            </Button>
          </>
        )}
      </main>
    </div>
  );
}
