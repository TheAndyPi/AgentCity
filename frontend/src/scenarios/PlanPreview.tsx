import {
  Check,
  Clock,
  ShieldAlert,
  Sparkles,
  Users,
  Building2,
} from "lucide-react";
import { pretty } from "../api/defaults";
import type { Plan, PlanResult } from "./schema";

function timingText(t: {
  start_tick: number;
  duration_ticks: number | null;
  repeat_every: number | null;
  repeat_count: number | null;
}) {
  const parts = [
    t.start_tick ? `starts at tick +${t.start_tick}` : "starts immediately",
  ];
  if (t.duration_ticks) parts.push(`lasts ${t.duration_ticks} ticks`);
  if (t.repeat_every)
    parts.push(`repeats every ${t.repeat_every} ticks ×${t.repeat_count ?? 1}`);
  return parts.join(" · ");
}

export function PlanPreview({
  result,
  plan,
}: {
  result: PlanResult;
  plan: Plan | null;
}) {
  const summary = result.summary;
  const text = (key: string) =>
    plan && typeof plan[key] === "string" ? (plan[key] as string) : "";
  return (
    <div className="preview-card plan-preview">
      <div className="preview-title">
        <Sparkles size={19} />
        <span>
          {plan?.source === "manual"
            ? "COMPOSED SCENARIO"
            : "INTERPRETED SCENARIO"}
        </span>
      </div>
      {plan && (
        <section>
          <h4>Scenario</h4>
          <h3>{text("title")}</h3>
          <p>{text("description")}</p>
          <p className="muted">
            {pretty(text("category"))} ·{" "}
            {text("duration") === "permanent"
              ? "Permanent change"
              : "Temporary change"}
          </p>
          {text("agent_knowledge") && (
            <p className="helper-text">
              Who knows what: {text("agent_knowledge")}
            </p>
          )}
        </section>
      )}
      {summary && (
        <>
          <section>
            <h4>Interpreted changes</h4>
            {summary.operations.map((o) => (
              <div className="event-effect" key={o.id}>
                <Check size={14} />
                <div>
                  <strong>{o.label}</strong>
                  <small className="muted"> · {timingText(o.timing)}</small>
                  {o.rationale && <p className="muted">{o.rationale}</p>}
                </div>
              </div>
            ))}
            <p className="helper-text">
              Citizens are not told how to react. Each one decides from their
              own situation, knowledge and relationships.
            </p>
          </section>
          <section>
            <h4>Affected systems</h4>
            <div className="scenario-prop-list">
              {summary.affected_systems.map((s) => (
                <span key={s}>{pretty(s)}</span>
              ))}
            </div>
            <div className="preview-facts">
              <span>
                <Users size={15} />
                {summary.affected_agent_count} citizens
              </span>
              <span>
                <Building2 size={15} />
                {summary.affected_building_count} buildings
              </span>
              <span>
                <Clock size={15} />
                {summary.measurement_ticks} ticks measured
              </span>
            </div>
          </section>
          <section>
            <h4>Measurements</h4>
            <ul className="plan-metrics">
              {summary.metrics.map((m) => (
                <li key={m.id}>{m.description}</li>
              ))}
            </ul>
          </section>
        </>
      )}
      {(summary?.warnings ?? result.warnings).map((w, i) => (
        <p className="helper-text" key={i}>
          {w}
        </p>
      ))}
      {result.errors.length > 0 && (
        <div className="warning">
          <ShieldAlert size={18} />
          <div>
            <strong>This plan needs changes before it can run</strong>
            {result.errors.map((e, i) => (
              <p key={i}>{e}</p>
            ))}
          </div>
        </div>
      )}
      {result.unsupported.length > 0 && (
        <div className="warning">
          <ShieldAlert size={18} />
          <div>
            <strong>
              {result.status === "ready"
                ? "Not simulated"
                : "This scenario cannot be simulated"}
            </strong>
            {result.unsupported.map((u, i) => (
              <p key={i}>{u}</p>
            ))}
          </div>
        </div>
      )}
      {result.clarification && (
        <div className="warning">
          <ShieldAlert size={18} />
          <div>
            <strong>More detail needed</strong>
            <p>{result.clarification}</p>
          </div>
        </div>
      )}
    </div>
  );
}
