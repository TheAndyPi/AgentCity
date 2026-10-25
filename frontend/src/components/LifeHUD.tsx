import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Coffee,
  Heart,
  MessageCircle,
  Pause,
  Play,
  SkipForward,
  Utensils,
  X,
} from "lucide-react";
import type {
  ActionName,
  CommandBody,
  Dialogue,
  Intent,
  WorldFrame,
} from "../api/types";
import { readBehavior } from "../behavior/client";
import { insideBuilding } from "../world/buildingAccess";
import { pretty } from "../api/defaults";
import { messageOf, useApp, useQuery } from "../state/app";
import { CitizenPortrait, groupConversations } from "./LifePanels";

export function lifeIntent(
  action: ActionName,
  target: string | null = null,
): Intent {
  return {
    action,
    target_id: target,
    destination: null,
    parameters: {
      resource_kind: action === "consume" ? "food" : null,
      amount: action === "consume" ? 1 : null,
      message: null,
    },
    motivation:
      {
        talk: "I'd like to get to know my neighbor",
        rest: "Take a little time to recharge",
        consume: "Have something to eat",
      }[action as "talk" | "rest" | "consume"] ?? "Follow an invitation",
    emotion: "calm",
  };
}
export default function LifeHUD({
  frame,
  focused,
  onFocus,
  onClose,
  onProfile,
  onCommand,
  locked,
  readOnly,
}: {
  frame: WorldFrame;
  focused: string[];
  onFocus: (ids: string[], interactionId?: string) => void;
  onClose: () => void;
  onProfile: (id: string) => void;
  onCommand: (body: CommandBody) => Promise<void>;
  locked: boolean;
  readOnly: boolean;
}) {
  const { client } = useApp();
  const [partner, setPartner] = useState("");
  const [visit, setVisit] = useState("");
  const [working, setWorking] = useState(false),
    [error, setError] = useState("");
  const transcript = useRef<HTMLDivElement>(null);
  const selected = frame.agents.find((a) => a.id === focused[0]);
  const currentBuilding = selected
    ? frame.map.buildings.find((b) => insideBuilding(selected.position, b))
    : undefined;
  const visitOptions = frame.map.buildings.filter(
    (b) => b.functional && b.id !== currentBuilding?.id,
  );
  const visitTarget =
    visitOptions.find((b) => b.id === visit) ?? visitOptions[0];
  const second = frame.agents.find((a) => a.id === focused[1]);
  const detail = useQuery(
    () =>
      selected
        ? client.agent(frame.simulation.id, selected.id, frame.ref.revision)
        : Promise.resolve(null),
    [client, frame.simulation.id, selected?.id, frame.ref.revision],
    `${frame.simulation.id}:${selected?.id}`,
  );
  const behavior = useQuery(
    () =>
      selected
        ? readBehavior(
            client.transport,
            frame.simulation.id,
            frame.ref.revision,
          )
        : Promise.resolve(null),
    [client, frame.simulation.id, selected?.id, frame.ref.revision],
    `${frame.simulation.id}:${selected?.id}:${frame.ref.revision}`,
  );
  const condition = selected ? behavior.data?.citizens[selected.id] : undefined;
  const archive = useQuery(
    () =>
      selected
        ? client.dialogue(frame.simulation.id, frame.ref.revision)
        : Promise.resolve([]),
    [
      client,
      frame.simulation.id,
      selected?.id,
      second?.id,
      readOnly ? frame.ref.revision : null,
    ],
    `${frame.simulation.id}:${selected?.id}:${second?.id}:${readOnly ? frame.ref.revision : "live"}`,
  );
  const remembered = useRef<{
    id: string;
    revision: number;
    messages: Map<string, Dialogue>;
  }>({ id: "", revision: -1, messages: new Map() });
  if (
    remembered.current.id !== frame.simulation.id ||
    frame.ref.revision < remembered.current.revision
  ) {
    remembered.current = {
      id: frame.simulation.id,
      revision: frame.ref.revision,
      messages: new Map(),
    };
  }
  remembered.current.revision = frame.ref.revision;
  const savedLines = (archive.data ?? [])
    .filter(
      (line) =>
        selected &&
        [line.speaker_id, ...line.recipient_ids].includes(selected.id) &&
        (!second ||
          [line.speaker_id, ...line.recipient_ids].includes(second.id)),
    )
    .slice(0, 200);
  for (const line of [...savedLines, ...frame.recent_dialogue])
    remembered.current.messages.set(line.id, line);
  const groups = groupConversations([...remembered.current.messages.values()]);
  const conversation = groups.find(
    (group) =>
      selected &&
      group.participants.includes(selected.id) &&
      (!second || group.participants.includes(second.id)),
  );
  if (remembered.current.messages.size > 500) {
    const keep = new Set([
      ...groups
        .slice(0, 50)
        .flatMap((group) => group.messages.map((line) => line.id)),
      ...(conversation?.messages.map((line) => line.id) ?? []),
    ]);
    for (const id of remembered.current.messages.keys())
      if (!keep.has(id)) remembered.current.messages.delete(id);
  }
  const lines = conversation?.messages ?? [];
  const last = lines.at(-1);
  const liveChat =
    last && !last.end_conversation && frame.ref.tick - last.tick <= 5;
  const neighbors = selected
    ? frame.agents
        .filter(
          (a) =>
            a.id !== selected.id && a.active && a.emotion !== "unconscious",
        )
        .sort(
          (a, b) =>
            Math.hypot(
              a.position.x - selected.position.x,
              a.position.y - selected.position.y,
            ) -
            Math.hypot(
              b.position.x - selected.position.x,
              b.position.y - selected.position.y,
            ),
        )
    : [];
  const target = neighbors.find((a) => a.id === partner) ?? neighbors[0];
  const relation = detail.data?.relationships.items.find(
    (r) => r.to_agent_id === second?.id,
  );
  useEffect(() => {
    setPartner("");
    setVisit("");
    setError("");
  }, [selected?.id]);
  useEffect(() => {
    transcript.current?.scrollTo({
      top: transcript.current.scrollHeight,
      behavior: "auto",
    });
  }, [last?.id]);
  const perform = async (action: "talk" | "rest" | "consume" | "move") => {
    if (
      !selected ||
      (action === "talk" && !target) ||
      (action === "move" && !visitTarget) ||
      working ||
      locked ||
      readOnly
    )
      return;
    setWorking(true);
    setError("");
    try {
      await onCommand({
        type: "override_agent",
        agent_id: selected.id,
        metrics: {},
        goal: null,
        memory_text: null,
        intent: {
          ...lifeIntent(
            action,
            action === "talk"
              ? target!.id
              : action === "move"
                ? visitTarget!.id
                : null,
          ),
          ...(action === "move"
            ? { motivation: `Visit ${visitTarget!.name}` }
            : {}),
        },
      });
      if (action === "move" && frame.simulation.status !== "running")
        await onCommand({ type: "play" });
      if (action === "talk") {
        onFocus([selected.id, target!.id]);
        await onCommand({ type: "set_speed", value: 0.25 });
        if (frame.simulation.status !== "running")
          await onCommand({ type: "play" });
      }
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setWorking(false);
    }
  };
  const disabled =
    working ||
    locked ||
    readOnly ||
    !selected?.active ||
    condition?.life === "unconscious" ||
    (condition?.care !== undefined && condition.care !== "none");
  return (
    <>
      {!selected && (
        <div className="life-hint">
          <p>
            <small>Select a citizen to follow them or see their details.</small>
          </p>
        </div>
      )}
      {selected && (
        <>
          <div className="focus-breadcrumb">
            <button onClick={onClose}>
              <ArrowLeft size={14} /> Neighborhood
            </button>
            <span>/</span>
            <strong>
              {selected.name.split(" ")[0]}
              {second && ` & ${second.name.split(" ")[0]}`}
            </strong>
            <span className="focus-live">
              {readOnly ? "A RECORDED MOMENT" : "UP CLOSE"}
            </span>
          </div>
          <aside
            className={`life-focus-card ${second ? "pair" : ""}`}
            aria-label="Character focus"
          >
            <button
              className="focus-close"
              aria-label="Close character focus"
              onClick={onClose}
            >
              <X size={16} />
            </button>
            <header>
              <CitizenPortrait name={selected.name} large />
              <div>
                <span className="eyebrow">
                  {second ? "Conversation" : "Citizen"}
                </span>
                <h2>{selected.name}</h2>
                <p>
                  {pretty(selected.role)} · {pretty(selected.emotion)}
                  {currentBuilding && (
                    <>
                      <br />
                      Inside {currentBuilding.name}
                    </>
                  )}
                </p>
              </div>
            </header>
            {second && (
              <div className="focus-other">
                <CitizenPortrait name={second.name} />
                <div>
                  <strong>With {second.name}</strong>
                  <small>
                    {relation
                      ? `${pretty(relation.kind)} · ${Math.round(relation.trust)}% trust`
                      : "Getting to know each other"}
                  </small>
                </div>
                <Heart size={15} />
              </div>
            )}
            <div className="focus-thought">
              <span>ON THEIR MIND</span>
              <p>
                {selected.thought_bubble ||
                  detail.data?.profile.primary_goal ||
                  "Taking in the neighborhood."}
              </p>
            </div>
            {detail.data && (
              <div
                className="life-needs"
                aria-label={`${selected.name}'s needs`}
              >
                {(
                  [
                    ["Energy", 100 - detail.data.needs.fatigue],
                    ["Fullness", 100 - detail.data.needs.hunger],
                    ["Health", detail.data.needs.health],
                    ["Social", 100 - detail.data.needs.social],
                    ...(condition
                      ? [["Mental", condition.mental] as const]
                      : []),
                  ] as const
                ).map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <meter min={0} max={100} value={value} aria-label={label} />
                    <small>{Math.round(value)}</small>
                  </div>
                ))}
              </div>
            )}
            {condition && (
              <div className="focus-thought" aria-label="Survival and care">
                <span>
                  {condition.life === "dead"
                    ? "DEAD"
                    : condition.life === "unconscious"
                      ? "UNCONSCIOUS"
                      : condition.care === "hospital"
                        ? "HOSPITALIZED"
                        : condition.episode &&
                            condition.episode.end_tick === null
                          ? condition.episode.mode.toUpperCase()
                          : "ALIVE"}
                </span>
                <p>
                  {condition.life === "dead"
                    ? `Tick ${condition.transition_tick}: ${condition.causes.join(" and ")}`
                    : `${condition.care === "none" ? "No active care" : condition.care === "hospital" ? "Hospital care" : pretty(condition.care) + " rescue"} · ${pretty(condition.wealth_band)} resource class`}
                </p>
                {condition.episode && condition.episode.end_tick === null && (
                  <p>
                    {condition.episode.causes.join(" and ")} · episode since
                    tick {condition.episode.start_tick}
                  </p>
                )}
                {condition.impacts
                  .filter((item) => item.tick === frame.ref.tick)
                  .slice(-5)
                  .map((item, i) => (
                    <small key={i} style={{ display: "block" }}>
                      {item.reason}: {item.delta >= 0 ? "+" : ""}
                      {item.delta.toFixed(2)} {pretty(item.meter)}
                    </small>
                  ))}
              </div>
            )}
            {condition && (
              <div className="focus-thought" aria-label="Behavior evidence">
                {(behavior.data?.events ?? [])
                  .filter(
                    (event) =>
                      event.actor_id === selected.id ||
                      event.target_id === selected.id,
                  )
                  .slice(-3)
                  .map((event) => (
                    <small key={event.id} style={{ display: "block" }}>
                      {pretty(event.kind)} · Tick {event.tick}:{" "}
                      {event.description}
                    </small>
                  ))}
              </div>
            )}
            {behavior.error && (
              <p role="alert" className="field-error">
                Behavior details: {behavior.error}
              </p>
            )}
            {!second && (
              <>
                <div className="life-small-actions">
                  <button
                    disabled={disabled}
                    onClick={() => void perform("rest")}
                  >
                    <Coffee size={15} />
                    Take a break
                  </button>
                  <button
                    disabled={
                      disabled || !detail.data || detail.data.inventory.food < 1
                    }
                    onClick={() => void perform("consume")}
                  >
                    <Utensils size={15} />
                    Have a snack
                  </button>
                </div>
                <label className="meet-picker">
                  <span>SPEND TIME WITH</span>
                  <select
                    aria-label="Choose a neighbor to meet"
                    value={target?.id ?? ""}
                    onChange={(e) => setPartner(e.target.value)}
                  >
                    {neighbors.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="invite-button"
                  disabled={disabled || !target}
                  onClick={() => void perform("talk")}
                >
                  <MessageCircle size={17} />
                  {working ? "On it…" : "Invite to chat"}
                  <ArrowUpRight size={15} />
                </button>
                <label className="meet-picker">
                  <span>VISIT A BUILDING</span>
                  <select
                    aria-label="Choose a building to visit"
                    value={visitTarget?.id ?? ""}
                    onChange={(event) => setVisit(event.target.value)}
                  >
                    {visitOptions.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="invite-button"
                  disabled={disabled || !visitTarget}
                  onClick={() => void perform("move")}
                >
                  Visit building <ArrowUpRight size={15} />
                </button>
              </>
            )}
            {conversation && !second && (
              <button
                className="watch-chat"
                onClick={() =>
                  onFocus(
                    conversation.participants.slice(0, 2),
                    conversation.id,
                  )
                }
              >
                <MessageCircle size={15} />
                Watch{" "}
                {liveChat ? "this conversation" : "their last conversation"}
                <ArrowUpRight size={14} />
              </button>
            )}
            {detail.error && (
              <p role="alert" className="field-error">
                {detail.error}
                <button onClick={detail.reload}>Try again</button>
              </p>
            )}
            {error && (
              <p role="alert" className="field-error">
                {error}
              </p>
            )}
            <button
              className="full-profile"
              onClick={() => onProfile(selected.id)}
            >
              Their story & relationships
              <ArrowUpRight size={13} />
            </button>
          </aside>
          {second && (
            <section
              className="closeup-chat"
              aria-label="Close-up conversation"
            >
              <header>
                <span>
                  <i />
                  {liveChat
                    ? "IN CONVERSATION"
                    : last?.end_conversation
                      ? "A MOMENT TOGETHER"
                      : "GETTING TOGETHER"}
                </span>
                <MessageCircle size={18} />
              </header>
              <div
                className="closeup-lines"
                ref={transcript}
                aria-live="polite"
                aria-relevant="additions"
              >
                {lines.length ? (
                  lines.map((line) => (
                    <article
                      key={line.id}
                      className={line.speaker_id === selected.id ? "" : "reply"}
                    >
                      <strong>
                        {
                          frame.agents
                            .find((a) => a.id === line.speaker_id)
                            ?.name.split(" ")[0]
                        }
                      </strong>
                      <p>{line.text}</p>
                      <small>{pretty(line.emotion)}</small>
                    </article>
                  ))
                ) : (
                  <div className="chat-waiting">
                    <span>···</span>
                    <p>
                      {selected.path.length
                        ? `${selected.name.split(" ")[0]} is walking over.`
                        : "A hello is the start of something."}
                    </p>
                    <small>
                      {frame.simulation.status === "paused"
                        ? "Press Play to let the moment unfold."
                        : "They'll talk when they're close enough."}
                    </small>
                  </div>
                )}
              </div>
              <footer>
                <span>
                  {last?.end_conversation
                    ? "Until next time. ♡"
                    : "Let them take their time."}
                </span>
                <button
                  disabled={disabled}
                  aria-label={
                    frame.simulation.status === "running"
                      ? "Pause to read"
                      : "Continue moment"
                  }
                  onClick={() =>
                    void onCommand({
                      type:
                        frame.simulation.status === "running"
                          ? "pause"
                          : "play",
                    }).catch(() => {})
                  }
                >
                  {frame.simulation.status === "running" ? (
                    <Pause size={14} />
                  ) : (
                    <Play size={14} />
                  )}
                </button>
                <button
                  disabled={disabled || frame.simulation.status === "running"}
                  aria-label="Next moment"
                  onClick={() =>
                    void onCommand({ type: "step", count: 1 }).catch(() => {})
                  }
                >
                  <SkipForward size={15} />
                </button>
              </footer>
            </section>
          )}
        </>
      )}
    </>
  );
}
