<!-- SHARED_CONTRACT_V1_BEGIN -->
### AgentCity shared integration contract, version 1.0.0

This entire block is normative and identical in both implementation prompts. The coordinator owns it. Neither agent may rename fields, change units, add a different endpoint, change transition semantics, or silently substitute payloads. Submit a proposed contract change with its reason, affected consumers, fixtures, and migration. Continue independent work against this version until a coordinated revision is approved. Internal implementation details may differ behind adapters.

#### C1. Scope, authority, and transport

- Browser: TypeScript, React, Three.js, React Three Fiber, `@react-three/drei`, instancing, Zod. Preserve the existing build system, router, styling, and store if present. With an empty frontend, use Vite, React Router, CSS variables, and React context/reducers with `useSyncExternalStore` for the world subscription. Zod validates data; it is not a state store.
- Server: one Python/FastAPI application, six logical simulation modules plus shared infrastructure. One active simulation runner per simulation, one commit lock per simulation. Start with one application worker. No microservices, Redis, task broker, or Concordia dependency is required by this contract.
- Runtime truth, geometry, physics, RNG, tick, agents, beliefs, relationships, memories, policies, scheduled effects, and metrics belong to the backend. Frontend owns camera, selection, panel navigation, drafts, theme, motion preferences, and view-only historical playback. It never computes authoritative outcomes.
- HTTP base `/api/v1`; WebSocket `/api/v1/simulations/{simulation_id}/stream`. All JSON uses `snake_case`, UTF-8, finite numbers, and `schema_version: "1.0.0"` in success envelopes and stream messages. Dates are RFC 3339 UTC strings. Client displays local time.
- REST writes only. WebSocket is server-to-client state delivery; client messages are limited to hello and heartbeat. No agent, scenario, or engine module receives a browser connection directly.
- In production use one origin with `/api` and WebSocket reverse-proxied to FastAPI. Local frontend defaults to port 5173 and backend to 8000. Same-origin paths are the default; development proxy must include WebSocket upgrades.
- MVP is a private single-owner demo. Optional additional browsers are observers of that same owner's world, not an implemented multi-tenant product. `AUTH_MODE=local` permits loopback development only. For internet deployment `AUTH_MODE=session` requires a server-set HttpOnly, Secure, SameSite=Lax cookie; login is a shared demo passphrase, not a new account system. Check allowed origins on unsafe HTTP requests and WebSocket handshakes, and require `X-CSRF-Token` on writes. Never put API keys or a shared backend secret in a frontend build or WebSocket URL. Owner scope applies to every resource and export. No public unauthenticated mutation API.

#### C2. Common scalar and spatial rules

IDs are opaque server-issued strings. Simulation and custom-profile IDs are globally unique; IDs for simulation-owned entities are unique within their simulation and entity namespace. IDs in copied history remain stable across a branch; address agents and other simulation-owned records by `(simulation_id, entity_id)`. Client request IDs are UUIDs. All integer counters are nonnegative safe integers. `Pct` is a finite number from 0 through 100, including traits, metrics, severity, trust, affection, familiarity, respect, and conflict. Probability is explicitly `probability: number` in [0,1] when used internally, never mixed with `Pct`. Resource units and people counts are nonnegative numbers, counts are integers. Missing optional request fields use documented defaults; all response fields shown below are required, with `null` when absent. Empty collections are `[]`, never `null`.

World coordinates are meters on a flat navigable ground plane: `{x,y}`, +x east, +y north. Three.js maps this to `[x,elevation_m,y]`. Building height is visual elevation, not a third navigation coordinate. Rotation is radians, clockwise from north. Frontend consumes backend map geometry, never regenerates topology from a seed. Navigability uses square cells and authoritative A* paths. The initial map default is 64 by 64 cells, each 2 meters wide. Exact dimensions are returned by the backend. Region polygons are simple, closed implicitly, with at least three vertices. No teleportation or client-authoritative collision checks.

Default `tick_seconds=10`, baseline `ticks_per_real_second=2`, `speed_multiplier` in `[0.25,0.5,1,2,5,10]`. A displayed 1x means the baseline simulation rate, not real-time seconds. Speed changes scheduling frequency, not tick duration or movement physics. A duration in ticks means ticks, not milliseconds. Human walking default is 1.4 m/s, modified by explicit mobility. Server reports achieved tick rate rather than pretending an overloaded 10x run is keeping up. Configuration defaults: population 30, allowed 10 through 100; sliders 50; simulation mode `sandbox`; settlement `suburb`; max_ticks 10000. Custom profiles selected at setup are included in the population count, not added on top. These are implementation assumptions, not claims about limits established by the PDF.

#### C3. Exact data models

The following TypeScript notation specifies JSON shapes for both languages. `Record` has string keys. `Partial` is permitted only where explicitly shown. Schemas must forbid unknown request fields, validate enum/range limits, and prohibit NaN/Infinity. Python models and Zod schemas must accept and reject the same fixtures.

