"""Narration orchestration. Never takes the simulation writer or per-simulation locks.

Deduplication layers:
- an exact retry of a completed idempotency key replays its stored response;
- an identical key still in flight joins the same task;
- different keys for the same simulation/text/voice/model/format share one
  synthesis in flight and then the cached audio, issuing a fresh URL.
Provider failures are not recorded, so a retry with the same key tries again.
"""

import asyncio
import hashlib
import hmac
import re
import time
from datetime import UTC, datetime

from app import contracts as c
from app.data.repository import encode
from app.infrastructure.errors import DomainError, require
from app.narration.speech import recorded_text
from app.narration.store import AUDIO_ID, Store
from app.narration.transport import ElevenLabsTransport, ProviderFailure
from app.narration.voices import VoiceAssignments

MEDIA_PATH = "/api/v1/integrations/narration/audio"
SIGNATURE = re.compile(r"[0-9a-f]{64}")
UNAVAILABLE = "Narration integration is unavailable"
MEDIA_MISSING = "Narration audio not found or expired"


def iso(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


class NarrationService:
    def __init__(self, parent, config, transport=None, clock=time.time):
        config.validate()
        self.parent, self.config, self.transport, self.clock = parent, config, transport, clock
        self.store = None
        self.voices = None
        self.pending = {}
        self.flights = {}
        self.tasks = set()
        self.reserved_bytes = 0
        self.reserved_entries = 0

    @property
    def enabled(self):
        return self.config.enabled

    @property
    def core(self):
        return self.parent.state.service

    def start(self):
        if self.enabled and self.store is None:
            self.store = Store(self.core.repo.directory / "narration", self.config)
            self.store.sweep(self.clock())
            self.voices = VoiceAssignments(self.store)
            self.transport = self.transport or ElevenLabsTransport(self.config)

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.transport:
            await self.transport.close()
        if self.store:
            self.store.close()

    def _track(self, task, registry, key):
        registry[key] = task
        self.tasks.add(task)

        def done(finished):
            if registry.get(key) is finished:
                registry.pop(key, None)
            self.tasks.discard(finished)

        task.add_done_callback(done)
        return task

    def sign(self, owner, audio_id, expires):
        message = f"v1\n{owner}\n{audio_id}\n{expires}".encode()
        return hmac.new(self.store.secret, message, hashlib.sha256).hexdigest()

    def _accessible(self, owner, entry):
        head = self.core.heads.get(entry.simulation_id)
        return entry.owner == owner and head is not None and head.owner_id == owner

    async def narrate(self, request, sid, body):
        owner, key = request.state.owner, request.state.request_id
        state = self.core.owned(owner, sid)
        require(self.enabled, "FEATURE_UNAVAILABLE", UNAVAILABLE, 501)
        fingerprint = hashlib.sha256(
            encode({"route": f"POST {request.url.path}", "body": body.model_dump(mode="json")})
        ).hexdigest()
        previous = self.store.operation(owner, key)
        if previous:
            recorded, audio_id, response, _ = previous
            require(
                recorded == fingerprint,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key was used for a different request",
            )
            now = self.clock()
            entry = self.store.get(audio_id, now)
            expires = datetime.fromisoformat(response["data"]["expires_at"].replace("Z", "+00:00"))
            require(
                entry is not None and expires.timestamp() > now and self._accessible(owner, entry),
                "INVALID_STATE",
                "This narration result has expired; request narration again",
            )
            return response
        identity = (owner, key)
        if identity in self.pending:
            recorded, task = self.pending[identity]
            require(
                recorded == fingerprint,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key was used for a different request",
            )
            return await asyncio.shield(task)
        # Resolve and reject before any capacity reservation or vendor request.
        text = recorded_text(state, body.source_type, body.source_id, self.config.max_characters)
        voice_id = self.voices.resolve(state, body.source_type, body.source_id, self.config)
        origin = self.config.public_origin or str(request.base_url).rstrip("/")
        task = asyncio.create_task(self._produce(owner, key, fingerprint, sid, text, origin, voice_id))
        self.tasks.add(task)
        self.pending[identity] = (fingerprint, task)

        def done(finished):
            if self.pending.get(identity, (None, None))[1] is finished:
                self.pending.pop(identity, None)
            self.tasks.discard(finished)

        task.add_done_callback(done)
        # A disconnected caller does not cancel work whose receipt a retry can replay.
        return await asyncio.shield(task)

    async def _produce(self, owner, key, fingerprint, sid, text, origin, voice_id):
        entry = await self._audio(owner, sid, text, voice_id)
        now = self.clock()
        expires = int(now + self.config.url_ttl)
        self.store.issue(entry, expires)
        query = f"expires={expires}&signature={self.sign(owner, entry.audio_id, expires)}"
        result = c.NarrationResult(
            audio_url=f"{origin}{MEDIA_PATH}/{entry.audio_id}?{query}", expires_at=iso(expires)
        )
        response = {"schema_version": "1.0.0", "request_id": key, "data": result.model_dump(mode="json")}
        self.store.record(owner, key, fingerprint, entry.audio_id, response, now + self.config.cache_ttl)
        return response

    def content_key(self, sid, text, voice_id):
        config = self.config
        return hashlib.sha256(
            encode([sid, voice_id, config.model_id, config.output_format, text])
        ).hexdigest()

    async def _audio(self, owner, sid, text, voice_id):
        content_key = self.content_key(sid, text, voice_id)
        entry = self.store.find(owner, content_key, self.clock())
        if entry:
            self.store.count("cache_hits")
            return entry
        flight = (owner, content_key)
        task = self.flights.get(flight)
        if task is None:
            task = self._track(
                asyncio.create_task(self._synthesize(owner, sid, content_key, text, voice_id)),
                self.flights,
                flight,
            )
        else:
            self.store.count("joined_in_flight")
        return await asyncio.shield(task)

    async def _synthesize(self, owner, sid, content_key, text, voice_id):
        size = self.config.max_audio_bytes
        room = await asyncio.to_thread(
            self.store.make_room, self.clock(), size, self.reserved_bytes, self.reserved_entries
        )
        require(
            room,
            "RATE_LIMITED",
            "The narration cache is full of unexpired audio; retry later",
            429,
        )
        self.reserved_bytes += size
        self.reserved_entries += 1
        try:
            self.store.count("syntheses_started")
            try:
                audio = await self.transport.synthesize(text, voice_id=voice_id)
            except ProviderFailure as failure:
                self.store.count("provider_failures")
                local = failure.reason in {"busy", "rate_limited"}
                raise DomainError(
                    "RATE_LIMITED" if local else "SERVICE_UNAVAILABLE", str(failure), 429 if local else 503
                ) from None
            entry = await asyncio.to_thread(self.store.insert, owner, content_key, sid, audio, self.clock())
            self.store.count("syntheses_cached")
            return entry
        finally:
            self.reserved_bytes -= size
            self.reserved_entries -= 1

    async def media(self, owner, audio_id, expires, signature):
        require(self.enabled, "FEATURE_UNAVAILABLE", UNAVAILABLE, 501)
        now = self.clock()
        authentic = (
            AUDIO_ID.fullmatch(audio_id) is not None
            and SIGNATURE.fullmatch(signature) is not None
            and expires > now
            and hmac.compare_digest(self.sign(owner, audio_id, expires), signature)
        )
        require(authentic, "NOT_FOUND", MEDIA_MISSING, 404)
        entry = self.store.get(audio_id, now)
        require(
            entry is not None and expires <= entry.tokens_until and self._accessible(owner, entry),
            "NOT_FOUND",
            MEDIA_MISSING,
            404,
        )
        try:
            data = await asyncio.to_thread(self.store.read, entry, now)
        except OSError:
            raise DomainError("NOT_FOUND", MEDIA_MISSING, 404) from None
        return data, expires - now
