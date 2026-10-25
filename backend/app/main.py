from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4

import anyio
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app import contracts as c
from app.api.security import COOKIE, Security
from app.api.views import Cursors, agent_detail, agent_records, frame, overview
from app.infrastructure.config import AppConfig
from app.infrastructure.errors import DomainError, require
from app.narration.router import install_narration, narrate
from app.service import Service, Transaction
from app.simulation.scenarios import event_report
from app.simulation.state import now, uid
from app.snowflake.config import SnowflakeConfig
from app.snowflake.router import install_snowflake

Revision = Annotated[int | None, Query(ge=0, le=9007199254740991)]
Limit = Annotated[int, Query(ge=1, le=100)]
API = "/api/v1"


def create_app(config: AppConfig | None = None, narration_config=None, narration_transport=None):
    runtime = config or AppConfig.from_env()
    snowflake_config = SnowflakeConfig.from_env()

    @asynccontextmanager
    async def lifespan(app):
        service = Service(runtime)
        app.state.service = service
        app.state.security = Security(service)
        app.state.cursors = Cursors(service.repo.meta["cursor_secret"])
        integrations.state.service = service
        integrations.state.security = app.state.security
        integrations.state.cursors = app.state.cursors
        await service.start()
        expirer = asyncio.create_task(service.expire_holds())
        try:
            yield
        finally:
            expirer.cancel()
            await asyncio.gather(expirer, return_exceptions=True)
            await service.close()

    errors = {status: {"model": c.Failure} for status in [400, 401, 403, 404, 409, 410, 422, 429, 501, 503]}
    app = FastAPI(title="AgentCity API", version="1.0.0", lifespan=lifespan, responses=errors)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
    )

    def failure(request, code, message, status, details=None):
        headers = {"Retry-After": "60"} if status == 429 else None
        return JSONResponse(
            {
                "schema_version": "1.0.0",
                "request_id": getattr(request.state, "request_id", str(uuid4())),
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": status in {429, 503},
                    "details": details or [],
                },
            },
            status_code=status,
            headers=headers,
        )

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return failure(request, error.code, error.message, error.status, error.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return failure(
            request,
            "VALIDATION_ERROR",
            "Request validation failed",
            422,
            [
                {"field": ".".join(str(x) for x in item["loc"]), "reason": item["msg"]}
                for item in error.errors()
            ],
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return failure(
            request,
            "NOT_FOUND" if error.status_code == 404 else "INVALID_REQUEST",
            str(error.detail),
            error.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        # Do not expose request bodies, credentials, provider URLs or exception text.
        import logging

        logging.getLogger("agentcity").error("Unhandled request failure: %s", type(error).__name__)
        return failure(request, "SERVICE_UNAVAILABLE", "The request could not be completed", 503)

    @app.middleware("http")
    async def guard(request, call_next):
        request.state.request_id = str(uuid4())
        try:
            unsafe = request.method in {"POST", "PUT", "PATCH", "DELETE"}
            if request.url.path.startswith(API) and request.method != "OPTIONS":
                is_login = request.url.path == API + "/session" and request.method == "POST"
                is_session_read = request.url.path == API + "/session" and request.method == "GET"
                if unsafe:
                    key = request.headers.get("idempotency-key", "")
                    try:
                        require(
                            str(UUID(key)) == key.lower(),
                            "INVALID_REQUEST",
                            "Idempotency-Key must use the canonical hyphenated UUID form",
                            400,
                        )
                    except ValueError:
                        raise DomainError("INVALID_REQUEST", "A UUID Idempotency-Key header is required", 400)
                    request.state.request_id = key
                if request.url.path != API + "/capabilities":
                    if is_session_read:
                        try:
                            owner, csrf = app.state.security.identity(request)
                        except DomainError as error:
                            if error.status != 401:
                                raise
                            owner, csrf = None, None
                    else:
                        owner, csrf = app.state.security.identity(request, unsafe, is_login)
                    request.state.owner = owner
                    request.state.csrf = csrf
            return await call_next(request)
        except DomainError as error:
            return failure(request, error.code, error.message, error.status, error.details)

    def ok(request, data):
        return dict(schema_version="1.0.0", request_id=request.state.request_id, data=data)

    def services(request):
        return request.app.state.service, request.app.state.cursors

    async def write(request, body, operation, sid=None, owner=None):
        service, _ = services(request)
        key = request.state.request_id
        if isinstance(body, c.CommandRequest):
            require(
                body.request_id == key, "INVALID_REQUEST", "Body request_id must match Idempotency-Key", 400
            )
        value = body.model_dump(mode="json") if isinstance(body, c.Model) else body
        response, status = await service.mutate(
            owner or request.state.owner, key, f"{request.method} {request.url.path}", value, operation, sid
        )
        return JSONResponse(response, status_code=status)

    def resolved(request, sid, revision=None, cursor=None, resource=None, filters=None):
        service, cursors = services(request)
        if cursor:
            value = cursors.context(request.state.owner, resource, filters or {}, revision, cursor)
            revision = value["revision"]
        return service.owned(request.state.owner, sid, revision)

    def paged(request, state, items, resource, filters, cursor, limit):
        return ok(
            request,
            app.state.cursors.page(
                items, request.state.owner, resource, filters, state.simulation.revision, cursor, limit
            ),
        )

    @app.get("/health/live", response_model=c.Health)
    async def live():
        return {"status": "ok", "details": []}

    @app.get(
        "/health/ready",
        response_model=c.Health,
        responses={503: {"model": c.Health, "description": "Persistence is degraded"}},
    )
    async def ready(request: Request):
        details = list(request.app.state.service.repo.degraded)
        return JSONResponse(
            {"status": "degraded" if details else "ok", "details": details},
            status_code=503 if details else 200,
        )

    @app.get(API + "/capabilities", response_model=c.Success[c.Capabilities])
    async def capabilities(request: Request):
        return ok(
            request,
            c.Capabilities(
                contract_version="1.0.0",
                auth_mode=runtime.auth_mode,
                max_agents=runtime.max_agents,
                max_concurrent_running_simulations=runtime.max_running,
                gemini=runtime.gemini_enabled,
                narration=request.app.state.narration.enabled,
                snowflake=app.state.integrations.state.comparison.config.enabled,
                persistence="local",
                replay=True,
                branching=True,
            ),
        )

    @app.get(API + "/session", response_model=c.Success[c.SessionInfo])
    async def session(request: Request):
        return ok(
            request,
            c.SessionInfo(authenticated=request.state.owner is not None, csrf_token=request.state.csrf),
        )

    @app.post(API + "/session", response_model=c.Success[c.LoginResult])
    async def login(request: Request, body: c.Login):
        service, _ = services(request)

        def operation():
            raw, key, record = app.state.security.login(request, body.passphrase)
            sessions = copy.deepcopy(service.repo.meta["sessions"])
            sessions[key] = record
            receipts = copy.deepcopy(service.repo.meta.get("login_receipts", {}))
            receipts[request.state.request_id] = raw
            return Transaction(
                c.LoginResult(csrf_token=record["csrf_token"]),
                metadata={"sessions": sessions, "login_receipts": receipts},
            )

        response = await write(request, body, operation, owner="login")
        raw = service.repo.meta.get("login_receipts", {}).get(request.state.request_id)
        if raw:
            response.set_cookie(
                COOKIE, raw, max_age=86400, httponly=True, secure=True, samesite="lax", path="/"
            )
        return response

    @app.delete(API + "/session", response_model=c.Success[c.SignedOut])
    async def sign_out(request: Request):
        service, _ = services(request)

        def operation():
            sessions = copy.deepcopy(service.repo.meta["sessions"])
            raw = request.cookies.get(COOKIE, "")
            sessions.pop(app.state.security.session_key(raw), None)
            return Transaction(c.SignedOut(signed_out=True), metadata={"sessions": sessions})

        response = await write(request, {}, operation)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    @app.post(API + "/simulations", status_code=202, response_model=c.Success[c.Simulation])
    async def create_simulation(request: Request, body: c.CreateSimulation):
        service, _ = services(request)
        return await write(request, body, lambda: service.create(request.state.owner, body))

    @app.get(API + "/simulations", response_model=c.Success[c.Page[c.Simulation]])
    async def simulations(
        request: Request, archived: bool = False, cursor: str | None = None, limit: Limit = 25
    ):
        service, cursors = services(request)
        owner = request.state.owner
        filters = {"archived": archived}
        value = cursors.context(owner, "simulations", filters, None, cursor)
        if value:
            selection = value["selection"]
            offset = value["offset"]
        else:
            heads = sorted(
                [
                    h
                    for h in service.heads.values()
                    if h.owner_id == owner and h.simulation.archived == archived
                ],
                key=lambda h: (h.simulation.updated_at, h.simulation.id),
                reverse=True,
            )
            selection = [(h.simulation.id, h.simulation.revision) for h in heads]
            offset = 0
        items = [
            service.owned(owner, sid, rev).simulation
            for sid, rev in selection[offset : offset + limit]
            if sid in service.heads
        ]
        next_cursor = (
            cursors.sign(
                dict(
                    owner=owner,
                    resource="simulations",
                    filters=filters,
                    revision=None,
                    selection=selection,
                    offset=offset + limit,
                )
            )
            if offset + limit < len(selection)
            else None
        )
        return ok(request, dict(items=items, next_cursor=next_cursor))

    @app.get(API + "/simulations/{sid}", response_model=c.Success[c.Simulation])
    async def simulation(request: Request, sid: str):
        return ok(request, resolved(request, sid).simulation)

    @app.get(API + "/simulations/{sid}/state", response_model=c.Success[c.WorldFrame])
    async def state(request: Request, sid: str, revision: Revision = None):
        return ok(request, frame(resolved(request, sid, revision)))

    @app.post(API + "/simulations/{sid}/commands", response_model=c.Success[c.CommandResult])
    async def command(request: Request, sid: str, body: c.CommandRequest):
        service, _ = services(request)
        return await write(request, body, lambda: service.command(request.state.owner, sid, body), sid)

    @app.get(API + "/simulations/{sid}/agents", response_model=c.Success[c.Page[c.AgentSummary]])
    async def agents(
        request: Request,
        sid: str,
        revision: Revision = None,
        q: Annotated[str | None, Query(max_length=2000)] = None,
        cursor: str | None = None,
        limit: Limit = 25,
    ):
        resource = f"{sid}/agents"
        filters = {"q": q}
        state = resolved(request, sid, revision, cursor, resource, filters)
        items = sorted(
            [
                citizen.summary
                for citizen in state.citizens.values()
                if not q or q.casefold() in (citizen.summary.name + " " + citizen.summary.role).casefold()
            ],
            key=lambda a: (a.name, a.id),
        )
        return paged(request, state, items, resource, filters, cursor, limit)

    @app.get(API + "/simulations/{sid}/agents/{aid}", response_model=c.Success[c.AgentDetail])
    async def agent(request: Request, sid: str, aid: str, revision: Revision = None):
        return ok(request, agent_detail(resolved(request, sid, revision), aid, app.state.cursors))

    @app.get(
        API + "/simulations/{sid}/agents/{aid}/{collection}",
        response_model=c.Success[c.Page[c.Memory] | c.Page[c.Relationship] | c.Page[c.Decision]],
    )
    async def collection(
        request: Request,
        sid: str,
        aid: str,
        collection: Literal["memories", "relationships", "decisions"],
        revision: Revision = None,
        cursor: str | None = None,
        limit: Limit = 25,
    ):
        resource = f"{sid}/agents/{aid}/{collection}"
        state = resolved(request, sid, revision, cursor, resource, {})
        return paged(request, state, agent_records(state, aid, collection), resource, {}, cursor, limit)

    @app.get(API + "/simulations/{sid}/decisions/{did}", response_model=c.Success[c.Decision])
    async def decision(request: Request, sid: str, did: str, revision: Revision = None):
        state = resolved(request, sid, revision)
        item = next((item for item in state.decisions if item.id == did), None)
        require(item is not None, "NOT_FOUND", "Decision not found at this revision", 404)
        return ok(request, item)

    @app.get(API + "/simulations/{sid}/events", response_model=c.Success[c.Page[c.EventSummary]])
    async def events(
        request: Request, sid: str, revision: Revision = None, cursor: str | None = None, limit: Limit = 25
    ):
        resource = f"{sid}/events"
        state = resolved(request, sid, revision, cursor, resource, {})
        return paged(
            request,
            state,
            sorted(
                [r.summary for r in state.events.values()], key=lambda e: (e.queued_tick, e.id), reverse=True
            ),
            resource,
            {},
            cursor,
            limit,
        )

    @app.get(API + "/simulations/{sid}/events/{eid}", response_model=c.Success[c.EventReport])
    async def event(request: Request, sid: str, eid: str, revision: Revision = None):
        state = resolved(request, sid, revision)
        runtime = state.events.get(eid)
        require(runtime is not None, "NOT_FOUND", "Event not found at this revision", 404)
        return ok(request, event_report(state, runtime))

    @app.get(API + "/simulations/{sid}/dialogue", response_model=c.Success[c.Page[c.Dialogue]])
    async def dialogue(
        request: Request, sid: str, revision: Revision = None, cursor: str | None = None, limit: Limit = 25
    ):
        resource = f"{sid}/dialogue"
        state = resolved(request, sid, revision, cursor, resource, {})
        return paged(
            request,
            state,
            sorted(state.dialogue, key=lambda d: (d.tick, d.id), reverse=True),
            resource,
            {},
            cursor,
            limit,
        )

    @app.get(API + "/simulations/{sid}/metrics", response_model=c.Success[c.MetricSeries])
    async def metrics(
        request: Request,
        sid: str,
        revision: Revision = None,
        from_tick: Annotated[int, Query(ge=0)] = 0,
        to_tick: Annotated[int | None, Query(ge=0)] = None,
        stride: Annotated[int, Query(ge=1, le=10000)] = 1,
    ):
        state = resolved(request, sid, revision)
        end = state.simulation.tick if to_tick is None else min(to_tick, state.simulation.tick)
        points = [
            p
            for p in state.metric_points
            if from_tick <= p.tick <= end and (p.tick - from_tick) % stride == 0
        ]
        return ok(request, c.MetricSeries(points=points))

    @app.get(API + "/simulations/{sid}/overview", response_model=c.Success[c.Overview])
    async def world_overview(request: Request, sid: str, revision: Revision = None):
        return ok(request, overview(resolved(request, sid, revision)))

    @app.get(API + "/simulations/{sid}/timeline", response_model=c.Success[c.Page[c.TimelinePoint]])
    async def timeline(
        request: Request, sid: str, revision: Revision = None, cursor: str | None = None, limit: Limit = 25
    ):
        resource = f"{sid}/timeline"
        state = resolved(request, sid, revision, cursor, resource, {})
        entries = app.state.service.repo.meta["simulations"][sid][: state.simulation.revision + 1]
        items = [
            c.TimelinePoint(
                ref=c.Ref(tick=item["tick"], revision=item["revision"]),
                sim_time_seconds=item["tick"] * state.simulation.config.tick_seconds,
            )
            for item in entries
        ]
        return paged(request, state, items, resource, {}, cursor, limit)

    @app.get(API + "/simulations/{sid}/snapshots", response_model=c.Success[c.Page[c.Snapshot]])
    async def snapshots(
        request: Request, sid: str, revision: Revision = None, cursor: str | None = None, limit: Limit = 25
    ):
        resource = f"{sid}/snapshots"
        state = resolved(request, sid, revision, cursor, resource, {})
        return paged(
            request,
            state,
            sorted(state.snapshots, key=lambda s: (s.ref.tick, s.id), reverse=True),
            resource,
            {},
            cursor,
            limit,
        )

    @app.post(
        API + "/simulations/{sid}/interventions", status_code=201, response_model=c.Success[c.Intervention]
    )
    async def open_intervention(request: Request, sid: str, body: c.ExpectedControl):
        service, _ = services(request)
        return await write(
            request, body, lambda: service.open_intervention(request.state.owner, sid, body), sid
        )

    @app.post(
        API + "/simulations/{sid}/scenario-previews",
        status_code=201,
        response_model=c.Success[c.ScenarioPreview],
    )
    async def preview(request: Request, sid: str, body: c.PreviewRequest):
        service, _ = services(request)
        provider = await service.prepare_scene(request.state.owner, sid, body, request.state.request_id)
        return await write(
            request, body, lambda: service.preview(request.state.owner, sid, body, provider), sid
        )

    @app.post(API + "/simulations/{sid}/interventions/{iid}/cancel", response_model=c.Success[c.Simulation])
    async def cancel(request: Request, sid: str, iid: str, body: c.ExpectedControl):
        service, _ = services(request)
        return await write(request, body, lambda: service.cancel(request.state.owner, sid, iid, body), sid)

    @app.post(
        API + "/simulations/{sid}/scenario-commits",
        status_code=201,
        response_model=c.Success[c.ScenarioResult],
    )
    async def scenario_commit(request: Request, sid: str, body: c.CommitScenario):
        service, _ = services(request)
        return await write(
            request, body, lambda: service.commit_scenario(request.state.owner, sid, body), sid
        )

    @app.post(API + "/simulations/{sid}/initial-scenario", response_model=c.Success[c.InitialResult])
    async def initial_scenario(request: Request, sid: str, body: c.InitialScenario):
        service, _ = services(request)
        return await write(
            request, body, lambda: service.commit_scenario(request.state.owner, sid, body, True), sid
        )

    @app.post(API + "/simulations/{sid}/branches", status_code=201, response_model=c.Success[c.BranchResult])
    async def branch(request: Request, sid: str, body: c.BranchRequest):
        service, _ = services(request)
        return await write(request, body, lambda: service.branch(request.state.owner, sid, body), sid)

    @app.delete(API + "/simulations/{sid}", response_model=c.Success[c.Deleted])
    async def delete(request: Request, sid: str, body: c.DeleteSimulation):
        service, _ = services(request)
        return await write(request, body, lambda: service.delete(request.state.owner, sid, body), sid)

    @app.get(API + "/custom-agents", response_model=c.Success[c.Page[c.CustomAgent]])
    async def custom_agents(request: Request, cursor: str | None = None, limit: Limit = 25):
        service, cursors = services(request)
        owner = request.state.owner
        value = cursors.context(owner, "custom-agents", {}, None, cursor)
        items = (
            value["selection"]
            if value
            else sorted(
                [
                    record["data"]
                    for record in service.repo.meta["profiles"].values()
                    if record["owner_id"] == owner
                ],
                key=lambda p: (p["profile"]["name"], p["id"]),
            )
        )
        offset = value["offset"] if value else 0
        token = (
            cursors.sign(
                dict(
                    owner=owner,
                    resource="custom-agents",
                    filters={},
                    revision=None,
                    selection=items,
                    offset=offset + limit,
                )
            )
            if offset + limit < len(items)
            else None
        )
        return ok(request, dict(items=items[offset : offset + limit], next_cursor=token))

    def change_profile(request, body, pid=None, delete=False):
        service, _ = services(request)
        profiles = copy.deepcopy(service.repo.meta["profiles"])
        version = 0
        if pid:
            record = profiles.get(pid)
            require(
                record is not None and record["owner_id"] == request.state.owner,
                "NOT_FOUND",
                "Custom profile not found",
                404,
            )
            version = record["data"]["version"]
            require(
                version == body.expected_version,
                "CONTROL_CONFLICT",
                "Profile version is stale",
                reason=f"Latest version={version}",
            )
        else:
            pid = uid("profile")
        if delete:
            profiles.pop(pid)
            return Transaction(c.Deleted(deleted_id=pid), metadata={"profiles": profiles})
        profile = c.CustomAgent(id=pid, version=version + 1, profile=body.profile, updated_at=now())
        profiles[pid] = dict(owner_id=request.state.owner, data=profile.model_dump())
        return Transaction(profile, 200 if version else 201, metadata={"profiles": profiles})

    @app.post(API + "/custom-agents", status_code=201, response_model=c.Success[c.CustomAgent])
    async def create_profile(request: Request, body: c.ProfileRequest):
        return await write(request, body, lambda: change_profile(request, body))

    @app.put(API + "/custom-agents/{pid}", response_model=c.Success[c.CustomAgent])
    async def update_profile(request: Request, pid: str, body: c.ProfileUpdate):
        return await write(request, body, lambda: change_profile(request, body, pid))

    @app.delete(API + "/custom-agents/{pid}", response_model=c.Success[c.Deleted])
    async def delete_profile(request: Request, pid: str, body: c.ExpectedVersion):
        return await write(request, body, lambda: change_profile(request, body, pid, True))

    @app.get(API + "/settings", response_model=c.Success[c.Settings])
    async def settings(request: Request):
        return ok(request, app.state.service.repo.settings(request.state.owner))

    @app.put(API + "/settings", response_model=c.Success[c.Settings])
    async def update_settings(request: Request, body: c.SettingsUpdate):
        service, _ = services(request)

        def operation():
            current = service.repo.settings(request.state.owner)
            require(
                current.version == body.expected_version,
                "CONTROL_CONFLICT",
                "Settings version is stale",
                reason=f"Latest version={current.version}",
            )
            values = c.Settings(version=current.version + 1, **body.settings.model_dump())
            stored = copy.deepcopy(service.repo.meta["settings"])
            stored[request.state.owner] = values.model_dump()
            return Transaction(values, metadata={"settings": stored})

        return await write(request, body, operation)

    @app.get(API + "/usage", response_model=c.Success[c.Usage])
    async def usage(request: Request, simulation_id: str | None = None):
        return ok(request, app.state.service.usage(request.state.owner, simulation_id))

    @app.get(API + "/templates", response_model=c.Success[c.Templates])
    async def templates(request: Request):
        return ok(
            request,
            c.Templates(
                items=[
                    c.Template(
                        id="template_flood_v1",
                        title="Flood response",
                        description="A 30-citizen flood experiment",
                        config=c.ConfigRequest(
                            name="Flood experiment",
                            seed=42,
                            population=min(30, runtime.max_agents),
                            scenario_description="A flood in the southwest for 12 ticks",
                        ).normalized(),
                    ),
                    c.Template(
                        id="template_community_v1",
                        title="Community day",
                        description="Observe ordinary social and work behavior",
                        config=c.ConfigRequest(
                            name="Community day", seed=7, population=min(30, runtime.max_agents)
                        ).normalized(),
                    ),
                    *[
                        c.Template(
                            id=f"template_{kind}_v1",
                            title=title,
                            description=description,
                            config=c.ConfigRequest(
                                name=title,
                                seed=seed,
                                mode=mode,
                                population=min(30, runtime.max_agents),
                                scenario_description=prompt,
                            ).normalized(),
                        )
                        for kind, title, description, seed, mode, prompt in [
                            (
                                "shortage",
                                "Supply shortage",
                                "Observe resource conservation and cooperation",
                                17,
                                "crisis_lab",
                                "A supply shortage for 12 ticks",
                            ),
                            (
                                "misinformation",
                                "Unverified warning",
                                "Observe local communication and uncertain beliefs",
                                23,
                                "behavior_lab",
                                "An unverified warning spreads for 12 ticks",
                            ),
                            (
                                "festival",
                                "Neighborhood festival",
                                "Observe community activity and measured social effects",
                                31,
                                "sandbox",
                                "A neighborhood festival for 12 ticks",
                            ),
                            (
                                "policy",
                                "Policy experiment",
                                "Compare an evacuation and ration policy with a branch",
                                43,
                                "policy_lab",
                                "An evacuation order policy for 12 ticks",
                            ),
                        ]
                    ],
                ]
            ),
        )

    @app.get(API + "/simulations/{sid}/export", response_model=c.Success[c.Export])
    async def export(
        request: Request,
        sid: str,
        format: Literal["json", "csv"] = "json",
        through_revision: Annotated[int | None, Query(ge=0)] = None,
    ):
        service, _ = services(request)
        state = resolved(request, sid, through_revision)
        if format == "csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(
                [
                    "simulation_id",
                    "tick",
                    "revision",
                    "happiness",
                    "safety",
                    "trust",
                    "resources",
                    "stress",
                    "cooperation_count",
                    "conflict_count",
                    "resources_consumed",
                    "evacuated_count",
                    "exposed_count",
                ]
            )
            for point in state.metric_points:
                writer.writerow(
                    [
                        sid,
                        point.tick,
                        point.revision,
                        *point.values.model_dump().values(),
                        point.cooperation_count,
                        point.conflict_count,
                        point.resources_consumed,
                        point.evacuated_count,
                        point.exposed_count,
                    ]
                )
            return Response(
                output.getvalue(),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="metrics.csv"'},
            )
        frames = []
        for rev in range(state.simulation.revision + 1):
            historical = service.owned(request.state.owner, sid, rev)
            if historical.simulation.initialization.stage == "ready":
                frames.append(frame(historical))
        return ok(
            request,
            c.Export(
                simulation=state.simulation,
                frames=frames,
                agents=[agent_detail(state, aid, all_records=True) for aid in state.citizens],
                events=[event_report(state, runtime) for runtime in state.events.values()],
                decisions=state.decisions,
                dialogue=state.dialogue,
                metrics=state.metric_points,
            ),
        )

    @app.post(API + "/simulations/{sid}/narration", response_model=c.Success[c.NarrationResult])
    async def narration(request: Request, sid: str, body: c.NarrationRequest):
        return await narrate(request, sid, body)

    @app.websocket(API + "/simulations/{sid}/stream")
    async def stream(websocket: WebSocket, sid: str):
        service = websocket.app.state.service
        try:
            owner, _ = websocket.app.state.security.identity(websocket)
            service.owned(owner, sid)
        except DomainError:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            payload = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            c.Hello.model_validate(payload)
        except (TimeoutError, ValidationError, ValueError, WebSocketDisconnect):
            await websocket.close(code=1008)
            return

        async def receiver():
            while True:
                c.Ping.model_validate(await websocket.receive_json())
                websocket.app.state.security.authorize_stream(websocket, owner)

        async def authorization():
            # Also revoke idle streams and cancel an in-flight, backpressured send.
            while True:
                websocket.app.state.security.authorize_stream(websocket, owner)
                await asyncio.sleep(0.1)

        async def sender():
            revision = -1
            ready_sent = False
            last_send = 0
            loop = asyncio.get_running_loop()
            while True:
                websocket.app.state.security.authorize_stream(websocket, owner)
                state = service.owned(owner, sid)
                message = None
                if service.repo.degraded:
                    message = dict(
                        type="error",
                        data=dict(
                            code="PERSISTENCE_UNAVAILABLE",
                            message="Persistence is degraded; mutations halted",
                            retryable=True,
                            details=[],
                        ),
                    )
                elif state.simulation.revision != revision:
                    if state.simulation.initialization.stage != "ready":
                        message = dict(type="initialization", data=state.simulation.model_dump())
                    else:
                        message = dict(
                            type="frame" if ready_sent else "snapshot", data=frame(state).model_dump()
                        )
                        ready_sent = True
                    revision = state.simulation.revision
                elif loop.time() - last_send >= 15:
                    message = dict(
                        type="heartbeat", data=dict(revision=revision, status=state.simulation.status)
                    )
                if message:
                    value = dict(schema_version="1.0.0", simulation_id=sid, sent_at=now(), **message)
                    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
                    websocket.app.state.security.authorize_stream(websocket, owner)
                    await asyncio.wait_for(websocket.send_text(encoded), timeout=2)
                    service.stats["socket_bytes"] += len(encoded.encode())
                    last_send = loop.time()
                    if message["type"] == "error":
                        return
                await asyncio.sleep(0.1)

        tasks = [
            asyncio.create_task(receiver()),
            asyncio.create_task(sender()),
            asyncio.create_task(authorization()),
        ]
        close_code = 1000
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except DomainError:
            close_code = 1008
        except (
            TimeoutError,
            WebSocketDisconnect,
            ValidationError,
            ValueError,
            asyncio.CancelledError,
        ):
            pass
        finally:
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await websocket.close(code=close_code)
                except (RuntimeError, WebSocketDisconnect):
                    pass

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method not in {"post", "put", "delete", "patch"}:
                    continue
                headers = operation.setdefault("parameters", [])
                headers.append(
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                        "description": "Same UUID as body request_id when present. Durable request deduplication.",
                    }
                )
                if path != API + "/session" or method != "post":
                    headers.append(
                        {
                            "name": "X-CSRF-Token",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Get from GET /api/v1/session after authentication.",
                        }
                    )
                headers.append(
                    {
                        "name": "Origin",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": "Must be allowed; required for unsafe requests in session mode.",
                    }
                )
        schema["info"]["description"] = (
            "Contract 1.0.0. Private single-owner demo. Local mode permits loopback only; session mode uses the server-set agentcity_session HttpOnly Secure SameSite=Lax cookie. All writes require Idempotency-Key and CSRF (except login). Full-frame WebSocket protocol is in contracts/v1/stream.schema.json."
        )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi
    from app.integrations.api import integration_app

    integrations = integration_app(lambda: app.state.service, app.exception_handlers)
    app.state.integrations = integrations
    app.mount(API + "/integrations", integrations)
    install_snowflake(app, snowflake_config)
    install_narration(app, narration_config, narration_transport)
    if runtime.frontend_dist:
        from app.infrastructure.frontend import mount_frontend

        mount_frontend(app, runtime.frontend_dist)
    return app


app = create_app()
