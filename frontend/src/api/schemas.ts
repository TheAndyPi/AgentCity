import { z } from "zod";
import type * as T from "./types";
import { defaultConfig, defaultTraits } from "./defaults";
const obj = z.object;
const finite = z.number().finite();
const count = finite.int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const pct = finite.min(0).max(100);
const id = z.string().min(1).max(200);
const text = z.string().max(2000);
const name = z
  .string()
  .min(1)
  .max(80)
  .refine((v) => v === v.trim(), "Names must be trimmed");
const recordIds = z.array(id);
const ids = z
  .array(id)
  .max(100)
  .refine((a) => new Set(a).size === a.length, "IDs must be unique");
const date = z
  .string()
  .datetime({ offset: true })
  .refine((v) => /(?:Z|\+00:00)$/.test(v), "Timestamp must be UTC");
export const vec = obj({ x: finite, y: finite }).strict();
export const ref = obj({ tick: count, revision: count }).strict();
export const metric = z.enum([
  "happiness",
  "safety",
  "trust",
  "resources",
  "stress",
]);
export const metrics = obj({
  happiness: pct,
  safety: pct,
  trust: pct,
  resources: pct,
  stress: pct,
}).strict();
const deltas = obj({
  happiness: finite,
  safety: finite,
  trust: finite,
  resources: finite,
  stress: finite,
}).strict();
export const traits = obj({
  curiosity: pct,
  empathy: pct,
  sociability: pct,
  trust: pct,
  cooperation: pct,
  risk_tolerance: pct,
}).strict();
export const profile: z.ZodType<T.Profile> = obj({
  name,
  age: count.max(120),
  role: name,
  background: text,
  personality: text,
  values: z.array(text),
  traits,
  primary_goal: text,
  secondary_goals: z.array(text),
  desires: z.array(text),
  fears: z.array(text),
  personal_history: text,
  skills: z.array(text),
  intelligence: pct,
  mobility: pct,
  physical_attributes: text,
  social_needs: pct,
}).strict();
const configObject = obj({
  name,
  seed: count.max(2147483647),
  mode: z.enum(["sandbox", "behavior_lab", "crisis_lab", "policy_lab"]),
  population: count.min(10).max(100),
  population_traits: traits,
  household_supplies: pct,
  personality_diversity: pct,
  environment: obj({
    resource_availability: pct,
    population_density: pct,
    infrastructure_capacity: pct,
    initial_community_trust: pct,
    settlement: z.enum(["urban", "suburb"]),
  }).strict(),
  scenario_description: z.string().max(4000),
  custom_agent_ids: ids,
  tick_seconds: z.union([z.literal(1), z.literal(10)]),
  max_ticks: count.min(1).max(100000),
}).strict();
export const config: z.ZodType<T.Config, T.Config> = configObject.refine(
  (c) => c.custom_agent_ids.length <= c.population,
  {
    message: "Custom citizens must fit within the population.",
    path: ["custom_agent_ids"],
  },
);
// Setup requests may omit documented defaults; response Config stays complete.
export const configRequest = configObject
  .omit({ population_traits: true, environment: true })
  .partial({
    mode: true,
    population: true,
    household_supplies: true,
    personality_diversity: true,
    scenario_description: true,
    custom_agent_ids: true,
    tick_seconds: true,
    max_ticks: true,
  })
  .extend({
    population_traits: traits.partial().optional(),
    environment: configObject.shape.environment.partial().optional(),
  })
  .transform((c) => ({
    ...defaultConfig,
    ...c,
    population_traits: { ...defaultTraits, ...c.population_traits },
    environment: { ...defaultConfig.environment, ...c.environment },
  }))
  .pipe(config);
