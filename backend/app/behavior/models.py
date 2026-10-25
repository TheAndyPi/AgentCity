"""Persisted behavior v2; deliberately separate from the frozen v1 wire DTOs."""

from typing import Any, Literal

from pydantic import Field

from app.contracts import Evidence, Inventory, Model, Vec2

Life = Literal["alive", "unconscious", "dead"]
Mode = Literal["withdrawal", "panic", "support", "aggression", "fire"]


class Impact(Model):
    tick: int
    phase: str
    meter: Literal["mental", "social", "energy", "health", "fullness"]
    reason: str
    delta: float
    evidence: Evidence


class Episode(Model):
    id: str
    mode: Mode
    start_tick: int
    causes: list[str]
    measurements: dict[str, float]
    rationale: str
    stable_ticks: int = 0
    last_checked_tick: int = -1
    acted_tick: int = -1
    ignited: bool = False
    end_tick: int | None = None


class Condition(Model):
    mental: float = Field(default=70, ge=0, le=100)
    life: Life = "alive"
    transition_tick: int | None = None
    causes: list[str] = Field(default_factory=list)
    evidence: Evidence | None = None
    episode: Episode | None = None
    cooldown_until: int = 0
    last_coupling_tick: int = -1
    last_passive_tick: int = -1
    last_action_tick: int = -1
    care: Literal["none", "claimed", "carried", "escorted", "hospital"] = "none"
    helper_id: str | None = None
    patient_id: str | None = None
    hospital_id: str | None = None
    wealth_band: Literal["poor", "middle", "rich"] = "middle"
    class_beliefs: dict[str, str] = Field(default_factory=dict)
    class_evidence_tick: dict[str, int] = Field(default_factory=dict)
    impacts: list[Impact] = Field(default_factory=list)


class BehaviorEvent(Model):
    id: str
    tick: int
    kind: str
    actor_id: str | None
    target_id: str | None
    description: str
    evidence: Evidence


class BehaviorDecision(Model):
    id: str
    tick: int
    actor_id: str
    action: Literal["attack", "ignite", "rescue", "admit", "comfort", "share", "suppress"]
    target_id: str
    accepted: bool
    reason: str
    effects: dict[str, float] = Field(default_factory=dict)


class Fire(Model):
    id: str
    actor_id: str
    target_id: str
    position: Vec2
    radius: float
    severity: float
    start_tick: int
    end_tick: int
    extinguished: bool = False


class Hospital(Model):
    inventory: Inventory
    patients: list[str] = Field(default_factory=list)
    reservations: dict[str, str] = Field(default_factory=dict)


class BehaviorState(Model):
    rng_state: list[Any] = Field(default_factory=list)
    version: str | None = None
    activated_tick: int | None = None
    initial_population: int = 0
    events: list[BehaviorEvent] = Field(default_factory=list)
    decisions: list[BehaviorDecision] = Field(default_factory=list)
    fires: dict[str, Fire] = Field(default_factory=dict)
    hospitals: dict[str, Hospital] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)
