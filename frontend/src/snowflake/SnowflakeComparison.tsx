import { useEffect, useMemo, useRef, useState } from "react";
import { SnowflakeClient } from "./client";
import type { Comparison, ComparisonRequest } from "./schema";
import "./comparison.css";

export function SnowflakeComparison({
  enabled,
  a,
  b,
  client: suppliedClient,
}: {
  enabled: boolean;
  a: ComparisonRequest["a"];
  b: ComparisonRequest["b"] | null;
  client?: SnowflakeClient;
}) {
  const client = useMemo(
    () => suppliedClient ?? new SnowflakeClient(),
    [suppliedClient],
  );
  const [question, setQuestion] = useState(
    "What recorded differences accompany lower cooperation in B?",
  );
  const [operation, setOperation] = useState<{
    body: ComparisonRequest;
    key: string;
  } | null>(null);
  const [data, setData] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const selection = JSON.stringify([a, b, enabled]);
  useEffect(() => {
    generation.current++;
    setOperation(null);
    setData(null);
    setBusy(false);
    setError("");
    return () => {
      generation.current++;
    };
  }, [selection]);
  if (!enabled)
    return (
      <p className="muted">
        Snowflake comparison is disabled. The history chart remains available.
      </p>
    );
  async function run(retry: boolean) {
    if (!b || busy) return;
    const op =
      retry && operation
        ? operation
        : {
            body: { a: { ...a }, b: { ...b }, question },
            key: crypto.randomUUID(),
          };
    const current = ++generation.current;
    setOperation(op);
    setBusy(true);
    setError("");
    setData(null);
    try {
      const value = await client.compare(op.body, op.key);
      if (current === generation.current) setData(value);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "Comparison unavailable");
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  return (
    <section
      className="snowflake-comparison"
      aria-label="Snowflake evidence comparison"
    >
      <div className="snowflake-kicker">History lab / recorded evidence</div>
      <h3>What changed between these histories?</h3>
      <p>
        Both revisions are pinned before retrieval. Each result keeps its
        original values and sources.
      </p>
      <label>
        Comparison question
        <textarea
          maxLength={500}
          value={question}
          disabled={busy || !!error}
          onChange={(e) => setQuestion(e.target.value)}
        />
      </label>
      <button
        className="button primary"
        disabled={!b || busy || !question.trim() || !!error}
        onClick={() => void run(false)}
      >
        {busy ? "Retrieving evidence…" : "Compare pinned histories"}
      </button>
      {!b && <p>Choose another history to compare.</p>}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button
            className="button"
            disabled={busy}
            onClick={() => void run(true)}
          >
            Retry same comparison
          </button>{" "}
          <button
            className="button"
            disabled={busy}
            onClick={() => {
              setError("");
              setOperation(null);
            }}
          >
            Start new comparison
          </button>
        </div>
      )}
      {data && (
        <div aria-live="polite">
          <div className="snowflake-sources">
            <span>
              {data.data_source === "snowflake"
                ? "Snowflake read-back"
                : "Local export · deterministic fallback"}
            </span>
            <span>
              {data.explanation.source === "cortex_selection"
                ? "Cortex selected verified facts"
                : "Cortex unavailable · deterministic comparison"}
            </span>
          </div>
          <dl className="snowflake-pins">
            {(["a", "b"] as const).map((side) => (
              <div key={side}>
                <dt>History {side.toUpperCase()}</dt>
                <dd>
                  {data[side].simulation_id}
                  <br />
                  Revision {data[side].revision} · tick{" "}
                  {data[side].endpoint_tick}
                  <br />
                  {data[side].sim_time_seconds} simulated seconds
                  <br />
                  Parent: {data[side].parent_simulation_id ?? "none"}
                  {data[side].fork_ref &&
                    ` · fork ${JSON.stringify(data[side].fork_ref)}`}
                </dd>
              </div>
            ))}
          </dl>
          <p>
            {data.horizon === "unequal_endpoint_ticks"
              ? "Unequal horizons: each endpoint uses its own tick; counts are not time-normalized."
              : "Equal endpoint ticks."}{" "}
            Lineage: {data.lineage}.
          </p>
          <div className="snowflake-table">
            <table>
              <caption>
                Exact recorded endpoint values · difference = B minus A
              </caption>
              <thead>
                <tr>
                  <th>Measure</th>
                  <th>A</th>
                  <th>B</th>
                  <th>Difference</th>
                </tr>
              </thead>
              <tbody>
                {data.differences.map((d) => (
                  <tr key={d.metric}>
                    <th scope="row">{d.metric}</th>
                    <td>{d.a ?? "Unavailable"}</td>
                    <td>{d.b ?? "Unavailable"}</td>
                    <td>{d.delta_b_minus_a ?? "Unavailable"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.explanation.reason && (
            <p role="status">{data.explanation.reason}</p>
          )}
          <ul>
            {data.explanation.observations.map((o) => (
              <li key={o.fact_id}>
                {o.text}
                {o.citation_ids.map((id) => (
                  <a key={id} href={`#snowflake-${id}`}>
                    {" "}
                    [{id}]
                  </a>
                ))}
              </li>
            ))}
          </ul>
          <details>
            <summary>
              Inspect recorded evidence ({data.citations.length})
            </summary>
            {data.citations.length === 0 && (
              <p>
                No event or decision evidence is available in this selection.
              </p>
            )}
            <ul>
              {data.citations.map((c) => (
                <li key={c.id} id={`snowflake-${c.id}`}>
                  <a href={c.url} target="_blank" rel="noreferrer">
                    {c.id}
                  </a>{" "}
                  · tick {c.tick} · revision {c.revision}: {c.excerpt}
                </li>
              ))}
            </ul>
          </details>
          <p className="snowflake-caution">{data.limitations.join(" ")}</p>
        </div>
      )}
    </section>
  );
}