export const createSimulationRequest = obj({ config: configRequest }).strict();
export const error = obj({
  code: id,
  message: text,
  retryable: z.boolean(),
  details: z.array(
    obj({ field: z.string().nullable(), reason: text }).strict(),
  ),
}).strict();
export const failure = obj({
  schema_version: z.literal("1.0.0"),
  request_id: id,
  error,
}).strict();
export const evidence = obj({
  event_ids: recordIds,
  decision_ids: recordIds,
  memory_ids: recordIds,
  description: text,
}).strict();
const polygon = z.array(vec).min(3);
const multiplier = finite.min(0).max(3);
export const policies = obj({
  evacuation_order: z.boolean(),
  ration_units_per_agent: finite.nonnegative().nullable(),
  aid_multiplier: multiplier,
}).strict();
export const effect = z.discriminatedUnion("type", [
  obj({
    type: z.literal("wellbeing"),
    happiness_delta: finite.min(-2).max(2),
    stress_delta: finite.min(-2).max(2),
    health_delta: finite.min(-2).max(2),
  }).strict(),
  obj({
    type: z.literal("hazard"),
    hazard: z.enum(["flood", "fire", "storm"]),
    severity: pct,
  }).strict(),
  obj({
    type: z.literal("resource_multiplier"),
    resource: z.enum(["food", "water", "supplies"]),
    multiplier,
  }).strict(),
  obj({
    type: z.literal("infrastructure"),
    functional: z.boolean(),
    capacity_multiplier: multiplier,
  }).strict(),
  obj({
    type: z.literal("information"),
    message: text,
    reliability: pct,
    delivery: z.enum(["local", "broadcast"]),
  }).strict(),
  obj({
    type: z.literal("community"),
    activity: z.enum(["festival", "aid"]),
    capacity: count,
  }).strict(),
  obj({ type: z.literal("policy"), ...policies.shape }).strict(),
]);
const kind = z.enum([
  "flood",
  "fire",
  "storm",
  "shortage",
  "outage",
  "misinformation",
  "festival",
  "policy",
  "custom",
]);
export const scenePart = obj({
  shape: z.enum(["box", "sphere", "cone", "cylinder"]),
  offset: obj({
    x: finite.min(-8).max(8),
    y: finite.min(0).max(10),
    z: finite.min(-8).max(8),
  }).strict(),
  size: obj({
    x: finite.min(0.1).max(8),
    y: finite.min(0.1).max(8),
    z: finite.min(0.1).max(8),
  }).strict(),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
}).strict();
export const sceneObject = obj({
  model: z.enum([
    "flood",
    "fire",
    "cloud",
    "crates",
    "generator",
    "broadcast",
    "stage",
    "stall",
    "tree",
    "dinosaur",
    "spacecraft",
    "robot",
    "barrier",
    "clinic",
    "snow",
    "heat",
    "meteor",
    "monument",
    "portal",
    "visitor",
    "deer",
    "generated",
  ]),
  label: name,
  position: vec,
  scale: finite.min(0.5).max(4),
  rotation: finite.min(0).max(6.284),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  parts: z.array(scenePart).max(8).optional(),
}).strict();
export const eventSpec = obj({
  title: name,
  description: text,
  kind,
  origin: vec,
  affected_polygon: polygon,
  severity: pct,
  duration_ticks: count.min(1).max(1000),
  effects: z.array(effect).max(20),
  success_condition: z.enum(["duration_elapsed", "all_safe_or_duration"]),
  scene: z.array(sceneObject).max(24).optional(),
}).strict();
export const preview: z.ZodType<T.ScenarioPreview> = obj({
  id,
  simulation_id: id,
  source: z.enum(["random", "repeat", "custom", "policy", "initial"]),
  source_event_id: id.nullable(),
  based_on: ref,
  expires_at: date,
  interpretation: text,
  spec: eventSpec,
  affected_agent_ids: recordIds,
  affected_building_ids: recordIds,
  warnings: z.array(text),
  unsupported_requests: z.array(text),
  can_commit: z.boolean(),
}).strict();
export const speed = z.union([
  z.literal(0.25),
  z.literal(0.5),
  z.literal(1),
  z.literal(2),
  z.literal(5),
  z.literal(10),
]);
export const simulation: z.ZodType<T.Simulation> = obj({
  id,
  name,
  config,
  created_at: date,
  updated_at: date,
  status: z.enum(["initializing", "paused", "running", "completed", "failed"]),
  pause_reason: z
    .enum(["manual", "intervention", "outcome", "loaded", "error"])
    .nullable(),
  archived: z.boolean(),
  tick: count,
  revision: count,
  control_version: count,
  sim_time_seconds: finite.nonnegative(),
  speed_multiplier: speed,
  achieved_ticks_per_second: finite.nonnegative(),
  agent_count: count,
  parent_simulation_id: id.nullable(),
  fork_ref: ref.nullable(),
  latest_snapshot_id: id.nullable(),
  saved_at: date.nullable(),
  pending_outcome_event_ids: recordIds,
  initialization: obj({
    stage: z.enum([
      "queued",
      "map",
      "population",
      "relationships",
      "scenario",
      "persistence",
      "ready",
      "failed",
    ]),
    progress: finite.min(0).max(100),
    message: text,
    error: error.nullable(),
  }).strict(),
  initial_preview: preview.nullable(),
}).strict();
export const map: z.ZodType<T.MapData> = obj({
  id,
  seed: count.max(2147483647),
  width_m: finite.positive(),
  height_m: finite.positive(),
  cell_size_m: finite.positive(),
  columns: count.positive(),
  rows: count.positive(),
  cells: z.array(
    obj({
      col: count,
      row: count,
      elevation_m: finite,
      terrain: z.enum(["land", "road", "water"]),
      walkable: z.boolean(),
      zone_id: id,
    }).strict(),
  ),
  zones: z.array(
    obj({
      id,
      name,
      polygon,
      metrics,
      population: count,
      population_density_per_km2: finite.nonnegative(),
    }).strict(),
  ),
  buildings: z.array(
    obj({
      id,
      name,
      kind: z.enum([
        "home",
        "work",
        "shop",
        "shelter",
        "hospital",
        "community",
      ]),
      footprint: polygon,
      entrance: vec,
      height_m: finite.nonnegative(),
      capacity: count,
      occupancy: count,
      functional: z.boolean(),
    }).strict(),
  ),
  resources: z.array(
    obj({
      id,
      kind: z.enum(["food", "water", "supplies"]),
      position: vec,
      available_units: finite.nonnegative(),
    }).strict(),
  ),
}).strict();
export const action = z.enum([
  "idle",
  "move",
  "work",
  "rest",
  "consume",
  "gather",
  "talk",
  "warn",
  "help",
  "trade",
  "evacuate",
]);
export const intent = obj({
  action,
  target_id: id.nullable(),
  destination: vec.nullable(),
  parameters: obj({
    resource_kind: z.enum(["food", "water", "supplies"]).nullable(),
    amount: finite.positive().nullable(),
    message: text.nullable(),
  }).strict(),
  motivation: text,
  emotion: text,
}).strict();
export const agent: z.ZodType<T.AgentSummary> = obj({
  id,
  name,
  role: name,
  position: vec,
  heading_rad: finite,
  path: z.array(vec),
  movement_speed_mps: finite.nonnegative(),
  metrics,
  emotion: text,
  action,
  action_target_id: id.nullable(),
  latest_decision_id: id.nullable(),
  thought_bubble: text.nullable(),
  active: z.boolean(),
}).strict();
export const memory: z.ZodType<T.Memory> = obj({
  id,
  tick: count,
  text,
  importance: pct,
  source: z.enum(["observed", "heard", "reflection", "injected"]),
  subject_ids: recordIds,
  evidence,
}).strict();
export const relationship: z.ZodType<T.Relationship> = obj({
  from_agent_id: id,
  to_agent_id: id,
  kind: z.enum([
    "family",
    "friend",
    "acquaintance",
    "rival",
    "romantic",
    "stranger",
  ]),
  trust: pct,
  affection: pct,
  respect: pct,
  familiarity: pct,
  conflict: pct,
  desired_relationship: text,
  shared_history: recordIds,
  evidence,
}).strict();
export const decision: z.ZodType<T.Decision> = obj({
  id,
  agent_id: id,
  tick: count,
  source: z.enum(["gemini", "rules", "replay"]),
  intent,
  observed_facts: z.array(text),
  memory_ids: recordIds,
  relationship_agent_ids: recordIds,
  concise_rationale: text,
  outcome: z.enum(["accepted", "rejected", "modified", "pending"]),
  outcome_description: text,
  rejection_code: id.nullable(),
  effects: z.array(
    obj({
      entity_id: id,
      field: id,
      before: z.union([z.string(), finite, z.boolean(), z.null()]),
      after: z.union([z.string(), finite, z.boolean(), z.null()]),
    }).strict(),
  ),
  event_ids: recordIds,
}).strict();
export const page = <S extends z.ZodTypeAny>(s: S) =>
  obj({ items: z.array(s), next_cursor: z.string().nullable() }).strict();
