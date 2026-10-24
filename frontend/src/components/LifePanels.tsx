import { useState } from "react";
import {
  ArrowUpRight,
  Heart,
  MessageCircle,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import type { Dialogue, Profile, Traits, WorldFrame } from "../api/types";
import { pretty } from "../api/defaults";
import { useApp, useQuery } from "../state/app";
import { Busy, Empty, ErrorBox } from "./ui";

const traitScales: {
  key: keyof Traits;
  low: string;
  high: string;
  icon: string;
}[] = [
  {
    key: "curiosity",
    low: "Content with the familiar",
    high: "Curious",
    icon: "✦",
  },
  { key: "empathy", low: "Practical", high: "Empathetic", icon: "♡" },
  { key: "sociability", low: "Reserved", high: "Outgoing", icon: "☀" },
  { key: "trust", low: "Cautious", high: "Trusting", icon: "❋" },
  { key: "cooperation", low: "Independent", high: "Cooperative", icon: "✿" },
  { key: "risk_tolerance", low: "Careful", high: "Adventurous", icon: "↗" },
];

export function CitizenPortrait({
  name,
  large = false,
}: {
  name: string;
  large?: boolean;
}) {
  const hue =
    [...name].reduce((sum, letter) => sum + letter.charCodeAt(0), 0) % 360;
  return (
    <span
      className={`citizen-portrait ${large ? "large" : ""}`}
      style={{
        background: `hsl(${hue} 36% 25%)`,
        color: `hsl(${hue} 75% 82%)`,
      }}
      aria-hidden="true"
    >
      <span className="portrait-hair" />
      <span className="portrait-face">
        <i />
        <i />
        <b />
      </span>
      <span className="portrait-shirt" />
    </span>
  );
}

export function Personality({ profile }: { profile: Profile }) {
  return (
    <div className="personality-panel">
      <div className="personality-intro">
        <Sparkles size={18} />
        <div>
          <span className="eyebrow">ONE OF A KIND</span>
          <h3>{profile.personality}</h3>
        </div>
      </div>
      <div className="personality-tags">
        {traitScales.map(({ key, low, high, icon }) => (
          <span key={key}>
            <b>{icon}</b>
            {profile.traits[key] >= 50 ? high : low}
          </span>
        ))}
      </div>
      <div className="personality-scales">
        {traitScales.map(({ key, low, high }) => (
          <div className="personality-scale" key={key}>
            <div>
              <span>{pretty(key)}</span>
              <strong>
                {Math.round(profile.traits[key])}
                <small>/100</small>
              </strong>
            </div>
            <div
              className="personality-track"
              role="meter"
              aria-label={pretty(key)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={profile.traits[key]}
            >
              <i style={{ left: `${profile.traits[key]}%` }} />
            </div>
            <div className="personality-poles">
              <span>{low}</span>
              <span>{high}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="life-wish">
        <Heart size={17} />
        <div>
          <span className="eyebrow">WHAT THEY WANT</span>
          <p>{profile.primary_goal}</p>
        </div>
      </div>
      {profile.values.length > 0 && (
        <div className="trait-tags">
          {profile.values.map((value) => (
            <span className="pill" key={value}>
              {value}
            </span>
          ))}
        </div>
      )}
      {profile.background && <p className="muted">{profile.background}</p>}
    </div>
  );
}

export function TraitsRoster({
  frame,
  revision,
  onAgent,
}: {
  frame: WorldFrame;
  revision: number;
  onAgent: (id: string) => void;
}) {
  const { client } = useApp();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const agents = frame.agents.filter((agent) =>
    `${agent.name} ${agent.role}`.toLowerCase().includes(query.toLowerCase()),
  );
  const id = agents.find((agent) => agent.id === selected)?.id ?? agents[0]?.id;
  const detail = useQuery(
    () =>
      id
        ? client.agent(frame.simulation.id, id, revision)
        : Promise.resolve(null),
    [client, frame.simulation.id, id, revision],
    JSON.stringify([frame.simulation.id, id]),
  );
  const agent = frame.agents.find((agent) => agent.id === id);
  return (
    <>
      <div className="life-panel-heading">
        <span className="life-sticker">
          <Users size={21} />
        </span>
        <div>
          <h3>Meet your people.</h3>
          <p>
            {frame.agents.length} personalities. A city full of possibilities.
          </p>
        </div>
      </div>
      <div className="search-input">
        <Search size={17} />
        <input
          aria-label="Search citizens"
          placeholder="Find a name or role…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="roster-grid" aria-label="All agents">
        {agents.map((agent) => (
          <button
            className={`roster-citizen ${id === agent.id ? "selected" : ""}`}
            key={agent.id}
            onClick={() => setSelected(agent.id)}
            aria-pressed={id === agent.id}
          >
            <CitizenPortrait name={agent.name} />
            <strong>{agent.name}</strong>
            <small>{agent.role}</small>
            <span className="roster-mood">
              {agent.active ? agent.emotion : "Inactive"}
            </span>
          </button>
        ))}
      </div>
      {!agents.length && (
        <Empty title="No matching citizens">Try another name or role.</Empty>
      )}
      {agent && (
        <section className="roster-profile" aria-label={`${agent.name} traits`}>
          <div className="roster-profile-heading">
            <CitizenPortrait name={agent.name} large />
            <div>
              <span className="eyebrow">GET TO KNOW</span>
              <h3>{agent.name}</h3>
              <p>{agent.role}</p>
            </div>
            <button
              className="icon-button"
              aria-label={`Open ${agent.name} profile`}
              onClick={() => onAgent(agent.id)}
            >
              <ArrowUpRight size={20} />
            </button>
          </div>
          {detail.error && (
            <ErrorBox error={detail.error} retry={detail.reload} />
          )}
          {!detail.data ? (
            !detail.error && <Busy text="Getting to know them…" />
          ) : (
            <Personality profile={detail.data.profile} />
          )}
        </section>
      )}
    </>
  );
}

export type Conversation = {
  id: string;
  participants: string[];
  messages: Dialogue[];
};
export function groupConversations(dialogue: Dialogue[]): Conversation[] {
  const groups = new Map<string, Conversation>();
  // IDs carry the persisted message sequence; ticks alone cannot order replies.
  const ordered = [...dialogue].sort(
    (a, b) =>
      a.tick - b.tick || a.id.localeCompare(b.id, undefined, { numeric: true }),
  );
  for (const message of ordered) {
    const group = groups.get(message.interaction_id) ?? {
      id: message.interaction_id,
      participants: [],
      messages: [],
    };
    group.messages.push(message);
    group.participants = [
      ...new Set([
        ...group.participants,
        message.speaker_id,
        ...message.recipient_ids,
      ]),
    ];
    groups.set(group.id, group);
  }
  return [...groups.values()].sort(
    (a, b) =>
      b.messages.at(-1)!.tick - a.messages.at(-1)!.tick ||
      b.messages
        .at(-1)!
        .id.localeCompare(a.messages.at(-1)!.id, undefined, { numeric: true }),
  );
}

export function Conversations({
  dialogue,
  frame,
  onAgent,
}: {
  dialogue: Dialogue[];
  frame: WorldFrame;
  onAgent: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const name = (id: string) =>
    frame.agents.find((agent) => agent.id === id)?.name ?? id;
  const all = groupConversations(dialogue);
  const groups = all.filter((group) =>
    group.participants.some((id) =>
      name(id).toLowerCase().includes(filter.toLowerCase()),
    ),
  );
  const conversation =
    groups.find((group) => group.id === selected) ?? groups[0];
  const last = conversation?.messages.at(-1);
  return (
    <>
      <div className="life-panel-heading">
        <span className="life-sticker peach">
          <MessageCircle size={22} />
        </span>
        <div>
          <h3>A little closer.</h3>
          <p>Who said what, and who said it back.</p>
        </div>
      </div>
      {all.length > 0 && (
        <div className="search-input">
          <Search size={17} />
          <input
            aria-label="Find conversations by citizen"
            placeholder="Find someone’s conversations…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
      )}
      {!conversation ? (
        <Empty title={all.length ? "No conversations match" : "A quiet moment"}>
          {all.length
            ? "Try another name."
            : "Press Play. As neighbors meet and talk, their conversations appear here together."}
        </Empty>
      ) : (
        <>
          <div className="conversation-picker" aria-label="Conversations">
            {groups.map((group) => (
              <button
                key={group.id}
                aria-pressed={conversation.id === group.id}
                onClick={() => setSelected(group.id)}
              >
                <span className="conversation-faces">
                  {group.participants.slice(0, 3).map((id) => (
                    <CitizenPortrait key={id} name={name(id)} />
                  ))}
                </span>
                <span>
                  <strong>{group.participants.map(name).join(" & ")}</strong>
                  <small>
                    {group.messages.length} messages · Tick{" "}
                    {group.messages.at(-1)!.tick}
                  </small>
                </span>
                <MessageCircle size={15} />
              </button>
            ))}
          </div>
          <section
            className="conversation-thread"
            aria-label="Conversation transcript"
          >
            <header>
              <span className="eyebrow">
                {last?.end_conversation
                  ? "CONVERSATION ENDED"
                  : "RECENT CONVERSATION"}
              </span>
              <span>
                Tick {conversation.messages[0].tick}
                {last && last.tick !== conversation.messages[0].tick
                  ? `–${last.tick}`
                  : ""}
              </span>
            </header>
            <div className="conversation-participants">
              {conversation.participants.map((id) => (
                <button key={id} onClick={() => onAgent(id)}>
                  <CitizenPortrait name={name(id)} />
                  <span>{name(id)}</span>
                  <ArrowUpRight size={13} />
                </button>
              ))}
            </div>
            <div className="conversation-messages">
              {conversation.messages.map((message) => (
                <article
                  className={`speech-message ${message.speaker_id !== conversation.participants[0] ? "reply" : ""}`}
                  key={message.id}
                >
                  <button onClick={() => onAgent(message.speaker_id)}>
                    <strong>{name(message.speaker_id)}</strong>
                    <span>
                      to{" "}
                      {message.recipient_ids.map(name).join(", ") ||
                        "the neighborhood"}
                    </span>
                  </button>
                  <div className="speech-bubble">
                    <p>{message.text}</p>
                  </div>
                  <small>
                    {message.emotion} · Tick {message.tick}
                  </small>
                </article>
              ))}
            </div>
            {last?.end_conversation && (
              <p className="conversation-end">✦ Until next time.</p>
            )}
          </section>
        </>
      )}
    </>
  );
}
