"""Strict wire DTOs. All response members, including nullable members, are required."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def trimmed(value: str) -> str:
    if value != value.strip() or not value:
        raise ValueError("must contain 1..80 trimmed characters")
    return value


def utc_date(value: str) -> str:
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None or date.utcoffset().total_seconds() != 0:
        raise ValueError("must be an RFC3339 UTC timestamp")
    return value


def uuid_string(value: str) -> str:
    UUID(value)
    return value


def unique_ids(value: list[str]) -> list[str]:
    if len(set(value)) != len(value):
        raise ValueError("IDs must be unique")
    return value


def integer_number(value):
    # JSON/TypeScript numbers have no int-versus-10.0 distinction. Reject strings/bools.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


Integer = Annotated[int, BeforeValidator(integer_number)]
ID = Annotated[str, Field(min_length=1, max_length=200)]
RequestID = Annotated[
    ID,
    Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    AfterValidator(uuid_string),
]
Name = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^\S(?:[\s\S]*\S)?$"), AfterValidator(trimmed)
]
Text = Annotated[str, Field(max_length=2000)]
ISODate = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$",
        json_schema_extra={"format": "date-time"},
    ),
    AfterValidator(utc_date),
]
Counter = Annotated[int, Field(ge=0, le=9007199254740991), BeforeValidator(integer_number)]
Pct = Annotated[float, Field(ge=0, le=100)]
Units = Annotated[float, Field(ge=0)]
Multiplier = Annotated[float, Field(ge=0, le=3)]
IDs = Annotated[
    list[ID], Field(max_length=100, json_schema_extra={"uniqueItems": True}), AfterValidator(unique_ids)
]


def numeric_speed(value):
    if type(value) not in {int, float}:
        raise ValueError("speed must be a number")
    return value


Speed = Annotated[Literal[0.25, 0.5, 1, 2, 5, 10], BeforeValidator(numeric_speed)]
Mode = Literal["sandbox", "behavior_lab", "crisis_lab", "policy_lab"]
Metric = Literal["happiness", "safety", "trust", "resources", "stress"]
ActionName = Literal[
    "idle", "move", "work", "rest", "consume", "gather", "talk", "warn", "help", "trade", "evacuate"
]
Resource = Literal["food", "water", "supplies"]
EventKind = Literal[
    "flood", "fire", "storm", "shortage", "outage", "misinformation", "festival", "policy", "custom"
]
RelationshipKind = Literal["family", "friend", "acquaintance", "rival", "romantic", "stranger"]


class Metrics(Model):
    happiness: Pct
    safety: Pct
    trust: Pct
    resources: Pct
    stress: Pct


class Vec2(Model):
    x: float
    y: float


class Ref(Model):
    tick: Counter
    revision: Counter


class Evidence(Model):
    event_ids: list[ID]
    decision_ids: list[ID]
    memory_ids: list[ID]
    description: Text


T = TypeVar("T")


class Success(Model, Generic[T]):
    schema_version: Literal["1.0.0"]
    request_id: ID
    data: T


class Page(Model, Generic[T]):
    items: list[T]
    next_cursor: str | None


class ErrorDetail(Model):
    field: str | None
    reason: str


class Error(Model):
    code: str
    message: str
    retryable: bool
    details: list[ErrorDetail]


class Failure(Model):
    schema_version: Literal["1.0.0"]
    request_id: ID
    error: Error


class Health(Model):
    status: Literal["ok", "degraded"]
    details: list[str]


class Traits(Model):
    curiosity: Pct
    empathy: Pct
    sociability: Pct
    trust: Pct
    cooperation: Pct
    risk_tolerance: Pct


class TraitsRequest(Traits):
    curiosity: Pct = 50
    empathy: Pct = 50
    sociability: Pct = 50
    trust: Pct = 50
    cooperation: Pct = 50
    risk_tolerance: Pct = 50


class Profile(Model):
    name: Name
    age: Annotated[int, Field(ge=0, le=120), BeforeValidator(integer_number)]
    role: Name
    background: Text
    personality: Text
    values: list[Text]
    traits: Traits
    primary_goal: Text
    secondary_goals: list[Text]
    desires: list[Text]
    fears: list[Text]
    personal_history: Text
    skills: list[Text]
    intelligence: Pct
    mobility: Pct
    physical_attributes: Text
    social_needs: Pct


class CustomAgent(Model):
    id: ID
    version: Counter
    profile: Profile
    updated_at: ISODate


class Environment(Model):
    resource_availability: Pct
    population_density: Pct
    infrastructure_capacity: Pct
    initial_community_trust: Pct
    settlement: Literal["urban", "suburb"]


class EnvironmentRequest(Environment):
    resource_availability: Pct = 50
    population_density: Pct = 50
    infrastructure_capacity: Pct = 50
    initial_community_trust: Pct = 50
    settlement: Literal["urban", "suburb"] = "suburb"


class Config(Model):
    name: Name
    seed: Annotated[int, Field(ge=0, le=2147483647), BeforeValidator(integer_number)]
    mode: Mode
    population: Annotated[int, Field(ge=10, le=100), BeforeValidator(integer_number)]
    population_traits: Traits
    household_supplies: Pct
    personality_diversity: Pct
    environment: Environment
    scenario_description: Annotated[str, Field(max_length=4000)]
    custom_agent_ids: IDs
    tick_seconds: Literal[1, 10]
    max_ticks: Annotated[int, Field(ge=1, le=100000), BeforeValidator(integer_number)]

    @model_validator(mode="after")
    def profile_count(self):
        if len(self.custom_agent_ids) > self.population:
            raise ValueError("custom profiles are included in population")
        return self


class ConfigRequest(Config):
    mode: Mode = "sandbox"
    population: Annotated[int, Field(ge=10, le=100), BeforeValidator(integer_number)] = 30
    population_traits: TraitsRequest = Field(default_factory=TraitsRequest)
    household_supplies: Pct = 50
    personality_diversity: Pct = 50
    environment: EnvironmentRequest = Field(default_factory=EnvironmentRequest)
    scenario_description: Annotated[str, Field(max_length=4000)] = ""
    custom_agent_ids: IDs = Field(default_factory=list)
    tick_seconds: Literal[1, 10] = 1
    max_ticks: Annotated[int, Field(ge=1, le=100000), BeforeValidator(integer_number)] = 100000

    def normalized(self):
        return Config.model_validate(self.model_dump())


class Job(Model):
    stage: Literal[
        "queued", "map", "population", "relationships", "scenario", "persistence", "ready", "failed"
    ]
    progress: Pct
    message: str
    error: Error | None


class Simulation(Model):
    id: ID
    name: Name
    config: Config
    created_at: ISODate
    updated_at: ISODate
    status: Literal["initializing", "paused", "running", "completed", "failed"]
    pause_reason: Literal["manual", "intervention", "outcome", "loaded", "error"] | None
    archived: bool
    tick: Counter
    revision: Counter
    control_version: Counter
    sim_time_seconds: Units
    speed_multiplier: Speed
    achieved_ticks_per_second: Units
    agent_count: Counter
    parent_simulation_id: ID | None
    fork_ref: Ref | None
    latest_snapshot_id: ID | None
    saved_at: ISODate | None
    pending_outcome_event_ids: list[ID]
    initialization: Job
    initial_preview: ScenarioPreview | None


class Cell(Model):
    col: Counter
    row: Counter
    elevation_m: float
    terrain: Literal["land", "road", "water"]
    walkable: bool
    zone_id: ID


Polygon = Annotated[list[Vec2], Field(min_length=3)]


class Zone(Model):
    id: ID
    name: Name
    polygon: Polygon
    metrics: Metrics
    population: Counter
    population_density_per_km2: Units


class Building(Model):
    id: ID
    name: Name
    kind: Literal["home", "work", "shop", "shelter", "hospital", "community"]
    footprint: Polygon
    entrance: Vec2
    height_m: Units
    capacity: Counter
    occupancy: Counter
    functional: bool


class ResourceSource(Model):
    id: ID
    kind: Resource
    position: Vec2
    available_units: Units


class MapData(Model):
    id: ID
    seed: Counter
    width_m: Units
    height_m: Units
    cell_size_m: Units
    columns: Counter
    rows: Counter
    cells: list[Cell]
    zones: list[Zone]
    buildings: list[Building]
    resources: list[ResourceSource]


class Parameters(Model):
    resource_kind: Resource | None
    amount: Annotated[float, Field(gt=0)] | None
    message: Text | None


class Intent(Model):
    action: ActionName
    target_id: ID | None
    destination: Vec2 | None
    parameters: Parameters
    motivation: Text
    emotion: Text


class AgentSummary(Model):
    id: ID
    name: Name
    role: Name
    position: Vec2
    heading_rad: float
    path: list[Vec2]
    movement_speed_mps: Units
    metrics: Metrics
    emotion: Text
    action: ActionName
    action_target_id: ID | None
    latest_decision_id: ID | None
    thought_bubble: Text | None
    active: bool


class Memory(Model):
    id: ID
    tick: Counter
    text: Text
    importance: Pct
    source: Literal["observed", "heard", "reflection", "injected"]
    subject_ids: list[ID]
    evidence: Evidence


class Relationship(Model):
    from_agent_id: ID
    to_agent_id: ID
    kind: RelationshipKind
    trust: Pct
    affection: Pct
    respect: Pct
    familiarity: Pct
    conflict: Pct
    desired_relationship: Text
    shared_history: list[ID]
    evidence: Evidence


class EffectChange(Model):
    entity_id: ID
    field: str
    before: str | float | bool | None
    after: str | float | bool | None


class Decision(Model):
    id: ID
    agent_id: ID
    tick: Counter
    source: Literal["gemini", "rules", "replay"]
    intent: Intent
    observed_facts: list[Text]
    memory_ids: list[ID]
    relationship_agent_ids: list[ID]
    concise_rationale: Text
    outcome: Literal["accepted", "rejected", "modified", "pending"]
    outcome_description: Text
    rejection_code: str | None
    effects: list[EffectChange]
    event_ids: list[ID]


class Needs(Model):
    hunger: Pct
    fatigue: Pct
    health: Pct
    social: Pct


class Inventory(Model):
    food: Units
    water: Units
    supplies: Units


class Belief(Model):
    text: Text
    confidence: Pct
    evidence: Evidence


class MetricReason(Model):
    metric: Metric
    delta: float
    evidence: Evidence


class AgentDetail(Model):
    ref: Ref
    agent: AgentSummary
    profile: Profile
    home: Vec2
    needs: Needs
    inventory: Inventory
    reputation: Pct
    beliefs: list[Belief]
    goals: list[Text]
    memories: Page[Memory]
    relationships: Page[Relationship]
    decisions: Page[Decision]
    major_event_ids: list[ID]
    metric_reasons: list[MetricReason]


class HazardEffect(Model):
    type: Literal["hazard"]
    hazard: Literal["flood", "fire", "storm"]
    severity: Pct


class ResourceEffect(Model):
    type: Literal["resource_multiplier"]
    resource: Resource
    multiplier: Multiplier


class InfrastructureEffect(Model):
    type: Literal["infrastructure"]
    functional: bool
    capacity_multiplier: Multiplier


class InformationEffect(Model):
    type: Literal["information"]
    message: Text
    reliability: Pct
    delivery: Literal["local", "broadcast"]


class CommunityEffect(Model):
    type: Literal["community"]
    activity: Literal["festival", "aid"]
    capacity: Counter


class PolicyEffect(Model):
    type: Literal["policy"]
    evacuation_order: bool
    ration_units_per_agent: Units | None
    aid_multiplier: Multiplier


class WellbeingEffect(Model):
    type: Literal["wellbeing"]
    happiness_delta: Annotated[float, Field(ge=-2, le=2)]
    stress_delta: Annotated[float, Field(ge=-2, le=2)]
    health_delta: Annotated[float, Field(ge=-2, le=2)]


EffectSpec = Annotated[
    HazardEffect
    | ResourceEffect
    | InfrastructureEffect
    | InformationEffect
    | CommunityEffect
    | PolicyEffect
    | WellbeingEffect,
    Field(discriminator="type"),
]


class SceneOffset(Model):
    x: Annotated[float, Field(ge=-8, le=8)]
    y: Annotated[float, Field(ge=0, le=10)]
    z: Annotated[float, Field(ge=-8, le=8)]


class SceneSize(Model):
    x: Annotated[float, Field(ge=0.1, le=8)]
    y: Annotated[float, Field(ge=0.1, le=8)]
    z: Annotated[float, Field(ge=0.1, le=8)]


class ScenePart(Model):
    shape: Literal["box", "sphere", "cone", "cylinder"]
    offset: SceneOffset
    size: SceneSize
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class SceneObject(Model):
    """Bounded procedural props: no external assets or executable model output."""

    model: Literal[
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
    ]
    label: Name
    position: Vec2
    scale: Annotated[float, Field(ge=0.5, le=4)]
    rotation: Annotated[float, Field(ge=0, le=6.284)]
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
    parts: Annotated[list[ScenePart], Field(max_length=8)] = Field(default_factory=list)


class EventSpec(Model):
    title: Name
    description: Text
    kind: EventKind
    origin: Vec2
    affected_polygon: Polygon
    severity: Pct
    duration_ticks: Annotated[int, Field(ge=1, le=10000), BeforeValidator(integer_number)]
    effects: Annotated[list[EffectSpec], Field(max_length=20)]
    success_condition: Literal["duration_elapsed", "all_safe_or_duration"]
    scene: Annotated[list[SceneObject], Field(max_length=24)] = Field(default_factory=list)


class ScenarioPreview(Model):
    id: ID
    simulation_id: ID
    source: Literal["random", "repeat", "custom", "policy", "initial"]
    source_event_id: ID | None
    based_on: Ref
    expires_at: ISODate
    interpretation: Text
    spec: EventSpec
    affected_agent_ids: list[ID]
    affected_building_ids: list[ID]
    warnings: list[Text]
    unsupported_requests: list[Text]
    can_commit: bool


class EventSummary(Model):
    id: ID
    title: Name
    kind: EventKind
    status: Literal["queued", "active", "resolved", "cancelled"]
    queued_tick: Counter
    start_tick: Counter | None
    end_tick: Counter | None
    affected_agent_count: Counter
    affected_polygon: Polygon
    pre_event_snapshot_id: ID
    summary: Text
    scene: Annotated[list[SceneObject], Field(max_length=24)] = Field(default_factory=list)


class Consequence(Model):
    text: Text
    evidence: Evidence


class MetricDeltas(Model):
    happiness: float
    safety: float
    trust: float
    resources: float
    stress: float


class EventReport(Model):
    ref: Ref
    event: EventSummary
    spec: EventSpec
    before: Metrics
    after: Metrics
    delta: MetricDeltas
    affected_agent_ids: list[ID]
    conflicts: Counter
    resources_consumed: Units
    evacuated_count: Counter
    exposed_count: Counter
    consequences: list[Consequence]
    community_lessons: list[Consequence]
    suggested_preparations: list[Text]


class Dialogue(Model):
    id: ID
    interaction_id: ID
    tick: Counter
    speaker_id: ID
    recipient_ids: list[ID]
    audible_to_ids: list[ID]
    text: Text
    intent: Text
    emotion: Text
    end_conversation: bool


class MetricPoint(Model):
    tick: Counter
    revision: Counter
    values: Metrics
    cooperation_count: Counter
    conflict_count: Counter
    resources_consumed: Units
    evacuated_count: Counter
    exposed_count: Counter


class Policies(Model):
    evacuation_order: bool
    ration_units_per_agent: Units | None
    aid_multiplier: Multiplier


class Hazard(Model):
    event_id: ID
    kind: Literal["flood", "fire", "storm"]
    polygon: Polygon
    severity: Pct


class WorldFrame(Model):
    ref: Ref
    simulation: Simulation
    map: MapData
    map_version: Counter = 0
    agents: list[AgentSummary]
    events: list[EventSummary]
    policies: Policies
    metrics: MetricPoint
    recent_dialogue: list[Dialogue]
    active_hazards: list[Hazard]


class ZoneUpdate(Model):
    id: ID
    metrics: Metrics
    population: Counter
    population_density_per_km2: Units


class BuildingUpdate(Model):
    id: ID
    capacity: Counter
    occupancy: Counter
    functional: bool


class ResourceUpdate(Model):
    id: ID
    available_units: Units


class MapUpdates(Model):
    zones: list[ZoneUpdate]
    buildings: list[BuildingUpdate]
    resources: list[ResourceUpdate]


class FrameDelta(WorldFrame):
    map: MapData | None = None
    map_updates: MapUpdates | None = None


class Snapshot(Model):
    id: ID
    simulation_id: ID
    ref: Ref
    created_at: ISODate
    reason: Literal["initial", "manual", "autosave", "navigation", "pre_event", "branch"]
    label: Text


class TopEvent(Model):
    event_id: ID
    title: Name
    impact_score: float
    evidence: Evidence


class OverviewReason(Model):
    metric: Metric
    text: Text
    evidence: Evidence


class Overview(Model):
    ref: Ref
    metrics: MetricPoint
    top_events: list[TopEvent]
    improvements: list[MetricReason]
    metric_reasons: list[OverviewReason]


class Usage(Model):
    simulation_id: ID | None
    input_tokens: Counter
    output_tokens: Counter
    cached_tokens: Counter
    calls: Counter
    failed_calls: Counter
    estimated_cost_usd: Units | None
    pricing_as_of: ISODate | None


SHORTCUTS = dict(
    zip(
        [
            "pause",
            "zoom_in",
            "zoom_out",
            "rotate_left",
            "rotate_right",
            "pan_up",
            "pan_down",
            "pan_left",
            "pan_right",
        ],
        [
            "Space",
            "Mod+Equal",
            "Mod+Minus",
            "Mod+ArrowLeft",
            "Mod+ArrowRight",
            "ArrowUp",
            "ArrowDown",
            "ArrowLeft",
            "ArrowRight",
        ],
        strict=True,
    )
)


class SettingsValues(Model):
    theme: Literal["dark", "light"]
    view_mode: Literal["3d", "2d"]
    autosave: bool
    reduce_motion: bool
    shortcuts: dict[str, str]

    @model_validator(mode="after")
    def valid_chords(self):
        if set(self.shortcuts) != set(SHORTCUTS) or len(set(self.shortcuts.values())) != len(SHORTCUTS):
            raise ValueError("all nine unique shortcuts are required")
        for chord in self.shortcuts.values():
            if not re.fullmatch(
                r"(?:Mod\+)?(?:Alt\+)?(?:Shift\+)?(?:Key[A-Z]|Digit[0-9]|Arrow(?:Up|Down|Left|Right)|Space|Equal|Minus|Enter|Escape|Tab|Backspace|Delete|Home|End|PageUp|PageDown|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Backquote|F(?:[1-9]|1[0-2]))",
                chord,
            ):
                raise ValueError("invalid canonical KeyboardEvent.code chord")
        return self


class Settings(SettingsValues):
    version: Counter


class Capabilities(Model):
    contract_version: Literal["1.0.0"]
    auth_mode: Literal["local", "session"]
    max_agents: Counter
    max_concurrent_running_simulations: Counter
    gemini: bool
    narration: bool
    snowflake: bool
    persistence: Literal["local", "postgres"]
    replay: bool
    branching: bool


class Intervention(Model):
    id: ID
    simulation_id: ID
    expires_at: ISODate
    based_on: Ref
    was_running: bool
    control_version: Counter


class Play(Model):
    type: Literal["play"]


class Pause(Model):
    type: Literal["pause"]


class Step(Model):
    type: Literal["step"]
    count: Annotated[int, Field(ge=1, le=10), BeforeValidator(integer_number)]


class SetSpeed(Model):
    type: Literal["set_speed"]
    value: Speed


class Save(Model):
    type: Literal["save"]
    reason: Literal["manual", "navigation"]
    label: Text


class Archive(Model):
    type: Literal["archive"]


class Unarchive(Model):
    type: Literal["unarchive"]


class AddAgents(Model):
    type: Literal["add_agents"]
    custom_agent_ids: Annotated[
        list[ID],
        Field(min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}),
        AfterValidator(unique_ids),
    ]


class SetRelationship(Model):
    type: Literal["set_relationship"]
    agent_id: ID
    target_id: ID
    preset: Literal["lovers", "friends", "rivals", "acquaintances"]


class OverrideAgent(Model):
    type: Literal["override_agent"]
    agent_id: ID
    metrics: dict[Metric, Pct]
    goal: Text | None
    memory_text: Text | None
    intent: Intent | None


class Acknowledge(Model):
    type: Literal["acknowledge_outcome"]
    event_id: ID
    resume: bool


CommandBody = Annotated[
    Play
    | Pause
    | Step
    | SetSpeed
    | Save
    | Archive
    | Unarchive
    | AddAgents
    | SetRelationship
    | OverrideAgent
    | Acknowledge,
    Field(discriminator="type"),
]


class CommandRequest(Model):
    request_id: RequestID
    expected_control_version: Counter
    command: CommandBody


class CommandResult(Model):
    simulation: Simulation
    snapshot: Snapshot | None
    affected_agent_ids: list[ID]


class CreateSimulation(Model):
    config: ConfigRequest


class ExpectedControl(Model):
    expected_control_version: Counter


class PreviewRequest(Model):
    intervention_id: ID
    source: Literal["random", "repeat", "custom", "policy"]
    source_event_id: ID | None
    prompt: Annotated[str, Field(max_length=4000)] | None
    policy: Policies | None

    @model_validator(mode="after")
    def source_fields(self):
        valid = {
            "random": self.prompt is None and self.source_event_id is None and self.policy is None,
            "repeat": self.source_event_id is not None and self.prompt is None and self.policy is None,
            "custom": bool(self.prompt and self.prompt.strip())
            and self.source_event_id is None
            and self.policy is None,
            "policy": self.policy is not None and self.prompt is None and self.source_event_id is None,
        }
        if not valid[self.source]:
            raise ValueError("source requires exactly its documented payload")
        return self


class CommitScenario(ExpectedControl):
    intervention_id: ID
    preview_id: ID


class InitialScenario(ExpectedControl):
    preview_id: ID
    decision: Literal["confirm", "skip"]


class WholeSource(Model):
    kind: Literal["whole"]


class RevisionSource(Model):
    kind: Literal["revision"]
    revision: Counter


class SnapshotSource(Model):
    kind: Literal["snapshot"]
    snapshot_id: ID


class BranchRequest(Model):
    name: Name
    source: Annotated[WholeSource | RevisionSource | SnapshotSource, Field(discriminator="kind")]


class BranchResult(Model):
    simulation: Simulation
    snapshot: Snapshot


class ScenarioResult(Model):
    simulation: Simulation
    event: EventSummary
    snapshot: Snapshot


class InitialResult(Model):
    simulation: Simulation
    event: EventSummary | None
    snapshot: Snapshot | None


class DeleteSimulation(Model):
    confirmation_name: Name


class ProfileRequest(Model):
    profile: Profile


class ProfileUpdate(ProfileRequest):
    expected_version: Counter


class ExpectedVersion(Model):
    expected_version: Counter


class SettingsUpdate(ExpectedVersion):
    settings: SettingsValues


class Login(Model):
    passphrase: Annotated[str, Field(min_length=1, max_length=2000)]


class SessionInfo(Model):
    authenticated: bool
    csrf_token: str | None


class LoginResult(Model):
    csrf_token: str


class SignedOut(Model):
    signed_out: Literal[True]


class Deleted(Model):
    deleted_id: ID


class MetricSeries(Model):
    points: list[MetricPoint]


class TimelinePoint(Model):
    ref: Ref
    sim_time_seconds: Units


class Template(Model):
    id: ID
    title: Name
    description: Text
    config: Config


class Templates(Model):
    items: list[Template]


class Export(Model):
    simulation: Simulation
    frames: list[WorldFrame]
    agents: list[AgentDetail]
    events: list[EventReport]
    decisions: list[Decision]
    dialogue: list[Dialogue]
    metrics: list[MetricPoint]


class NarrationRequest(Model):
    source_type: Literal["event", "decision", "dialogue"]
    source_id: ID


class NarrationResult(Model):
    audio_url: str
    expires_at: ISODate


class Hello(Model):
    type: Literal["hello"]
    schema_version: Literal["1.0.0"]
    last_revision: Counter | None


class Ping(Model):
    type: Literal["ping"]


class StreamBase(Model):
    schema_version: Literal["1.0.0"]
    simulation_id: ID
    sent_at: ISODate


class SnapshotMessage(StreamBase):
    type: Literal["snapshot"]
    data: WorldFrame


class FrameMessage(StreamBase):
    type: Literal["frame"]
    data: FrameDelta


class InitializationMessage(StreamBase):
    type: Literal["initialization"]
    data: Simulation


class HeartbeatData(Model):
    revision: Counter
    status: Literal["initializing", "paused", "running", "completed", "failed"]


class HeartbeatMessage(StreamBase):
    type: Literal["heartbeat"]
    data: HeartbeatData


class ErrorMessage(StreamBase):
    type: Literal["error"]
    data: Error


ServerMessage = Annotated[
    SnapshotMessage | FrameMessage | InitializationMessage | HeartbeatMessage | ErrorMessage,
    Field(discriminator="type"),
]
