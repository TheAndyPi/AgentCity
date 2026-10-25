import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useApp } from "../../state/app";
import { ObservationsClient, type Selection } from "./client";
import type {
  Change,
  Changes,
  EventDetail,
  Events,
  Metrics,
  ObservationEvent,
  ObservationStatus,
  TrendPoint,
  Trends,
} from "./schema";
import "./observations.css";

export type ObservationsPanelProps = {
  simulationId: string;
  revision: number;
  readOnly?: boolean;
  agentId?: string;
  eventId?: string;
  onAgent?: (id: string) => void;
  onEvent?: (id: string) => void;
};

export function formatObservation(value: unknown): string {
  if (value === null || value === undefined) return "Unavailable";
  if (typeof value === "number")
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function observationUnit(unit: string): string {
  const labels: Record<string, string> = {
    population_mean_0_100: "Population mean (0–100)",
    directed_mean_0_100: "Directed relationship mean (0–100)",
    recorded_count: "Recorded count",
    recorded_confidence_0_100: "Recorded confidence (0–100)",
  };
  return labels[unit] ?? unit.replaceAll("_", " ");
}

/** Keep gaps unknown: a missing observation never becomes a zero or a connecting line. */
export function trendSegments(points: TrendPoint[]): TrendPoint[][] {
  const segments: TrendPoint[][] = [];
  let current: TrendPoint[] = [];
  for (const point of points) {
    if (point.mean === null) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push(point);
  }
  if (current.length) segments.push(current);
  return segments;
}

export function TrendChart({
  data,
  label,
  onEvent,
}: {
  data: Trends;
  label: string;
  onEvent: (id: string) => void;
}) {
  const titleId = useId();
  const points = data.items;
  if (!points.some((point) => point.mean !== null))
    return (
      <p className="muted">
        No measured values are available for this selection.
      </p>
    );
  const first = points[0].tick;
  const last = Math.max(first + 1, points.at(-1)!.tick);
  const values = points
    .flatMap((point) => [point.min, point.max, point.mean])
    .filter((v): v is number => v !== null);
  const boundedScore = data.unit.endsWith("_0_100");
  const bottom = boundedScore ? 0 : Math.min(0, ...values);
  const top = boundedScore ? 100 : Math.max(bottom + 1, ...values);
  const x = (tick: number) => 39 + (302 * (tick - first)) / (last - first);
  const y = (value: number) => 145 - (120 * (value - bottom)) / (top - bottom);
  return (
    <svg
      className="observations-chart"
      viewBox="0 0 360 180"
      role="img"
      aria-labelledby={titleId}
    >
      <title
        id={titleId}
      >{`${label}, ticks ${first} to ${points.at(-1)!.tick}. Event intervals are shaded. Exact values follow in the data table.`}</title>
      <path
        d="M39 25V145H341M39 85H341M39 25H341"
        className="observations-grid"
      />
      {data.events
        .filter((event) => event.start_tick !== null)
        .map((event) => {
          const start = Math.max(first, event.start_tick!);
          const end = Math.min(last, event.end_tick ?? last);
          if (end < first || start > last) return null;
          const eventLabel = `${event.title}, ${event.status}, ticks ${event.start_tick} to ${event.end_tick ?? "ongoing"}`;
          return (
            <g key={event.event_id}>
              <rect
                x={x(start)}
                y="25"
                width={Math.max(1, x(end) - x(start))}
                height="120"
                className="observations-interval"
              />
              <line
                x1={x(start)}
                x2={x(start)}
                y1="25"
                y2="145"
                className="observations-marker"
              />
              <circle
                cx={x(start)}
                cy="18"
                r="5"
                tabIndex={0}
                role="button"
                aria-label={eventLabel}
                onClick={() => onEvent(event.event_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onEvent(event.event_id);
                  }
                }}
              >
                <title>{eventLabel}</title>
              </circle>
            </g>
          );
        })}
      {trendSegments(points).map((segment, index) => (
        <g key={index}>
          <polygon
            className="observations-range"
            points={[
              ...segment.map((p) => `${x(p.tick)},${y(p.max ?? p.mean!)}`),
              ...[...segment]
                .reverse()
                .map((p) => `${x(p.tick)},${y(p.min ?? p.mean!)}`),
            ].join(" ")}
          />
          <polyline
            className="observations-line"
            points={segment.map((p) => `${x(p.tick)},${y(p.mean!)}`).join(" ")}
          />
        </g>
      ))}
      {points
        .filter((p) => p.mean !== null)
        .map((p) => (
          <circle
            key={`${p.tick}:${p.revision}`}
            cx={x(p.tick)}
            cy={y(p.mean!)}
            r="2.5"
            className="observations-point"
            tabIndex={0}
            aria-label={`Tick ${p.tick}: ${formatObservation(p.mean)}; denominator ${p.denominator}`}
          >
            <title>{`Tick ${p.tick}: ${formatObservation(p.mean)}; range ${formatObservation(p.min)}–${formatObservation(p.max)}; denominator ${p.denominator}`}</title>
          </circle>
        ))}
      <text x="3" y="29">
        {formatObservation(top)}
      </text>
      <text x="3" y="148">
        {formatObservation(bottom)}
      </text>
      <text x="39" y="166">
        {first}
      </text>
      <text x="341" y="166" textAnchor="end">
        {points.at(-1)!.tick} ticks
      </text>
    </svg>
  );
}

