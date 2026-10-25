from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Counter = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class PinnedHistory(Model):
    simulation_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
    revision: Counter


class ComparisonRequest(Model):
    a: PinnedHistory
    b: PinnedHistory
    question: Annotated[str, Field(min_length=1, max_length=500)] = (
        "What recorded differences accompany lower cooperation in B?"
    )


class Provenance(PinnedHistory):
    endpoint_tick: Counter
    metric_tick: Counter
    metric_revision: Counter
    sim_time_seconds: float
    parent_simulation_id: str | None
    fork_ref: dict | None
    seed: int
    contract_version: Literal["1.0.0"] = "1.0.0"
    engine_version: Literal["1.0.0"] = "1.0.0"
    export_sha256: str
    ingested_at: str | None


class Difference(Model):
    metric: str
    a: float | None
    b: float | None
    delta_b_minus_a: float | None
    unit: Literal["population_mean_0_100", "recorded_count", "resource_units"]


class Citation(PinnedHistory):
    id: str
    kind: Literal["event", "decision"]
    record_id: str
    tick: Counter
    excerpt: str
    url: str


class Observation(Model):
    fact_id: str
    text: str
    citation_ids: list[str]


class Explanation(Model):
    source: Literal["cortex_selection", "deterministic"]
    status: Literal["available", "unavailable"]
    reason: str | None
    observations: list[Observation]


class Comparison(Model):
    a: Provenance
    b: Provenance
    data_source: Literal["snowflake", "local_export"]
    horizon: Literal["equal_endpoint_ticks", "unequal_endpoint_ticks"]
    lineage: Literal["same_history", "parent_branch", "siblings", "unrelated"]
    differences: list[Difference]
    citations: list[Citation]
    explanation: Explanation
    limitations: list[str]


class ComparisonResponse(Model):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: str
    data: Comparison


class Issue(Model):
    field: str | None
    reason: str


class ErrorBody(Model):
    code: str
    message: str
    retryable: bool
    details: list[Issue]


class Failure(Model):
    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: str
    error: ErrorBody


class Selection(Model):
    fact_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
