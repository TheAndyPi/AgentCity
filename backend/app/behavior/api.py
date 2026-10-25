"""Owned, revision-pinned v2 behavior read/export API under the guarded v1 mount."""

from typing import Literal

from fastapi import Query, Request

from app.behavior.learning import RestLesson
from app.behavior.models import BehaviorDecision, BehaviorEvent, Condition, Fire, Hospital
from app.behavior.rules import VERSION
from app.behavior.vitals import living
from app.contracts import Model, Ref


class Analytics(Model):
    population: int
    living: int
    unconscious: int
    dead: int
    survival_fraction: float
    deaths_by_cause: dict[str, int]
    counters: dict[str, int]
    means_population: Literal["living including unconscious"]
    population_composition_changed: bool
    tiger_behavior_supported: Literal[False]
    snowflake_behavior_supported: Literal[False]


class BehaviorSnapshot(Model):
    simulation_id: str
    ref: Ref
    seed: int
    rule_version: str
    activated_tick: int | None
    citizens: dict[str, Condition]
    learned_rules: dict[str, list[RestLesson]]
    fires: dict[str, Fire]
    hospitals: dict[str, Hospital]
    events: list[BehaviorEvent]
    decisions: list[BehaviorDecision]
    analytics: Analytics


class BehaviorResponse(Model):
    schema_version: Literal["2.0.0"]
    request_id: str
    data: BehaviorSnapshot


def snapshot(state):
    people = list(state.citizens.values())
    alive = sum(living(c) for c in people)
    dead = len(people) - alive
    causes = {}
    for c in people:
        if not living(c):
            for cause in c.condition.causes or ["legacy_inactive"]:
                causes[cause] = causes.get(cause, 0) + 1
    conditions = {c.summary.id: c.condition.model_copy(deep=True) for c in people}
    for c in people:
        if not c.summary.active:
            conditions[c.summary.id].life = "dead"
    return BehaviorSnapshot(
        simulation_id=state.simulation.id,
        ref=state.ref(),
        seed=state.simulation.config.seed,
        rule_version=state.behavior.version or f"legacy; pending {VERSION}",
        activated_tick=state.behavior.activated_tick,
        citizens=conditions,
        learned_rules={c.summary.id: c.rest_lessons for c in people},
        fires=state.behavior.fires,
        hospitals=state.behavior.hospitals,
        events=state.behavior.events,
        decisions=state.behavior.decisions,
        analytics=Analytics(
            population=len(people),
            living=alive,
            unconscious=sum(living(c) and c.condition.life == "unconscious" for c in people),
            dead=dead,
            survival_fraction=alive / len(people) if people else 0,
            deaths_by_cause=causes,
            counters=state.behavior.counters,
            means_population="living including unconscious",
            population_composition_changed=bool(dead),
            tiger_behavior_supported=False,
            snowflake_behavior_supported=False,
        ),
    )


def install(child, service):
    @child.get("/behavior/v2/simulations/{sid}", response_model=BehaviorResponse)
    @child.get("/behavior/v2/simulations/{sid}/export", response_model=BehaviorResponse)
    async def read(request: Request, sid: str, revision: int | None = Query(default=None, ge=0)):
        state = service().published_state(request.state.owner, sid, revision)
        return BehaviorResponse(
            schema_version="2.0.0", request_id=request.state.request_id, data=snapshot(state)
        )