```ts
type ID = string;
type Pct = number;
type ISODate = string;
type Mode = "sandbox" | "behavior_lab" | "crisis_lab" | "policy_lab";
type Speed = 0.25 | 0.5 | 1 | 2 | 5 | 10;
type Metric = "happiness" | "safety" | "trust" | "resources" | "stress";
type Metrics = Record<Metric, Pct>;
type Vec2 = { x: number; y: number };
type Ref = { tick: number; revision: number };
type Evidence = {
  event_ids: ID[]; decision_ids: ID[]; memory_ids: ID[];
  description: string;
};
type Success<T> = { schema_version: "1.0.0"; request_id: ID; data: T };
type Page<T> = { items: T[]; next_cursor: string | null };
type Failure = {
  schema_version: "1.0.0"; request_id: ID;
  error: { code: string; message: string; retryable: boolean;
    details: { field: string | null; reason: string }[] };
};
type Traits = {
  curiosity: Pct; empathy: Pct; sociability: Pct; trust: Pct;
  cooperation: Pct; risk_tolerance: Pct;
};
type Profile = {
  name: string; age: number; role: string; background: string;
  personality: string; values: string[]; traits: Traits;
  primary_goal: string; secondary_goals: string[];
  desires: string[]; fears: string[]; personal_history: string;
  skills: string[]; intelligence: Pct; mobility: Pct;
  physical_attributes: string; social_needs: Pct;
};
type CustomAgent = { id: ID; version: number; profile: Profile; updated_at: ISODate };
type Config = {
  name: string; seed: number; mode: Mode; population: number;
  population_traits: Traits; household_supplies: Pct;
  personality_diversity: Pct;
  environment: { resource_availability: Pct; population_density: Pct;
    infrastructure_capacity: Pct; initial_community_trust: Pct;
    settlement: "urban" | "suburb" };
  scenario_description: string; custom_agent_ids: ID[];
  tick_seconds: number; max_ticks: number;
};
type Job = {
  stage: "queued" | "map" | "population" | "relationships" | "scenario" |
         "persistence" | "ready" | "failed";
  progress: number; message: string; error: Failure["error"] | null;
};
type Simulation = {
  id: ID; name: string; config: Config; created_at: ISODate; updated_at: ISODate;
  status: "initializing" | "paused" | "running" | "completed" | "failed";
  pause_reason: "manual" | "intervention" | "outcome" | "loaded" | "error" | null;
  archived: boolean; tick: number; revision: number; control_version: number;
  sim_time_seconds: number; speed_multiplier: Speed; achieved_ticks_per_second: number;
  agent_count: number; parent_simulation_id: ID | null; fork_ref: Ref | null;
  latest_snapshot_id: ID | null; saved_at: ISODate | null;
  pending_outcome_event_ids: ID[]; initialization: Job;
  initial_preview: ScenarioPreview | null;
};
type MapData = {
  id: ID; seed: number; width_m: number; height_m: number;
  cell_size_m: number; columns: number; rows: number;
  cells: { col: number; row: number; elevation_m: number;
    terrain: "land" | "road" | "water"; walkable: boolean; zone_id: ID }[];
  zones: { id: ID; name: string; polygon: Vec2[]; metrics: Metrics;
    population: number; population_density_per_km2: number }[];
  buildings: { id: ID; name: string;
    kind: "home" | "work" | "shop" | "shelter" | "hospital" | "community";
    footprint: Vec2[]; entrance: Vec2; height_m: number;
    capacity: number; occupancy: number; functional: boolean }[];
  resources: { id: ID; kind: "food" | "water" | "supplies";
    position: Vec2; available_units: number }[];
};
type ActionName = "idle" | "move" | "work" | "rest" | "consume" |
  "gather" | "talk" | "warn" | "help" | "trade" | "evacuate";
type Intent = {
  action: ActionName; target_id: ID | null; destination: Vec2 | null;
  parameters: { resource_kind: "food" | "water" | "supplies" | null;
    amount: number | null; message: string | null };
  motivation: string; emotion: string;
};
type AgentSummary = {
  id: ID; name: string; role: string; position: Vec2; heading_rad: number;
  path: Vec2[]; movement_speed_mps: number;
  metrics: Metrics; emotion: string; action: ActionName;
  action_target_id: ID | null; latest_decision_id: ID | null;
  thought_bubble: string | null; active: boolean;
};
type Memory = {
  id: ID; tick: number; text: string; importance: Pct;
  source: "observed" | "heard" | "reflection" | "injected";
  subject_ids: ID[]; evidence: Evidence;
};
type Relationship = {
  from_agent_id: ID; to_agent_id: ID;
  kind: "family" | "friend" | "acquaintance" | "rival" | "romantic" | "stranger";
  trust: Pct; affection: Pct; respect: Pct; familiarity: Pct; conflict: Pct;
  desired_relationship: string; shared_history: ID[]; evidence: Evidence;
};
type Decision = {
  id: ID; agent_id: ID; tick: number;
  source: "gemini" | "rules" | "replay";
  intent: Intent; observed_facts: string[]; memory_ids: ID[];
  relationship_agent_ids: ID[]; concise_rationale: string;
  outcome: "accepted" | "rejected" | "modified" | "pending";
  outcome_description: string; rejection_code: string | null;
  effects: { entity_id: ID; field: string;
    before: string | number | boolean | null;
    after: string | number | boolean | null }[];
  event_ids: ID[];
};
type AgentDetail = {
  ref: Ref; agent: AgentSummary; profile: Profile; home: Vec2;
  needs: { hunger: Pct; fatigue: Pct; health: Pct; social: Pct };
  inventory: { food: number; water: number; supplies: number };
  reputation: Pct; beliefs: { text: string; confidence: Pct; evidence: Evidence }[];
  goals: string[]; memories: Page<Memory>; relationships: Page<Relationship>;
  decisions: Page<Decision>; major_event_ids: ID[];
  metric_reasons: { metric: Metric; delta: number; evidence: Evidence }[];
};
type EffectSpec =
  | { type: "hazard"; hazard: "flood" | "fire" | "storm"; severity: Pct }
  | { type: "resource_multiplier"; resource: "food" | "water" | "supplies"; multiplier: number }
  | { type: "infrastructure"; functional: boolean; capacity_multiplier: number }
  | { type: "information"; message: string; reliability: Pct;
      delivery: "local" | "broadcast" }
  | { type: "community"; activity: "festival" | "aid"; capacity: number }
  | { type: "policy"; evacuation_order: boolean; ration_units_per_agent: number | null;
      aid_multiplier: number };
type EventSpec = {
  title: string; description: string;
  kind: "flood" | "fire" | "storm" | "shortage" | "outage" |
        "misinformation" | "festival" | "policy" | "custom";
  origin: Vec2; affected_polygon: Vec2[]; severity: Pct;
  duration_ticks: number; effects: EffectSpec[];
  success_condition: "duration_elapsed" | "all_safe_or_duration";
};
type ScenarioPreview = {
  id: ID; simulation_id: ID; source: "random" | "repeat" | "custom" | "policy" | "initial";
  source_event_id: ID | null; based_on: Ref; expires_at: ISODate;
  interpretation: string; spec: EventSpec;
  affected_agent_ids: ID[]; affected_building_ids: ID[];
  warnings: string[]; unsupported_requests: string[];
  can_commit: boolean;
};
type EventSummary = {
  id: ID; title: string; kind: EventSpec["kind"];
  status: "queued" | "active" | "resolved" | "cancelled";
  queued_tick: number; start_tick: number | null; end_tick: number | null;
  affected_agent_count: number; affected_polygon: Vec2[];
  pre_event_snapshot_id: ID; summary: string;
};
type EventReport = {
  ref: Ref; event: EventSummary; spec: EventSpec;
  before: Metrics; after: Metrics; delta: Record<Metric, number>;
  affected_agent_ids: ID[]; conflicts: number; resources_consumed: number;
  evacuated_count: number; exposed_count: number;
  consequences: { text: string; evidence: Evidence }[];
  community_lessons: { text: string; evidence: Evidence }[];
  suggested_preparations: string[];
};
type Dialogue = {
  id: ID; interaction_id: ID; tick: number; speaker_id: ID;
  recipient_ids: ID[]; audible_to_ids: ID[]; text: string;
  intent: string; emotion: string; end_conversation: boolean;
};
type MetricPoint = {
  tick: number; revision: number; values: Metrics;
  cooperation_count: number; conflict_count: number;
  resources_consumed: number; evacuated_count: number; exposed_count: number;
};
type Policies = {
  evacuation_order: boolean; ration_units_per_agent: number | null; aid_multiplier: number;
};
type WorldFrame = {
  ref: Ref; simulation: Simulation; map: MapData;
  agents: AgentSummary[]; events: EventSummary[]; policies: Policies;
  metrics: MetricPoint; recent_dialogue: Dialogue[];
  active_hazards: { event_id: ID; kind: "flood" | "fire" | "storm";
    polygon: Vec2[]; severity: Pct }[];
};
type Snapshot = {
  id: ID; simulation_id: ID; ref: Ref; created_at: ISODate;
  reason: "initial" | "manual" | "autosave" | "navigation" | "pre_event" | "branch";
  label: string;
};
type Overview = {
  ref: Ref; metrics: MetricPoint;
  top_events: { event_id: ID; title: string; impact_score: number; evidence: Evidence }[];
  improvements: { metric: Metric; delta: number; evidence: Evidence }[];
  metric_reasons: { metric: Metric; text: string; evidence: Evidence }[];
};
type Usage = {
  simulation_id: ID | null; input_tokens: number; output_tokens: number;
  cached_tokens: number; calls: number; failed_calls: number;
  estimated_cost_usd: number | null; pricing_as_of: ISODate | null;
};
type Settings = {
  version: number; theme: "dark" | "light"; view_mode: "3d" | "2d";
  autosave: boolean; reduce_motion: boolean;
  shortcuts: Record<"pause" | "zoom_in" | "zoom_out" | "rotate_left" |
    "rotate_right" | "pan_up" | "pan_down" | "pan_left" | "pan_right", string>;
};
type Capabilities = {
  contract_version: "1.0.0"; auth_mode: "local" | "session";
  max_agents: number; max_concurrent_running_simulations: number;
  gemini: boolean; narration: boolean; snowflake: boolean;
  persistence: "local" | "postgres"; replay: boolean; branching: boolean;
};
type Intervention = {
  id: ID; simulation_id: ID; expires_at: ISODate; based_on: Ref;
  was_running: boolean; control_version: number;
};
type CommandBody =
  | { type: "play" }
  | { type: "pause" }
  | { type: "step"; count: number }
  | { type: "set_speed"; value: Speed }
  | { type: "save"; reason: "manual" | "navigation"; label: string }
  | { type: "archive" }
  | { type: "unarchive" }
  | { type: "add_agents"; custom_agent_ids: ID[] }
  | { type: "override_agent"; agent_id: ID;
      metrics: Partial<Metrics>; goal: string | null; memory_text: string | null;
      intent: Intent | null }
  | { type: "acknowledge_outcome"; event_id: ID; resume: boolean };
type CommandRequest = { request_id: ID; expected_control_version: number; command: CommandBody };
type CommandResult = {
  simulation: Simulation; snapshot: Snapshot | null; affected_agent_ids: ID[];
};
```

