"""Composition seam for independently documented integration routes."""

from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from app import contracts as c
from app.infrastructure.errors import DomainError


class Progress(BaseModel):
    simulation_id: str
    published_revision: int
    ingested_revision: int
    lag_revisions: int


class TigerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    state: Literal["disabled", "healthy", "catching_up", "unavailable"]
    error_code: Literal["PROGRESS_INVALID", "PROJECTION_LIMIT", "INGESTION_UNAVAILABLE"] | None
    retry_in_seconds: float
    simulations: list[Progress]
    next_after: str | None


class StatusResponse(BaseModel):
    schema_version: str
    request_id: str
    data: TigerStatus


def integration_app(service, failure):
    child = FastAPI(
        title="AgentCity integrations",
        version="1.0.0",
        servers=[{"url": "/api/v1/integrations"}],
        responses={
            status: {"model": c.Failure} for status in [400, 401, 403, 404, 409, 410, 422, 429, 501, 503]
        },
    )
    # Parent handlers do not apply to a mounted FastAPI application.
    child.add_exception_handler(DomainError, failure[DomainError])
    child.add_exception_handler(RequestValidationError, failure[RequestValidationError])
    child.add_exception_handler(HTTPException, failure[HTTPException])
    child.add_exception_handler(Exception, failure[Exception])

    @child.get("/tiger/status", response_model=StatusResponse)
    async def status(
        request: Request,
        simulation_id: str | None = None,
        after: str | None = Query(default=None, max_length=128),
        limit: int = Query(default=25, ge=1, le=100),
    ):
        current = service()
        if simulation_id is not None:
            current.owned(request.state.owner, simulation_id)
        data = current.tiger.status(request.state.owner, simulation_id, after, limit)
        return dict(schema_version="1.0.0", request_id=request.state.request_id, data=data)

    from app.scenario_engine.api import register
    from app.behavior.api import install

    register(child, service)
    install(child, service)
    return child
