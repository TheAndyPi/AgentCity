import { useRef, useState } from "react";
import { ArrowRight, GitBranch, CheckCircle2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Modal, Busy, ErrorBox, Button } from "./ui";
import { useApp, useQuery, messageOf } from "../state/app";
import { metricLabels } from "../api/defaults";
import { metricDelta } from "../api/format";
import type { EventReport, Metric, Simulation } from "../api/types";
export function ReportMetrics({ report }: { report: EventReport }) {
  return (
    <div className="report-metrics">
      <div className="report-row report-labels">
        <span>Community measure</span>
        <span>Before</span>
        <span>After</span>
        <span>Change</span>
      </div>
      {(Object.keys(metricLabels) as Metric[]).map((k) => (
        <div className="report-row" key={k}>
          <span>{metricLabels[k]}</span>
          <span>{report.before[k].toFixed(2)}</span>
          <strong>{report.after[k].toFixed(2)}</strong>
          <span
            className={
              (k === "stress" ? report.delta[k] < 0 : report.delta[k] > 0)
                ? "positive"
                : report.delta[k] === 0
                  ? ""
                  : "negative"
            }
          >
            {metricDelta(report.delta[k])}
          </span>
        </div>
      ))}
    </div>
  );
}
export default function OutcomeDialog({
  simulation,
  eventId,
  onUpdated,
}: {
  simulation: Simulation;
  eventId: string;
  onUpdated: () => Promise<void>;
}) {
  const { client } = useApp(),
    navigate = useNavigate();
  const report = useQuery(
    () => client.report(simulation.id, eventId, simulation.revision),
    [simulation.id, eventId, simulation.revision],
    `${simulation.id}:${eventId}`,
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [expandedEvidence, setExpandedEvidence] = useState<number | null>(null);
  const ackKey = useRef(crypto.randomUUID()),
    branchKey = useRef(crypto.randomUUID());
  const acknowledge = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await client.command(
        simulation,
        { type: "acknowledge_outcome", event_id: eventId, resume: true },
        ackKey.current,
      );
      await onUpdated();
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  };
  const undo = async () => {
    if (!report.data) return;
    setBusy(true);
    try {
      const r = await client.branch(
        simulation.id,
        `${simulation.name.slice(0, 55)} · before event`,
        {
          kind: "snapshot",
          snapshot_id: report.data.event.pre_event_snapshot_id,
        },
        branchKey.current,
      );
      navigate(`/simulations/${r.simulation.id}`);
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Event outcome"
      eyebrow="Simulation paused"
      onClose={() => void acknowledge()}
      busy={busy}
      wide
    >
      {report.error ? (
        <ErrorBox error={report.error} retry={report.reload} />
      ) : !report.data ? (
        <Busy text="Reading the recorded outcome…" />
      ) : (
        <>
          <div className="outcome-title">
            <CheckCircle2 size={22} />
            <div>
              <h3>{report.data.event.title}</h3>
              <p>{report.data.event.summary}</p>
            </div>
          </div>
          <ReportMetrics report={report.data} />
          <div className="outcome-counts">
            <div>
              <strong>{report.data.evacuated_count}</strong>
              <span>reached safety</span>
            </div>
            <div>
              <strong>{report.data.conflicts}</strong>
              <span>conflicts recorded</span>
            </div>
            <div>
              <strong>{report.data.resources_consumed}</strong>
              <span>units consumed</span>
            </div>
          </div>
          <h4>Recorded consequences</h4>
          {report.data.consequences.length ? (
            report.data.consequences.map((c, i) => (
              <button
                className="evidence-block"
                key={i}
                disabled={busy}
                onClick={() =>
                  setExpandedEvidence(expandedEvidence === i ? null : i)
                }
              >
                {c.text}
                {expandedEvidence === i && (
                  <span className="evidence-details">
                    {c.evidence.description} · Events:{" "}
                    {c.evidence.event_ids.join(", ") || "none"} · Decisions:{" "}
                    {c.evidence.decision_ids.join(", ") || "none"} · Memories:{" "}
                    {c.evidence.memory_ids.join(", ") || "none"}
                  </span>
                )}
                <span>
                  View evidence <ArrowRight size={13} />
                </span>
              </button>
            ))
          ) : (
            <p className="muted">No recorded consequences are available.</p>
          )}
          <div className="lessons">
            <h4>What the community learned</h4>
            {report.data.community_lessons.map((c, i) => (
              <p key={i}>{c.text}</p>
            ))}
            {!report.data.community_lessons.length && (
              <p className="muted">
                No community lessons were recorded for this event.
              </p>
            )}
          </div>
          {report.data.suggested_preparations.length > 0 && (
            <div className="suggestions">
              <h4>Ideas for your next experiment</h4>
              <small>Suggestions, separate from measured results.</small>
              {report.data.suggested_preparations.map((s, i) => (
                <p key={i}>↗ {s}</p>
              ))}
            </div>
          )}
          <p className="helper-text">
            Changes describe this event’s recorded interval; they do not
            establish causation.
          </p>
          {error && <ErrorBox error={error} />}
          <div className="modal-actions">
            <Button
              kind="secondary"
              disabled={busy}
              onClick={() => void undo()}
            >
              <GitBranch size={16} />
              Undo event, open restored copy
            </Button>
            <Button disabled={busy} onClick={() => void acknowledge()}>
              Continue
              <ArrowRight size={16} />
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}
