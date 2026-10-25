import { useRef, useState } from "react";
import { useApp, messageOf } from "../state/app";
import type { WorldFrame } from "../api/types";
import { repairBuilding, stopDisaster, type DisasterState } from "./client";
import "./disasters.css";
export default function ConditionPanel({
  data,
  frame,
  readOnly,
  refresh,
}: {
  data: DisasterState | null;
  frame: WorldFrame;
  readOnly: boolean;
  refresh: () => Promise<void>;
}) {
  const { client } = useApp();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ signature: string; key: string } | null>(null);
  if (!data) return null;
  const damaged = frame.map.buildings.filter(
    (b) => data.conditions[b.id]?.integrity < 100,
  );
  const active = data.events.filter((e) =>
    ["active", "queued"].includes(e.phase),
  );
  if (!damaged.length && !active.length && !data.repairs.length) return null;
  const act = async (kind: "repair" | "clear" | "stop", id: string) => {
    const signature = JSON.stringify([
      kind,
      id,
      frame.simulation.control_version,
    ]);
    if (pending.current?.signature !== signature)
      pending.current = { signature, key: crypto.randomUUID() };
    setBusy(true);
    setError("");
    try {
      if (kind !== "stop")
        await repairBuilding(
          client,
          frame.simulation.id,
          id,
          frame.simulation.control_version,
          pending.current.key,
          kind,
        );
      else
        await stopDisaster(
          client,
          frame.simulation.id,
          id,
          frame.simulation.control_version,
          pending.current.key,
        );
      pending.current = null;
      await refresh();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="disaster-panel glass">
      <summary>City condition · {damaged.length} damaged buildings</summary>
      <p>
        Intact 100 · Damaged 50–99 · Unsafe 1–49 · Destroyed 0. Capacity follows
        integrity. Hatched cells indicate blocked debris; × marks damage.
      </p>
      {active.map((e) => (
        <p key={e.id}>
          {e.parameters.kind} · {e.parameters.intensity} {e.unit} · {e.phase}{" "}
          {!readOnly && (
            <button disabled={busy} onClick={() => void act("stop", e.id)}>
              Stop disaster
            </button>
          )}
        </p>
      ))}
      <ul>
        {damaged.map((b) => {
          const c = data.conditions[b.id];
          const job = data.repairs.find(
            (j) => j.building_id === b.id && j.status === "pending",
          );
          return (
            <li key={b.id}>
              <strong>{b.name}</strong>
              <div>
                {c.stage} · Integrity {c.integrity.toFixed(1)} / 100
              </div>
              <meter min={0} max={100} value={c.integrity} />
              <div>
                {b.functional ? "Open" : "Closed"} · Capacity {b.capacity}/
                {c.design_capacity} · Occupants {b.occupancy}
              </div>
              <small>Cause: {c.cause_ids.join(", ")}</small>
              {job ? (
                <p>Repair in progress · finishes tick {job.finish_tick}</p>
              ) : (
                !readOnly && (
                  <button
                    disabled={busy}
                    onClick={() => void act("repair", b.id)}
                  >
                    Repair +25 · 10 supplies · 30s
                  </button>
                )
              )}
              {!readOnly && c.integrity < 50 && !job && (
                <button disabled={busy} onClick={() => void act("clear", b.id)}>
                  Clear doorway debris · 2 supplies · 10s
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {!!data.rescue_needs.length && (
        <p role="alert">
          {data.rescue_needs.length} trapped citizens need a clear legal exit.
          Clear debris through repairs after safe evacuation.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <a
        href={`/api/v1/integrations/disasters/v2/simulations/${encodeURIComponent(frame.simulation.id)}/export?revision=${frame.ref.revision}`}
        target="_blank"
        rel="noreferrer"
      >
        Export disaster evidence at this revision
      </a>
    </details>
  );
}