Names are 1..80 trimmed characters, other prose fields at most 2000 unless `scenario_description` (max 4000). Age integer 0..120. Seed integer 0..2147483647. Request arrays max 100 IDs and unique IDs unless explicitly ordered dialogue. `tick_seconds` is 10 in v1; `max_ticks` 1..10000. `step.count` 1..10. Resources use abstract documented units; `amount` must be positive when required. Multipliers 0..3, duration_ticks 1..1000. Token counters are measured or explicitly unavailable, never fabricated. `estimated_cost_usd=null` without configured current pricing. Profiles stored in simulations are copies of the selected custom-agent version; editing a template does not rewrite existing citizens.

#### C4. REST endpoints

Every successful JSON response is `Success<T>` with the indicated `T`. Every failure is `Failure`, including FastAPI validation errors. Use 200 by default, 201 for created resources, and 202 only for initialization. All mutations carry `Idempotency-Key` equal to the request UUID. Requests without a body UUID use a UUID in that header. Same key and same normalized request return the original result without another side effect. Same key with a different request is 409. Persist idempotency results with mutations. Failed requests that make no mutation can be retried after correction with a new key.

| Method and path, relative to `/api/v1` | Request | `data` response |
|---|---|---|
| GET `/capabilities` | none | `Capabilities` |
| POST `/session` | `{passphrase:string}`; session mode only; origin check | `{csrf_token:string}` and session cookie |
| GET `/session` | cookie | `{authenticated:boolean,csrf_token:string|null}` |
| DELETE `/session` | CSRF header | `{signed_out:true}` |
| POST `/simulations` | `{config:Config}` | 202 `Simulation`, durable initializing job |
| GET `/simulations` | `archived=true|false` default false; cursor; limit | `Page<Simulation>` |
| GET `/simulations/{s}` | none | `Simulation` including initialization progress |
| GET `/simulations/{s}/state` | optional `revision`; omitted means live head | `WorldFrame` at exact committed revision |
| POST `/simulations/{s}/commands` | `CommandRequest` | `CommandResult` after atomic command commit |
| GET `/simulations/{s}/agents` | optional `q`, `revision`, cursor, limit | `Page<AgentSummary>` |
| GET `/simulations/{s}/agents/{a}` | optional `revision` | `AgentDetail`; first 25 memories/relationships/decisions |
| GET `/simulations/{s}/agents/{a}/{collection}` | collection is `memories`, `relationships`, or `decisions`; revision, cursor, limit | `Page<Memory>`, `Page<Relationship>`, or `Page<Decision>` respectively |
| GET `/simulations/{s}/decisions/{d}` | optional revision | `Decision` |
| GET `/simulations/{s}/events` | optional revision, cursor, limit | `Page<EventSummary>` |
| GET `/simulations/{s}/events/{e}` | optional revision | `EventReport` |
| GET `/simulations/{s}/dialogue` | optional revision, cursor, limit | `Page<Dialogue>` |
| GET `/simulations/{s}/metrics` | optional revision; from_tick default 0; to_tick default tick at that revision; stride default 1 | `{points:MetricPoint[]}`; one latest committed point at/before revision per requested tick |
| GET `/simulations/{s}/overview` | optional revision | `Overview` |
| GET `/simulations/{s}/timeline` | optional revision, cursor, limit | `Page<{ref:Ref,sim_time_seconds:number}>` at/before revision |
| GET `/simulations/{s}/snapshots` | optional revision, cursor, limit | `Page<Snapshot>` at/before revision |
| POST `/simulations/{s}/interventions` | `{expected_control_version:number}` | 201 `Intervention`; pauses atomically |
| POST `/simulations/{s}/scenario-previews` | `{intervention_id:ID,source:"random"|"repeat"|"custom"|"policy",source_event_id:ID|null,prompt:string|null,policy:Policies|null}` | 201 `ScenarioPreview`; no event applied |
| POST `/simulations/{s}/interventions/{i}/cancel` | `{expected_control_version:number}` | `Simulation`; releases editing hold |
| POST `/simulations/{s}/scenario-commits` | `{intervention_id:ID,preview_id:ID,expected_control_version:number}` | 201 `{simulation:Simulation,event:EventSummary,snapshot:Snapshot}` |
| POST `/simulations/{s}/initial-scenario` | `{preview_id:ID,decision:"confirm"|"skip",expected_control_version:number}` | `{simulation:Simulation,event:EventSummary|null,snapshot:Snapshot|null}` |
| POST `/simulations/{s}/branches` | `{name:string,source:{kind:"whole"}|{kind:"revision",revision:number}|{kind:"snapshot",snapshot_id:ID}}` | 201 `{simulation:Simulation,snapshot:Snapshot}` |
| DELETE `/simulations/{s}` | `{confirmation_name:string}`; archived and not running required | `{deleted_id:ID}` |
| GET `/custom-agents` | cursor, limit | `Page<CustomAgent>` |
| POST `/custom-agents` | `{profile:Profile}` | 201 `CustomAgent` |
| PUT `/custom-agents/{a}` | `{expected_version:number,profile:Profile}` | `CustomAgent` |
| DELETE `/custom-agents/{a}` | `{expected_version:number}` | `{deleted_id:ID}` |
| GET `/settings` | none | `Settings` |
| PUT `/settings` | `{expected_version:number,settings:Omit<Settings,"version">}` | `Settings` |
| GET `/usage` | optional simulation_id | `Usage` |
| GET `/templates` | none | `{items:{id:ID,title:string,description:string,config:Config}[]}` |
| GET `/simulations/{s}/export` | `format=json|csv`, `through_revision` defaults head | JSON `Success<{simulation:Simulation,frames:WorldFrame[],agents:AgentDetail[],events:EventReport[],decisions:Decision[],dialogue:Dialogue[],metrics:MetricPoint[]}>` or CSV attachment |
| POST `/simulations/{s}/narration` | `{source_type:"event"|"decision"|"dialogue",source_id:ID}` | `{audio_url:string,expires_at:ISODate}`; optional feature, 501 if unavailable |

