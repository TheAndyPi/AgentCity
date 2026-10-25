"""Narration media extension at /api/v1/integrations/narration and core POST wiring."""

from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException
from starlette.routing import Mount

from app import contracts as c
from app.infrastructure.errors import DomainError
from app.narration.config import NarrationConfig
from app.narration.service import MEDIA_PATH, NarrationService

MOUNT_PATH = MEDIA_PATH.removesuffix("/audio")


class LiveDialogueRequest(BaseModel):
    """Versioned extension; frozen core NarrationRequest remains unchanged."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)

    @property
    def source_type(self):
        return "dialogue"


def _failure(request, code, message, status, details=None):
    body = dict(
        schema_version="1.0.0",
        request_id=getattr(request.state, "request_id", None) or str(uuid4()),
        error=dict(code=code, message=message, retryable=status in {429, 503}, details=details or []),
    )
    return JSONResponse(body, status_code=status, headers={"Retry-After": "60"} if status == 429 else None)


def _byte_range(header, size):
    """One satisfiable `bytes=a-b` range, None for a full response, or False if unsatisfiable."""
    if not header:
        return None
    unit, _, spec = header.partition("=")
    if unit.strip() != "bytes" or "," in spec:
        return None
    start, _, end = spec.strip().partition("-")
    try:
        if start:
            first = int(start)
            last = min(int(end), size - 1) if end else size - 1
        else:
            first, last = max(0, size - int(end)), size - 1
    except ValueError:
        return None
    return (first, last) if 0 <= first <= last < size else False


def create_narration_app(narration: NarrationService):
    child = FastAPI(title="AgentCity narration extension", version="1.0.0")
    child.state.narration = narration

    @child.post(
        "/v1/simulations/{sid}/dialogue",
        response_model=c.Success[c.NarrationResult],
        description="Speak only the committed dialogue source at an owned pinned revision. "
        "Requires the parent session, CSRF token and UUID Idempotency-Key. No client text is accepted.",
        responses={status: {"model": c.Failure} for status in (400, 401, 403, 404, 409, 429, 501, 503)},
    )
    async def live_dialogue(request: Request, sid: str, body: LiveDialogueRequest):
        return await narration.narrate(request, sid, body, live=True)

    @child.exception_handler(DomainError)
    async def domain_error(request, error):
        return _failure(request, error.code, error.message, error.status, error.details)

    @child.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.method == "POST":
            return _failure(request, "INVALID_REQUEST", "Invalid live dialogue request", 400)
        return _failure(request, "NOT_FOUND", "Narration audio not found or expired", 404)

    @child.exception_handler(HTTPException)
    async def http_error(request, error):
        return _failure(
            request,
            "NOT_FOUND" if error.status_code == 404 else "INVALID_REQUEST",
            "Narration route unavailable",
            error.status_code if error.status_code in {404, 405} else 400,
        )

    @child.exception_handler(Exception)
    async def unexpected(request, error):
        return _failure(request, "SERVICE_UNAVAILABLE", "Narration audio could not be delivered", 503)

    @child.middleware("http")
    async def security(request, call_next):
        try:
            # The parent guard already authenticated /api/v1; re-check so this child
            # never serves media if it is composed under a different parent prefix.
            unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
            owner, _ = narration.parent.state.security.identity(request, unsafe=unsafe)
            request.state.owner = owner
            return await call_next(request)
        except DomainError as error:
            return _failure(request, error.code, error.message, error.status, error.details)

    media = dict(
        response_class=Response,
        description=(
            "Owner-only narration audio. Requires the parent session (or loopback local mode) "
            "and the unexpired signature issued by POST /api/v1/simulations/{sid}/narration. "
            "Supports a single byte range for browser media playback."
        ),
        responses={
            200: {"content": {"audio/mpeg": {}}, "description": "Complete MP3 audio"},
            206: {"content": {"audio/mpeg": {}}, "description": "Requested byte range"},
            **{s: {"model": c.Failure} for s in (401, 403, 404, 416, 501, 503)},
        },
    )

    @child.get("/audio/{audio_id}", operation_id="get_narration_audio", **media)
    @child.head("/audio/{audio_id}", operation_id="head_narration_audio", **media)
    async def audio(
        request: Request,
        audio_id: str,
        expires: Annotated[int, Query(ge=0, le=9007199254740991)],
        signature: Annotated[str, Query(max_length=64)],
    ):
        data, remaining = await narration.media(request.state.owner, audio_id, expires, signature)
        size = len(data)
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": f"private, max-age={max(0, int(remaining))}",
            "Content-Disposition": "inline",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        }
        selected = _byte_range(request.headers.get("range"), size)
        if selected is False:
            headers["Content-Range"] = f"bytes */{size}"
            return Response(status_code=416, headers=headers)
        status, body = 200, data
        if selected:
            first, last = selected
            status, body = 206, data[first : last + 1]
            headers["Content-Range"] = f"bytes {first}-{last}/{size}"
        headers["Content-Length"] = str(len(body))
        if request.method == "HEAD":
            body = b""
        return Response(body, status_code=status, media_type="audio/mpeg", headers=headers)

    return child


def _precede_enclosing_mounts(parent, mount):
    routes = parent.router.routes
    routes.remove(mount)
    enclosing = next(
        (
            index
            for index, route in enumerate(routes)
            if isinstance(route, Mount) and MOUNT_PATH.startswith(route.path + "/")
        ),
        0,
    )
    routes.insert(enclosing, mount)


def install_narration(parent, config=None, transport=None):
    """Mount media delivery before the SPA catch-all and any generic integrations mount."""
    config = config or NarrationConfig.from_env()
    narration = NarrationService(parent, config, transport)
    parent.state.narration = narration
    parent.mount(MOUNT_PATH, create_narration_app(narration))
    mount = parent.router.routes[-1]
    _precede_enclosing_mounts(parent, mount)
    original = parent.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        # Mounts installed after this one (for example a generic integrations child)
        # must not shadow the more specific media path.
        _precede_enclosing_mounts(parent, mount)
        async with original(app) as state:
            narration.start()
            try:
                yield state
            finally:
                await narration.close()

    parent.router.lifespan_context = lifespan
    return narration


async def narrate(request, sid, body):
    """Implementation of the frozen core POST /api/v1/simulations/{sid}/narration."""
    return JSONResponse(await request.app.state.narration.narrate(request, sid, body))
