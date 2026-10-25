// Mechanical TypeScript projection of the supplied contract v1.0.0.
export type ID = string;
export type Pct = number;
export type ISODate = string;
export type Mode = "sandbox" | "behavior_lab" | "crisis_lab" | "policy_lab";
export type Speed = 0.25 | 0.5 | 1 | 2 | 5 | 10;
export type Metric = "happiness" | "safety" | "trust" | "resources" | "stress";
export type Metrics = Record<Metric, Pct>;
export type Vec2 = { x: number; y: number };
export type Ref = { tick: number; revision: number };
export type Evidence = {
  event_ids: ID[];
  decision_ids: ID[];
  memory_ids: ID[];
  description: string;
};
export type Success<T> = { schema_version: "1.0.0"; request_id: ID; data: T };
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Failure = {
  schema_version: "1.0.0";
  request_id: ID;
  error: {
    code: string;
    message: string;
    retryable: boolean;
    details: { field: string | null; reason: string }[];
  };
};
export type Traits = {
  curiosity: Pct;
  empathy: Pct;
  sociability: Pct;
  trust: Pct;
  cooperation: Pct;
  risk_tolerance: Pct;
};
export type Profile = {
  name: string;
  age: number;
  role: string;
  background: string;
  personality: string;
  values: string[];
  traits: Traits;
  primary_goal: string;
  secondary_goals: string[];
  desires: string[];
  fears: string[];
  personal_history: string;
  skills: string[];
  intelligence: Pct;
  mobility: Pct;
  physical_attributes: string;
  social_needs: Pct;
};
export type CustomAgent = {
  id: ID;
  version: number;
  profile: Profile;
  updated_at: ISODate;
};
export type Config = {
  name: string;
  seed: number;
  mode: Mode;
  population: number;
  population_traits: Traits;
  household_supplies: Pct;
  personality_diversity: Pct;
  environment: {
    resource_availability: Pct;
    population_density: Pct;
    infrastructure_capacity: Pct;
    initial_community_trust: Pct;
    settlement: "urban" | "suburb";
  };
  scenario_description: string;
  custom_agent_ids: ID[];
  tick_seconds: number;
  calendar_seconds_per_tick?: number;
  max_ticks: number;
};
export type Job = {
  stage:
    | "queued"
    | "map"
    | "population"
    | "relationships"
    | "scenario"
    | "persistence"
    | "ready"
    | "failed";
  progress: number;
  message: string;
  error: Failure["error"] | null;
};
export type Simulation = {
  id: ID;
  name: string;
  config: Config;
  created_at: ISODate;
  updated_at: ISODate;
  status: "initializing" | "paused" | "running" | "completed" | "failed";
  pause_reason:
    | "manual"
    | "intervention"
    | "outcome"
    | "loaded"
    | "error"
    | null;
  archived: boolean;
  tick: number;
  revision: number;
  control_version: number;
  sim_time_seconds: number;
  calendar_time_seconds?: number;
  speed_multiplier: Speed;
  achieved_ticks_per_second: number;
  agent_count: number;
  parent_simulation_id: ID | null;
  fork_ref: Ref | null;
  latest_snapshot_id: ID | null;
  saved_at: ISODate | null;
  pending_outcome_event_ids: ID[];
  initialization: Job;
  initial_preview: ScenarioPreview | null;
};
export type MapData = {
  id: ID;
  seed: number;
  width_m: number;
  height_m: number;
  cell_size_m: number;
  columns: number;
  rows: number;
  cells: {
    col: number;
    row: number;
    elevation_m: number;
    terrain: "land" | "road" | "water";
    walkable: boolean;
    zone_id: ID;
  }[];
  zones: {
    id: ID;
    name: string;
    polygon: Vec2[];
    metrics: Metrics;
    population: number;
    population_density_per_km2: number;
  }[];
  buildings: {
    id: ID;
    name: string;
    kind: "home" | "work" | "shop" | "shelter" | "hospital" | "community";
    footprint: Vec2[];
    entrance: Vec2;
    height_m: number;
    capacity: number;
    occupancy: number;
    functional: boolean;
  }[];
  resources: {
    id: ID;
    kind: "food" | "water" | "supplies";
    position: Vec2;
    available_units: number;
  }[];
};
export type ActionName =
  | "idle"
  | "move"
  | "work"
  | "rest"
  | "consume"
  | "gather"
  | "talk"
  | "warn"
  | "help"
  | "trade"
  | "evacuate";
