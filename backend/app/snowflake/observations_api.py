"""Read-only v1 observation extension with session/ownership checks on every request."""

from fastapi import Query, Request

from app.snowflake.observations import ObservationService
from app.snowflake.observations_dto import METRICS, empty_coverage

PREFIX = "/snowflake/observations/v1/simulations/{sid}"


def install_observations(child, parent, config, transport=None, gate=None):
    previous = getattr(child.state, "observations", None)
    if previous is not None and previous.db is not None:
        raise RuntimeError("Cannot replace active observation integration")
    child.router.routes[:] = [r for r in child.routes if not getattr(r, "path", "").startswith(PREFIX)]
    service = ObservationService(parent, config, transport, gate)
    child.state.observations = service
    child.openapi_schema = None

    def response(request, data):
        return dict(schema_version="1.0.0", request_id=request.state.request_id, data=data)

    @child.get(PREFIX + "/status", tags=["Snowflake observations"])
    async def status(request: Request, sid: str, through_revision: int | None = Query(default=None, ge=0)):
        return response(request, service.status(request.state.owner, sid, through_revision))

    @child.get(PREFIX + "/metrics", tags=["Snowflake observations"])
    async def metrics(request: Request, sid: str, through_revision: int | None = Query(default=None, ge=0)):
        head = service.core.owned(request.state.owner, sid, through_revision)
        revision = head.simulation.revision if through_revision is None else through_revision
        return response(
            request,
            {
                "source": "snowflake",
                "simulation_id": sid,
                "requested_revision": revision,
                "effective_revision": None,
                "coverage": empty_coverage(),
                "items": list(METRICS.values()),
            },
        )

    @child.get(PREFIX + "/trends", tags=["Snowflake observations"])
    async def trends(
        request: Request,
        sid: str,
        through_revision: int = Query(ge=0),
        metric: str = Query(default="health", max_length=64),
        start_tick: int = Query(default=0, ge=0),
        end_tick: int = Query(default=9007199254740991, ge=0),
        agent_id: str | None = Query(default=None, max_length=128),
        event_id: str | None = Query(default=None, max_length=128),
    ):
        value = await service.query(
            request.state.owner,
            sid,
            "trends",
            through_revision,
            metric=metric,
            start_tick=start_tick,
            end_tick=end_tick,
            agent_id=agent_id,
            event_id=event_id,
        )
        return response(request, value)

    @child.get(PREFIX + "/events", tags=["Snowflake observations"])
    async def events(
        request: Request,
        sid: str,
        through_revision: int = Query(ge=0),
        start_tick: int = Query(default=0, ge=0),
        end_tick: int = Query(default=9007199254740991, ge=0),
        event_id: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=50, ge=1, le=100),
        after: str | None = Query(default=None, max_length=4096),
    ):
        value = await service.query(
            request.state.owner,
            sid,
            "events",
            through_revision,
            start_tick=start_tick,
            end_tick=end_tick,
            event_id=event_id,
            limit=limit,
            after=after,
        )
        return response(request, value)

    @child.get(PREFIX + "/events/{event_id}", tags=["Snowflake observations"])
    async def event_detail(
        request: Request,
        sid: str,
        event_id: str,
        through_revision: int = Query(ge=0),
    ):
        value = await service.query(
            request.state.owner, sid, "event_detail", through_revision, event_id=event_id
        )
        return response(request, value)

    @child.get(PREFIX + "/changes", tags=["Snowflake observations"])
    async def changes(
        request: Request,
        sid: str,
        through_revision: int = Query(ge=0),
        start_tick: int = Query(default=0, ge=0),
        end_tick: int = Query(default=9007199254740991, ge=0),
        agent_id: str | None = Query(default=None, max_length=128),
        event_id: str | None = Query(default=None, max_length=128),
        entity_kind: str | None = Query(default=None, pattern="^(agent|relationship|opinion|event)$"),
        limit: int = Query(default=50, ge=1, le=100),
        after: str | None = Query(default=None, max_length=4096),
    ):
        value = await service.query(
            request.state.owner,
            sid,
            "changes",
            through_revision,
            start_tick=start_tick,
            end_tick=end_tick,
            agent_id=agent_id,
            event_id=event_id,
            entity_kind=entity_kind,
            limit=limit,
            after=after,
        )
        return response(request, value)

    return service
