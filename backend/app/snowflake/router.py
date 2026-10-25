import asyncio
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.requests import Request as StarletteRequest

from app.infrastructure.errors import DomainError, require
from app.snowflake.comparison import accept_selection, build, canonical, digest, facts, prompt, stage
from app.snowflake.config import SnowflakeConfig
from app.snowflake.dto import ComparisonRequest, ComparisonResponse, Failure
from app.snowflake.ledger import Ledger
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable


class ComparisonService:
    def __init__(self, parent, config, transport=None):
        self.parent, self.config = parent, config
        self.transport = transport
        self.ledger = None
        self.gate = asyncio.Lock()
        self.inflight = set()

    def start(self):
        if self.ledger is None:
            # Runs after the parent lifespan initializes its data directory.
            self.ledger = Ledger(self.parent.state.service.config.data_dir / "snowflake-receipts.sqlite3")
            self.transport = self.transport or SnowflakeTransport(self.config)

    async def close(self):
        if self.inflight:
            await asyncio.gather(*self.inflight, return_exceptions=True)
        if self.transport:
            await self.transport.close()
        if self.ledger:
            self.ledger.close()

    async def exports(self, request, body):
        service = self.parent.state.service
        owner = request.state.owner
        # Verify BOTH ownership and explicit revisions before export construction or any vendor I/O.
        for item in (body.a, body.b):
            service.owned(owner, item.simulation_id, item.revision)
            require(item.revision <= 2000, "INVALID_REQUEST", "Comparison revision limit is 2000", 400)
        endpoint = next(
            r.endpoint
            for r in self.parent.routes
            if getattr(r, "path", "") == "/api/v1/simulations/{sid}/export"
        )
        scope = dict(request.scope, app=self.parent)
        local_request = StarletteRequest(scope)
        results = []
        for item in (body.a, body.b):
            exported = await endpoint(
                local_request, item.simulation_id, format="json", through_revision=item.revision
            )
            value = exported["data"].model_dump(mode="json")
            pinned = service.owned(owner, item.simulation_id, item.revision)
            if pinned.conditions:
                from app.disasters.physics import view

                value["disaster_projection"] = view(pinned)
                value["disaster_projection"]["totals"] = dict(
                    damaged_buildings=sum(c.integrity < 100 for c in pinned.conditions.values()),
                    structural_transitions=sum(d.units == "integrity" for d in pinned.damage_records),
                    stock_units_lost=sum(
                        d.before - d.after for d in pinned.damage_records if d.units == "stock"
                    ),
                )
            results.append(stage(value))
        return results

    async def compare(self, request, body):
        require(self.config.enabled, "FEATURE_UNAVAILABLE", "Snowflake comparison is disabled", 501)
        self.start()
        owner, key = request.state.owner, request.state.request_id
        fingerprint = digest(body.model_dump(mode="json"))
        # Even cached results require current authorization to both histories.
        for item in (body.a, body.b):
            self.parent.state.service.owned(owner, item.simulation_id, item.revision)
        cached = self.ledger.lookup(owner, key, fingerprint)
        if cached:
            return cached
        require(not self.gate.locked(), "RATE_LIMITED", "Another comparison is running; retry later", 429)
        await self.gate.acquire()
        try:
            exports = await self.exports(request, body)
            self.ledger.begin(owner, key, fingerprint)
        except BaseException:
            self.gate.release()
            raise

        async def run():
            try:
                return await self.complete(owner, key, body, exports)
            finally:
                self.gate.release()

        task = asyncio.create_task(run())
        self.inflight.add(task)
        task.add_done_callback(self.inflight.discard)
        # Continue through a disconnected caller and persist its exact receipt.
        return await asyncio.shield(task)

    async def complete(self, owner, key, body, exports):
        fingerprints = [digest(p) for p in exports]
        comparison = build(*exports, fingerprints, [None, None], "local_export")
        reason = "Snowflake unavailable; values are deterministic calculations from pinned local exports"
        try:
            async with asyncio.timeout(self.config.deadline):
                stamps = []
                queried = []
                for payload, fingerprint in zip(exports, fingerprints, strict=True):
                    sim = payload["simulation"]
                    values = (owner, sim["id"], sim["revision"])
                    await self.transport.execute("ingest", (*values, fingerprint, canonical(payload)))
                    rows = await self.transport.execute("query", values)
                    if len(rows) != 1 or rows[0][1] != fingerprint:
                        raise VendorUnavailable()
                    retrieved = json.loads(rows[0][0])
                    # Read-back integrity also prevents stale/wrong-branch/corrupt evidence.
                    if digest(retrieved) != fingerprint:
                        raise VendorUnavailable()
                    queried.append(retrieved)
                    stamps.append(rows[0][2])
                comparison = build(*queried, fingerprints, stamps, "snowflake")
                context = prompt(comparison, body.question)
                reason = "Cortex daily call budget exhausted"
                if self.ledger.reserve_model(self.config.daily_model_calls):
                    reason = "Cortex unavailable or output rejected; deterministic values remain available"
                    rows = await self.transport.execute("explain", (self.config.model, context))
                    if len(rows) != 1 or len(rows[0]) != 1:
                        raise VendorUnavailable()
                    accept_selection(comparison, rows[0][0])
        except (VendorUnavailable, TimeoutError, ValueError, TypeError, KeyError, IndexError):
            pass
        if comparison.explanation.status != "available":
            comparison.explanation.reason = reason
            comparison.explanation.observations = list(facts(comparison).values())[:5]
        response = ComparisonResponse(request_id=key, data=comparison).model_dump(mode="json")
        self.ledger.finish(owner, key, response)
        return response