`/health/live` and `/health/ready` are unauthenticated outside `/api/v1`; JSON `{status:"ok"|"degraded",details:string[]}` with 200 for ready and 503 for not ready. Readiness requires the persistence store, not optional LLM/narration/analytics vendors.

Pagination defaults to 25, maximum 100. Sort agents by `(name,id)`, simulations by descending `(updated_at,id)`, logs by descending `(tick,id)`, and timeline by ascending revision. Cursor binds owner, resource, filters, and resolved revision; never combine pages from different revisions. For history UI explicitly pin revision across all queries. `metrics.stride` integer 1..10000, return at most 10001 points. Requests for data newer than the resolved revision return 404; requests for a nonexistent revision return 404, and deliberately unavailable retained history returns 410. CSV columns are `simulation_id,tick,revision,happiness,safety,trust,resources,stress,cooperation_count,conflict_count,resources_consumed,evacuated_count,exposed_count`, UTF-8 with a header. Export arrays contain only records at or before through_revision; agent detail represents that revision and exports must exhaust nested pages. JSON exports may stream the envelope as an attachment, without inventing a second data format.

EventReport is readable while queued/active: before is the pre-event metric sample, after is the latest permitted sample, delta is their difference, and consequences/lessons may be empty. Only a resolved report is final. Global Usage does not rewind; it reflects actual billable calls, including branch creation and failed calls with known usage. A historical inspector may show the source of its recorded decisions, never pretend historical playback spends those tokens again.

