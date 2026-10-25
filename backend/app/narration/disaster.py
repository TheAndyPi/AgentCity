"""Server-owned sound prompts, persistent at-most-once jobs and media manifests."""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass

from pydantic import Field

from app.contracts import Model
from app.infrastructure.errors import DomainError, require
from app.narration.service import MEDIA_PATH, iso
from app.narration.transport import MPEG_RATES, ProviderFailure, _frame_length

DIRECTIONS = {
    "earthquake": (
        "Low ground rumble, building vibration and intermittent cracking",
        "Dark low drones, tense pulses and restrained percussion",
    ),
    "tornado": (
        "Swirling wind roar and intermittent debris impacts",
        "Fast anxious pulse and rising tension",
    ),
    "flood": ("Rushing surging water and distant water impacts", "Slow tense swells with uncertainty"),
    "fire": ("Fire crackle and occasional structural creak", "Uneasy rhythmic tension"),
    "storm": ("Wind, rain and restrained distant thunder", "Brooding atmospheric suspense"),
}


class AssetRequest(Model):
    source_id: str = Field(min_length=1, max_length=200)
    category: str = Field(pattern="^(effects|music|reactions)$")
    revision: int = Field(ge=0)


def payload_for(config, kind, band, category, reaction=None):
    if category == "effects":
        return dict(
            text=f"{DIRECTIONS[kind][0]}. {band} intensity. Seamless ambient bed; no speech, music, explosions or human screams.",
            duration_seconds=8.0,
            loop=True,
            model_id=config.effects_model,
        )
    if category == "music":
        return dict(
            prompt=f"Original scary instrumental suspense score. {DIRECTIONS[kind][1]}. {band} tension. No vocals. Smooth restrained loop ending.",
            music_length_ms=30000,
            force_instrumental=True,
            model_id=config.music_model,
        )
    return dict(
        text=("[screaming] " if reaction.kind == "scream" else "[shouting] ") + reaction.text,
        model_id=config.reactions_model,
    )


def mp3_seconds(data):
    offset = 0
    if data[:3] == b"ID3":
        size = 0
        for b in data[6:10]:
            size = size * 128 + b
        offset = 10 + size + (10 if data[5] & 16 else 0)
    seconds = 0
    while offset + 4 <= len(data):
        length = _frame_length(data, offset)
        if not length:
            if len(data) - offset == 128 and data[offset : offset + 3] == b"TAG":
                break
            return 0.0
        if offset + length > len(data):
            return 0.0
        version = (data[offset + 1] >> 3) & 3
        rate = (data[offset + 2] >> 2) & 3
        seconds += (1152 if version == 3 else 576) / MPEG_RATES[version][rate]
        offset += length
    return seconds


