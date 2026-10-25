import { useEffect, useRef, useState } from "react";
import { useApp } from "../../state/app";
import type { MetricPoint } from "../../api/types";

export function inferMetrics(points: MetricPoint[]) {
  const first = points[0];
  const latest = points.at(-1);
  if (!first || !latest) return null;
  const changes = Object.entries(latest.values).map(([metric, value]) => ({
    metric,
    value,
    delta: value - first.values[metric as keyof typeof first.values],
  }));
  const strongest = [...changes].sort(
    (a, b) => Math.abs(b.delta) - Math.abs(a.delta),
  )[0];
  return {
    latest,
    fromTick: first.tick,
    changes,
    text:
      points.length < 2 || first.tick === latest.tick
        ? "This is your city baseline. Trends appear as the simulation advances."
        : strongest.delta === 0
          ? "City measures are stable."
          : `Largest change: ${strongest.metric.replaceAll("_", " ")} is ${strongest.delta > 0 ? "rising" : "falling"} ${Math.abs(strongest.delta).toFixed(1)} points since tick ${first.tick}.`,
  };
}

export function QuickSummary({
  simulationId,
  revision,
}: {
  simulationId: string;
  revision: number;
}) {
  const { client } = useApp();
  const [result, setResult] = useState<{
    sid: string;
    revision: number;
    points: MetricPoint[];
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const latestRevision = useRef(revision);
  latestRevision.current = revision;
  // Refresh at most every five seconds during live ticks, while retaining useful data.
  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    async function load() {
      if (inFlight) return;
      inFlight = true;
      try {
        const requested = latestRevision.current;
        const { points } = await client.metrics(simulationId, requested);
        if (!cancelled) {
          setResult({ sid: simulationId, revision: requested, points });
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        inFlight = false;
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client, simulationId]);
  const summary =
    result?.sid === simulationId && result.revision <= revision
      ? inferMetrics(result.points)
      : null;
  return (
    <section
      className="observations-snapshot"
      aria-label="City analytics summary"
      aria-live="polite"
    >
      <div className="observations-section-heading">
        <h4>City at a glance</h4>
        {summary && (
          <span className="observations-tick">Tick {summary.latest.tick}</span>
        )}
      </div>
      {summary ? (
        <>
          <p className="observations-insight">{summary.text}</p>
          <table className="observations-metrics">
            <caption>
              City scores out of 100 · change since tick {summary.fromTick}
            </caption>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Now</th>
                <th scope="col">Change</th>
              </tr>
            </thead>
            <tbody>
              {summary.changes.map(({ metric, value, delta }) => (
                <tr key={metric}>
                  <th scope="row">{metric.replaceAll("_", " ")}</th>
                  <td>{value.toFixed(1)}</td>
                  <td
                    className={
                      Math.abs(delta) < 0.05
                        ? "observations-unchanged"
                        : "observations-changed"
                    }
                  >
                    {Math.abs(delta) < 0.05
                      ? "—"
                      : `${delta > 0 ? "+" : ""}${delta.toFixed(1)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="observations-activity">
            <span>
              <b>{summary.latest.cooperation_count}</b> cooperative actions
            </span>
            <span>
              <b>{summary.latest.conflict_count}</b> conflicts
            </span>
          </div>
          <p className="observations-footnote">
            Changes show trends, not what caused them.
          </p>
          {failed && (
            <p className="muted">Showing the last available recorded data.</p>
          )}
        </>
      ) : (
        <p className="muted">
          {failed
            ? "Recorded metrics are temporarily unavailable."
            : "Reading the available city data…"}
        </p>
      )}
    </section>
  );
}
