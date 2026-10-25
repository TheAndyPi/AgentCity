import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  X,
  Users,
  Heart,
  Shield,
  MessageSquare,
  Target,
  Eye,
  Navigation,
  GitBranch,
  ChevronRight,
} from "lucide-react";
import { useApp, useQuery, messageOf } from "../state/app";
import { Busy, ErrorBox, Empty, Button, Field, Slider } from "./ui";
import { colors, metricLabels, pretty } from "../api/defaults";
import type {
  AgentDetail,
  CommandBody,
  Decision,
  Evidence,
  Metric,
  WorldFrame,
} from "../api/types";
import type { Overlay } from "../world/World";
import * as S from "../api/schemas";
import Narration from "./Narration";
import { SnowflakeComparison } from "../snowflake/SnowflakeComparison";
import { SnowflakeClient } from "../snowflake/client";
import {
  AgentSystemsPanel,
  CitySystemsPanel,
  ScenarioAnalysis,
} from "../scenarios/Insights";
import { Conversations, Personality, TraitsRoster } from "./LifePanels";
import { ReportMetrics } from "./OutcomeDialog";
export type DrawerNode =
  | { type: "search" }
  | { type: "traits" }
  | { type: "agent"; id: string }
  | { type: "decision"; id: string }
  | { type: "events" }
  | { type: "event"; id: string }
  | { type: "overview" }
  | { type: "overlays" }
  | { type: "agents" }
  | { type: "feed" }
  | { type: "compare"; otherId?: string };