export type Intent = {
  action: ActionName;
  target_id: ID | null;
  destination: Vec2 | null;
  parameters: {
    resource_kind: "food" | "water" | "supplies" | null;
    amount: number | null;
    message: string | null;
  };
  motivation: string;
  emotion: string;
};
export type AgentSummary = {
  routine_state?: string;
  activity_until_calendar_seconds?: number | null;
  id: ID;
  name: string;
  role: string;
  position: Vec2;
  heading_rad: number;
  path: Vec2[];
  movement_speed_mps: number;
  metrics: Metrics;
  emotion: string;
  action: ActionName;
  action_target_id: ID | null;
  latest_decision_id: ID | null;
  thought_bubble: string | null;
  active: boolean;
};
export type Memory = {
  id: ID;
  tick: number;
  text: string;
  importance: Pct;
  source: "observed" | "heard" | "reflection" | "injected";
  subject_ids: ID[];
  evidence: Evidence;
};
export type Relationship = {
  from_agent_id: ID;
  to_agent_id: ID;
  kind:
    | "family"
    | "friend"
    | "acquaintance"
    | "rival"
    | "romantic"
    | "stranger";
  trust: Pct;
  affection: Pct;
  respect: Pct;
  familiarity: Pct;
  conflict: Pct;
  desired_relationship: string;
  shared_history: ID[];
  evidence: Evidence;
};
export type Decision = {
  id: ID;
  agent_id: ID;
  tick: number;
  source: "gemini" | "rules" | "replay";
  intent: Intent;
  observed_facts: string[];
  memory_ids: ID[];
  relationship_agent_ids: ID[];
  concise_rationale: string;
  outcome: "accepted" | "rejected" | "modified" | "pending";
  outcome_description: string;
  rejection_code: string | null;
  effects: {
    entity_id: ID;
    field: string;
    before: string | number | boolean | null;
    after: string | number | boolean | null;
  }[];
  event_ids: ID[];
};
export type AgentDetail = {
  ref: Ref;
  agent: AgentSummary;
  profile: Profile;
  home: Vec2;
  needs: { hunger: Pct; fatigue: Pct; health: Pct; social: Pct };
  inventory: { food: number; water: number; supplies: number };
  reputation: Pct;
  beliefs: { text: string; confidence: Pct; evidence: Evidence }[];
  goals: string[];
  memories: Page<Memory>;
  relationships: Page<Relationship>;
  decisions: Page<Decision>;
  major_event_ids: ID[];
  metric_reasons: { metric: Metric; delta: number; evidence: Evidence }[];
};
export type EffectSpec =
  | {
      type: "wellbeing";
      happiness_delta: number;
      stress_delta: number;
      health_delta: number;
    }
  | { type: "hazard"; hazard: "flood" | "fire" | "storm"; severity: Pct }
  | {
      type: "resource_multiplier";
      resource: "food" | "water" | "supplies";
      multiplier: number;
    }
  | { type: "infrastructure"; functional: boolean; capacity_multiplier: number }
  | {
      type: "information";
      message: string;
      reliability: Pct;
      delivery: "local" | "broadcast";
    }
  | { type: "community"; activity: "festival" | "aid"; capacity: number }
  | {
      type: "policy";
      evacuation_order: boolean;
      ration_units_per_agent: number | null;
      aid_multiplier: number;
    };
