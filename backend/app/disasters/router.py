"""Authenticated disaster v2 extension. Mutation receipts share the core writer."""

import copy
import math
import re
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from pydantic import Field

from app import contracts as c
from app.disasters.geometry import envelope, intersects
from app.disasters.models import LIMITS, ExportView, Parameters, PreviewResult, Repair, StateView
from app.disasters.physics import STRUCTURAL_RATES, initialize, view
from app.infrastructure.errors import require
from app.narration.router import _failure
from app.service import Transaction
from app.simulation.navigation import polygon_contains
from app.simulation.scenario_scene import CATALOG, build_scene
from app.simulation.scenarios import queue_event
from app.simulation.state import expired, expiry

PATH = "/api/v1/integrations/disasters"


class PreviewRequest(c.Model):
    editor_generation: int = Field(default=0, ge=0)
    original_prompt: str | None = Field(default=None, max_length=2000)
    intervention_id: str = Field(min_length=1, max_length=200)
    parameters: Parameters


class CommitRequest(c.Model):
    intervention_id: str = Field(min_length=1, max_length=200)
    preview_id: str = Field(min_length=1, max_length=200)
    expected_control_version: int = Field(ge=0)


class RepairRequest(c.Model):
    action: str = Field(default="repair", pattern="^(repair|clear)$")
    expected_control_version: int = Field(ge=0)
    building_id: str = Field(min_length=1, max_length=200)


class Control(c.Model):
    expected_control_version: int = Field(ge=0)


def make_preview(state, body):
    params = body.parameters
    poly = envelope(params, state.map)
    spec = c.EventSpec(
        title=f"{params.kind.title()} · {params.intensity:g} {LIMITS[params.kind]['unit']}",
        description="Versioned local physical disaster; persistent damage survives resolution.",
        kind=params.kind if params.kind in {"flood", "fire", "storm"} else "custom",
        origin=params.origin,
        affected_polygon=poly,
        severity=params.normalized * 100,
        duration_ticks=params.duration_ticks,
        effects=[
            dict(
                type="hazard",
                hazard=params.kind if params.kind in {"flood", "fire", "storm"} else "storm",
                severity=params.normalized * 100,
            )
        ],
        success_condition="duration_elapsed",
    )
    if params.normalized > 0 and params.kind in {"flood", "fire", "storm"}:
        spec.scene = build_scene(state, spec, [recipe for recipe in CATALOG if recipe["id"] == params.kind])
    preview = c.ScenarioPreview(
        id=f"preview_{uuid4().hex}",
        simulation_id=state.simulation.id,
        source="custom",
        source_event_id=None,
        based_on=state.ref(),
        expires_at=expiry(),
        interpretation=f"{params.kind.title()}: {params.intensity:g} {LIMITS[params.kind]['unit']}, {params.extent_m:g} m {'width' if params.kind == 'tornado' else 'radius'}. Simplified gameplay rules; damage is projected, not committed.",
        spec=spec,
        affected_agent_ids=[
            aid for aid, citizen in state.citizens.items() if polygon_contains(citizen.summary.position, poly)
        ],
        affected_building_ids=[b.id for b in state.map.buildings if intersects(b.footprint, poly)],
        warnings=[
            "Unsafe buildings close below 50 integrity; repair is explicit.",
            "Indoor injury multiplier 0.4; unsafe structure multiplier 1.4.",
        ],
        unsupported_requests=[
            f"Only the displayed typed controls are executable. Other narrative modifiers are not applied: {body.original_prompt[:500]}"
        ]
        if body.original_prompt
        else [],
        can_commit=True,
    )
    return dict(
        schema_version="2.0.0",
        damage_projection=dict(
            min_integrity_loss=0.0,
            max_integrity_loss=min(
                100.0,
                STRUCTURAL_RATES[params.kind]
                * params.normalized**2
                * (params.duration_ticks + 1)
                * state.simulation.config.tick_seconds
                / 5,
            ),
            description="Conservative integrity-loss range per structure at peak exposure and resistance 1 over the full event. Local attenuation, existing integrity and cancellation can reduce actual loss; separate disasters can compound it.",
        ),
        parameters=params.model_dump(),
        preview=preview.model_dump(),
        bounds=dict(
            min_extent_m=state.map.cell_size_m, max_extent_m=math.hypot(state.map.width_m, state.map.height_m)
        ),
        duration_seconds=params.duration_ticks * state.simulation.config.tick_seconds,
    )


