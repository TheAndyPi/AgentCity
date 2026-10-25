"""Scenario engine routes, mounted on the integrations sub-application.

Interpretation and validation never change the world. Commit runs through the
service's idempotent mutation path with the same intervention, version and
single-event checks as the core scenario commit.
"""

from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.contracts import ID, Model
from app.infrastructure.errors import DomainError, require
from app.scenario_engine import outcomes
from app.scenario_engine.interpreter import interpret
from app.scenario_engine.mutations import describe, parse
from app.scenario_engine.registry import METRICS, OPERATIONS, capabilities
from app.scenario_engine.runtime import attach
from app.scenario_engine.validator import compile_preview, validate_plan
from app.scenario_engine.world import enable
from app.simulation.scenarios import queue_event

PREFIX = "/scenarios"


class PlanRequest(Model):
    intervention_id: ID
    prompt: str = Field(min_length=1, max_length=4000)


class ValidateRequest(Model):
    plan: dict[str, Any]


class CommitRequest(Model):
    intervention_id: ID
    expected_control_version: int
    plan: dict[str, Any]


def ok(request, data, status=200):
    return JSONResponse(dict(schema_version="1.0.0", request_id=request.state.request_id, data=data), status_code=status)


def preview_summary(state, plan, warnings):
    """What the preview modal shows: compiled on a copy so nothing is allocated in the world."""
    copy = state.model_copy(deep=True)
    preview = compile_preview(copy, plan, warnings)
    systems = list(dict.fromkeys([*plan.affected_systems, *(s for op in plan.operations for s in OPERATIONS[op.type][1])]))
    return dict(
        operations=[
            dict(id=op.id, type=op.type, label=describe(op), rationale=op.rationale,
                 timing=op.timing.model_dump(), physical=OPERATIONS[op.type][2])
            for op in plan.operations
        ],
        affected_systems=systems,
        metrics=[dict(id=m, description=METRICS[m]) for m in plan.metrics],
        event_kind=preview.spec.kind,
        region_polygon=[p.model_dump() for p in preview.spec.affected_polygon],
        affected_agent_count=len(preview.affected_agent_ids),
        affected_building_count=len(preview.affected_building_ids),
        measurement_ticks=plan.measurement_ticks,
        warnings=preview.warnings,
    )


def checked(state, raw):
    plan, errors, warnings = validate_plan(state, raw)
    if plan is None:
        return dict(status="invalid", plan=raw, errors=errors, warnings=warnings, unsupported=raw.get("unsupported", []),
                    clarification="", summary=None)
    return dict(status="ready", plan=plan.model_dump(mode="json"), errors=[], warnings=warnings,
                unsupported=plan.unsupported, clarification="", summary=preview_summary(state, plan, warnings))


def commit(service, owner, sid, body):
    from app.service import Transaction

    state = service.owned(owner, sid).model_copy(deep=True)
    service.version(state, body.expected_control_version)
    service.ready(state, True)
    hold = service.hold(state, body.intervention_id)
    record = service.repo.meta.get("editors", {}).get(sid, {})
    if record.get("hold_id") == hold.id:
        state.entity_sequence = max(state.entity_sequence, record["sequence"])
    require(
        not any(r.summary.status in {"queued", "active"} for r in state.events.values()),
        "EVENT_ACTIVE",
        "Another major event is pending",
    )
    plan, errors, warnings = validate_plan(state, body.plan)
    if plan is None:
        raise DomainError("VALIDATION_ERROR", "The scenario plan is not valid", 422, field="plan", reason="; ".join(errors)[:2000])
    resume = hold.was_running
    if resume:
        service.running_slot(sid)
    previous_ref = state.ref()
    service.bump(state, True)
    service.clear_editor(state)
    enable(state)
    preview = compile_preview(state, plan, warnings)
    snapshot = service.snapshot(state, "pre_event", f"Before {plan.title}", previous_ref)
    event = queue_event(state, preview, snapshot.id, resume)
    attach(state, event.id, plan)
    state.simulation.status = "running" if resume else "paused"
    state.simulation.pause_reason = None if resume else "manual"
    data = dict(
        simulation=state.simulation.model_dump(mode="json"),
        event=event.model_dump(mode="json"),
        snapshot=snapshot.model_dump(mode="json"),
        plan=plan.model_dump(mode="json"),
        queued_until_play=not resume,
    )
    return Transaction(data, 201, [state])


def active_record(state):
    return next((r for r in state.systems.plans.values() if r.status == "active"), None)


def systems_view(state):
    systems = state.systems
    record = active_record(state)
    return dict(
        enabled=systems.enabled,
        tick=state.simulation.tick,
        revision=state.simulation.revision,
        policy=systems.policy.model_dump(),
        treasury=round(systems.treasury, 3),
        organizations=[
            dict(id=o.id, kind=o.kind, name=o.name, members=len(o.members), active=o.active, event_id=o.event_id)
            for o in systems.organizations.values()
        ],
        norms=systems.norms,
        conditions=systems.conditions,
        closed_buildings=[
            dict(id=b.id, name=b.name, kind=b.kind) for b in state.map.buildings if not b.functional
        ],
        plans=[
            dict(event_id=r.event_id, title=r.plan["title"], status=r.status,
                 activated_tick=r.activated_tick, resolved_tick=r.resolved_tick)
            for r in systems.plans.values()
        ],
        live=outcomes.measure(state, record) if systems.enabled else None,
        active_event_id=record.event_id if record else None,
    )