def create_snowflake_app(parent, config=None, transport=None):
    config = config or SnowflakeConfig.from_env()
    config.validate()
    service = ComparisonService(parent, config, transport)
    child = FastAPI(title="AgentCity Snowflake extension", version="1.0.0")
    child.state.comparison = service

    def failure(request, code, message, status, details=None):
        body = dict(
            schema_version="1.0.0",
            request_id=getattr(request.state, "request_id", str(uuid4())),
            error=dict(code=code, message=message, retryable=status in {429, 503}, details=details or []),
        )
        return JSONResponse(body, status_code=status, headers={"Retry-After": "2"} if status == 429 else None)

    @child.exception_handler(DomainError)
    async def domain_error(request, error):
        return failure(request, error.code, error.message, error.status, error.details)

    @child.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return failure(
            request,
            "VALIDATION_ERROR",
            "Request validation failed",
            422,
            [{"field": ".".join(map(str, item["loc"])), "reason": item["msg"]} for item in error.errors()],
        )

    @child.exception_handler(HTTPException)
    async def http_error(request, error):
        return failure(
            request,
            "NOT_FOUND" if error.status_code == 404 else "INVALID_REQUEST",
            "Extension route unavailable",
            error.status_code,
        )

    @child.exception_handler(Exception)
    async def unexpected(request, error):
        return failure(request, "SERVICE_UNAVAILABLE", "Comparison could not be completed", 503)

    @child.middleware("http")
    async def security(request, call_next):
        try:
            unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
            owner, _ = parent.state.security.identity(request, unsafe=unsafe)
            request.state.owner = owner
            if unsafe:
                key = request.headers.get("idempotency-key", "")
                try:
                    require(
                        str(UUID(key)) == key.lower(), "INVALID_REQUEST", "Canonical UUID key required", 400
                    )
                except ValueError:
                    raise DomainError("INVALID_REQUEST", "Canonical UUID Idempotency-Key required", 400)
                request.state.request_id = key
            return await call_next(request)
        except DomainError as error:
            return failure(request, error.code, error.message, error.status, error.details)

    @child.post(
        "/snowflake/comparisons",
        response_model=ComparisonResponse,
        description=(
            "Two explicit owned history revisions. No caller SQL. The parent session cookie, "
            "allowed Origin, CSRF token, and canonical UUID idempotency key are required for writes. "
            "Exact successful retries return the durable receipt; changed bodies conflict."
        ),
        openapi_extra={
            "parameters": [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                },
                {"name": "X-CSRF-Token", "in": "header", "required": True, "schema": {"type": "string"}},
                {
                    "name": "Origin",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Required in session mode; must be allowed.",
                },
            ]
        },
        responses={s: {"model": Failure} for s in (400, 401, 403, 404, 409, 422, 429, 501, 503)},
    )
    async def compare(request: Request, body: ComparisonRequest):
        return await service.compare(request, body)

    return child


def install_snowflake(parent, config=None, transport=None):
    """Compose with the coordinator's shared child, preserving one prefix mount."""
    extension = create_snowflake_app(parent, config, transport)
    child = getattr(parent.state, "integrations", None)
    if child is not None:
        previous = getattr(child.state, "comparison", None)
        if previous is not None and previous.ledger is not None:
            raise RuntimeError("Cannot replace an active Snowflake integration")
        path = "/snowflake/comparisons"
        child.router.routes[:] = [route for route in child.routes if getattr(route, "path", "") != path]
        child.router.routes.extend(route for route in extension.routes if getattr(route, "path", "") == path)
        child.state.comparison = extension.state.comparison
        child.openapi_schema = None
    else:
        child = extension
        parent.state.integrations = child
        parent.mount("/api/v1/integrations", child)
        mount = parent.router.routes.pop()
        parent.router.routes.insert(0, mount)
    if getattr(parent.state, "snowflake_lifespan_installed", False):
        return parent
    parent.state.snowflake_lifespan_installed = True
    original = parent.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            try:
                yield
            finally:
                await child.state.comparison.close()

    parent.router.lifespan_context = lifespan
    return parent