def parse_prompt(prompt, map_data, seed):
    text = prompt.lower()
    kind = next((k for k in LIMITS if re.search(rf"\b{k}\b", text)), None)
    if kind is None:
        return None
    intensity = LIMITS[kind]["default"]
    patterns = {
        "earthquake": r"(?:magnitude|mw)\s*([\d.]+)",
        "tornado": r"([\d.]+)\s*m/s",
        "storm": r"([\d.]+)\s*m/s",
        "flood": r"([\d.]+)\s*(?:m|meters?)\s*(?:deep|depth)",
        "fire": r"(?:heat|danger)\s*([\d.]+)",
    }
    match = re.search(patterns[kind], text)
    if match:
        intensity = float(match[1])
    extent = next(iter(re.findall(r"([\d.]+)[ -]*(?:m|meter|meters)[ -]*(?:width|radius)", text)), None)
    ticks = re.search(r"(\d+)\s*ticks?", text)
    origin = c.Vec2(x=map_data.width_m / 2, y=map_data.height_m / 2)
    return Parameters(
        kind=kind,
        intensity=intensity,
        extent_m=float(extent) if extent else 24.0,
        origin=origin,
        track_end=c.Vec2(x=min(map_data.width_m, origin.x + 32), y=origin.y) if kind == "tornado" else None,
        duration_ticks=int(ticks[1]) if ticks else 12,
        seed=seed % 2147483648,
    )