const titles = {
  search: "Agent traits",
  traits: "Agent traits",
  agent: "A closer look",
  decision: "Why this action",
  events: "City chronicle",
  event: "A turning point",
  overview: "The bigger picture",
  overlays: "A different perspective",
  agents: "Bring someone new",
  feed: "Conversations",
  compare: "Two paths, one beginning",
};
export default function Drawer({
  stack,
  frame,
  revision,
  onPush,
  onBack,
  onClose,
  onCommand,
  overlay,
  setOverlay,
  hazards,
  setHazards,
  follow,
  setFollow,
  readOnly,
  onWatch,
}: {
  readOnly: boolean;
  onWatch?: (ids: string[], interactionId?: string) => void;
  stack: DrawerNode[];
  frame: WorldFrame;
  revision: number;
  onPush: (n: DrawerNode) => void;
  onBack: () => void;
  onClose: () => void;
  onCommand: (c: CommandBody) => Promise<void>;
  overlay: Overlay;
  setOverlay: (o: Overlay) => void;
  hazards: boolean;
  setHazards: (b: boolean) => void;
  follow: string | null;
  setFollow: (id: string | null) => void;
}) {
  const top = stack[stack.length - 1];
  const queryScope = JSON.stringify([
    frame.simulation.id,
    readOnly ? revision : "live",
    top.type,
  ]);
  const ref = useRef<HTMLElement>(null),
    opener = useRef<HTMLElement | null>(document.activeElement as HTMLElement);
  useEffect(() => {
    ref.current?.focus();
    return () => opener.current?.focus();
  }, []);
  return (
    <aside
      className="drawer"
      role="complementary"
      aria-label={titles[top.type]}
      tabIndex={-1}
      ref={ref}
    >
      <header className="drawer-header">
        <button
          className="icon-button"
          onClick={onBack}
          aria-label={
            stack.length > 1 ? "Back to previous panel" : "Close panel"
          }
        >
          <ArrowLeft size={19} />
        </button>
        <div>
          <div className="eyebrow">
            {top.type === "agent" ? "Citizen" : "Simulation"}
          </div>
          <h2>{titles[top.type]}</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close panel"
        >
          <X size={19} />
        </button>
      </header>
      <div className="drawer-scroll">
        {!["search", "traits", "feed"].includes(top.type) && (
          <div className="revision-label">Tick {frame.ref.tick}</div>
        )}
        {top.type === "search" || top.type === "traits" ? (
          <TraitsRoster
            frame={frame}
            revision={revision}
            onAgent={(id) => onPush({ type: "agent", id })}
          />
        ) : top.type === "agent" ? (
          <AgentInspector
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            id={top.id}
            onPush={onPush}
            onCommand={onCommand}
            follow={follow}
            setFollow={setFollow}
            readOnly={readOnly}
          />
        ) : top.type === "decision" ? (
          <DecisionPanel
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            id={top.id}
            onPush={onPush}
          />
        ) : top.type === "events" ? (
          <EventsPanel
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            onPush={onPush}
          />
        ) : top.type === "event" ? (
          <EventPanel
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            id={top.id}
            onPush={onPush}
          />
        ) : top.type === "overview" ? (
          <OverviewPanel
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            onPush={onPush}
          />
        ) : top.type === "overlays" ? (
          <OverlayPanel
            overlay={overlay}
            setOverlay={setOverlay}
            hazards={hazards}
            setHazards={setHazards}
          />
        ) : top.type === "agents" ? (
          <AgentPicker onCommand={onCommand} />
        ) : top.type === "feed" ? (
          <FeedPanel
            onWatch={onWatch}
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            onPush={onPush}
          />
        ) : (
          <ComparePanel
            queryScope={queryScope}
            frame={frame}
            revision={revision}
            otherId={top.otherId}
          />
        )}
      </div>
    </aside>
  );
}
function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  return (
    <span className={`avatar ${large ? "large" : ""}`}>
      {name
        .split(" ")
        .slice(0, 2)
        .map((s) => s[0])
        .join("")}
    </span>
  );
}
function AgentInspector({
  queryScope,
  frame,
  revision,
  id,
  onPush,
  onCommand,
  follow,
  setFollow,
  readOnly,
}: {
  queryScope: string;
  readOnly: boolean;
  frame: WorldFrame;
  revision: number;
  id: string;
  onPush: (n: DrawerNode) => void;
  onCommand: (c: CommandBody) => Promise<void>;
  follow: string | null;
  setFollow: (id: string | null) => void;
}) {
  const { client } = useApp();
  const result = useQuery(
    () => client.agent(frame.simulation.id, id, revision),
    [frame.simulation.id, id, revision],
    JSON.stringify([queryScope, id]),
  );
  const [tab, setTab] = useState("traits");
  if (result.error && !result.data)
    return <ErrorBox error={result.error} retry={result.reload} />;
  if (!result.data) return <Busy text="Reading this citizen’s story…" />;
  const d = result.data,
    a = d.agent;
  return (
    <>
      {result.error && <ErrorBox error={result.error} retry={result.reload} />}
      <div className="agent-heading" data-revision={d.ref.revision}>
        <Avatar name={a.name} large />
        <div>
          <h2>{a.name}</h2>
          <p>
            {a.role} · {d.profile.age}
          </p>
          <span className="pill green">
            <i />
            {a.active ? "Active citizen" : "Inactive"}
          </span>
        </div>
      </div>
      <div className="agent-state">
        <span>
          <Heart size={15} />
          {a.emotion}
        </span>
        <span>
          <Navigation size={15} />
          {pretty(a.action)}
        </span>
        <button
          aria-pressed={follow === id}
          onClick={() => setFollow(follow === id ? null : id)}
        >
          <Eye size={15} />
          {follow === id ? "Following" : "Follow"}
        </button>
      </div>
      <div className="agent-metrics">
        {(Object.keys(metricLabels) as Metric[]).map((k) => (
          <div key={k}>
            <span>{metricLabels[k]}</span>
            <strong>
              {a.metrics[k].toFixed(0)}
              <small>/100</small>
            </strong>
            <div className="metric-bar">
              <i style={{ width: `${a.metrics[k]}%`, background: colors[k] }} />
            </div>
          </div>
        ))}
      </div>
      <div className="drawer-tabs" role="tablist" aria-label="Citizen details">
        {["traits", "story", "memories", "relationships", "mind"].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            key={t}
            onClick={() => setTab(t)}
          >
            {pretty(t)}
          </button>
        ))}
      </div>
      {tab === "traits" ? (
        <Personality profile={d.profile} />
      ) : tab === "story" ? (
        <>
          <div className="thought-card">
            <MessageSquare size={16} />
            <p>
              {a.thought_bubble ??
                d.profile.primary_goal ??
                "No current thought recorded."}
            </p>
            <small>RECORDED CITIZEN EXPRESSION</small>
          </div>
          <h4 className="panel-label">RECENT DECISIONS</h4>
          {d.decisions.items.map((decision) => (
            <button
              className="decision-card"
              key={decision.id}
              onClick={() => onPush({ type: "decision", id: decision.id })}
            >
              <div>
                <span
                  className={`pill ${decision.outcome === "rejected" ? "pink" : "green"}`}
                >
                  {pretty(decision.outcome)}
                </span>
                <span className="muted">
                  Tick {decision.tick} · {decision.source}
                </span>
              </div>
              <h3>
                {pretty(decision.intent.action)} <ArrowRight size={15} />
              </h3>
              <p>{decision.concise_rationale}</p>
              <span className="link-text">
                Why this action <ArrowRight size={13} />
              </span>
            </button>
          ))}
          {d.decisions.next_cursor && (
            <CollectionMore
              detail={d}
              collection="decisions"
              revision={d.ref.revision}
              simulationId={frame.simulation.id}
            />
          )}
          <AgentSystemsPanel
            simulationId={frame.simulation.id}
            agentId={id}
            revision={revision}
            names={Object.fromEntries(frame.agents.map((x) => [x.id, x.name]))}
            onAgent={(agent) => onPush({ type: "agent", id: agent })}
          />
          <h4 className="panel-label">REASONS FOR CHANGE</h4>
          {d.metric_reasons.length ? (
            d.metric_reasons.map((r, i) => (
              <div className="reason" key={i}>
                <span>
                  {metricLabels[r.metric]}{" "}
                  <b>
                    {r.delta > 0 ? "+" : ""}
                    {r.delta}
                  </b>
                </span>
                <EvidenceLinks evidence={r.evidence} onPush={onPush} />
              </div>
            ))
          ) : (
            <p className="muted">No metric changes recorded.</p>
          )}
          <h4 className="panel-label">IMPORTANT EVENTS</h4>
          {d.major_event_ids.length ? (
            d.major_event_ids.map((e) => (
              <button
                className="list-link"
                key={e}
                onClick={() => onPush({ type: "event", id: e })}
              >
                {frame.events.find((x) => x.id === e)?.title ?? e}
                <ArrowRight size={14} />
              </button>
            ))
          ) : (
            <p className="muted">No major events yet.</p>
          )}
          <Override
            detail={d}
            onCommand={onCommand}
            readOnly={readOnly || client.mode === "mock"}
          />
        </>
      ) : tab === "memories" ? (
        <>
          {d.memories.items.map((m) => (
            <article className="memory-card" key={m.id}>
              <span className="eyebrow">
                TICK {m.tick} · {m.source}
              </span>
              <p>{m.text}</p>
              <small>Importance {m.importance}/100</small>
              <EvidenceLinks evidence={m.evidence} onPush={onPush} />
            </article>
          ))}
          {d.memories.next_cursor && (
            <CollectionMore
              detail={d}
              collection="memories"
              revision={d.ref.revision}
              simulationId={frame.simulation.id}
            />
          )}
        </>
      ) : tab === "relationships" ? (
        <>
          <RelationshipGraph detail={d} />
          {d.relationships.items.map((r) => (
            <article className="relationship-card" key={r.to_agent_id}>
              <button
                onClick={() => onPush({ type: "agent", id: r.to_agent_id })}
              >
                <Users size={17} />
                <strong>
                  {frame.agents.find((a) => a.id === r.to_agent_id)?.name ??
                    r.to_agent_id}
                </strong>
                <ChevronRight size={15} />
              </button>
              <p>
                {a.name} →{" "}
                {frame.agents.find((a) => a.id === r.to_agent_id)?.name ??
                  r.to_agent_id}{" "}
                · {r.kind}
              </p>
              <div className="relationship-values">
                {(
                  [
                    "trust",
                    "affection",
                    "respect",
                    "familiarity",
                    "conflict",
                  ] as const
                ).map((k) => (
                  <span key={k}>
                    {pretty(k)} <b>{r[k]}</b>
                  </span>
                ))}
              </div>
              <small>{r.desired_relationship}</small>
            </article>
          ))}
          {d.relationships.next_cursor && (
            <CollectionMore
              detail={d}
              collection="relationships"
              revision={d.ref.revision}
              simulationId={frame.simulation.id}
            />
          )}
        </>
      ) : (
        <>
          <h4 className="panel-label">GOALS</h4>
          {d.goals.map((g, i) => (
            <p className="goal" key={i}>
              <Target size={16} />
              {g}
            </p>
          ))}
          <h4 className="panel-label">BELIEFS</h4>
          {d.beliefs.map((b, i) => (
            <article className="memory-card" key={i}>
              <p>{b.text}</p>
              <small>Confidence {b.confidence}/100</small>
              <EvidenceLinks evidence={b.evidence} onPush={onPush} />
            </article>
          ))}
          <h4 className="panel-label">PERSONALITY & BACKGROUND</h4>
          <p>{d.profile.personality}</p>
          <p className="muted">{d.profile.background}</p>
          <div className="trait-tags">
            {d.profile.values.map((v) => (
              <span className="pill" key={v}>
                {v}
              </span>
            ))}
          </div>
        </>
      )}
    </>
  );
}
function CollectionMore({
  detail,
  collection,
  revision,
  simulationId,
}: {
  detail: AgentDetail;
  collection: "memories" | "relationships" | "decisions";
  revision: number;
  simulationId: string;
}) {
  const { client } = useApp();
  const [items, setItems] = useState<unknown[] | null>(null),
    [error, setError] = useState("");
  return (
    <div>
      {!items ? (
        <Button
          kind="secondary"
          onClick={() => {
            void client
              .collection(simulationId, detail.agent.id, collection, revision)
              .then(setItems)
              .catch((e) => setError(messageOf(e)));
          }}
        >
          Load full {collection}
        </Button>
      ) : (
        <div className="collection-more">
          {items.map((item: any, i) => (
            <article key={i}>
              <p>
                {item.text ??
                  item.concise_rationale ??
                  `${item.from_agent_id} → ${item.to_agent_id}`}
              </p>
              {item.trust !== undefined && (
                <small>
                  Trust {item.trust} · Affection {item.affection} · Respect{" "}
                  {item.respect} · Familiarity {item.familiarity} · Conflict{" "}
                  {item.conflict}
                </small>
              )}
            </article>
          ))}
        </div>
      )}
      {error && <ErrorBox error={error} />}
    </div>
  );
}
function RelationshipGraph({ detail }: { detail: AgentDetail }) {
  const relationships = detail.relationships.items.slice(0, 5);
  return (
    <div className="relationship-graph">
      <svg
        viewBox="0 0 320 160"
        role="img"
        aria-label="Directed outgoing relationships from this citizen"
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <path d="M0 0 6 3 0 6" fill="#a4dbc8" />
          </marker>
        </defs>
        {relationships.map((r, i) => (
          <g key={r.to_agent_id}>
            <path
              d={`M80 80 L245 ${25 + i * 30}`}
              stroke="#8ab9aa"
              strokeWidth="1.2"
              markerEnd="url(#arrowhead)"
            />
            <circle
              cx="260"
              cy={25 + i * 30}
              r="13"
              fill="#302440"
              stroke="#a99ac2"
            />
            <text x="158" y={55 + i * 16} fill="#a4dbc8" fontSize="9">
              {r.trust}
            </text>
          </g>
        ))}
        <circle cx="65" cy="80" r="24" fill="#4b3a65" stroke="#c7acf2" />
        <text x="65" y="84" textAnchor="middle" fill="#eee5ff" fontSize="11">
          {detail.agent.name
            .split(" ")
            .map((s) => s[0])
            .join("")}
        </text>
      </svg>
      <small>Arrows show direction. Labels show trust /100.</small>
    </div>
  );
}
function Override({
  detail,
  onCommand,
  readOnly,
}: {
  detail: AgentDetail;
  onCommand: (c: CommandBody) => Promise<void>;
  readOnly: boolean;
}) {
  const [metric, setMetric] = useState<Metric>("happiness"),
    [value, setValue] = useState(50),
    [goal, setGoal] = useState(""),
    [memory, setMemory] = useState(""),
    [intent, setIntent] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <details className="advanced">
      <summary>
        Advanced intervention <Shield size={14} />
      </summary>
      <p className="helper-text">
        Overrides are recorded as user interventions. They still obey server
        validation.
      </p>
      <Field label="Metric">
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as Metric)}
        >
          {Object.entries(metricLabels).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </Field>
      <Slider label="Override value" value={value} onChange={setValue} />
      <Field label="New goal (optional)">
        <input value={goal} onChange={(e) => setGoal(e.target.value)} />
      </Field>
      <Field label="Inject a memory (optional)">
        <textarea
          value={memory}
          onChange={(e) => setMemory(e.target.value)}
          maxLength={2000}
        />
      </Field>
      <Field
        label="Direct intent JSON (optional)"
        hint="Must match the contract Intent object; legal actions are validated by the server."
      >
        <textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder='{"action":"idle",…}'
        />
      </Field>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        Confirm this substantive intervention
      </label>
      <Button
        disabled={!confirmed || busy || readOnly}
        kind="danger"
        onClick={() => {
          setBusy(true);
          setError("");
          void (async () => {
            try {
              await onCommand({
                type: "override_agent",
                agent_id: detail.agent.id,
                metrics: { [metric]: value },
                goal: goal || null,
                memory_text: memory || null,
                intent: intent ? S.intent.parse(JSON.parse(intent)) : null,
              });
              setConfirmed(false);
            } catch (e) {
              setError(messageOf(e));
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        Apply intervention
      </Button>
      {readOnly && (
        <p className="helper-text">
          Interventions require a live backend and the current live view.
        </p>
      )}
      {error && <ErrorBox error={error} />}
    </details>
  );
}
function EvidenceLinks({
  evidence,
  onPush,
}: {
  evidence: Evidence;
  onPush: (n: DrawerNode) => void;
}) {
  return (
    <div className="evidence">
      <p>{evidence.description}</p>
      {evidence.event_ids.map((id) => (
        <button key={id} onClick={() => onPush({ type: "event", id })}>
          Event evidence <ArrowRight size={12} />
        </button>
      ))}
      {evidence.decision_ids.map((id) => (
        <button key={id} onClick={() => onPush({ type: "decision", id })}>
          Decision evidence <ArrowRight size={12} />
        </button>
      ))}
      {evidence.memory_ids.length > 0 && (
        <small>Related memories: {evidence.memory_ids.join(", ")}</small>
      )}
    </div>
  );
}
function DecisionPanel({
  queryScope,
  frame,
  revision,
  id,
  onPush,
}: {
  queryScope: string;
  frame: WorldFrame;
  revision: number;
  id: string;
  onPush: (n: DrawerNode) => void;
}) {
  const { client } = useApp();
  const r = useQuery(
    () => client.decision(frame.simulation.id, id, revision),
    [frame.simulation.id, id, revision],
    JSON.stringify([queryScope, id]),
  );
  return r.error ? (
    <ErrorBox error={r.error} retry={r.reload} />
  ) : !r.data ? (
    <Busy />
  ) : (
    <DecisionContent decision={r.data} frame={frame} onPush={onPush} />
  );
}
function DecisionContent({
  decision: d,
  frame,
  onPush,
}: {
  decision: Decision;
  frame: WorldFrame;
  onPush: (n: DrawerNode) => void;
}) {
  return (
    <>
      <span className={`pill ${d.outcome === "rejected" ? "pink" : "green"}`}>
        {pretty(d.outcome)} · {d.source}
      </span>
      <h2 className="decision-title">{pretty(d.intent.action)}</h2>
      <Narration
        simulationId={frame.simulation.id}
        sourceType="decision"
        sourceId={d.id}
      />
      <div className="decision-flow">
        <section>
          <span>01 / INTENTION</span>
          <p>{d.intent.motivation}</p>
          <small>{d.intent.emotion}</small>
        </section>
        <section>
          <span>02 / OBSERVED INFORMATION</span>
          {d.observed_facts.map((f, i) => (
            <p key={i}>{f}</p>
          ))}
          {d.memory_ids.length > 0 && (
            <small>Related memory IDs: {d.memory_ids.join(", ")}</small>
          )}
          {d.relationship_agent_ids.map((id) => (
            <button
              className="list-link"
              key={id}
              onClick={() => onPush({ type: "agent", id })}
            >
              {frame.agents.find((a) => a.id === id)?.name ?? id}
              <ArrowRight size={13} />
            </button>
          ))}
        </section>
        <section>
          <span>03 / WHY THIS ACTION</span>
          <p>{d.concise_rationale}</p>
          <small>Recorded rationale, linked to available evidence.</small>
        </section>
        <section>
          <span>04 / VALIDATED OUTCOME</span>
          <p>{d.outcome_description}</p>
          {d.rejection_code && (
            <span className="pill pink">{d.rejection_code}</span>
          )}
          {d.effects.map((e, i) => (
            <p key={i}>
              {pretty(e.field)}: {String(e.before)} → {String(e.after)}
            </p>
          ))}
          {!d.effects.length && <small>No committed changes.</small>}
        </section>
      </div>
      {d.event_ids.map((id) => (
        <button
          className="list-link"
          key={id}
          onClick={() => onPush({ type: "event", id })}
        >
          Related event
          <ArrowRight size={13} />
        </button>
      ))}
    </>
  );
}
function EventsPanel({
  queryScope,
  frame,
  revision,
  onPush,
}: {
  queryScope: string;
  frame: WorldFrame;
  revision: number;
  onPush: (n: DrawerNode) => void;
}) {
  const { client } = useApp();
  const r = useQuery(
    () => client.events(frame.simulation.id, revision),
    [frame.simulation.id, revision],
    queryScope,
  );
  return r.error ? (
    <ErrorBox error={r.error} />
  ) : !r.data ? (
    <Busy />
  ) : !r.data.length ? (
    <Empty title="The story is just beginning">
      No major events occurring. Introduce an event to explore a change.
    </Empty>
  ) : (
    <div className="event-list">
      {r.data.map((e) => (
        <button key={e.id} onClick={() => onPush({ type: "event", id: e.id })}>
          <span className="event-node" />
          <div>
            <span className="pill">{pretty(e.status)}</span>
            <h3>{e.title}</h3>
            <p>{e.summary}</p>
            <small>
              Tick {e.start_tick ?? e.queued_tick} · {e.affected_agent_count}{" "}
              citizens
            </small>
          </div>
          <ChevronRight size={16} />
        </button>
      ))}
    </div>
  );
}
function EventPanel({
  queryScope,
  frame,
  revision,
  id,
  onPush,
}: {
  queryScope: string;
  frame: WorldFrame;
  revision: number;
  id: string;
  onPush: (n: DrawerNode) => void;
}) {
  const { client } = useApp();
  const r = useQuery(
    () => client.report(frame.simulation.id, id, revision),
    [frame.simulation.id, id, revision],
    JSON.stringify([queryScope, id]),
  );
  return r.error ? (
    <ErrorBox error={r.error} retry={r.reload} />
  ) : !r.data ? (
    <Busy />
  ) : (
    <>
      <span className="pill">{pretty(r.data.event.status)}</span>
      <h2 className="decision-title">{r.data.event.title}</h2>
      <Narration
        simulationId={frame.simulation.id}
        sourceType="event"
        sourceId={r.data.event.id}
      />
      <p>{r.data.spec.description}</p>
      {r.data.event.status !== "resolved" && (
        <p className="warning">
          This report is in progress. Values are measured through this revision.
        </p>
      )}
      <ReportMetrics report={r.data} />
      <ScenarioAnalysis
        simulationId={frame.simulation.id}
        eventId={id}
        revision={revision}
        names={Object.fromEntries(frame.agents.map((x) => [x.id, x.name]))}
        onAgent={(agent) => onPush({ type: "agent", id: agent })}
      />
      <h4 className="panel-label">CONSEQUENCES</h4>
      {r.data.consequences.map((c, i) => (
        <article className="memory-card" key={i}>
          <p>{c.text}</p>
          <EvidenceLinks evidence={c.evidence} onPush={onPush} />
        </article>
      ))}
      <h4 className="panel-label">COMMUNITY LESSONS</h4>
      {r.data.community_lessons.map((c, i) => (
        <article className="memory-card" key={i}>
          <p>{c.text}</p>
          <EvidenceLinks evidence={c.evidence} onPush={onPush} />
        </article>
      ))}
      <h4 className="panel-label">AFFECTED CITIZENS</h4>
      {r.data.affected_agent_ids.map((id) => (
        <button
          className="list-link"
          key={id}
          onClick={() => onPush({ type: "agent", id })}
        >
          {frame.agents.find((a) => a.id === id)?.name ?? id}
          <ChevronRight size={14} />
        </button>
      ))}
    </>
  );
}
function OverviewPanel({
  queryScope,
  frame,
  revision,
  onPush,
}: {
  queryScope: string;
  frame: WorldFrame;
  revision: number;
  onPush: (n: DrawerNode) => void;
}) {
  const { client } = useApp();
  const r = useQuery(
    () => client.overview(frame.simulation.id, revision),
    [frame.simulation.id, revision],
    queryScope,
  );
  return r.error ? (
    <ErrorBox error={r.error} />
  ) : !r.data ? (
    <Busy />
  ) : (
    <>
      <h3>How your city is doing</h3>
      {client.mode === "live" && (
        <a
          className="button secondary"
          href={client.exportUrl(frame.simulation.id, revision)}
          download
        >
          Export metrics CSV
        </a>
      )}
      <div className="overview-counts">
        <span>
          <strong>{r.data.metrics.cooperation_count}</strong>cooperative actions
        </span>
        <span>
          <strong>{r.data.metrics.conflict_count}</strong>conflicts
        </span>
        <span>
          <strong>{r.data.metrics.resources_consumed}</strong>units consumed
        </span>
      </div>
      <CitySystemsPanel
        simulationId={frame.simulation.id}
        revision={revision}
        onEvent={(event) => onPush({ type: "event", id: event })}
      />
      <h4 className="panel-label">EVENTS WITH THE LARGEST CHANGES</h4>
      {r.data.top_events.length ? (
        r.data.top_events.slice(0, 3).map((e, i) => (
          <button
            className="list-link"
            key={e.event_id}
            onClick={() => onPush({ type: "event", id: e.event_id })}
          >
            <span>
              {i + 1}. {e.title}
            </span>
            <ArrowRight size={14} />
          </button>
        ))
      ) : (
        <p className="muted">No ranked events yet.</p>
      )}
      <h4 className="panel-label">TOP IMPROVEMENTS</h4>
      {r.data.improvements.length ? (
        r.data.improvements.slice(0, 3).map((m, i) => (
          <p key={i}>
            {metricLabels[m.metric]} +{m.delta.toFixed(1)}
          </p>
        ))
      ) : (
        <p className="muted">No recorded improvements yet.</p>
      )}
      <h4 className="panel-label">BEHIND THE MEASURES</h4>
      {r.data.metric_reasons.map((r, i) => (
        <details className="reason" key={i}>
          <summary>
            {metricLabels[r.metric]} <ChevronRight size={15} />
          </summary>
          <p>{r.text}</p>
          <EvidenceLinks evidence={r.evidence} onPush={onPush} />
        </details>
      ))}
    </>
  );
}
function OverlayPanel({
  overlay,
  setOverlay,
  hazards,
  setHazards,
}: {
  overlay: Overlay;
  setOverlay: (o: Overlay) => void;
  hazards: boolean;
  setHazards: (b: boolean) => void;
}) {
  return (
    <>
      <p className="muted">
        One measure at a time, with zone values supplied by the server.
      </p>
      <div className="overlay-options">
        {([null, "safety", "happiness", "density", "resources"] as const).map(
          (o) => (
            <button
              key={o ?? "none"}
              aria-pressed={overlay === o}
              className={overlay === o ? "active" : ""}
              onClick={() => setOverlay(o)}
            >
              <span>
                {o === "density"
                  ? "Population density"
                  : o
                    ? metricLabels[o]
                    : "No heatmap"}
              </span>
              <i />
            </button>
          ),
        )}
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={hazards}
          onChange={(e) => setHazards(e.target.checked)}
        />{" "}
        Show affected area and hazard outlines
      </label>
      {overlay && (
        <div className="overlay-legend">
          <div className="legend-gradient" />
          <span>
            {overlay === "density" ? "0 people/km²" : "0 /100"}
            <span>
              {overlay === "density" ? "10,000+ people/km²" : "100 /100"}
            </span>
          </span>
          <p>
            Display scale only. Values above the density maximum use the same
            maximum color.
          </p>
        </div>
      )}
    </>
  );
}
function AgentPicker({
  onCommand,
}: {
  onCommand: (c: CommandBody) => Promise<void>;
}) {
  const { client } = useApp();
  const profiles = useQuery(() => client.profiles(), [client]);
  const [selected, setSelected] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <>
      {profiles.error ? (
        <ErrorBox error={profiles.error} />
      ) : !profiles.data ? (
        <Busy />
      ) : !profiles.data.length ? (
        <Empty title="No custom agents created">
          Create a saved profile in Settings, then bring them into this city.
        </Empty>
      ) : (
        <>
          <p className="muted">
            Saved profiles become new, independent citizens.
          </p>
          {profiles.data.map((p) => (
            <label className="profile-picker" key={p.id}>
              <input
                type="checkbox"
                checked={selected.includes(p.id)}
                onChange={(e) =>
                  setSelected((ids) =>
                    e.target.checked
                      ? [...ids, p.id]
                      : ids.filter((id) => id !== p.id),
                  )
                }
              />
              <Avatar name={p.profile.name} />
              <span>
                <strong>{p.profile.name}</strong>
                <small>{p.profile.role}</small>
              </span>
            </label>
          ))}
          <Button
            disabled={!selected.length || busy}
            onClick={() => {
              setBusy(true);
              void onCommand({ type: "add_agents", custom_agent_ids: selected })
                .then(() => setSelected([]))
                .catch((e) => setError(messageOf(e)))
                .finally(() => setBusy(false));
            }}
          >
            Add {selected.length} citizens <ArrowRight size={14} />
          </Button>
        </>
      )}
      {error && <ErrorBox error={error} />}
    </>
  );
}
function FeedPanel({
  queryScope,
  frame,
  revision,
  onPush,
  onWatch,
}: {
  onWatch?: (ids: string[], interactionId?: string) => void;
  queryScope: string;
  frame: WorldFrame;
  revision: number;
  onPush: (n: DrawerNode) => void;
}) {
  const { client } = useApp();
  const r = useQuery(
    () => client.dialogue(frame.simulation.id, revision),
    [frame.simulation.id, revision],
    queryScope,
  );
  return (
    <>
      {r.error && <ErrorBox error={r.error} retry={r.reload} />}
      {!r.data && !r.error ? (
        <Busy text="Listening in…" />
      ) : (
        <Conversations
          onWatch={onWatch}
          dialogue={r.data ?? frame.recent_dialogue}
          frame={frame}
          onAgent={(id) => onPush({ type: "agent", id })}
        />
      )}
    </>
  );
}
export function ComparePanel({
  queryScope,
  frame,
  revision,
  otherId,
}: {
  queryScope?: string;
  frame: WorldFrame;
  revision: number;
  otherId?: string;
}) {
  const { client, capabilities } = useApp();
  const [snowflakeClient] = useState(
    () => new SnowflakeClient(client.transport),
  );
  const worlds = useQuery(
    async () => [
      ...(await client.simulations()),
      ...(await client.simulations(true)),
    ],
    [client],
  );
  const [selected, setSelected] = useState(otherId ?? "");
  const [metric, setMetric] = useState<Metric>("happiness");
  const data = useQuery(
    async () => {
      if (!selected) return null;
      const [a, b, sim] = await Promise.all([
        client.metrics(frame.simulation.id, revision),
        client.metrics(selected),
        client.simulation(selected),
      ]);
      return { a: a.points, b: b.points, sim };
    },
    [selected, frame.simulation.id, revision],
    queryScope === undefined
      ? undefined
      : JSON.stringify([queryScope, selected]),
  );
  const shared =
    data.data &&
    (data.data.sim.parent_simulation_id === frame.simulation.id
      ? data.data.sim.fork_ref?.tick
      : frame.simulation.parent_simulation_id === data.data.sim.id
        ? frame.simulation.fork_ref?.tick
        : frame.simulation.parent_simulation_id &&
            frame.simulation.parent_simulation_id ===
              data.data.sim.parent_simulation_id
          ? Math.min(
              frame.simulation.fork_ref?.tick ?? 0,
              data.data.sim.fork_ref?.tick ?? 0,
            )
          : undefined);
  const start = shared ?? 0;
  const pointsA = data.data?.a.filter((p) => p.tick >= start) ?? [],
    pointsB = data.data?.b.filter((p) => p.tick >= start) ?? [];
  const max = Math.max(
    1,
    ...pointsA.map((p) => p.tick - start),
    ...pointsB.map((p) => p.tick - start),
  );
  const path = (p: typeof pointsA) =>
    p
      .map(
        (p) =>
          `${25 + ((p.tick - start) / max) * 290},${125 - p.values[metric]}`,
      )
      .join(" ");
  return (
    <>
      <p className="muted">
        Explore how two histories differ using the same scales. These are
        exploratory runs.
      </p>
      <Field label="Compare with">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">Choose a world</option>
          {worlds.data
            ?.filter((s) => s.id !== frame.simulation.id)
            .map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
        </select>
      </Field>
      {data.error && <ErrorBox error={data.error} />}{" "}
      {data.data && (
        <>
          <div className="lineage">
            <GitBranch size={17} />
            {shared !== undefined
              ? `Shared lineage · aligned from tick ${start}`
              : "No verified common branch point · aligned by tick 0"}
          </div>
          <Field label="Measure">
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value as Metric)}
            >
              {Object.entries(metricLabels).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <svg
            className="compare-chart"
            viewBox="0 0 340 155"
            role="img"
            aria-label={`${metricLabels[metric]} from 0 to 100, aligned by ticks since ${start}`}
          >
            <path
              d="M25 25V125H320M25 75H320M25 25H320"
              stroke="#635473"
              fill="none"
              strokeWidth=".5"
            />
            <text x="0" y="29" fill="currentColor" fontSize="9">
              100
            </text>
            <text x="10" y="128" fill="currentColor" fontSize="9">
              0
            </text>
            <text x="25" y="148" fill="currentColor" fontSize="9">
              0
            </text>
            <text x="280" y="148" fill="currentColor" fontSize="9">
              {max} ticks
            </text>
            <polyline
              points={path(pointsA)}
              fill="none"
              stroke="#c4a4ff"
              strokeWidth="2"
            />
            <polyline
              points={path(pointsB)}
              fill="none"
              stroke="#7ce9ba"
              strokeWidth="2"
            />
          </svg>
          <div className="chart-key">
            <span>
              <i />
              {frame.simulation.name}
            </span>
            <span>
              <i />
              {data.data.sim.name}
            </span>
          </div>
          <div className="comparison-values">
            <p>
              {frame.simulation.name}
              <b>{pointsA.at(-1)?.values[metric].toFixed(1) ?? "—"}</b>
            </p>
            <p>
              {data.data.sim.name}
              <b>{pointsB.at(-1)?.values[metric].toFixed(1) ?? "—"}</b>
            </p>
            <p>
              Endpoint difference
              <b>
                {(
                  (pointsA.at(-1)?.values[metric] ?? 0) -
                  (pointsB.at(-1)?.values[metric] ?? 0)
                ).toFixed(1)}
              </b>
            </p>
          </div>
          <p className="helper-text">
            Endpoint ticks can differ. Separate model runs do not establish
            statistical significance.
          </p>
          <SnowflakeComparison
            enabled={client.mode === "live" && !!capabilities?.snowflake}
            a={{ simulation_id: frame.simulation.id, revision }}
            b={{
              simulation_id: data.data.sim.id,
              revision: data.data.sim.revision,
            }}
            client={snowflakeClient}
          />
        </>
      )}
    </>
  );
}