function ChangesTable({
  items,
  onAgent,
}: {
  items: Change[];
  onAgent?: (id: string) => void;
}) {
  if (!items.length)
    return <p className="muted">No recorded changes in this selection.</p>;
  return (
    <div className="observations-table">
      <table>
        <caption>Committed changes and their recorded evidence</caption>
        <thead>
          <tr>
            <th scope="col">Tick</th>
            <th scope="col">Change</th>
            <th scope="col">Before → after</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map((change) => (
            <tr key={change.id}>
              <td>
                {change.tick}
                <small>revision {change.revision}</small>
              </td>
              <th scope="row">
                {change.entity_kind} · {change.field}
                <small>
                  {change.agent_id && onAgent ? (
                    <button
                      type="button"
                      onClick={() => onAgent(change.agent_id!)}
                    >
                      {change.agent_id}
                    </button>
                  ) : (
                    change.entity_id
                  )}
                </small>
              </th>
              <td>
                {formatObservation(change.before)} →{" "}
                {formatObservation(change.after)}
              </td>
              <td>
                <details>
                  <summary>
                    {change.link === "explicit"
                      ? "Recorded event link"
                      : "Same time interval"}
                  </summary>
                  <p>
                    {change.event_ids.length
                      ? `Events: ${change.event_ids.join(", ")}`
                      : "No explicit event reference recorded."}
                  </p>
                  <pre>{JSON.stringify(change.evidence, null, 2)}</pre>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventReport({
  detail,
  onEvent,
  onAgent,
}: {
  detail: EventDetail;
  onEvent?: (id: string) => void;
  onAgent?: (id: string) => void;
}) {
  const metrics = [
    ...new Set([
      ...Object.keys(detail.baseline.city),
      ...Object.keys(detail.resolution.city),
      ...Object.keys(detail.followup.city),
    ]),
  ];
  return (
    <section className="observations-event" aria-label="Event measurements">
      <h4>{detail.event.title}</h4>
      <p>
        {detail.event.status} · activation tick{" "}
        {detail.event.start_tick ?? "pending"} · resolution{" "}
        {detail.event.end_tick ?? "pending"}
      </p>
      <p>
        Recorded event links: {detail.change_counts.explicit}. Other changes in
        the observation window: {detail.change_counts.temporal}. Evidence below
        is a bounded sample; the totals cover all recorded changes.
      </p>
      {!detail.followup_complete && (
        <p className="observations-notice">
          Follow-up is partial. The 30 physical ticks after resolution have not
          all been observed; paused cities do not advance this window.
        </p>
      )}
      {detail.overlaps.length > 0 && (
        <p className="observations-notice">
          Overlapping events:{" "}
          {detail.overlaps.map((event, i) => (
            <span key={event.event_id}>
              {i > 0 && ", "}
              {onEvent ? (
                <button type="button" onClick={() => onEvent(event.event_id)}>
                  {event.title}
                </button>
              ) : (
                event.title
              )}
            </span>
          ))}
          . Changes in this interval may have several contributors.
        </p>
      )}
      {(["city", "cohort"] as const).map((scope) => (
        <details key={scope} open={scope === "city"}>
          <summary>
            {scope === "city"
              ? "Citywide measurements"
              : "Fixed activation cohort and survival"}
          </summary>
          <div className="observations-table">
            <table>
              <caption>
                {scope === "city" ? "City" : "Activation cohort"}: baseline,
                resolution and follow-up values; missing values are unavailable.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Before · {detail.baseline.tick ?? "—"}</th>
                  <th scope="col">
                    At resolution · {detail.resolution.tick ?? "—"}
                  </th>
                  <th scope="col">Follow-up · {detail.followup.tick ?? "—"}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ...new Set([
                    ...metrics,
                    ...Object.keys(detail.baseline[scope]),
                    ...Object.keys(detail.resolution[scope]),
                    ...Object.keys(detail.followup[scope]),
                  ]),
                ].map((metric) => (
                  <tr key={metric}>
                    <th scope="row">{metric.replaceAll("_", " ")}</th>
                    {(["baseline", "resolution", "followup"] as const).map(
                      (phase) => (
                        <td key={phase}>
                          {formatObservation(detail[phase][scope][metric])}
                          {detail[phase].denominators?.[scope]?.[metric] !==
                            undefined && (
                            <small>
                              n ={" "}
                              {detail[phase].denominators?.[scope]?.[metric]}
                            </small>
                          )}
                        </td>
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
      {detail.observations.length > 0 && (
        <ul>
          {detail.observations.map((observation) => (
            <li key={observation.id}>
              {observation.text}
              {observation.citation_ids.length > 0 && (
                <small>
                  {" "}
                  Sources:{" "}
                  {observation.citation_ids.map((id, i) => (
                    <span key={id}>
                      {i > 0 && ", "}
                      <a
                        href={`#observation-citation-${encodeURIComponent(id)}`}
                      >
                        {id}
                      </a>
                    </span>
                  ))}
                </small>
              )}
            </li>
          ))}
        </ul>
      )}
      {detail.citations.length > 0 && (
        <details>
          <summary>Observation sources</summary>
          <ul>
            {detail.citations.map((citation) => (
              <li
                key={citation.id}
                id={`observation-citation-${encodeURIComponent(citation.id)}`}
              >
                Tick {citation.tick}, revision {citation.revision}:{" "}
                {citation.description}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>Event change evidence</summary>
        <ChangesTable items={detail.changes} onAgent={onAgent} />
      </details>
    </section>
  );
}

type Loaded = {
  key: string;
  metrics: Metrics;
  trends: Trends;
  events: Events;
  changes: Changes;
  detail: EventDetail | null;
};

export function ObservationsPanel({
  simulationId,
  revision,
  readOnly = false,
  agentId,
  eventId,
  onAgent,
  onEvent,
}: ObservationsPanelProps) {
  const { client } = useApp();
  const observations = useMemo(
    () => new ObservationsClient(client.transport),
    [client.transport],
  );
  const id = useId();
  const container = useRef<HTMLElement>(null);
  const inView = useRef(true);
  const latestRevision = useRef(revision);
  latestRevision.current = revision;
  const [visible, setVisible] = useState(true);
  const [pin, setPin] = useState(revision);
  const [refresh, setRefresh] = useState(0);
  const [metric, setMetric] = useState("health");
  const [selectedAgent, setSelectedAgent] = useState(agentId ?? "");
  const [selectedEvent, setSelectedEvent] = useState(eventId ?? "");
  const [startText, setStartText] = useState("");
  const [endText, setEndText] = useState("");
  const [interval, setIntervalFilter] = useState<{
    start_tick?: number;
    end_tick?: number;
  }>({});
  const [status, setStatus] = useState<ObservationStatus | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pageBusy, setPageBusy] = useState(false);
  const scope = JSON.stringify([simulationId, readOnly, agentId, eventId]);
  const selection: Selection = {
    through_revision: readOnly ? revision : pin,
    ...interval,
    ...(selectedAgent ? { agent_id: selectedAgent } : {}),
    ...(selectedEvent ? { event_id: selectedEvent } : {}),
  };
  const key = JSON.stringify([simulationId, selection, metric]);
  const activeKey = useRef(key);
  activeKey.current = key;
  const data = loaded?.key === key ? loaded : null;

  useEffect(() => {
    setPin(latestRevision.current);
    setSelectedAgent(agentId ?? "");
    setSelectedEvent(eventId ?? "");
    setStartText("");
    setEndText("");
    setIntervalFilter({});
    setStatus(null);
    setLoaded(null);
  }, [scope, agentId, eventId]);
  useEffect(() => {
    const node = container.current;
    const updateVisibility = () =>
      setVisible(inView.current && document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", updateVisibility);
    const observer =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((entries) => {
            inView.current = entries.some((entry) => entry.isIntersecting);
            updateVisibility();
          });
    if (node) observer?.observe(node);
    return () => {
      observer?.disconnect();
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);
  useEffect(() => {
    if (readOnly || !visible || client.mode !== "live") return;
    const timer = window.setInterval(() => {
      setPin(latestRevision.current);
      setRefresh((value) => value + 1);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [readOnly, visible, client.mode]);
  useEffect(() => {
    if (client.mode !== "live" || !visible) return;
    const controller = new AbortController();
    let cancelled = false;
    setBusy(true);
    setError("");
    const selected = JSON.parse(key) as [string, Selection, string];
    const [sid, query, selectedMetric] = selected;
    void (async () => {
      const progress = await observations.status(sid, query, controller.signal);
      if (cancelled) return;
      setStatus(progress);
      if (!progress.enabled || progress.effective_revision === null) {
        setLoaded(null);
        return;
      }
      const [catalog, trend, events, changes, detail] = await Promise.all([
        observations.metrics(sid, query, controller.signal),
        observations.trends(sid, query, selectedMetric, controller.signal),
        observations.events(sid, query, undefined, controller.signal),
        observations.changes(sid, query, undefined, controller.signal),
        query.event_id
          ? observations.event(sid, query, query.event_id, controller.signal)
          : Promise.resolve(null),
      ]);
      if (!cancelled)
        setLoaded({
          key,
          metrics: catalog,
          trends: trend,
          events,
          changes,
          detail,
        });
    })()
      .catch((reason: unknown) => {
        if (!cancelled)
          setError(
            reason instanceof Error
              ? reason.message
              : "Snowflake observations are unavailable.",
          );
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [key, observations, refresh, visible, client.mode]);
  useEffect(() => {
    if (client.mode !== "live") return;
    let cancelled = false;
    void client
      .agents(simulationId, readOnly ? revision : undefined)
      .then((items) => {
        if (!cancelled) setAgents(items.map(({ id, name }) => ({ id, name })));
      })
      .catch(() => {
        if (!cancelled) setAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [client, simulationId, readOnly, readOnly ? revision : undefined]);

  function retry() {
    observations.invalidate();
    setPin(latestRevision.current);
    setRefresh((value) => value + 1);
  }
  function applyInterval() {
    const start = startText === "" ? undefined : Number(startText);
    const end = endText === "" ? undefined : Number(endText);
    if (
      [start, end].some(
        (value) =>
          value !== undefined && (!Number.isSafeInteger(value) || value < 0),
      ) ||
      (start !== undefined && end !== undefined && end < start)
    ) {
      setError(
        "Choose nonnegative whole ticks with the end at or after the start.",
      );
      return;
    }
    setError("");
    setIntervalFilter({ start_tick: start, end_tick: end });
  }
  async function moreChanges() {
    if (!data?.changes.next_after || pageBusy) return;
    setPageBusy(true);
    try {
      const next = await observations.changes(
        simulationId,
        selection,
        data.changes.next_after,
      );
      if (activeKey.current === key)
        setLoaded((previous) =>
          previous?.key === key
            ? {
                ...previous,
                changes: {
                  ...next,
                  items: [...previous.changes.items, ...next.items],
                },
              }
            : previous,
        );
    } catch (reason) {
      if (activeKey.current === key)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not load more changes.",
        );
    } finally {
      setPageBusy(false);
    }
  }
  async function moreEvents() {
    if (!data?.events.next_after || pageBusy) return;
    setPageBusy(true);
    try {
      const next = await observations.events(
        simulationId,
        selection,
        data.events.next_after,
      );
      if (activeKey.current === key)
        setLoaded((previous) =>
          previous?.key === key
            ? {
                ...previous,
                events: {
                  ...next,
                  items: [...previous.events.items, ...next.items],
                },
              }
            : previous,
        );
    } catch (reason) {
      if (activeKey.current === key)
        setError(
          reason instanceof Error
            ? reason.message
            : "Could not load more events.",
        );
    } finally {
      setPageBusy(false);
    }
  }
  const selected = data?.metrics.items.find((item) => item.id === metric);
  const events: ObservationEvent[] = data?.events.items ?? [];
  return (
    <section
      ref={container}
      className="observations-panel"
      aria-labelledby={`${id}-title`}
      aria-busy={busy}
    >
      <div className="snowflake-kicker">Snowflake / recorded evidence</div>
      <h3 id={`${id}-title`}>Observations</h3>
      <p className="muted">
        City trends and changes around events. These are observed changes;
        overlapping events and other activity can contribute.
      </p>
      {client.mode !== "live" ? (
        <p className="observations-notice">
          Snowflake observations require a live city connection. Existing local
          graphs remain available.
        </p>
      ) : (
        <>
          <div className="observations-status" role="status" aria-live="polite">
            {status ? (
              <>
                <strong>
                  {status.state === "disabled"
                    ? "Observations disabled"
                    : status.state === "healthy"
                      ? "Warehouse up to date"
                      : status.state === "backfilling"
                        ? "Backfilling history"
                        : status.state === "lagged"
                          ? "Warehouse catching up"
                          : "Warehouse unavailable"}
                </strong>
                {status.enabled && (
                  <span>
                    {" "}
                    revision{" "}
                    {status.ingested_revision < 0
                      ? "pending"
                      : status.ingested_revision}{" "}
                    / {status.published_revision} · {status.lag_revisions}{" "}
                    revisions behind
                  </span>
                )}
                {status.error_code && <small>{status.error_code}</small>}
              </>
            ) : busy ? (
              "Loading observation status…"
            ) : (
              "Observation status unavailable"
            )}
          </div>
          {status && !status.enabled && (
            <p className="muted">
              Enable observation ingestion on the server to collect warehouse
              trends. Existing local graphs remain available.
            </p>
          )}
          {error && (
            <div role="alert" className="observations-notice">
              {error}{" "}
              <button type="button" onClick={retry}>
                Retry observations
              </button>
            </div>
          )}
          {status?.enabled && (
            <>
              <p className="observations-provenance">
                {readOnly
                  ? "Historical view"
                  : "Refreshes about every 30 seconds while visible"}{" "}
                · requested revision {selection.through_revision} · coverage{" "}
                {data?.trends.coverage.state ?? status.coverage.state}
                {data?.trends.coverage.from_tick !== null &&
                  data?.trends.coverage.from_tick !== undefined && (
                    <>
                      {" "}
                      · ticks {data.trends.coverage.from_tick}–
                      {data.trends.coverage.through_tick ?? "pending"}
                    </>
                  )}
              </p>
              <div className="observations-filters">
                <label htmlFor={`${id}-metric`}>
                  Measure
                  <select
                    id={`${id}-metric`}
                    aria-label="Measure"
                    value={metric}
                    onChange={(e) => setMetric(e.target.value)}
                  >
                    {!data?.metrics.items.some(
                      (item) => item.id === metric,
                    ) && (
                      <option value={metric}>
                        {metric.replaceAll("_", " ")}
                      </option>
                    )}
                    {(data?.metrics.items ?? []).map((item) => (
                      <option
                        key={item.id}
                        value={item.id}
                        disabled={
                          !!selectedAgent &&
                          ["cooperation_count", "conflict_count"].includes(
                            item.id,
                          )
                        }
                      >
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor={`${id}-agent`}>
                  Citizen
                  <select
                    id={`${id}-agent`}
                    aria-label="Citizen"
                    value={selectedAgent}
                    onChange={(e) => {
                      setSelectedAgent(e.target.value);
                      if (
                        e.target.value &&
                        ["cooperation_count", "conflict_count"].includes(metric)
                      )
                        setMetric("health");
                    }}
                  >
                    <option value="">Whole city</option>
                    {selectedAgent &&
                      !agents.some((agent) => agent.id === selectedAgent) && (
                        <option value={selectedAgent}>{selectedAgent}</option>
                      )}
                    {agents.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor={`${id}-event`}>
                  Event
                  <select
                    id={`${id}-event`}
                    aria-label="Event"
                    value={selectedEvent}
                    onChange={(e) => setSelectedEvent(e.target.value)}
                  >
                    <option value="">All events</option>
                    {selectedEvent &&
                      !events.some(
                        (event) => event.event_id === selectedEvent,
                      ) && (
                        <option value={selectedEvent}>{selectedEvent}</option>
                      )}
                    {events.map((event) => (
                      <option key={event.event_id} value={event.event_id}>
                        {event.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor={`${id}-from`}>
                  From tick
                  <input
                    id={`${id}-from`}
                    type="number"
                    min="0"
                    step="1"
                    placeholder="Beginning"
                    value={startText}
                    onChange={(e) => setStartText(e.target.value)}
                  />
                </label>
                <label htmlFor={`${id}-to`}>
                  Through tick
                  <input
                    id={`${id}-to`}
                    type="number"
                    min="0"
                    step="1"
                    placeholder="Latest in revision"
                    value={endText}
                    onChange={(e) => setEndText(e.target.value)}
                  />
                </label>
                <button type="button" onClick={applyInterval}>
                  Apply interval
                </button>
              </div>
              {selectedAgent && onAgent && (
                <button type="button" onClick={() => onAgent(selectedAgent)}>
                  Inspect selected citizen
                </button>
              )}
              {!data && !busy && status.coverage.state === "unavailable" && (
                <p className="muted">
                  No complete warehouse revision is available yet. The
                  simulation can continue while ingestion catches up.
                </p>
              )}
              {data && (
                <>
                  <h4>{selected?.label ?? metric.replaceAll("_", " ")}</h4>
                  <p className="observations-provenance">
                    {observationUnit(data.trends.unit)} ·{" "}
                    {selected?.denominator ?? "See each point's denominator"}
                  </p>
                  <TrendChart
                    data={data.trends}
                    label={selected?.label ?? metric}
                    onEvent={setSelectedEvent}
                  />
                  {data.trends.distribution.length > 0 && (
                    <section
                      aria-label="Recorded distribution"
                      className="observations-distribution"
                    >
                      <h4>
                        {metric.startsWith("relationship")
                          ? "Known relationship pairs"
                          : "Recorded opinion distribution"}
                      </h4>
                      <p className="muted">
                        {metric.startsWith("relationship")
                          ? "Each known pair is counted once. Different directed kinds remain visible together."
                          : "Counts describe existing recorded beliefs and norms."}
                      </p>
                      <ul>
                        {data.trends.distribution.map((item) => (
                          <li key={item.label}>
                            <span>{item.label}</span>
                            <meter
                              aria-label={`${item.label}: ${item.count}`}
                              min={0}
                              max={Math.max(
                                1,
                                ...data.trends.distribution.map((d) => d.count),
                              )}
                              value={item.count}
                            />
                            <b>{item.count}</b>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  <details>
                    <summary>
                      Trend data table · {data.trends.items.length} measured
                      buckets
                    </summary>
                    <div className="observations-table">
                      <table>
                        <caption>
                          {selected?.label ?? metric}: measurements pinned
                          through revision {data.trends.effective_revision};
                          missing values remain unavailable.
                        </caption>
                        <thead>
                          <tr>
                            <th scope="col">Tick</th>
                            <th scope="col">Mean</th>
                            <th scope="col">Min–max</th>
                            <th scope="col">Samples</th>
                            <th
                              scope="col"
                              title="Largest contributing group within the bucket"
                            >
                              Max denominator
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.trends.items.map((point) => (
                            <tr key={`${point.tick}:${point.revision}`}>
                              <th scope="row">{point.tick}</th>
                              <td>{formatObservation(point.mean)}</td>
                              <td>
                                {formatObservation(point.min)}–
                                {formatObservation(point.max)}
                              </td>
                              <td>{point.sample_count}</td>
                              <td>{point.denominator}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                  {data.detail && (
                    <EventReport
                      detail={data.detail}
                      onAgent={onAgent}
                      onEvent={onEvent ?? setSelectedEvent}
                    />
                  )}
                  <details>
                    <summary>
                      Events in this history · {events.length}
                      {data.events.next_after ? "+" : ""}
                    </summary>
                    {events.length ? (
                      <ul>
                        {events.map((event) => (
                          <li key={event.event_id}>
                            <button
                              type="button"
                              onClick={() => setSelectedEvent(event.event_id)}
                            >
                              {event.title}
                            </button>{" "}
                            · {event.status} · tick{" "}
                            {event.start_tick ?? "pending"}
                            {onEvent && (
                              <button
                                type="button"
                                onClick={() => onEvent(event.event_id)}
                              >
                                Inspect event
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">
                        No recorded events in this selection.
                      </p>
                    )}
                    {data.events.next_after && (
                      <button
                        type="button"
                        disabled={pageBusy}
                        onClick={() => void moreEvents()}
                      >
                        {pageBusy ? "Loading events…" : "Load more events"}
                      </button>
                    )}
                  </details>
                  <details>
                    <summary>
                      Agent, relationship and opinion changes ·{" "}
                      {data.changes.items.length}
                      {data.changes.next_after ? "+" : ""}
                    </summary>
                    <ChangesTable
                      items={data.changes.items}
                      onAgent={onAgent}
                    />
                    {data.changes.next_after && (
                      <button
                        type="button"
                        disabled={pageBusy}
                        onClick={() => void moreChanges()}
                      >
                        {pageBusy ? "Loading changes…" : "Load more changes"}
                      </button>
                    )}
                  </details>
                </>
              )}
            </>
          )}
          <button
            type="button"
            className="observations-refresh"
            onClick={retry}
            disabled={busy}
          >
            Refresh observations
          </button>
        </>
      )}
    </section>
  );
}

export default ObservationsPanel;