Command preconditions are checked atomically after idempotency lookup and before mutation. All mismatched control versions return CONTROL_CONFLICT with the latest version in the details reason. Play requires ready, unarchived, noncompleted state, no open intervention, no unconfirmed initial preview, and no pending outcome. Pause is safe on already-paused ready worlds and explicitly revokes pending auto-resume intent. Step requires paused state, no editing hold/initial preview/pending report; it executes up to count ticks and stops early on outcome/completion/error. Set_speed preserves current playback status. Save creates a checkpoint; reason navigation additionally pauses, revokes auto-resume, cancels any editor hold, and invalidates previews. Manual save preserves playback after the atomic boundary. Archive pauses/saves/cancels holds; unarchive stays paused. Add_agents and override_agent are rejected while an intervention is open, during initialization, or when archived/completed/failed; otherwise commit at the next safe boundary. Acknowledge_outcome requires that pending event ID, clears it once, and resumes only if requested and the stored prior intent still permits it. Branching is allowed from durable ready history, captures one exact source revision even if the source is running, and starts the copy paused. Play on completed history requires a new branch with an explicit supported run horizon, not an implicit reset; branches at max_ticks cannot advance and UI should choose an earlier point.

Default shortcut values are `Space`, `Mod+Equal`, `Mod+Minus`, `Mod+ArrowLeft`, `Mod+ArrowRight`, `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight` in the Settings key order above. Mod means Cmd on macOS and Ctrl elsewhere. Canonical chords use ordered `Mod`, `Alt`, `Shift` modifiers and a browser KeyboardEvent.code key, separated by `+`; reject duplicate chords. Physical plus may require Shift and is accepted as the zoom-in alias in the viewport. Keyboard remapping is display-only configuration, not a simulation mutation.

Preview request constraints: `random` has null prompt/source_event_id/policy; `repeat` has a resolved event from the same simulation or inherited history and other fields null; `custom` has a nonblank prompt only; `policy` has a complete Policies object only. Repeat copies the original validated spec, then revalidates it against current map and agents. Random choice is fixed in the returned preview, never rerolled at commit. A custom natural-language request compiles only into the six EffectSpec families. Unsupported parts appear in `unsupported_requests`; partial support requires the user to confirm the stated supported interpretation. Unsupported-only requests have `can_commit=false`. No arbitrary execution of user prose.

Error codes: 400 `INVALID_REQUEST`; 401 `UNAUTHENTICATED`; 403 `FORBIDDEN`; 404 `NOT_FOUND`; 409 `CONTROL_CONFLICT`, `INVALID_STATE`, `INTERVENTION_OPEN`, `EVENT_ACTIVE`, `IDEMPOTENCY_CONFLICT`, or `PREVIEW_STALE`; 410 `PREVIEW_EXPIRED` or `HISTORY_UNAVAILABLE`; 422 `VALIDATION_ERROR`; 429 `RATE_LIMITED`; 501 `FEATURE_UNAVAILABLE`; 503 `PERSISTENCE_UNAVAILABLE` or `SERVICE_UNAVAILABLE`. Provider failures are contained inside the simulation fallback path where possible. Include `Retry-After` for 429/503 when known. A failed preview leaves the dialog open and simulation paused. A failed save must never display “Saved.”