def install_disasters(parent):
    child = FastAPI(title="AgentCity disasters", version="2.0.0")
    child.exception_handlers.update(parent.exception_handlers)

    @child.middleware("http")
    async def guard(request, call_next):
        try:
            owner, _ = parent.state.security.identity(
                request, unsafe=request.method not in {"GET", "HEAD", "OPTIONS"}
            )
            request.state.owner = owner
            return await call_next(request)
        except Exception as error:
            from app.infrastructure.errors import DomainError

            if isinstance(error, DomainError):
                return _failure(request, error.code, error.message, error.status)
            raise

    async def write(request, body, sid, operation):
        result, status = await parent.state.service.mutate(
            request.state.owner,
            request.state.request_id,
            f"{request.method} {request.url.path}",
            body.model_dump(mode="json"),
            operation,
            sid,
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(result, status_code=status)

    def owned(request, sid, revision=None):
        return parent.state.service.owned(request.state.owner, sid, revision)

    def ok(request, data):
        return dict(schema_version="1.0.0", request_id=request.state.request_id, data=data)

    @child.get("/v2/simulations/{sid}/state", response_model=c.Success[StateView])
    async def state(request: Request, sid: str, revision: int | None = Query(default=None, ge=0)):
        return ok(request, view(owned(request, sid, revision)))

    @child.get("/v2/simulations/{sid}/export", response_model=c.Success[ExportView])
    async def export(request: Request, sid: str, revision: int | None = Query(default=None, ge=0)):
        # Complete canonical records, not snippets; callers pin this revision.
        state = owned(request, sid, revision)
        data = view(state)
        data["reactions"] = [r.model_dump() for r in state.reactions]
        data["totals"] = dict(
            damaged_buildings=sum(c.integrity < 100 for c in state.conditions.values()),
            structural_transitions=sum(r.units == "integrity" for r in state.damage_records),
            stock_units_lost=sum(r.before - r.after for r in state.damage_records if r.units == "stock"),
        )
        return ok(request, data)

    @child.post("/v2/simulations/{sid}/previews", status_code=201, response_model=c.Success[PreviewResult])
    async def preview(request: Request, sid: str, body: PreviewRequest):
        service = parent.state.service

        def operation():
            state = owned(request, sid)
            service.hold(state, body.intervention_id)
            previous = service.repo.meta.get("disaster_editors", {}).get(sid, {})
            require(
                previous.get("hold_id") != body.intervention_id
                or body.editor_generation >= previous.get("editor_generation", 0),
                "PREVIEW_STALE",
                "A newer control preview is already available",
            )
            result = make_preview(state, body)
            editors = copy.deepcopy(service.repo.meta.get("disaster_editors", {}))
            editors[sid] = dict(
                hold_id=body.intervention_id, editor_generation=body.editor_generation, **result
            )
            return Transaction(result, 201, metadata={"disaster_editors": editors})

        return await write(request, body, sid, operation)

    @child.post("/v2/simulations/{sid}/commits", status_code=201, response_model=c.Success[c.ScenarioResult])
    async def commit(request: Request, sid: str, body: CommitRequest):
        service = parent.state.service

        def operation():
            state = owned(request, sid).model_copy(deep=True)
            service.version(state, body.expected_control_version)
            service.ready(state, True)
            hold = service.hold(state, body.intervention_id)
            record = service.repo.meta.get("disaster_editors", {}).get(sid, {})
            require(
                record.get("hold_id") == hold.id and record.get("preview", {}).get("id") == body.preview_id,
                "PREVIEW_STALE",
                "Refresh the disaster preview",
            )
            p = c.ScenarioPreview.model_validate(record["preview"])
            require(not expired(p.expires_at), "PREVIEW_EXPIRED", "Preview expired", 410)
            require(p.based_on == state.ref(), "PREVIEW_STALE", "World changed; refresh preview")
            require(
                not state.simulation.pending_outcome_event_ids,
                "INVALID_STATE",
                "Continue the previous outcome first",
            )
            initialize(state)
            previous = state.ref()
            service.bump(state, True)
            snapshot = service.snapshot(state, "pre_event", f"Before {p.spec.title}", previous)
            event = queue_event(state, p, snapshot.id, hold.was_running)
            state.events[event.id].physical = Parameters.model_validate(record["parameters"])
            state.simulation.status = "running" if hold.was_running else "paused"
            state.simulation.pause_reason = None if hold.was_running else "manual"
            service.clear_editor(state)
            return Transaction(
                c.ScenarioResult(simulation=state.simulation, event=event, snapshot=snapshot), 201, [state]
            )

        return await write(request, body, sid, operation)

    @child.post("/v2/simulations/{sid}/events/{eid}/cancel", response_model=c.Success[StateView])
    async def cancel(request: Request, sid: str, eid: str, body: Control):
        service = parent.state.service

        def operation():
            state = owned(request, sid).model_copy(deep=True)
            service.version(state, body.expected_control_version)
            runtime = state.events.get(eid)
            require(
                runtime and runtime.physical and runtime.summary.status in {"active", "queued"},
                "INVALID_STATE",
                "Disaster is not active or queued",
            )
            runtime.cancelled = True
            runtime.summary.status = "cancelled"  # Existing strict v1 status
            runtime.summary.end_tick = state.simulation.tick
            runtime.summary.summary = "Cancelled; committed damage remains"
            runtime.after = state.metric_points[-1].values.model_copy()
            from app.disasters.physics import effective_services

            effective_services(state)
            service.bump(state, True)
            return Transaction(view(state), states=[state])

        return await write(request, body, sid, operation)

    @child.post("/v2/simulations/{sid}/repairs", status_code=201, response_model=c.Success[Repair])
    async def repair(request: Request, sid: str, body: RepairRequest):
        service = parent.state.service

        def operation():
            state = owned(request, sid).model_copy(deep=True)
            service.version(state, body.expected_control_version)
            service.ready(state, True)
            initialize(state)
            b = next((b for b in state.map.buildings if b.id == body.building_id), None)
            require(b is not None, "NOT_FOUND", "Building not found", 404)
            require(state.conditions[b.id].integrity < 100, "INVALID_STATE", "Building is intact")
            require(
                not any(j.building_id == b.id and j.status == "pending" for j in state.repairs),
                "INVALID_STATE",
                "Repair already scheduled",
            )
            require(
                body.action == "clear"
                or not any(
                    b.id
                    in {
                        c.inside_building_id,
                        c.entering_building_id,
                        c.leaving_building_id,
                        c.trapped_building_id,
                    }
                    for c in state.citizens.values()
                ),
                "INVALID_STATE",
                "Evacuate occupants and reservations before repair",
            )
            require(
                not any(
                    r.summary.status in {"queued", "active"}
                    and intersects(b.footprint, r.spec.affected_polygon)
                    for r in state.events.values()
                ),
                "INVALID_STATE",
                "Stop the local hazard before repair",
            )
            cost = 2.0 if body.action == "clear" else 10.0
            resource = next(
                (r for r in state.map.resources if r.kind == "supplies" and r.available_units >= cost), None
            )
            require(resource is not None, "INVALID_STATE", "Repair needs 10 public supplies")
            resource.available_units -= cost
            job = Repair(
                action=body.action,
                id=state.next_id("repair"),
                building_id=b.id,
                start_tick=state.simulation.tick,
                finish_tick=state.simulation.tick
                + max(
                    1,
                    math.ceil((10 if body.action == "clear" else 30) / state.simulation.config.tick_seconds),
                ),
                before=state.conditions[b.id].integrity,
                supplies=cost,
                resource_id=resource.id,
            )
            state.repairs.append(job)
            service.bump(state, True)
            return Transaction(job.model_dump(), 201, [state])

        return await write(request, body, sid, operation)

    parent.mount(PATH, child)
    mount = parent.router.routes.pop()
    enclosing = next(
        (i for i, r in enumerate(parent.router.routes) if getattr(r, "path", None) == "/api/v1/integrations"),
        0,
    )
    parent.router.routes.insert(enclosing, mount)
    parent.state.disasters = child
