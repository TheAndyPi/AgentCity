"""Public observation v1 responses, separate from frozen core contracts."""

from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Counter = Annotated[int, Field(ge=0, le=9007199254740991)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Coverage(Model):
    state: Literal["complete", "partial", "unavailable"]
    from_tick: Counter | None
    through_tick: Counter | None


class Provenance(Model):
    source: Literal["snowflake"]
    simulation_id: str
    requested_revision: Counter
    effective_revision: Counter | None
    coverage: Coverage


class Status(Provenance):
    enabled: bool
    state: Literal["disabled", "healthy", "backfilling", "lagged", "failed"]
    published_revision: Counter
    ingested_revision: Annotated[int, Field(ge=-1)]
    lag_revisions: Counter
    error_code: str | None


class Metric(Model):
    id: str
    label: str
    unit: str
    denominator: str


class Metrics(Provenance):
    items: list[Metric]


class Event(Model):
    event_id: str
    title: str
    status: str
    start_tick: Counter | None
    end_tick: Counter | None


class Point(Model):
    tick: Counter
    revision: Counter
    mean: float | None
    min: float | None
    max: float | None
    sample_count: Counter
    denominator: Annotated[float, Field(ge=0)]


class Distribution(Model):
    label: str
    count: Counter


class Trends(Provenance):
    metric: str
    unit: str
    items: Annotated[list[Point], Field(max_length=500)]
    events: list[Event]
    distribution: list[Distribution]


class Change(Model):
    id: str
    tick: Counter
    revision: Counter
    entity_kind: str
    entity_id: str
    agent_id: str | None
    field: str
    before: Any
    after: Any
    link: Literal["explicit", "temporal"]
    event_ids: list[str]
    evidence: dict[str, Any]


class Changes(Provenance):
    items: Annotated[list[Change], Field(max_length=100)]
    next_after: str | None


class Events(Provenance):
    items: Annotated[list[Event], Field(max_length=100)]
    next_after: str | None


class Measurement(Model):
    tick: Counter | None
    city: dict[str, float | None]
    cohort: dict[str, float | None]
    denominators: dict[str, dict[str, Counter]] | None = None


class Observation(Model):
    id: str
    text: str
    citation_ids: list[str]


class Citation(Model):
    id: str
    tick: Counter
    revision: Counter
    description: str


class ChangeCounts(Model):
    explicit: Counter
    temporal: Counter


class EventDetail(Provenance):
    event: Event
    baseline: Measurement
    resolution: Measurement
    followup: Measurement
    followup_complete: bool
    change_counts: ChangeCounts
    observations: list[Observation]
    citations: list[Citation]
    overlaps: list[Event]
    changes: Annotated[list[Change], Field(max_length=100)]


Data = TypeVar("Data")


class Response(Model, Generic[Data]):
    schema_version: Literal["1.0.0"]
    request_id: UUID
    data: Data
