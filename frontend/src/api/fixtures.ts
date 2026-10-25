/** Frontend-only deterministic review fixtures. These are not simulation physics. */
import type * as T from "./types";
import { scenarioFixture } from "./scenarioFixtures";
import { defaultConfig, defaultProfile, defaultSettings } from "./defaults";
export const fixtureDate = "2026-10-24T10:00:00.000Z";
export const baseline: T.Metrics = {
  happiness: 78,
  safety: 92,
  trust: 74,
  resources: 86,
  stress: 18,
};
export const floodAfter: T.Metrics = {
  happiness: 69,
  safety: 81,
  trust: 82,
  resources: 70,
  stress: 34,
};
export const area = [
  { x: 12, y: 12 },
  { x: 61, y: 12 },
  { x: 61, y: 58 },
  { x: 12, y: 58 },
];
const rect = (x: number, y: number, w: number, h: number) => [
  { x, y },
  { x: x + w, y },
  { x: x + w, y: y + h },
  { x, y: y + h },
];
const zones = [
  {
    id: "west",
    name: "West Quarter",
    polygon: rect(0, 0, 64, 128),
    metrics: { ...baseline },
    population: 15,
    population_density_per_km2: 1831,
  },
  {
    id: "east",
    name: "Garden District",
    polygon: rect(64, 0, 64, 128),
    metrics: {
      happiness: 82,
      safety: 94,
      trust: 76,
      resources: 88,
      stress: 14,
    },
    population: 15,
    population_density_per_km2: 1831,
  },
];
const buildings: T.MapData["buildings"] = [];
for (let row = 0; row < 5; row++)
  for (let col = 0; col < 5; col++) {
    const x = 12 + col * 22,
      y = 10 + row * 22;
    const kind: T.MapData["buildings"][number]["kind"] =
      row === 2 && col === 2
        ? "community"
        : row === 1 && col === 3
          ? "hospital"
          : row === 3 && col === 1
            ? "shelter"
            : (row + col) % 5 === 0
              ? "work"
              : (row + col) % 4 === 0
                ? "shop"
                : "home";
    buildings.push({
      id: `building-${row}-${col}`,
      name:
        kind === "community"
          ? "Community Square"
          : kind === "hospital"
            ? "St. Eden Clinic"
            : kind === "shelter"
              ? "Westside Shelter"
              : `${kind === "home" ? ((row + col) % 3 ? "Apartments" : "Townhouse") : kind === "work" ? "Company Offices" : (row + col) % 2 ? "Market" : "Restaurant"} at ${["Neon", "Circuit", "Cobalt", "Vector", "Quartz"][col]} Avenue & ${["Aurora", "Byte", "Chrome", "Datum", "Echo"][row]} Street`,
      kind,
      footprint: rect(x, y, 12, 10),
      entrance: { x: x + 6, y: y + 12 },
      height_m:
        kind === "work"
          ? 18
          : kind === "community"
            ? 9
            : 6 + ((row * 3 + col) % 5) * 2,
      capacity:
        kind === "hospital"
          ? 40
          : kind === "shelter"
            ? 110
            : kind === "community"
              ? 32
              : 3 + ((row * 7 + col * 3) % 9) * 2,
      occupancy: 2,
      functional: true,
    });
  }
