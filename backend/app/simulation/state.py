"""Complete checkpoint state, distinct from the public WorldFrame projection."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from app.behavior.learning import RestLesson
from app.behavior.models import BehaviorState, Condition
from app.contracts import (
    AgentSummary,
    Belief,
    Decision,
    Dialogue,
    EventSpec,
    EventSummary,
    Intervention,
    Inventory,
    MapData,
    Memory,
    MetricPoint,
    MetricReason,
    Metrics,
    Model,
    Needs,
    Policies,
    Profile,
    Relationship,
    ScenarioPreview,
    Simulation,
    Snapshot,
    Vec2,
)
from app.scenario_engine.systems import WorldSystems


def now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def expiry(minutes=10):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def expired(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) <= datetime.now(UTC)


def uid(prefix):
    return f"{prefix}_{uuid4().hex}"


class Citizen(Model):
    rest_lessons: list[RestLesson] = Field(default_factory=list)
    condition: Condition = Field(default_factory=Condition)
    summary: AgentSummary
    profile: Profile
    home: Vec2
    needs: Needs
    inventory: Inventory
    reputation: float = 50
    beliefs: list[Belief] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)
    relationships: dict[str, Relationship] = Field(default_factory=dict)
    major_event_ids: list[str] = Field(default_factory=list)
    metric_reasons: list[MetricReason] = Field(default_factory=list)
    target_inventory_units: float = 12
    generation: int = 0
    task_generation: int = 0
    next_deliberation_tick: int = 0
    plan: dict[str, Any] | None = None
    inside_building_id: str | None = None
    entering_building_id: str | None = None
    leaving_building_id: str | None = None
    last_building_id: str | None = None
    visit_until_tick: int = 0
    blocked_movement_ticks: int = 0
    next_social_tick: int = 0
    profile_template_id: str | None = None
    profile_template_version: int | None = None
    known_locations: dict[str, Vec2] = Field(default_factory=dict)


class EventRuntime(Model):
    summary: EventSummary
    spec: EventSpec
    before: Metrics
    after: Metrics
    cohort: list[str] = Field(default_factory=list)
    baseline_conflicts: int = 0
    baseline_consumed: float = 0
    baseline_cooperation: float | None = None
    conflicts: int = 0
    resources_consumed: float = 0
    evacuated_count: int = 0
    exposed_count: int = 0
    infrastructure_before: dict[str, dict[str, Any]] = Field(default_factory=dict)
    consequences: list[dict[str, Any]] = Field(default_factory=list)
    lessons: list[dict[str, Any]] = Field(default_factory=list)
    lesson_facts: list[dict[str, Any]] = Field(default_factory=list)
    lessons_source: Literal["rules", "gemini"] = "rules"
    resume_allowed: bool = False


class Interaction(Model):
    id: str
    kind: str
    initiator_id: str
    participant_ids: list[str]
    accepted_ids: list[str]
    expires_tick: int
    turns: int = 0
    status: str = "invited"
    proposal: dict[str, Any] = Field(default_factory=dict)


class State(Model):
    behavior: BehaviorState = Field(default_factory=BehaviorState)
    schema_version: str = "1.0.0"
    rule_version: str = "1.0.0"
    owner_id: str
    simulation: Simulation
    map: MapData | None = None
    citizens: dict[str, Citizen] = Field(default_factory=dict)
    events: dict[str, EventRuntime] = Field(default_factory=dict)
    decisions: list[Decision] = Field(default_factory=list)
    dialogue: list[Dialogue] = Field(default_factory=list)
    metric_points: list[MetricPoint] = Field(default_factory=list)
    initial_metrics: Metrics | None = None
    policies: Policies = Field(
        default_factory=lambda: Policies(
            evacuation_order=False, ration_units_per_agent=None, aid_multiplier=1
        )
    )
    baseline_policies: Policies = Field(
        default_factory=lambda: Policies(
            evacuation_order=False, ration_units_per_agent=None, aid_multiplier=1
        )
    )
    snapshots: list[Snapshot] = Field(default_factory=list)
    rng_state: list[Any] = Field(default_factory=list)
    schedules: list[dict[str, Any]] = Field(default_factory=list)
    intervention: Intervention | None = None
    previews: dict[str, ScenarioPreview] = Field(default_factory=dict)
    auto_resume: bool = False
    interactions: dict[str, Interaction] = Field(default_factory=dict)
    applied_social_evidence: list[str] = Field(default_factory=list)
    provider_references: list[dict[str, Any]] = Field(default_factory=list)
    external_resource_changes: list[dict[str, Any]] = Field(default_factory=list)
    counters: dict[str, float] = Field(
        default_factory=lambda: {"cooperation_count": 0, "conflict_count": 0, "resources_consumed": 0}
    )
    entity_sequence: int = 0
    lineage_generation: int = 0
    initialization_profiles: list[dict[str, Any]] = Field(default_factory=list)
    systems: WorldSystems = Field(default_factory=WorldSystems)

    def next_id(self, prefix):
        self.entity_sequence += 1
        return f"{prefix}_{self.entity_sequence:08d}"

    def ref(self):
        from app.contracts import Ref

        return Ref(tick=self.simulation.tick, revision=self.simulation.revision)
