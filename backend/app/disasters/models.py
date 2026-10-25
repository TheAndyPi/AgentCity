"""Disaster controls and durable condition, gameplay rules 2.0.0."""

from typing import Literal

from pydantic import Field, model_validator

from app.contracts import Model, Ref, ScenarioPreview, Vec2

RULE_VERSION = "disasters-2.0.0"
Kind = Literal["earthquake", "tornado", "flood", "fire", "storm"]
LIMITS = {
    "earthquake": dict(min=2.0, max=9.0, step=0.1, default=5.5, unit="Mw", label="Moment magnitude"),
    "tornado": dict(min=0.0, max=130.0, step=1.0, default=50.0, unit="m/s", label="Peak wind speed"),
    "flood": dict(min=0.0, max=5.0, step=0.1, default=1.0, unit="m", label="Water depth"),
    "fire": dict(min=0.0, max=100.0, step=1.0, default=50.0, unit="/100", label="Gameplay heat"),
    "storm": dict(min=0.0, max=75.0, step=1.0, default=30.0, unit="m/s", label="Peak wind speed"),
}


class Parameters(Model):
    kind: Kind
    intensity: float
    extent_m: float = Field(gt=0)  # radius, or full tornado width
    origin: Vec2
    track_end: Vec2 | None = None
    duration_ticks: int = Field(ge=1, le=1000)
    seed: int = Field(ge=0, le=2147483647)
    rule_version: Literal["disasters-2.0.0"] = RULE_VERSION

    @model_validator(mode="after")
    def valid_intensity(self):
        limits = LIMITS[self.kind]
        if not limits["min"] <= self.intensity <= limits["max"]:
            raise ValueError(f"Intensity must be {limits['min']}..{limits['max']} {limits['unit']}")
        units = (self.intensity - limits["min"]) / limits["step"]
        if abs(units - round(units)) > 1e-6:
            raise ValueError(f"Intensity precision is {limits['step']} {limits['unit']}")
        if self.kind == "tornado" and (self.track_end is None or self.track_end == self.origin):
            raise ValueError("Tornado needs a distinct track end")
        if self.kind != "tornado" and self.track_end is not None:
            raise ValueError("Only tornadoes have a track")
        return self

    @property
    def normalized(self):
        if self.kind == "earthquake":
            return ((self.intensity - 2) / 7) ** 1.5
        return self.intensity / LIMITS[self.kind]["max"]


class Condition(Model):
    integrity: float = Field(default=100, ge=0, le=100)
    design_capacity: int = Field(ge=0)
    baseline_functional: bool = True
    resistance: float = 1.0
    cause_ids: list[str] = Field(default_factory=list)

    @property
    def stage(self):
        return (
            "destroyed"
            if self.integrity == 0
            else "unsafe"
            if self.integrity < 50
            else "damaged"
            if self.integrity < 100
            else "intact"
        )


class DamageRecord(Model):
    id: str
    event_id: str
    entity_id: str
    tick: int
    revision: int
    sim_time_seconds: float
    exposure: float
    before: float
    after: float
    units: Literal["integrity", "stock", "health"]
    rule_version: str = RULE_VERSION


class TerrainDamage(Model):
    col: int
    row: int
    stage: str
    blocked: bool
    cause_ids: list[str] = Field(default_factory=list)


class Reaction(Model):
    id: str
    event_id: str
    agent_id: str
    tick: int
    revision: int
    sim_time_seconds: float
    position: Vec2
    threat: float
    kind: Literal["scream", "help", "warning"]
    text: str
    episode_id: str
    evidence_ids: list[str]
    alive: bool = True
    conscious: bool = True


class Repair(Model):
    action: Literal["repair", "clear"] = "repair"
    id: str
    building_id: str
    start_tick: int
    finish_tick: int
    before: float
    supplies: float
    resource_id: str
    status: Literal["pending", "completed", "blocked"] = "pending"
    after: float | None = None


class Bounds(Model):
    min_extent_m: float
    max_extent_m: float


class DamageProjection(Model):
    min_integrity_loss: float
    max_integrity_loss: float
    description: str


class PreviewResult(Model):
    damage_projection: DamageProjection
    schema_version: Literal["2.0.0"]
    parameters: Parameters
    preview: ScenarioPreview
    bounds: Bounds
    duration_seconds: float


class EventView(Model):
    legacy_projection: bool
    id: str
    phase: Literal["queued", "active", "resolved", "cancel"]
    phase_id: str
    parameters: Parameters
    normalized_intensity: float
    unit: str
    start_tick: int | None
    end_tick: int | None
    footprint: list[Vec2]
    current_footprint: list[Vec2]
    current_origin: Vec2
    exposure_count: int
    damage_ids: list[str]


class ConditionView(Model):
    integrity: float
    design_capacity: int
    baseline_functional: bool
    resistance: float
    cause_ids: list[str]
    stage: Literal["intact", "damaged", "unsafe", "destroyed"]


class VocalState(Model):
    alive: bool
    conscious: bool


class RescueNeed(Model):
    agent_id: str
    building_id: str


class StateView(Model):
    schema_version: Literal["2.0.0"]
    rule_version: str
    simulation_id: str
    ref: Ref
    sim_time_seconds: float
    events: list[EventView]
    service_changes: list[dict]
    vocal_states: dict[str, VocalState]
    conditions: dict[str, ConditionView]
    terrain: list[TerrainDamage]
    damage: list[DamageRecord]
    reactions: list[Reaction]
    repairs: list[Repair]
    rescue_needs: list[RescueNeed]


class ExportView(StateView):
    totals: dict[str, float]