export const fixtureMap: T.MapData = {
  id: "map-eden",
  seed: 42,
  width_m: 128,
  height_m: 128,
  cell_size_m: 2,
  columns: 64,
  rows: 64,
  cells: Array.from({ length: 4096 }, (_, i) => {
    const col = i % 64,
      row = Math.floor(i / 64);
    return {
      col,
      row,
      elevation_m: 0,
      terrain:
        col < 4 ? "water" : col % 11 < 3 || row % 11 < 3 ? "road" : "land",
      walkable: col >= 4,
      zone_id: col < 32 ? "west" : "east",
    };
  }),
  zones,
  buildings,
  resources: [
    {
      id: "food-store",
      kind: "food",
      position: { x: 68, y: 58 },
      available_units: 200,
    },
    {
      id: "water-store",
      kind: "water",
      position: { x: 90, y: 80 },
      available_units: 200,
    },
  ],
};
const names = [
  "Maya Chen",
  "Oliver Brooks",
  "Amara Okafor",
  "Leo Martinez",
  "Sofia Patel",
  "Noah Kim",
  "Isla Thompson",
  "Ethan Rivera",
  "Ava Laurent",
  "Jasper Reed",
  "Zara Ahmed",
  "Theo Wilson",
  "Luna Park",
  "Felix Morgan",
  "Ivy Santos",
  "Arlo James",
  "Nora Evans",
  "Kai Nakamura",
  "Freya Scott",
  "Milo Davis",
  "Ada Williams",
  "Oscar Green",
  "Mina Ali",
  "Eli Turner",
  "Ruby Clarke",
  "Hugo Silva",
  "Sage Bennett",
  "Finn Taylor",
  "Cleo Wright",
  "Alex Stone",
];
const roles = [
  "Community organizer",
  "Teacher",
  "Nurse",
  "Shopkeeper",
  "Engineer",
  "Student",
  "Gardener",
  "Researcher",
];
export function fixtureAgents(
  population = 30,
  profiles: T.CustomAgent[] = [],
): T.AgentSummary[] {
  return Array.from({ length: population }, (_, i) => ({
    id: `citizen-${i + 1}`,
    name:
      profiles[i]?.profile.name ??
      names[i % names.length] + (i >= 30 ? ` ${Math.floor(i / 30) + 1}` : ""),
    role: profiles[i]?.profile.role ?? roles[i % roles.length],
    position: {
      x: 18 + (i % 5) * 22,
      y: 23 + (Math.floor(i / 5) % 5) * 22 + (i >= 25 ? 3 : 0),
    },
    heading_rad: i % 3,
    path: [],
    movement_speed_mps: 1.4,
    metrics: { ...baseline },
    emotion: i % 3 === 0 ? "Hopeful" : "Calm",
    action: i % 5 === 0 ? "talk" : i % 4 === 0 ? "work" : "idle",
    action_target_id: null,
    latest_decision_id: `decision-${i + 1}`,
    thought_bubble: i === 0 ? "A little kindness goes a long way." : null,
    active: true,
  }));
}
export function fixtureSimulation(
  id = "preview-eden",
  config: T.Config = { ...defaultConfig, name: "New Eden" },
): T.Simulation {
  return {
    id,
    name: config.name,
    config: structuredClone(config),
    created_at: fixtureDate,
    updated_at: fixtureDate,
    status: "paused",
    pause_reason: "loaded",
    archived: false,
    tick: 0,
    revision: 0,
    control_version: 0,
    sim_time_seconds: 0,
    calendar_time_seconds: 8 * 3600,
    speed_multiplier: 1,
    achieved_ticks_per_second: 0,
    agent_count: config.population,
    parent_simulation_id: null,
    fork_ref: null,
    latest_snapshot_id: "snapshot-initial",
    saved_at: fixtureDate,
    pending_outcome_event_ids: [],
    initialization: {
      stage: "ready",
      progress: 100,
      message: "Your city is ready",
      error: null,
    },
    initial_preview: null,
  };
}
/** Urban review cities raise their homes and offices into towers. */
export function fixtureMapFor(config: T.Config): T.MapData {
  const map = structuredClone(fixtureMap);
  if (config.environment.settlement !== "urban") return map;
  return {
    ...map,
    buildings: map.buildings.map((b, i) => ({
      ...b,
      height_m:
        b.kind === "work" || b.kind === "home"
          ? i % 8 === 3
            ? 40 + ((i * 17) % 45)
            : 12 + ((i * 7) % 12)
          : b.height_m,
    })),
  };
}
export function fixtureWorld(
  simulation = fixtureSimulation(),
  agents = fixtureAgents(simulation.agent_count),
): T.WorldFrame {
  return {
    ref: { tick: simulation.tick, revision: simulation.revision },
    simulation: structuredClone(simulation),
    map: fixtureMapFor(simulation.config),
    agents,
    events: [],
    policies: {
      evacuation_order: false,
      ration_units_per_agent: null,
      aid_multiplier: 1,
    },
    metrics: {
      tick: simulation.tick,
      revision: simulation.revision,
      values: { ...baseline },
      cooperation_count: 0,
      conflict_count: 0,
      resources_consumed: 0,
      evacuated_count: 0,
      exposed_count: 0,
    },
    recent_dialogue: [],
    curfew: {
      enabled: false,
      start_minute: 1320,
      end_minute: 360,
      revision: 0,
      informed_agent_ids: [],
    },
    conversation_sessions: [],
    active_hazards: [],
  };
}
export const emptyEvidence: T.Evidence = {
  event_ids: [],
  decision_ids: [],
  memory_ids: [],
  description: "Recorded fixture observation.",
};
export function fixtureDetail(
  frame: T.WorldFrame,
  id: string,
  template?: T.Profile,
): T.AgentDetail {
  const a = frame.agents.find((a) => a.id === id)!;
  const memory: T.Memory = {
    id: `memory-${id}`,
    tick: 0,
    text: "I met my neighbors at Community Square. We agreed to look out for each other.",
    importance: 72,
    source: "observed",
    subject_ids: ["citizen-2"],
    evidence: emptyEvidence,
  };
  const decision: T.Decision = {
    id: a.latest_decision_id ?? `decision-${id}`,
    agent_id: id,
    tick: 0,
    source: "rules",
    intent: {
      action: "help",
      target_id: "citizen-2",
      destination: null,
      parameters: {
        resource_kind: null,
        amount: null,
        message: "Let me help.",
      },
      motivation: "Looking out for a neighbor matters to me.",
      emotion: "Concerned",
    },
    observed_facts: [
      "Oliver is within speaking distance.",
      "The community shelter is open.",
    ],
    memory_ids: [memory.id],
    relationship_agent_ids: ["citizen-2"],
    concise_rationale:
      "I know Oliver from the square. Helping now makes it easier for us to prepare together.",
    outcome: id === "citizen-3" ? "rejected" : "accepted",
    outcome_description:
      id === "citizen-3"
        ? "Help rejected: recipient is outside the permitted interaction range."
        : "Shared the location of the community shelter.",
    rejection_code: id === "citizen-3" ? "OUT_OF_RANGE" : null,
    effects:
      id === "citizen-3"
        ? []
        : [{ entity_id: id, field: "trust", before: 72, after: 74 }],
    event_ids: [],
  };
  return {
    ref: frame.ref,
    agent: a,
    profile: template ?? {
      ...defaultProfile,
      name: a.name,
      role: a.role,
      background:
        "A resident of New Eden who enjoys bringing neighbors together.",
      personality: "Thoughtful, curious, and community minded.",
      primary_goal: "Build a resilient neighborhood",
      values: ["Kindness", "Community"],
      skills: ["Organizing", "Listening"],
    },
    home: { x: 18, y: 20 },
    needs: { hunger: 20, fatigue: 15, health: 100, social: 65 },
    inventory: { food: 8, water: 10, supplies: 7 },
    reputation: 78,
    beliefs: [
      {
        text: "Neighbors can accomplish more when they work together.",
        confidence: 82,
        evidence: emptyEvidence,
      },
    ],
    goals: [
      "Build a resilient neighborhood",
      "Make sure everyone knows where the shelter is",
    ],
    memories: { items: [memory], next_cursor: null },
    relationships: {
      items: [
        {
          from_agent_id: id,
          to_agent_id: id === "citizen-2" ? "citizen-1" : "citizen-2",
          kind: "friend",
          trust: 78,
          affection: 72,
          respect: 81,
          familiarity: 65,
          conflict: 6,
          desired_relationship: "A reliable friend",
          shared_history: [memory.id],
          evidence: emptyEvidence,
        },
      ],
      next_cursor: null,
    },
    decisions: { items: [decision], next_cursor: null },
    major_event_ids: frame.events.map((e) => e.id),
    metric_reasons: [
      {
        metric: "trust",
        delta: 2,
        evidence: {
          ...emptyEvidence,
          decision_ids: [decision.id],
          description: "A successful exchange with a neighbor.",
        },
      },
    ],
  };
}
export function fixturePreview(
  frame: T.WorldFrame,
  source: T.ScenarioPreview["source"] = "random",
  prompt = "",
): T.ScenarioPreview {
  return scenarioFixture(frame, source, prompt);
}