export type ScenePart = {
  shape: "box" | "sphere" | "cone" | "cylinder";
  offset: { x: number; y: number; z: number };
  size: { x: number; y: number; z: number };
  color: string;
};
export type SceneObject = {
  model:
    | "flood"
    | "fire"
    | "cloud"
    | "crates"
    | "generator"
    | "broadcast"
    | "stage"
    | "stall"
    | "tree"
    | "dinosaur"
    | "spacecraft"
    | "robot"
    | "barrier"
    | "clinic"
    | "snow"
    | "heat"
    | "meteor"
    | "monument"
    | "portal"
    | "visitor"
    | "deer"
    | "generated";
  label: string;
  position: Vec2;
  scale: number;
  rotation: number;
  color: string;
  parts?: ScenePart[];
};
export type EventSpec = {
  title: string;
  description: string;
  kind:
    | "flood"
    | "fire"
    | "storm"
    | "shortage"
    | "outage"
    | "misinformation"
    | "festival"
    | "policy"
    | "custom";
  origin: Vec2;
  affected_polygon: Vec2[];
  severity: Pct;
  duration_ticks: number;
  effects: EffectSpec[];
  success_condition: "duration_elapsed" | "all_safe_or_duration";
  scene?: SceneObject[];
};
export type ScenarioPreview = {
  id: ID;
  simulation_id: ID;
  source: "random" | "repeat" | "custom" | "policy" | "initial";
  source_event_id: ID | null;
  based_on: Ref;
  expires_at: ISODate;
  interpretation: string;
  spec: EventSpec;
  affected_agent_ids: ID[];
  affected_building_ids: ID[];
  warnings: string[];
  unsupported_requests: string[];
  can_commit: boolean;
};
export type EventSummary = {
  id: ID;
  title: string;
  kind: EventSpec["kind"];
  status: "queued" | "active" | "resolved" | "cancelled";
  queued_tick: number;
  start_tick: number | null;
  end_tick: number | null;
  affected_agent_count: number;
  affected_polygon: Vec2[];
  pre_event_snapshot_id: ID;
  summary: string;
  scene?: SceneObject[];
};
export type EventReport = {
  ref: Ref;
  event: EventSummary;
  spec: EventSpec;
  before: Metrics;
  after: Metrics;
  delta: Record<Metric, number>;
  affected_agent_ids: ID[];
  conflicts: number;
  resources_consumed: number;
  evacuated_count: number;
  exposed_count: number;
  consequences: { text: string; evidence: Evidence }[];
  community_lessons: { text: string; evidence: Evidence }[];
  suggested_preparations: string[];
};
export type Dialogue = {
  id: ID;
  interaction_id: ID;
  tick: number;
  speaker_id: ID;
  recipient_ids: ID[];
  audible_to_ids: ID[];
  text: string;
  intent: string;
  emotion: string;
  end_conversation: boolean;
};
export type MetricPoint = {
  tick: number;
  revision: number;
  values: Metrics;
  cooperation_count: number;
  conflict_count: number;
  resources_consumed: number;
  evacuated_count: number;
  exposed_count: number;
};
export type Policies = {
  evacuation_order: boolean;
  ration_units_per_agent: number | null;
  aid_multiplier: number;
};
export type WorldFrame = {
  curfew?: CurfewPolicy;
  conversation_sessions?: ConversationSession[];
  ref: Ref;
  simulation: Simulation;
  map: MapData;
  map_version?: number;
  agents: AgentSummary[];
  events: EventSummary[];
  policies: Policies;
  metrics: MetricPoint;
  recent_dialogue: Dialogue[];
  active_hazards: {
    event_id: ID;
    kind: "flood" | "fire" | "storm";
    polygon: Vec2[];
    severity: Pct;
  }[];
};
export type MapUpdates = {
  zones: Pick<
    MapData["zones"][number],
    "id" | "metrics" | "population" | "population_density_per_km2"
  >[];
  buildings: Pick<
    MapData["buildings"][number],
    "id" | "capacity" | "occupancy" | "functional"
  >[];
  resources: Pick<MapData["resources"][number], "id" | "available_units">[];
};
export type FrameDelta = Omit<WorldFrame, "map"> & {
  map?: MapData | null;
  map_updates?: MapUpdates | null;
};
export type CurfewPolicy = {
  enabled: boolean;
  start_minute: number;
  end_minute: number;
  revision: number;
  informed_agent_ids: ID[];
};
export type ConversationSession = {
  id: ID;
  participant_ids: ID[];
  status: string;
  accepted_calendar_seconds: number | null;
  minimum_end_calendar_seconds: number | null;
  next_turn_calendar_seconds: number | null;
  end_reason: string | null;
};
export type Snapshot = {
  id: ID;
  simulation_id: ID;
  ref: Ref;
  created_at: ISODate;
  reason:
    | "initial"
    | "manual"
    | "autosave"
    | "navigation"
    | "pre_event"
    | "branch";
  label: string;
};
export type Overview = {
  ref: Ref;
  metrics: MetricPoint;
  top_events: {
    event_id: ID;
    title: string;
    impact_score: number;
    evidence: Evidence;
  }[];
  improvements: { metric: Metric; delta: number; evidence: Evidence }[];
  metric_reasons: { metric: Metric; text: string; evidence: Evidence }[];
};
export type Usage = {
  simulation_id: ID | null;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  calls: number;
  failed_calls: number;
  estimated_cost_usd: number | null;
  pricing_as_of: ISODate | null;
};
export type Settings = {
  version: number;
  theme: "dark" | "light";
  view_mode: "3d" | "2d";
  autosave: boolean;
  reduce_motion: boolean;
  shortcuts: Record<
    | "pause"
    | "zoom_in"
    | "zoom_out"
    | "rotate_left"
    | "rotate_right"
    | "pan_up"
    | "pan_down"
    | "pan_left"
    | "pan_right",
    string
  >;
};
export type Capabilities = {
  contract_version: "1.0.0";
  auth_mode: "local" | "session";
  max_agents: number;
  max_concurrent_running_simulations: number;
  gemini: boolean;
  narration: boolean;
  snowflake: boolean;
  persistence: "local" | "postgres";
  replay: boolean;
  branching: boolean;
};
export type Intervention = {
  id: ID;
  simulation_id: ID;
  expires_at: ISODate;
  based_on: Ref;
  was_running: boolean;
  control_version: number;
};
export type RelationshipPreset =
  | "lovers"
  | "friends"
  | "rivals"
  | "acquaintances";
export type CommandBody =
  | {
      type: "set_relationship";
      agent_id: ID;
      target_id: ID;
      preset: RelationshipPreset;
    }
  | { type: "play" }
  | { type: "pause" }
  | { type: "step"; count: number }
  | { type: "set_speed"; value: Speed }
  | { type: "save"; reason: "manual" | "navigation"; label: string }
  | { type: "archive" }
  | { type: "unarchive" }
  | { type: "add_agents"; custom_agent_ids: ID[] }
  | {
      type: "override_agent";
      agent_id: ID;
      metrics: Partial<Metrics>;
      goal: string | null;
      memory_text: string | null;
      intent: Intent | null;
    }
  | { type: "acknowledge_outcome"; event_id: ID; resume: boolean };
export type CommandRequest = {
  request_id: ID;
  expected_control_version: number;
  command: CommandBody;
};
export type CommandResult = {
  simulation: Simulation;
  snapshot: Snapshot | null;
  affected_agent_ids: ID[];
};