@dataclass
class SoundLibrary:
    narration: object

    def __post_init__(self):
        self.status = {category: "unconfigured" for category in ("effects", "music", "reactions")}
        self.pending = {}
        self.job_slot = asyncio.Semaphore(1)
        self.started = False

    def start(self):
        n = self.narration
        if not n.enabled or not n.store or self.started:
            return
        self.started = True
        with n.store.lock:
            n.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS disaster_audio_jobs (
              owner TEXT NOT NULL, content_key TEXT NOT NULL, status TEXT NOT NULL,
              audio_id TEXT, PRIMARY KEY(owner,content_key));
            CREATE TABLE IF NOT EXISTS disaster_audio_manifests (
              owner TEXT NOT NULL, simulation_id TEXT NOT NULL, source_id TEXT NOT NULL,
              category TEXT NOT NULL, manifest TEXT NOT NULL,
              PRIMARY KEY(owner,simulation_id,source_id,category));
            """)
            n.store.db.commit()
        for category in self.status:
            if getattr(n.config, f"disaster_{category}"):
                self.status[category] = "unverified"

    def capabilities(self):
        self.start()
        return dict(schema_version="2.0.0", categories=self.status.copy(), requires_user_gesture=True)

    async def request(self, request, sid, body):
        n = self.narration
        owner, key = request.state.owner, request.state.request_id
        n.core.owned(owner, sid, body.revision)
        require(n.enabled, "FEATURE_UNAVAILABLE", "Disaster audio is unconfigured", 501)
        self.start()
        fingerprint = hashlib.sha256(
            json.dumps([str(request.url.path), body.model_dump()], sort_keys=True).encode()
        ).hexdigest()
        previous = n.store.operation(owner, key)
        if previous:
            recorded, audio_id, response, _ = previous
            require(recorded == fingerprint, "IDEMPOTENCY_CONFLICT", "Key already used with another request")
            require(
                n.store.get(audio_id, n.clock()) is not None,
                "INVALID_STATE",
                "Cached sound expired; request a fresh authorized URL",
            )
            return response
        identity = (owner, key)
        if identity in n.pending:
            recorded, task = n.pending[identity]
            require(recorded == fingerprint, "IDEMPOTENCY_CONFLICT", "Key already used with another request")
            return await asyncio.shield(task)
        require(
            len(n.pending) < n.config.queue_limit + n.config.concurrency,
            "RATE_LIMITED",
            "Sound preparation queue is full",
            429,
        )

        async def run():
            response = await self._request(request, sid, body)
            audio_id = response["data"]["manifest"]["asset_id"]
            n.store.record(owner, key, fingerprint, audio_id, response, n.clock() + n.config.cache_ttl)
            return response

        task = asyncio.create_task(run())
        n.pending[identity] = (fingerprint, task)
        n.tasks.add(task)

        def done(finished):
            n.pending.pop(identity, None)
            n.tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # detached callers must not leak an unhandled failure

        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _request(self, request, sid, body):
        n = self.narration
        state = n.core.owned(request.state.owner, sid, body.revision)
        self.start()
        category = body.category
        require(category in self.status, "INVALID_REQUEST", "Unknown audio category", 400)
        require(
            n.enabled and getattr(n.config, f"disaster_{category}"),
            "FEATURE_UNAVAILABLE",
            f"Disaster {category} audio is unconfigured",
            501,
        )
        head = n.core.owned(request.state.owner, sid)
        require(
            head.simulation.revision >= body.revision and head.simulation.status == "running",
            "INVALID_STATE",
            "Only current running committed sources can request new sound; history is silent",
        )
        require(
            category != "reactions" or n.config.reactions_model in {"eleven_v3", "eleven_v3_conversational"},
            "FEATURE_UNAVAILABLE",
            "Configured expressive reaction model is unsupported",
            501,
        )
        reaction = None
        if category == "reactions":
            reaction = next((r for r in state.reactions if r.id == body.source_id), None)
            require(reaction is not None, "NOT_FOUND", "Recorded reaction not found", 404)
            runtime = state.events.get(reaction.event_id)
            citizen = head.citizens.get(reaction.agent_id)
            require(
                citizen
                and citizen.summary.active
                and citizen.needs.health > 0
                and citizen.needs.fatigue < 100
                and head.simulation.sim_time_seconds - reaction.sim_time_seconds <= 30,
                "INVALID_STATE",
                "Reaction is no longer eligible",
            )
            voice = n.voices.resolve(state, "reaction", reaction.id, n.config)
        else:
            runtime = state.events.get(body.source_id)
            voice = ""
        require(
            runtime and runtime.physical and runtime.summary.status == "active",
            "INVALID_STATE",
            "Sound requires an active committed disaster",
        )
        require(
            head.events.get(runtime.summary.id)
            and head.events[runtime.summary.id].summary.status == "active",
            "INVALID_STATE",
            "Disaster source is no longer active",
        )
        band = (
            "low"
            if runtime.physical.normalized < 0.35
            else "medium"
            if runtime.physical.normalized < 0.7
            else "high"
        )
        payload = payload_for(n.config, runtime.physical.kind, band, category, reaction)
        identity = json.dumps(
            dict(payload=payload, voice=voice, format=n.config.output_format, version="sound-2.0.0"),
            sort_keys=True,
        )
        key = n.content_key(sid, identity, voice, source="disaster-library-v2")

        inherited = None
        parent_id = state.simulation.parent_simulation_id
        if parent_id:
            with n.store.lock:
                parent_row = n.store.db.execute(
                    "SELECT manifest FROM disaster_audio_manifests WHERE owner=? AND simulation_id=? AND source_id=? AND category=?",
                    (state.owner_id, parent_id, body.source_id, category),
                ).fetchone()
            if parent_row:
                candidate = json.loads(parent_row[0])
                if (
                    candidate.get("model") == payload["model_id"]
                    and candidate.get("band") == band
                    and candidate.get("voice_id") == (voice or None)
                ):
                    original = n.store.get(candidate["asset_id"], n.clock())
                    if original and original.owner == state.owner_id:
                        inherited = (candidate, original)

        async def produce():
            if inherited:
                return await asyncio.to_thread(n.store.read, inherited[1], n.clock())
            with n.store.lock:
                row = n.store.db.execute(
                    "SELECT status FROM disaster_audio_jobs WHERE owner=? AND content_key=?",
                    (state.owner_id, key),
                ).fetchone()
                require(
                    not row,
                    "SERVICE_UNAVAILABLE",
                    "This sound generation was already attempted; restore its cached media or prepare a new library version",
                    503,
                )
                n.store.db.execute(
                    "INSERT INTO disaster_audio_jobs VALUES (?,?,'pending',NULL)", (state.owner_id, key)
                )
                n.store.db.commit()
            try:
                async with self.job_slot:
                    if category == "reactions":
                        await n.transport.validate_voice(voice)
                    audio = await n.transport.generate_asset(category, payload, voice)
                duration = mp3_seconds(audio)
                require(
                    (
                        {"effects": 6.0, "music": 25.0, "reactions": 0.1}[category]
                        <= duration
                        <= {"effects": 10.0, "music": 35.0, "reactions": 8.0}[category]
                    ),
                    "SERVICE_UNAVAILABLE",
                    "Provider audio duration is outside bounds",
                    503,
                )
                self.status[category] = "ready"
                return audio
            except (ProviderFailure, DomainError) as failure:
                if not (
                    category == "reactions"
                    and isinstance(failure, ProviderFailure)
                    and failure.reason == "voice_unavailable"
                ):
                    self.status[category] = "unavailable"
                raise

        require(
            len(n.flights) < n.config.queue_limit + n.config.concurrency,
            "RATE_LIMITED",
            "Sound preparation queue is full",
            429,
        )
        try:
            async with asyncio.timeout(n.config.sound_deadline):
                entry = await n._audio(state.owner_id, sid, identity, voice, "disaster-library-v2", produce)
        except (ProviderFailure, TimeoutError):
            self.status[category] = "unavailable"
            raise DomainError(
                "SERVICE_UNAVAILABLE", f"Disaster {category} provider is unavailable", 503
            ) from None
        # Recheck after slow generation; cached bytes may survive, obsolete playback may not.
        latest = n.core.owned(state.owner_id, sid)
        require(
            latest.events.get(runtime.summary.id)
            and latest.events[runtime.summary.id].summary.status == "active"
            and latest.simulation.status == "running",
            "INVALID_STATE",
            "Disaster ended while sound was preparing",
        )
        if reaction:
            citizen = latest.citizens.get(reaction.agent_id)
            require(
                citizen
                and citizen.summary.active
                and citizen.needs.health > 0
                and citizen.needs.fatigue < 100
                and latest.simulation.sim_time_seconds - reaction.sim_time_seconds <= 30,
                "INVALID_STATE",
                "Reaction expired while preparing",
            )
        expires = int(n.clock() + n.config.url_ttl)
        n.store.issue(entry, expires)
        origin = n.config.public_origin or str(request.base_url).rstrip("/")
        manifest = dict(
            schema_version="2.0.0",
            source_id=body.source_id,
            event_id=runtime.summary.id,
            category=category,
            phase="active",
            tick=state.simulation.tick,
            revision=state.simulation.revision,
            sim_time_seconds=state.simulation.sim_time_seconds,
            asset_id=entry.audio_id,
            content_hash=hashlib.sha256(n.store.read(entry, n.clock())).hexdigest(),
            voice_id=voice or None,
            model=payload["model_id"],
            prompt_version="sound-2.0.0",
            band=band,
            provider="elevenlabs",
            recorded_at=iso(time.time()),
            inherited_from=dict(simulation_id=parent_id, asset_id=inherited[0]["asset_id"])
            if inherited
            else None,
        )
        with n.store.lock:
            n.store.db.execute(
                "UPDATE disaster_audio_jobs SET status='ready',audio_id=? WHERE owner=? AND content_key=?",
                (entry.audio_id, state.owner_id, key),
            )
            n.store.db.execute(
                "INSERT OR REPLACE INTO disaster_audio_manifests VALUES (?,?,?,?,?)",
                (state.owner_id, sid, body.source_id, category, json.dumps(manifest)),
            )
            n.store.db.commit()
        return dict(
            schema_version="1.0.0",
            request_id=request.state.request_id,
            data=dict(
                audio_url=f"{origin}{MEDIA_PATH}/{entry.audio_id}?expires={expires}&signature={n.sign(state.owner_id, entry.audio_id, expires)}",
                expires_at=iso(expires),
                manifest=manifest,
            ),
        )