#### C5. Real-time synchronization

Client connects with cookies and allowed Origin, sends `{type:"hello",schema_version:"1.0.0",last_revision:number|null}` within 5 seconds. Server always replies with a complete current snapshot. This deliberately uses full frames for a 100-agent maximum, avoiding a second delta language. Every subsequent committed revision can produce a full frame; intermediate frames may be coalesced per slow client. No partial upserts or implicit removals. Event/decision history is durable and fetched separately, so skipped animation frames do not lose audit records.

```ts
type ServerMessage = {
  schema_version: "1.0.0"; simulation_id: ID; sent_at: ISODate;
} & (
  | {type:"snapshot"; data:WorldFrame}
  | {type:"frame"; data:WorldFrame}
  | {type:"initialization"; data:Simulation}
  | {type:"heartbeat"; data:{revision:number,status:Simulation["status"]}}
  | {type:"error"; data:Failure["error"]}
);
type ClientHeartbeat = {type:"ping"};
```

During initialization send `initialization`, not a fabricated empty WorldFrame. Once ready send snapshot before frames. New connection always supersedes old connection; frontend tags callbacks with a connection generation. Discard lower/equal revisions from the same simulation after an accepted snapshot. Since every frame is complete, a revision gap is legal. Invalid schema freezes the last valid view, reports a visible reconnecting/error state, and triggers fresh snapshot acquisition. Never apply an older REST fetch over a newer stream frame.

Heartbeat every 15 seconds; reconnect after 45 seconds without server traffic, exponential delays 1,2,4,8 seconds capped at 10 with jitter. After three failed attempts, poll GET state every 2 seconds and keep retrying WebSocket. Display stale/connection state. Show toast events by detecting new persisted event IDs/status transitions and pending outcome IDs, not by trusting that every transient message arrived. Client queue capacity is one latest WorldFrame plus reliable control/error messages; disconnect consistently slow clients. Server never blocks ticks on a socket.

#### C6. User-flow state machine, mandatory for both agents

1. Landing -> single-page setup -> server initialization -> live simulation. Setup draft survives navigation to custom-agent settings. The returned initializing ID is used for real progress. 0..10% is queue/setup; 10..80% reflects actual map, population, relationship, and scenario stages; 80..100% validates and persists. Do not advance by a fake timer. Initialization finishes paused. If scenario_description is nonblank, `initial_preview` must be confirmed or skipped before Play. Confirmation follows the same pre-event snapshot and queued-event rules as any intervention. Empty descriptions have null initial_preview. A failed initialization can be inspected and retried as a new create request with retained form data.
2. A tick is an atomic committed simulation transition. `tick` increments only for a simulation step, `revision` increments for every committed simulation state change, and `control_version` increments for administrative control changes, including automatic outcome pauses. No wall-clock timer may mutate a paused world. Job progress can update initialization metadata without fabricating a world tick.
3. Opening Random, Repeat, Custom, or Policy event UI first creates an Intervention. Server captures prior running status, waits for any in-progress atomic commit, pauses, and returns a reference. Only one intervention and one queued/active major user event are allowed per simulation in v1. Natural background behavior and minor logs continue outside this major-event restriction. The dialog is not editable until pause is acknowledged. Enter submits for PREVIEW; explicit Confirm introduces the event. This reconciles the PDF's Enter shortcut with its requirement to preview effects before introduction.
4. Preview never changes world state. Editing input discards the old preview. Preview and intervention expire after 10 minutes. Expired holds release without auto-resuming, preventing a forgotten tab from unexpectedly starting a world. Confirm checks ownership, control_version, exact based_on revision, expiry, can_commit, and resource/map constraints. In one transaction it creates a complete pre-event snapshot, appends the queued event, consumes the preview/hold, and restores the captured running state only if no later explicit user pause revoked it. Actual effects start on the next committed tick. If previously paused, remain paused and show “Event will begin once you press Play.”
5. Cancel/Escape/backdrop closes the event editor, releases its hold, and restores prior running state only when its version/intent is still valid. If already manually paused by another tab, stay paused. An explicit Pause command during editing revokes auto-resume. A navigation save revokes it too. Never silently resume following a failed commit, expired hold, disconnect, or ambiguous response. On ambiguous retry use the same idempotency key before deciding whether the event was created.
6. Event duration ends at `start_tick + duration_ticks`; for all_safe_or_duration it may end earlier when every initially exposed active agent is in a safe region. Snapshot all pre-event agent exposure IDs at activation. Outcomes use committed measurements. At event completion server pauses with `pause_reason=outcome` and a durable pending outcome event ID. UI opens a centered report. Continue, back arrow, or backdrop acknowledges it with `resume=true` only when the run was playing before the automatic pause. If manually stepping, remain paused. A later manual Pause revokes auto-resume. Server validates that state on acknowledgment. Escape matches the same controlled dismissal, not a generic Play command.
7. Undo branches from the event's pre_event_snapshot_id, returns a NEW paused simulation, and the frontend switches to it. Original history remains available. It never attempts to subtract downstream effects or rerun old LLM calls. Label this “Undo event, open restored copy” so the preservation of the original timeline is clear.
8. Rewind enters a client-local read-only historical view at an exact revision. Pause live execution before entering replay. All inspector, event, and metric requests bind that revision. Hide future information. Replay Play traverses recorded revisions, fast-forward advances recorded history; it never calls Gemini. “Return to live” loads current head and clears replay. “Continue from here” creates a paused branch. In live mode fast-forward changes speed; it does not jump past uncomputed ticks. Reset means branch from the initial snapshot, never destructive history truncation.
9. Navigation from a simulation to Create, History, Settings, About, or Landing pauses and saves atomically through `save` with reason navigation. Save succeeds before the route changes; show a confirmed autosave notification on destination. Navigation save and mandatory pre-event/branch snapshots still occur if periodic autosave is disabled, as the PDF explicitly requires them. Explain that the toggle controls periodic snapshots. Warn on browser close if unconfirmed save is pending; browser-unload network requests are not a reliable save mechanism.
10. Archive pauses, saves, and marks archived. Unarchive returns paused. Delete requires archived state, exact name confirmation, and no active runner. Bulk deletion calls the same endpoint separately for each confirmed selected ID and reports partial failures; no global implicit delete. Whole duplication copies committed history through current head and all runtime state into a new lineage; point duplication copies only through selected revision/snapshot. Both start paused. Stored immutable prefix objects may be shared internally only if deleting a source cannot delete a branch's history.
11. Custom agents added to a running world are enqueued through the same commit boundary; initialize copied profiles, placement at a valid free entrance, needs, memories, and directed relationships. Return actual spawned IDs. Reject if total exceeds 100. An override changes only provided metrics, optional goal, injected memory, or validated intent, and is logged as a user intervention. It cannot bypass collision, resource conservation, or perception rules. UI provides these as an advanced inspector section.
12. Reads never change playback. Inspectors, overlays, search, and log drawers leave the simulation running unless user explicitly pauses. Reopening a stored simulation reads current head; server restart always restores worlds paused. The scheduler never secretly resumes a saved session.