export const fixtureSettings = structuredClone(defaultSettings);
// Fixed recorded poses. The adapter selects a sample; it does not compute navigation.
export const recordedOffsets = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(
  (n) => ({ x: n * 0.15, y: 0 }),
);

/** Fixed outcome samples for the review adapter; never used by the live client. */
export const recordedOutcomes = {
  flood: {
    values: floodAfter,
    cooperation: 14,
    conflicts: 2,
    consumed: 36,
    evacuated: 10,
    exposed: 2,
    consequence:
      "10 initially exposed citizens reached safety. Neighbors shared supplies during the event.",
    lesson:
      "Prior knowledge of the shelter supported preparation in this recorded fixture.",
  },
  fire: {
    values: { happiness: 67, safety: 79, trust: 80, resources: 68, stress: 38 },
    cooperation: 12,
    conflicts: 2,
    consumed: 38,
    evacuated: 9,
    exposed: 3,
    consequence:
      "9 initially exposed citizens reached safety during the recorded fire.",
    lesson: "Shared knowledge of safe gathering places supported the response.",
  },
  storm: {
    values: { happiness: 71, safety: 83, trust: 79, resources: 74, stress: 31 },
    cooperation: 11,
    conflicts: 1,
    consumed: 28,
    evacuated: 10,
    exposed: 2,
    consequence:
      "Citizens shared shelter information during the recorded storm.",
    lesson: "Nearby shelters gave neighbors a common destination.",
  },
  festival: {
    values: { happiness: 86, safety: 92, trust: 82, resources: 78, stress: 12 },
    cooperation: 18,
    conflicts: 0,
    consumed: 24,
    evacuated: 0,
    exposed: 0,
    consequence:
      "Citizens gathered at Community Square and shared food in the recorded festival.",
    lesson: "A common gathering place created opportunities for conversation.",
  },
  outage: {
    values: { happiness: 71, safety: 84, trust: 76, resources: 80, stress: 33 },
    cooperation: 8,
    conflicts: 1,
    consumed: 18,
    evacuated: 0,
    exposed: 0,
    consequence:
      "Affected infrastructure was unavailable during the recorded outage.",
    lesson: "Shared supplies helped citizens adjust their routines.",
  },
  shortage: {
    values: { happiness: 70, safety: 90, trust: 77, resources: 57, stress: 30 },
    cooperation: 9,
    conflicts: 4,
    consumed: 16,
    evacuated: 0,
    exposed: 0,
    consequence:
      "Food availability fell and citizens shared available supplies in this recorded shortage.",
    lesson: "Resource access was uneven across the recorded interval.",
  },
  misinformation: {
    values: { happiness: 72, safety: 90, trust: 62, resources: 84, stress: 39 },
    cooperation: 4,
    conflicts: 3,
    consumed: 6,
    evacuated: 0,
    exposed: 0,
    consequence:
      "An unverified warning spread between citizens in the recorded exchange.",
    lesson:
      "Citizens encountered conflicting information from their social contacts.",
  },
  policy: {
    values: { happiness: 80, safety: 95, trust: 80, resources: 83, stress: 14 },
    cooperation: 16,
    conflicts: 0,
    consumed: 20,
    evacuated: 0,
    exposed: 0,
    consequence:
      "The recorded community aid policy made additional supplies available.",
    lesson:
      "Policy effects are recorded separately from suggestions about future runs.",
  },
  custom: {
    values: { happiness: 82, safety: 92, trust: 80, resources: 81, stress: 16 },
    cooperation: 12,
    conflicts: 0,
    consumed: 20,
    evacuated: 0,
    exposed: 0,
    consequence: "Citizens participated in a recorded community aid activity.",
    lesson: "The aid center provided a shared point of contact.",
  },
} satisfies Record<
  T.EventSpec["kind"],
  {
    values: T.Metrics;
    cooperation: number;
    conflicts: number;
    consumed: number;
    evacuated: number;
    exposed: number;
    consequence: string;
    lesson: string;
  }
>;