export const agentDetail: z.ZodType<T.AgentDetail> = obj({
  ref,
  agent,
  profile,
  home: vec,
  needs: obj({ hunger: pct, fatigue: pct, health: pct, social: pct }).strict(),
  inventory: obj({
    food: finite.nonnegative(),
    water: finite.nonnegative(),
    supplies: finite.nonnegative(),
  }).strict(),
  reputation: pct,
  beliefs: z.array(obj({ text, confidence: pct, evidence }).strict()),
  goals: z.array(text),
  memories: page(memory),
  relationships: page(relationship),
  decisions: page(decision),
  major_event_ids: recordIds,
  metric_reasons: z.array(obj({ metric, delta: finite, evidence }).strict()),
}).strict();
export const event: z.ZodType<T.EventSummary> = obj({
  id,
  title: name,
  kind,
  status: z.enum(["queued", "active", "resolved", "cancelled"]),
  queued_tick: count,
  start_tick: count.nullable(),
  end_tick: count.nullable(),
  affected_agent_count: count,
  affected_polygon: polygon,
  pre_event_snapshot_id: id,
  summary: text,
  scene: z.array(sceneObject).max(24).optional(),
}).strict();
export const eventReport: z.ZodType<T.EventReport> = obj({
  ref,
  event,
  spec: eventSpec,
  before: metrics,
  after: metrics,
  delta: deltas,
  affected_agent_ids: recordIds,
  conflicts: count,
  resources_consumed: finite.nonnegative(),
  evacuated_count: count,
  exposed_count: count,
  consequences: z.array(obj({ text, evidence }).strict()),
  community_lessons: z.array(obj({ text, evidence }).strict()),
  suggested_preparations: z.array(text),
}).strict();
export const dialogue = obj({
  id,
  interaction_id: id,
  tick: count,
  speaker_id: id,
  recipient_ids: ids,
  audible_to_ids: ids,
  text,
  intent: text,
  emotion: text,
  end_conversation: z.boolean(),
}).strict();
export const metricPoint = obj({
  tick: count,
  revision: count,
  values: metrics,
  cooperation_count: count,
  conflict_count: count,
  resources_consumed: finite.nonnegative(),
  evacuated_count: count,
  exposed_count: count,
}).strict();
const worldFields = {
  ref,
  simulation,
  map,
  map_version: count.optional(),
  agents: z.array(agent),
  events: z.array(event),
  policies,
  metrics: metricPoint,
  recent_dialogue: z.array(dialogue),
  active_hazards: z.array(
    obj({
      event_id: id,
      kind: z.enum(["flood", "fire", "storm"]),
      polygon,
      severity: pct,
    }).strict(),
  ),
};
export const world: z.ZodType<T.WorldFrame> = obj(worldFields).strict();
// Delta validation skips the large, unchanged map on the hot stream path.
export const streamFrame: z.ZodType<T.FrameDelta> = obj({
  ...worldFields,
  map: map.nullable().optional(),
  map_updates: obj({
    zones: z.array(
      obj({
        id,
        metrics,
        population: count,
        population_density_per_km2: finite.nonnegative(),
      }).strict(),
    ),
    buildings: z.array(
      obj({
        id,
        capacity: count,
        occupancy: count,
        functional: z.boolean(),
      }).strict(),
    ),
    resources: z.array(
      obj({ id, available_units: finite.nonnegative() }).strict(),
    ),
  })
    .strict()
    .nullable()
    .optional(),
}).strict();
export const snapshot = obj({
  id,
  simulation_id: id,
  ref,
  created_at: date,
  reason: z.enum([
    "initial",
    "manual",
    "autosave",
    "navigation",
    "pre_event",
    "branch",
  ]),
  label: z.string(),
}).strict();
export const overview = obj({
  ref,
  metrics: metricPoint,
  top_events: z.array(
    obj({ event_id: id, title: name, impact_score: finite, evidence }).strict(),
  ),
  improvements: z.array(obj({ metric, delta: finite, evidence }).strict()),
  metric_reasons: z.array(obj({ metric, text, evidence }).strict()),
}).strict();
export const customAgent = obj({
  id,
  version: count,
  profile,
  updated_at: date,
}).strict();
export const settings: z.ZodType<T.Settings> = obj({
  version: count,
  theme: z.enum(["dark", "light"]),
  view_mode: z.enum(["3d", "2d"]),
  autosave: z.boolean(),
  reduce_motion: z.boolean(),
  shortcuts: obj({
    pause: id,
    zoom_in: id,
    zoom_out: id,
    rotate_left: id,
    rotate_right: id,
    pan_up: id,
    pan_down: id,
    pan_left: id,
    pan_right: id,
  })
    .strict()
    .refine(
      (s) => new Set(Object.values(s)).size === 9,
      "Each shortcut must be unique",
    )
    .refine(
      (s) =>
        Object.values(s).every((v) =>
          /^(?:Mod\+)?(?:Alt\+)?(?:Shift\+)?(?:Key[A-Z]|Digit[0-9]|Arrow(?:Up|Down|Left|Right)|Space|Equal|Minus|Enter|Escape|Tab|Backspace|Delete|Home|End|PageUp|PageDown|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Backquote|F(?:[1-9]|1[0-2]))$/.test(
            v,
          ),
        ),
      "Use canonical chords such as Mod+Equal",
    ),
}).strict();
export const usage = obj({
  simulation_id: id.nullable(),
  input_tokens: count,
  output_tokens: count,
  cached_tokens: count,
  calls: count,
  failed_calls: count,
  estimated_cost_usd: finite.nonnegative().nullable(),
  pricing_as_of: date.nullable(),
}).strict();
export const capabilities = obj({
  contract_version: z.literal("1.0.0"),
  auth_mode: z.enum(["local", "session"]),
  max_agents: count,
  max_concurrent_running_simulations: count,
  gemini: z.boolean(),
  narration: z.boolean(),
  snowflake: z.boolean(),
  persistence: z.enum(["local", "postgres"]),
  replay: z.boolean(),
  branching: z.boolean(),
}).strict();
export const intervention = obj({
  id,
  simulation_id: id,
  expires_at: date,
  based_on: ref,
  was_running: z.boolean(),
  control_version: count,
}).strict();
export const command = z.discriminatedUnion("type", [
  obj({ type: z.literal("play") }).strict(),
  obj({ type: z.literal("pause") }).strict(),
  obj({ type: z.literal("step"), count: count.min(1).max(10) }).strict(),
  obj({ type: z.literal("set_speed"), value: speed }).strict(),
  obj({
    type: z.literal("save"),
    reason: z.enum(["manual", "navigation"]),
    label: z.string().max(2000),
  }).strict(),
  obj({ type: z.literal("archive") }).strict(),
  obj({ type: z.literal("unarchive") }).strict(),
  obj({
    type: z.literal("add_agents"),
    custom_agent_ids: ids.refine(
      (a) => a.length > 0,
      "Choose at least one profile",
    ),
  }).strict(),
  obj({
    type: z.literal("override_agent"),
    agent_id: id,
    metrics: metrics.partial(),
    goal: text.nullable(),
    memory_text: text.nullable(),
    intent: intent.nullable(),
  }).strict(),
  obj({
    type: z.literal("acknowledge_outcome"),
    event_id: id,
    resume: z.boolean(),
  }).strict(),
]);
export const commandRequest = obj({
  // v1 accepts every canonical hexadecimal UUID, without version/variant limits.
  // Zod 4's uuid() additionally enforces RFC variant bits, unlike this contract.
  request_id: z
    .string()
    .regex(
      /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/,
    ),
  expected_control_version: count,
  command,
}).strict();
export const commandResult = obj({
  simulation,
  snapshot: snapshot.nullable(),
  affected_agent_ids: recordIds,
}).strict();
export function success<T>(s: z.ZodType<T>): z.ZodType<T.Success<T>>;
export function success(s: z.ZodType): z.ZodType {
  return obj({
    schema_version: z.literal("1.0.0"),
    request_id: id,
    data: s,
  }).strict();
}
export const serverMessage = z.discriminatedUnion("type", [
  obj({
    schema_version: z.literal("1.0.0"),
    simulation_id: id,
    sent_at: date,
    type: z.literal("snapshot"),
    data: world,
  }).strict(),
  obj({
    schema_version: z.literal("1.0.0"),
    simulation_id: id,
    sent_at: date,
    type: z.literal("frame"),
    data: streamFrame,
  }).strict(),
  obj({
    schema_version: z.literal("1.0.0"),
    simulation_id: id,
    sent_at: date,
    type: z.literal("initialization"),
    data: simulation,
  }).strict(),
  obj({
    schema_version: z.literal("1.0.0"),
    simulation_id: id,
    sent_at: date,
    type: z.literal("heartbeat"),
    data: obj({
      revision: count,
      status: z.enum([
        "initializing",
        "paused",
        "running",
        "completed",
        "failed",
      ]),
    }).strict(),
  }).strict(),
  obj({
    schema_version: z.literal("1.0.0"),
    simulation_id: id,
    sent_at: date,
    type: z.literal("error"),
    data: error,
  }).strict(),
]);