def event_view(state, eid):
    record = state.systems.plans.get(eid)
    require(record is not None, "NOT_FOUND", "No scenario plan for this event", 404)
    traces = [t for t in state.systems.traces if t.event_id == eid]
    operations = [t.model_dump() for t in traces if t.kind == "operation"]
    return dict(
        event_id=eid,
        status=record.status,
        plan=record.plan,
        operations=[dict(id=op["id"], type=op["type"], label=describe(parse(op))) for op in record.plan["operations"]],
        activated_tick=record.activated_tick,
        resolved_tick=record.resolved_tick,
        baseline=record.baseline,
        current=outcomes.measure(state, record) if record.status == "active" else (record.series[-1] if record.series else None),
        series=record.series[-200:],
        findings=record.findings,
        policy_before=record.policy_before,
        policy_after=record.policy_after,
        operation_traces=operations[-60:],
        decisions=[t.model_dump() for t in outcomes.significant_decisions(state, eid)],
        decision_count=sum(t.kind == "decision" for t in traces),
    )


def agent_view(state, aid):
    citizen = state.citizens.get(aid)
    require(citizen is not None, "NOT_FOUND", "Citizen not found", 404)
    agent = state.systems.agents.get(aid)
    traces = [t for t in state.systems.traces if t.agent_id == aid][-40:]
    traces.reverse()
    return dict(
        agent_id=aid,
        enabled=state.systems.enabled,
        systems=None if agent is None else dict(
            wallet=round(agent.wallet, 3),
            income=agent.income,
            owns_car=agent.owns_car,
            habit=agent.habit,
            institutional_trust=round(agent.institutional_trust, 2),
            housing_status=agent.housing_status,
            renter=agent.renter,
            home_id=agent.home_id,
            norms=agent.norms,
            organizations=[
                dict(id=o, name=state.systems.organizations[o].name)
                for o in agent.organizations if o in state.systems.organizations
            ],
            incentives=agent.incentives,
            beliefs=[b.model_dump() for b in agent.beliefs.values()][-12:],
            trips=agent.trips,
            satisfaction=round(agent.satisfaction, 2),
        ),
        traces=[t.model_dump() for t in traces],
    )


def register(child, service):
    @child.get(PREFIX + "/capabilities")
    async def get_capabilities(request: Request):
        return ok(request, capabilities() | dict(interpreter=service().config.gemini_enabled))

    @child.post(PREFIX + "/simulations/{sid}/plans")
    async def create_plan(request: Request, sid: str, body: PlanRequest):
        current = service()
        state = current.owned(request.state.owner, sid)
        current.hold(state, body.intervention_id)
        result = await interpret(current.gateway, state, sid, body.prompt, state.simulation.config.mode)
        state = current.owned(request.state.owner, sid)
        if result["status"] == "ready":
            plan, _, warnings = validate_plan(state, result["plan"])
            if plan is None:
                result = checked(state, result["plan"])
            else:
                result["summary"] = preview_summary(state, plan, warnings)
        else:
            result["summary"] = None
        return ok(request, result)

    @child.post(PREFIX + "/simulations/{sid}/plans/validate")
    async def validate(request: Request, sid: str, body: ValidateRequest):
        state = service().owned(request.state.owner, sid)
        return ok(request, checked(state, body.plan))

    @child.post(PREFIX + "/simulations/{sid}/commits")
    async def create_commit(request: Request, sid: str, body: CommitRequest):
        current = service()
        owner = request.state.owner
        response, status = await current.mutate(
            owner, request.state.request_id, f"POST {request.url.path}", body.model_dump(mode="json"),
            lambda: commit(current, owner, sid, body), sid,
        )
        return JSONResponse(response, status_code=status)

    @child.get(PREFIX + "/simulations/{sid}/state")
    async def get_state(request: Request, sid: str, revision: int | None = Query(default=None, ge=0)):
        return ok(request, systems_view(service().owned(request.state.owner, sid, revision)))

    @child.get(PREFIX + "/simulations/{sid}/events/{eid}")
    async def get_event(request: Request, sid: str, eid: str, revision: int | None = Query(default=None, ge=0)):
        return ok(request, event_view(service().owned(request.state.owner, sid, revision), eid))

    @child.get(PREFIX + "/simulations/{sid}/agents/{aid}/traces")
    async def get_traces(request: Request, sid: str, aid: str, revision: int | None = Query(default=None, ge=0)):
        return ok(request, agent_view(service().owned(request.state.owner, sid, revision), aid))

    @child.get(PREFIX + "/simulations/{sid}/initial-plan")
    async def initial_plan(request: Request, sid: str):
        state = service().owned(request.state.owner, sid)
        pending = state.simulation.initial_preview
        plan = state.systems.initial_plan if pending and pending.id == state.systems.initial_preview_id else None
        summary = None
        if plan:
            parsed, _, warnings = validate_plan(state, plan)
            summary = preview_summary(state, parsed, warnings) if parsed else None
        return ok(request, dict(plan=plan, summary=summary))
