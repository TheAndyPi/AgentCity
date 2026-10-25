import type { WorldFrame } from "../api/types";
import { pretty } from "../api/defaults";
import { useApp, useQuery } from "../state/app";
import { readBehavior } from "./client";

export default function BehaviorEvidencePanel({
  frame,
  revision,
  id,
  onAgent,
}: {
  frame: WorldFrame;
  revision: number;
  id: string;
  onAgent: (id: string) => void;
}) {
  const { client } = useApp();
  const result = useQuery(
    () => readBehavior(client.transport, frame.simulation.id, revision),
    [client, frame.simulation.id, revision, id],
    `${frame.simulation.id}:${revision}:${id}`,
  );
  const record =
    result.data?.decisions.find((item) => item.id === id) ??
    result.data?.events.find((item) => item.id === id);
  if (result.error) return <p role="alert">{result.error}</p>;
  if (!result.data) return <p role="status">Loading recorded evidence…</p>;
  if (!record)
    return (
      <p role="alert">
        This behavior record is unavailable at revision {revision}.
      </p>
    );
  return (
    <div className="decision-flow" aria-label="Behavior action evidence">
      <h2>{pretty("action" in record ? record.action : record.kind)}</h2>
      <p>
        Tick {record.tick} · Revision {revision}
      </p>
      {"accepted" in record && (
        <span className={`pill ${record.accepted ? "green" : "pink"}`}>
          {record.accepted ? "Accepted" : "Rejected"}
        </span>
      )}
      <section>
        <span>RECORDED CAUSE AND OUTCOME</span>
        <p>{"reason" in record ? record.reason : record.description}</p>
      </section>
      {"effects" in record &&
        Object.entries(record.effects).map(([meter, delta]) => (
          <p key={meter}>
            {pretty(meter)}: {delta >= 0 ? "+" : ""}
            {delta.toFixed(2)}
          </p>
        ))}
      {[record.actor_id, record.target_id]
        .filter((aid): aid is string => Boolean(aid))
        .map((aid) => (
          <button className="list-link" key={aid} onClick={() => onAgent(aid)}>
            {frame.agents.find((a) => a.id === aid)?.name ?? aid}
          </button>
        ))}
    </div>
  );
}