#### C7. Simulation and explanation invariants

- At each tick: select due external effects -> build bounded perception from the previous committed state -> gather available, version-tagged intents -> resolve interactions/conflicts -> advance valid movement and physical effects -> update needs, beliefs, directed relationships, memories -> calculate metrics -> atomically persist state/audit/RNG/scheduler -> publish. Planning may run asynchronously, but obsolete proposals are discarded or revalidated against current state before use.
- Perception default sight 20m with line-of-sight obstruction, hearing 8m, physical interaction 3m. Explicit broadcast messages can reach farther; they remain heard information with a source. Speaking nearby does not reveal private thoughts or memories. Revalidate proximity after movement; proposed help/trade across town becomes travel or is rejected, never immediate remote action.
- Relationship edges are directed, A's trust of B is independent from B's trust of A. Trust, affection, respect, familiarity, and conflict are distinct values. Reflection and social evaluation propose changes once; only the validated outcome commit applies them. No double-application through both Interaction Handler and Agent Handler.
- Gemini returns intentions and concise character explanations with evidence references, not authoritative world patches or unrestricted executable code. “God” framing is retained in Game Master narrative templates, while deterministic server rules enforce all mutations. A rationale is a recorded character explanation, not a verified transcript of private model reasoning. The frontend calls it “Why this action,” connects it to observed facts, memory, relationships, and actual consequences, and separates attempted from successful actions.
- All metrics are derived from committed state. Population Metrics are arithmetic means over active citizens. Agent resource score is `100 * min(1,(food+water+supplies)/max(1,target_inventory_units))`; retain the target in full internal state. Trust is the mean of outgoing known-person trust edges; with no known people use initial_community_trust. Zone metrics average citizens currently in the zone; empty zones use world mean and include population=0. Population density is people divided by polygon area in square kilometers. Safety is `100-max(local_hazard_severity,health_deficit)` with health_deficit `100-health`, clamped. Happiness and stress are stored state variables updated by versioned rule deltas and bounded to [0,100]; record every contributing delta. Environmental severity and all metric effects are engine rules, not LLM-invented percentages.
- Counts in MetricPoint are cumulative from tick zero except exposed_count (current exposed active citizens) and evacuated_count (current active event's initially exposed citizens now safe, zero if none). EventReport counts cover the event interval and its frozen exposure cohort. Cooperation counts accepted help, accepted trade, and coordinated aid actions; conflicts count rejected contested-resource claims or validated interpersonal conflicts, not every rejected move. Resources consumed is the sum of removed food/water/supplies units, not transferred units. Snapshot before/after metric differences show association over that interval, not proven causal effect. Top events sort by sum of absolute five-metric deltas, ties by earlier start tick then ID. Improvements sort positive endpoint-minus-initial deltas descending, with stress sign inverted. Never invent three entries when fewer exist.

#### C8. Persistence, replay, deployment, and configuration

Local-first means server-side durable storage under `DATA_DIR`, not browser localStorage as simulation truth. Start with an append-only committed revision journal plus immutable checkpoints, implemented using atomic temp-write/rename, checksums, and an fsynced commit manifest. A revision becomes visible only after its commit manifest is durable. On failure, do not advance the published state. Recovery ignores incomplete temp files and restores the latest valid committed prefix. An existing working SQLite/PostgreSQL store may be preserved if it meets the same transactional contract; do not rewrite it simply to match the fallback file layout.

Internal checkpoints contain every agent's profile, goals, inventory, needs, position/path, memories, beliefs, both relationship directions, ongoing interactions, event schedules and active effects, policy state, map, all RNG states, decision scheduler state, simulation time, pending outcomes, provider-result references, and lineage. Wire WorldFrame is a view, not a complete restorable checkpoint. Pending network calls are never serialized as executable work. On restore cancel old tasks and replan from restored state. Record accepted model outputs; historical replay consumes recorded committed revisions and never calls the model. New branches may generate different future decisions, even with the same seed, and must not be described as deterministic LLM reruns.

A branch retains the source's committed revision/tick numbers through the selected ref, then writes a new branch-creation revision `source_revision+1` at the same tick with control_version 0, status paused, and pause_reason loaded. Its historical projections use the NEW simulation_id while retaining domain record IDs and internal source provenance. Copied snapshot/event references resolve within the copied branch prefix; deleting the source cannot invalidate them. Fresh future revisions increment from the branch-creation revision. Clear editor holds, preview tokens, sockets, pending provider tasks, source command idempotency records, and auto-resume permissions. Set initial_preview null, since an uncommitted scenario proposal is not part of the restored world. Existing pending outcome reports may remain for inspection, but acknowledgment cannot auto-resume a restored world. Event undo must therefore never restore an open event editor or immediately requeue the event being undone.

PostgreSQL/Tiger Data is the optional hosted operational adapter behind the same repository, with tables for simulations, revisions, snapshots, profiles, agent states, memories, directed relationships, decisions, interactions/messages, scenario events, metric samples, usage, sessions, and idempotency records. Foreign keys include simulation scope. Revision commits, events, and state rows are transactional. Index history by `(simulation_id,revision)` and memories by `(simulation_id,agent_id,tick)`. Do not require a Timescale extension for correctness. Snowflake is an optional asynchronous analytics sink/read model, never a second state authority. A failed export cannot stall ticks. ElevenLabs is on-demand cached narration of recorded dialogue, decisions, or reports, not continuous per-agent audio.

Environment, backend only: `HOST=127.0.0.1`, `PORT=8000`, `DATA_DIR=./data`, `PERSISTENCE_MODE=local|postgres`, optional `DATABASE_URL`, `AUTH_MODE=local|session`, `SESSION_SECRET`, `DEMO_PASSPHRASE`, `ALLOWED_ORIGINS`, `LLM_MODE=gemini|rules`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `LLM_MAX_CONCURRENCY=4`, `LLM_REQUEST_TIMEOUT_SECONDS=8`, `LLM_REQUESTS_PER_MINUTE=30`, `LLM_MAX_OUTPUT_TOKENS=512`, `LLM_SESSION_TOKEN_BUDGET=200000`, `SIM_BASE_TICKS_PER_SECOND=2`, `SIM_MAX_AGENTS=100`, `SIM_MAX_RUNNING=1`, `AUTOSAVE_INTERVAL_TICKS=20`, `ENABLE_SNOWFLAKE=false`, `ENABLE_NARRATION=false`, optional `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, optional Snowflake credentials and explicit model-pricing configuration. Model names and credentials must be selected from available accounts, not invented defaults. Server advertises actual supported capabilities.

Frontend environment: `VITE_API_BASE_URL=/api/v1`, `VITE_DATA_MODE=live|mock`. WebSocket URL derives from API URL and page scheme, HTTP->WS and HTTPS->WSS. Never use VITE variables for secrets. Mock mode has a persistent visible label. Frontend assets are built for Vultr reverse proxy or an existing static host; backend requires a persistent process/disk and WebSocket support. Single-process operation is a deliberate MVP limitation, not horizontal scaling. Only the backend reads/writes simulation persistence; frontend preference drafts may be cached locally, and confirmed Settings remain server-backed.

#### C9. Contract fixtures and gates

Before parallel implementation the coordinator commits this file as `contracts/v1/CONTRACT.md` and a manifest fixing version 1.0.0. No participant may edit that contract directory during normal frontend/backend work. The contract bootstrap owner produces `schemas.json` (JSON Schema 2020-12 for DTOs), `openapi.yaml` (OpenAPI 3.1 HTTP definitions), `stream.schema.json`, and JSON fixtures without implementing the application, and the coordinator freezes them before either side integrates transport. If the repository already has equivalent contracts, compare them and freeze compatible adapters; do not overwrite them blindly. A mechanical schema translation must not make new product choices. Stop only the affected interface work if a specification ambiguity is discovered, and record a decision request.

Fixture set must include: initializing job; ready paused city; initial scenario preview; running city; paused queued event; active flood; rejected out-of-range help; two asymmetric relationship edges; event report and pending outcome; restored branch; all empty lists; rules fallback; archived simulation; validation error; stale preview; duplicate idempotent command; transport reconnection; historical agent with no future memories. Coordinates include unequal x/y values, not only zeros, to expose axis swaps. Each fixture has a revision and no invented extra fields.

Frontend and backend independently run every valid fixture and deliberately invalid fixture through their validators. HTTP OpenAPI snapshot comparison and WebSocket schema checks must pass. Shared file hashes remain unchanged. Both agents include the exact contract version, test commands/results, known gaps, and a request/response trace in their handoff. Working incremental functionality is required; mock demonstrations and unavailable optional integrations must be labeled honestly.
<!-- SHARED_CONTRACT_V1_END -->
