import { useMemo } from "react";
import { ArrowRight, ChevronRight } from "lucide-react";
import { useApp, useQuery } from "../state/app";
import { ApiError } from "../api/client";
import { pretty } from "../api/defaults";
import { ScenarioEngineClient } from "./client";
import type { Trace } from "./schema";

export function useEngine() {
  const { client } = useApp();
  return useMemo(() => new ScenarioEngineClient(client.transport), [client]);
}

const missing = (error: unknown) =>
  error instanceof ApiError && error.code === "NOT_FOUND";

function format(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

const percentMetrics = new Set([
  "transit_usage",
  "car_usage",
  "walking_trips",
  "policy_compliance",
  "service_access",
]);
function metricValue(id: string, value: unknown) {
  return typeof value === "number" && percentMetrics.has(id)
    ? `${Math.round(value * 100)}%`
    : format(value);
}

export function TraceCard({
  trace,
  onAgent,
  names,
}: {
  trace: Trace;
  onAgent?: (id: string) => void;
  names?: Record<string, string>;
}) {
  return (
    <details className="reason trace-card">
      <summary>
        <span>
          <small className="muted">Tick {trace.tick}</small> {trace.title}
        </span>
        <ChevronRight size={15} />
      </summary>
      {trace.observations.length > 0 && (
        <>
          <h5>Observed</h5>
          <ul>
            {trace.observations.map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ul>
        </>
      )}
      {trace.candidates.length > 0 && (
        <>
          <h5>Options weighed</h5>
          <ul>
            {trace.candidates.map((c, i) => (
              <li key={i}>
                {c.action === trace.selected ? (
                  <b>{String(c.label)}</b>
                ) : (
                  String(c.label)
                )}{" "}
                <small className="muted">score {format(c.score)}</small>
              </li>
            ))}
          </ul>
        </>
      )}
      {trace.motivation && (
        <p>
          <b>Why:</b> {trace.motivation}
        </p>
      )}
      {trace.changes.length > 0 && (
        <>
          <h5>State changes</h5>
          <ul>
            {trace.changes.slice(0, 8).map((c, i) => (
              <li key={i}>
                {names?.[String(c.entity_id)] ?? String(c.entity_id)} ·{" "}
                {pretty(String(c.field))}: {format(c.before)} →{" "}
                {format(c.after)}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="evidence">
        {trace.agent_id && onAgent && (
          <button onClick={() => onAgent(trace.agent_id!)}>
            {names?.[trace.agent_id] ?? "Citizen"} <ArrowRight size={12} />
          </button>
        )}
        {trace.affected_ids.length > 0 && (
          <small>
            Affected:{" "}
            {trace.affected_ids
              .slice(0, 6)
              .map((id) => names?.[id] ?? id)
              .join(", ")}
          </small>
        )}
        {trace.memory_ids.length > 0 && (
          <small>Related memories: {trace.memory_ids.join(", ")}</small>
        )}
      </div>
    </details>
  );
}

export function ScenarioAnalysis({
  simulationId,
  eventId,
  revision,
  names,
  onAgent,
}: {
  simulationId: string;
  eventId: string;
  revision: number;
  names: Record<string, string>;
  onAgent: (id: string) => void;
}) {
  const engine = useEngine();
  const r = useQuery(
    () =>
      engine.available
        ? engine.event(simulationId, eventId, revision)
        : Promise.resolve(null),
    [simulationId, eventId, revision],
    `${simulationId}:${eventId}`,
  );
  if (!engine.available || missing(r.error) || (!r.data && !r.error))
    return null;
  if (!r.data)
    return <p className="muted">Scenario analysis is unavailable right now.</p>;
  const a = r.data;
  const metrics = (a.plan.metrics as string[] | undefined) ?? [];
  return (
    <section className="scenario-analysis">
      <h4 className="panel-label">INTERPRETED CHANGES</h4>
      {a.operations.map((o) => (
        <p className="event-effect" key={o.id}>
          {o.label}
        </p>
      ))}
      <h4 className="panel-label">MEASURED OUTCOMES</h4>
      <table className="analysis-table">
        <thead>
          <tr>
            <th>Measure</th>
            <th>At start</th>
            <th>{a.status === "resolved" ? "At end" : "Now"}</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m}>
              <td>{pretty(m)}</td>
              <td>{metricValue(m, a.baseline[m])}</td>
              <td>{metricValue(m, a.current?.[m])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {a.baseline.habit_basis === true && (
        <p className="helper-text">
          Travel shares at the start are the citizens’ habitual modes; later
          values are recorded trips.
        </p>
      )}
      {a.findings.length > 0 && (
        <>
          <h4 className="panel-label">FINDINGS</h4>
          {a.findings.map((f, i) => (
            <article className="memory-card" key={i}>
              <p>{f.text}</p>
            </article>
          ))}
        </>
      )}
      <h4 className="panel-label">
        CITIZEN DECISIONS{" "}
        <small className="muted">({a.decision_count} recorded)</small>
      </h4>
      {a.decisions.length ? (
        a.decisions.map((t) => (
          <TraceCard key={t.id} trace={t} names={names} onAgent={onAgent} />
        ))
      ) : (
        <p className="muted">No citizen has reacted yet.</p>
      )}
      <h4 className="panel-label">WORLD CHANGES</h4>
      {a.operation_traces.map((t) => (
        <TraceCard key={t.id} trace={t} names={names} />
      ))}
    </section>
  );
}

export function AgentSystemsPanel({
  simulationId,
  agentId,
  revision,
  names,
  onAgent,
}: {
  simulationId: string;
  agentId: string;
  revision: number;
  names: Record<string, string>;
  onAgent: (id: string) => void;
}) {
  const engine = useEngine();
  const r = useQuery(
    () =>
      engine.available
        ? engine.traces(simulationId, agentId, revision)
        : Promise.resolve(null),
    [simulationId, agentId, revision],
    `${simulationId}:${agentId}`,
  );
  const s = r.data?.systems;
  if (!engine.available || !r.data || !s) return null;
  return (
    <section className="agent-systems">
      <h4 className="panel-label">CITY LIFE</h4>
      <div className="overview-counts">
        <span>
          <strong>{s.wallet.toFixed(1)}</strong>credits
        </span>
        <span>
          <strong>{pretty(s.income)}</strong>income
        </span>
        <span>
          <strong>{Math.round(s.institutional_trust)}</strong>trust in
          institutions
        </span>
      </div>
      <p>
        Usually travels{" "}
        {s.habit === "walk"
          ? "on foot"
          : s.habit === "car"
            ? "by car"
            : "by transit"}
        {s.owns_car ? " · owns a car" : ""} ·{" "}
        {s.renter ? "renter" : "homeowner"} · housing {pretty(s.housing_status)}
      </p>
      {s.organizations.length > 0 && (
        <p>Member of {s.organizations.map((o) => o.name).join(", ")}</p>
      )}
      {Object.keys(s.norms).length > 0 && (
        <p>Follows: {Object.keys(s.norms).map(pretty).join(", ")}</p>
      )}
      {s.beliefs.length > 0 && (
        <>
          <h4 className="panel-label">WHAT THEY HEARD</h4>
          {s.beliefs.map((b, i) => (
            <article className="memory-card" key={i}>
              <p>{String(b.message)}</p>
              <small className="muted">
                {pretty(String(b.channel))} · confidence {format(b.confidence)}
              </small>
            </article>
          ))}
        </>
      )}
      {r.data.traces.length > 0 && (
        <>
          <h4 className="panel-label">DECISION TRACES</h4>
          {r.data.traces.slice(0, 12).map((t) => (
            <TraceCard key={t.id} trace={t} names={names} onAgent={onAgent} />
          ))}
        </>
      )}
    </section>
  );
}

const POLICY_ROWS: [string, string, string][] = [
  ["transportation", "transit_fare", "Transit fare"],
  ["transportation", "car_trip_cost", "Car trip cost"],
  ["public_services", "hospital_funding", "Hospital funding"],
  ["housing", "rent_level", "Rent level"],
  ["taxation", "business_tax_rate", "Business tax"],
  ["taxation", "household_tax_rate", "Household tax"],
  ["business", "price_level", "Shop prices"],
];

export function CitySystemsPanel({
  simulationId,
  revision,
  onEvent,
}: {
  simulationId: string;
  revision: number;
  onEvent: (id: string) => void;
}) {
  const engine = useEngine();
  const r = useQuery(
    () =>
      engine.available
        ? engine.state(simulationId, revision)
        : Promise.resolve(null),
    [simulationId, revision],
    simulationId,
  );
  const s = r.data;
  if (!engine.available || !s?.enabled) return null;
  const live = s.live ?? {};
  return (
    <section className="city-systems">
      <h4 className="panel-label">CITY SYSTEMS</h4>
      <div className="overview-counts">
        <span>
          <strong>{s.treasury.toFixed(0)}</strong>treasury credits
        </span>
        <span>
          <strong>{metricValue("transit_usage", live.transit_usage)}</strong>
          transit trips
        </span>
        <span>
          <strong>{format(live.financial_strain)}</strong>under financial strain
        </span>
      </div>
      <table className="analysis-table">
        <tbody>
          {POLICY_ROWS.map(([domain, field, label]) => (
            <tr key={field}>
              <td>{label}</td>
              <td>{format(s.policy[domain]?.[field])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {s.closed_buildings.length > 0 && (
        <p className="warning">
          Closed: {s.closed_buildings.map((b) => b.name).join(", ")}
        </p>
      )}
      {s.organizations
        .filter((o) => o.active)
        .map((o) => (
          <p key={o.id}>
            {o.name} · {o.members} members
          </p>
        ))}
      {s.plans.map((p) => (
        <button
          className="list-link"
          key={p.event_id}
          onClick={() => onEvent(p.event_id)}
        >
          <span>
            {p.title} · {pretty(p.status)}
          </span>
          <ArrowRight size={14} />
        </button>
      ))}
    </section>
  );
}