export const previewRequest = obj({
  intervention_id: id,
  source: z.enum(["random", "repeat", "custom", "policy"]),
  source_event_id: id.nullable(),
  prompt: z.string().max(4000).nullable(),
  policy: policies.nullable(),
})
  .strict()
  .superRefine((r, ctx) => {
    const valid =
      r.source === "random"
        ? r.source_event_id === null && r.prompt === null && r.policy === null
        : r.source === "repeat"
          ? r.source_event_id !== null && r.prompt === null && r.policy === null
          : r.source === "custom"
            ? r.source_event_id === null &&
              !!r.prompt?.trim() &&
              r.policy === null
            : r.source_event_id === null &&
              r.prompt === null &&
              r.policy !== null;
    if (!valid)
      ctx.addIssue({
        code: "custom",
        message: "Preview fields must match the selected source.",
      });
  });
export const branchRequest = obj({
  name,
  source: z.discriminatedUnion("kind", [
    obj({ kind: z.literal("whole") }).strict(),
    obj({ kind: z.literal("revision"), revision: count }).strict(),
    obj({ kind: z.literal("snapshot"), snapshot_id: id }).strict(),
  ]),
}).strict();
export const interventionRequest = obj({
  expected_control_version: count,
}).strict();
export const initialRequest = obj({
  preview_id: id,
  decision: z.enum(["confirm", "skip"]),
  expected_control_version: count,
}).strict();
export const commitRequest = obj({
  intervention_id: id,
  preview_id: id,
  expected_control_version: count,
}).strict();
