"""Application orchestration. Every mutation stages copies, persists, then publishes."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app import contracts as c
from app.behavior.vitals import conscious
from app.data.repository import Repository, encode
from app.infrastructure.errors import DomainError, require
from app.infrastructure.gemini import Gateway, context_for, relevance
from app.integrations.tiger import TigerIngestor
from app.scenario_engine import interpreter, validator
from app.scenario_engine.registry import ScenarioPlan
from app.scenario_engine.runtime import attach as attach_plan
from app.scenario_engine.world import enable as enable_systems
from app.simulation.agents import (
    connect,
    evidence,
    generated_profile,
    hazard_severity,
    metric_delta,
    remember,
    spawn,
    update_metrics,
)
from app.simulation.building_visits import same_room, sync_building_location
from app.simulation.characters import upgrade_placeholder_citizens
from app.simulation.daily import model_available
from app.simulation.engine import list_tree, tick
from app.simulation.game_master import apply_intent, make_intent
from app.simulation.lessons import adopt_drafts, lesson_material
from app.simulation.navigation import cell_at, distance, meeting_point, pathfind
from app.simulation.scenario_scene import CATALOG, matches
from app.simulation.scenarios import compile_preview, generate_map, queue_event, validate_spec
from app.simulation.state import State, expired, expiry, now, uid
from app.simulation.timing import legacy_ticks, ticks_for

# Historical records are appended/replaced, never edited after publication.
_APPEND_ONLY = {
    "decisions",
    "dialogue",
    "metric_points",
    "pending_decisions",
    "pending_metric_points",
    "memories",
    "metric_reasons",
    "provider_references",
    "external_resource_changes",
    "applied_social_evidence",
    "damage_records",
    "reactions",
    "service_changes",
    "cells",
    "impacts",
    "events",
    "snapshots",
}
# These fields are immutable during tick execution. HTTP mutators still deep-copy
# their input before editing any configuration, profile or map geometry.
_STATIC_FIELDS = {
    "profile",
    "config",
    "home",
    "known_locations",
    "footprint",
    "entrance",
    "polygon",
    "evidence",
}
_SCALARS = (str, int, float, bool, type(None))


def staging_copy(value):
    """Fork mutable world data while sharing immutable geometry and history."""
    kind = type(value)
    if kind in _SCALARS:
        return value
    if isinstance(value, BaseModel):
        # Construct a trusted fork directly: validation and generic deepcopy are
        # unnecessary for data already validated at the command boundary.
        cloned = object.__new__(kind)
        fields = value.__dict__.copy()
        for key, item in fields.items():
            if key in _STATIC_FIELDS or type(item) in _SCALARS:
                continue
            fields[key] = list(item) if key in _APPEND_ONLY and isinstance(item, list) else staging_copy(item)
        object.__setattr__(cloned, "__dict__", fields)
        object.__setattr__(cloned, "__pydantic_fields_set__", value.__pydantic_fields_set__.copy())
        object.__setattr__(cloned, "__pydantic_extra__", value.__pydantic_extra__)
        private = getattr(value, "__pydantic_private__", None)
        if private:
            private = {
                key: copy.deepcopy(private.get(key))
                if key in {"_dialogue_index", "_social_index"}
                else attr.get_default()
                for key, attr in kind.__private_attributes__.items()
            }
        object.__setattr__(cloned, "__pydantic_private__", private)
        return cloned
    if kind is dict:
        return {key: staging_copy(item) for key, item in value.items()}
    if kind is list:
        return [staging_copy(item) for item in value]
    if kind is tuple:
        return tuple(staging_copy(item) for item in value)
    return value


@dataclass
class Transaction:
    data: Any
    status: int = 200
    states: list[State] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    branches: dict = field(default_factory=dict)
    delete: str | None = None
    initialize: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    tag: str
    context_tick: int
    intent: c.Intent
    expires_at: float


class ProviderProposals(dict):
    """The tick requests each proposal after activation and prior actors' actions.

    Revalidate at that boundary, not just when the application starts the tick.
    This preserves the engine's existing mapping interface without a second
    writer or changes to simulation modules owned by the other workstream.
    """

    def __init__(self, service, state):
        super().__init__()
        self.service, self.state = service, state

    def get(self, aid, default=None):
        result = self.pop(aid, None)
        if result is None:
            return default
        if not self.service.valid_proposal(self.state, aid, result):
            self.service.discard_proposal(self.state, aid)
            return default
        self.state.provider_references.append(
            dict(
                agent_id=aid,
                context_tick=result.context_tick,
                accepted_tick=self.state.simulation.tick,
                source="gemini",
            )
        )
        return result.intent, result.tag


class Service:
    def __init__(self, config):
        config.validate()
        self.config = config
        self.repo = Repository(config.data_dir, recover=False)
        self.heads = {}
        self.saved_summaries = None
        self.load_locks = {}
        self.writer = asyncio.Lock()
        self.transactions = asyncio.Lock()
        self.commit_lock = asyncio.Lock()
        self.pending_commits = {}
        self.commit_task = None
        self.head_events = {}
        self.staging = {}
        self.locks = {sid: asyncio.Lock() for sid in self.heads}
        self.runners = {}
        self.initializers = {}
        self.provider_tasks = {}
        self.provider_results = {}
        self.scene_tasks = {}
        self.lesson_tasks = {}
        self.closed = False
        self.gateway = Gateway(config, self.record_usage)
        billed = self.repo.meta["usage"].get("global", {})
        self.gateway.tokens = (
            billed.get("input_tokens", 0) + billed.get("output_tokens", 0) + billed.get("budget_charge", 0)
        )
        self.stats = {
            "ticks": 0,
            "tick_seconds": [],
            "commit_seconds": [],
            "fallbacks": 0,
            "socket_bytes": 0,
            "publish_seconds": [],
            "commits": 0,
        }
        self.tiger = TigerIngestor(self)

    async def start(self):
        # Saved worlds stay on disk until history or a specific world is requested.
        self.tiger.start()

    async def load(self, owner, sid):
        async with self.load_locks.setdefault(sid, asyncio.Lock()):
            if sid in self.heads:
                return self.owned(owner, sid)
            try:
                head = await asyncio.to_thread(self.repo.restore, sid)
            except KeyError:
                raise DomainError("NOT_FOUND", "Simulation not found", 404)
            except (OSError, ValueError) as error:
                raise DomainError(
                    "PERSISTENCE_UNAVAILABLE", "Saved simulation could not be loaded", 503
                ) from error
            require(head.owner_id == owner, "NOT_FOUND", "Simulation not found", 404)
            self.heads[sid] = head
            self.locks.setdefault(sid, asyncio.Lock())
            await self.recover_head(sid, head)
            return self.heads[sid]

    async def summaries(self):
        if self.saved_summaries is None:
            self.saved_summaries = await asyncio.to_thread(self.repo.summaries)
        result = {
            sid: (summary.owner_id, summary.simulation)
            for sid, summary in self.saved_summaries.items()
            if sid in self.repo.meta["simulations"]
        }
        result.update({sid: (head.owner_id, head.simulation) for sid, head in self.heads.items()})
        return result

    async def recover_head(self, sid, head):
        # Recovery happens only when opening this world, preserving immutable history.
        if head.simulation.status == "initializing":
            self.initializers[sid] = asyncio.create_task(self.initialize(sid))
            return
        state = head.model_copy(deep=True)
        upgraded = upgrade_placeholder_citizens(state)
        recovering = head.simulation.status == "running" or head.intervention or head.auto_resume
        if recovering or upgraded:
            self.bump(state, control=bool(recovering))
            if recovering:
                state.simulation.status = "paused"
                state.simulation.pause_reason = "loaded"
                self.clear_editor(state)
                state.auto_resume = False
                state.lineage_generation += 1
                for runtime in state.events.values():
                    runtime.resume_allowed = False
            try:
                await self.persist([state])
            except DomainError:
                pass

    async def close(self):
        self.closed = True
        tasks = [
            *self.runners.values(),
            *self.initializers.values(),
            *self.provider_tasks.values(),
            *self.scene_tasks.values(),
            *self.lesson_tasks.values(),
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Cancellation stops producers first, then the latest valid heads become durable.
        if self.commit_task:
            await asyncio.gather(self.commit_task, return_exceptions=True)
        if not self.repo.degraded:
            await self.persist(list(self.heads.values()), publish=False)
        await self.gateway.close()
        await self.tiger.close()
        self.repo.close()

    def owned(self, owner, sid, revision=None):
        head = self.heads.get(sid)
        require(head is not None and head.owner_id == owner, "NOT_FOUND", "Simulation not found", 404)
        if revision is None:
            return head
        if revision == head.simulation.revision:
            return head
        require(0 <= revision <= head.simulation.revision, "NOT_FOUND", "Revision not found", 404)
        entries = self.repo.meta["simulations"].get(sid, ())
        revision = min(revision, entries[-1]["revision"]) if entries else revision
        try:
            state = self.repo.read(sid, revision)
        except KeyError:
            raise DomainError("NOT_FOUND", "Revision not found", 404)
        require(state.owner_id == owner, "NOT_FOUND", "Simulation not found", 404)
        return state

    def bump(self, state, control=False):
        state.simulation.revision += 1
        state.simulation.updated_at = now()
        if control:
            state.simulation.control_version += 1

    def version(self, state, expected):
        require(
            state.simulation.control_version == expected,
            "CONTROL_CONFLICT",
            "Control version is stale",
            field="expected_control_version",
            reason=f"Latest control_version={state.simulation.control_version}",
        )

    def ready(self, state, mutable=False):
        require(state.simulation.initialization.stage == "ready", "INVALID_STATE", "Simulation is not ready")
        if mutable:
            require(
                not state.simulation.archived and state.simulation.status not in {"completed", "failed"},
                "INVALID_STATE",
                "Simulation cannot be changed",
            )

    def can_play(self, state, slot=True):
        self.ready(state, True)
        require(
            state.simulation.tick < state.simulation.config.max_ticks,
            "INVALID_STATE",
            "The run horizon has been reached; branch from an earlier revision",
        )
        require(state.intervention is None, "INTERVENTION_OPEN", "An event editor is open")
        require(
            state.simulation.initial_preview is None,
            "INVALID_STATE",
            "Confirm or skip the initial scenario first",
        )
        require(
            not state.simulation.pending_outcome_event_ids,
            "INVALID_STATE",
            "Acknowledge the pending outcome first",
        )
        if slot:
            self.running_slot(state.simulation.id)

    def running_slot(self, sid):
        running = sum(h.simulation.status == "running" for key, h in self.heads.items() if key != sid)
        require(
            running < self.config.max_running,
            "INVALID_STATE",
            "Maximum concurrently running simulations reached",
        )

    def clear_editor(self, state):
        state.intervention = None
        state.previews = {}

    def revoke_resume(self, state):
        state.auto_resume = False
        if state.intervention:
            state.intervention.was_running = False
        for runtime in state.events.values():
            runtime.resume_allowed = False

    def snapshot(self, state, reason, label, ref=None):
        snapshot = c.Snapshot(
            id=state.next_id("snapshot"),
            simulation_id=state.simulation.id,
            ref=ref or state.ref(),
            created_at=now(),
            reason=reason,
            label=label,
        )
        state.snapshots.append(snapshot)
        state.simulation.latest_snapshot_id = snapshot.id
        state.simulation.saved_at = snapshot.created_at
        return snapshot

    def head_event(self, sid):
        return self.head_events.setdefault(sid, asyncio.Event())

    def publish_head(self, sid, state):
        self.heads[sid] = state
        event = self.head_events.pop(sid, None)
        if event:
            event.set()

    def history(self, state, kind):
        records = self.repo.history(state.simulation.id, kind, state.simulation.revision)
        records.extend(getattr(state, "pending_" + kind, ()))
        records.extend(getattr(state, kind))
        # A committed segment may overlap a still-published pending buffer.
        return list({self.repo.history_key(kind, item): item for item in records}.values())

    def prune_pending(self, state):
        watermarks = self.repo.meta.get("history_watermarks", {}).get(state.simulation.id, {})
        for kind in ("decisions", "metric_points"):
            through = watermarks.get(kind, -1)
            pending = getattr(state, "pending_" + kind, ())
            if pending:
                setattr(
                    state,
                    "pending_" + kind,
                    [item for item in pending if self.repo.history_key(kind, item) > through],
                )

    async def persist(self, states, *, publish=True, **kwargs):
        # Only this lock orders fsyncs; the world writer is never needed by storage.
        async with self.commit_lock:
            states = [
                state
                for state in states
                if state.simulation.revision
                > (self.repo.meta["simulations"].get(state.simulation.id) or [{"revision": -1}])[-1][
                    "revision"
                ]
            ]
            if not states and not any(value is not None for value in kwargs.values()):
                return
            start = time.perf_counter()
            task = asyncio.create_task(asyncio.to_thread(self.repo.commit, states, **kwargs))
            try:
                # Cancelling a producer must never release ordering before fsync finishes.
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
            except (OSError, ValueError) as error:
                if not self.repo.degraded:
                    self.repo.degraded.append("Persistence commit failed; mutations halted")
                for event in self.head_events.values():
                    event.set()
                raise DomainError(
                    "PERSISTENCE_UNAVAILABLE", "Commit failed; last durable state remains available", 503
                ) from error
            self.stats["commit_seconds"].append(time.perf_counter() - start)
            self.stats["commit_seconds"] = self.stats["commit_seconds"][-1000:]
            self.stats["commits"] += 1
            if publish:
                for state in states:
                    self.publish_head(state.simulation.id, state)
                    self.schedule_lessons(state)
            self.tiger.notify()

    def queue_commit(self, state):
        self.pending_commits[state.simulation.id] = state
        if self.commit_task is None or self.commit_task.done():
            self.commit_task = asyncio.create_task(self.drain_commits())

    async def drain_commits(self):
        try:
            while self.pending_commits:
                states = list(self.pending_commits.values())
                self.pending_commits.clear()
                await self.persist(states, publish=False)
        except DomainError:
            # The runner sees degraded persistence and stops; durable reads remain usable.
            self.pending_commits.clear()

    def schedule_lessons(self, state):
        if not self.config.gemini_enabled or self.closed:
            return
        sid = state.simulation.id
        for eid, runtime in state.events.items():
            # Only the commit that resolved the event schedules; copies and branches never re-trigger.
            if (
                runtime.summary.status == "resolved"
                and runtime.summary.end_tick == state.simulation.tick
                and runtime.lessons_source == "rules"
                and runtime.lesson_facts
                and (sid, eid) not in self.lesson_tasks
            ):
                self.lesson_tasks[(sid, eid)] = asyncio.create_task(
                    self.rewrite_lessons(sid, eid, lesson_material(runtime))
                )

    async def rewrite_lessons(self, sid, eid, material):
        try:
            drafts = await self.gateway.lessons(sid, material)
        except DomainError:
            return
        if not drafts:
            return
        async with self.locks.setdefault(sid, asyncio.Lock()):
            async with self.writer:
                head = self.heads.get(sid)
                runtime = head.events.get(eid) if head else None
                if self.closed or self.repo.degraded or not runtime or runtime.lessons_source != "rules":
                    return
                lessons = adopt_drafts(runtime, drafts)
                if not lessons:
                    self.gateway.diagnostics["discarded"] += 1
                    return
                state = head.model_copy(deep=True)
                self.bump(state)
                state.events[eid].lessons = lessons
                state.events[eid].lessons_source = "gemini"
            try:
                await self.persist([state])
            except DomainError:
                pass

    async def mutate(self, owner, key, route, body, operation, sid=None):
        fingerprint = hashlib.sha256(encode({"route": route, "body": body})).hexdigest()
        identity = f"{owner}:{key}"
        async with self.transactions:
            previous = self.repo.meta["idempotency"].get(identity)
            if previous:
                require(
                    previous["fingerprint"] == fingerprint,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency key was used for a different request",
                )
                return previous["response"], previous["status"]
            if self.repo.degraded:
                raise DomainError(
                    "PERSISTENCE_UNAVAILABLE", "Persistence is degraded; mutations are halted", 503
                )
            if sid:
                self.owned(owner, sid)
                lock = self.locks.setdefault(sid, asyncio.Lock())
            else:
                lock = asyncio.Lock()
            async with lock:
                async with self.writer:
                    result = operation()
                data = (
                    result.data.model_dump(mode="json") if isinstance(result.data, c.Model) else result.data
                )
                response = {"schema_version": "1.0.0", "request_id": key, "data": data}
                saved = {"fingerprint": fingerprint, "response": response, "status": result.status}
                durable_states = list(result.states)
                if sid and sid in self.heads:
                    previous_head = self.heads[sid]
                    journal = self.repo.meta["simulations"].get(sid, ())
                    if not journal or previous_head.simulation.revision > journal[-1]["revision"]:
                        # Pre-event snapshots and whole-world branches must retain the
                        # exact prior head even when it falls between periodic commits.
                        durable_states.insert(0, previous_head)
                await self.persist(
                    durable_states,
                    idempotency=(identity, saved),
                    metadata=result.metadata or None,
                    branches=result.branches or None,
                    delete=result.delete,
                )
                if result.delete:
                    self.heads.pop(result.delete, None)
                    runner = self.runners.pop(result.delete, None)
                    if runner:
                        runner.cancel()
                    for task_key, task in list(self.provider_tasks.items()):
                        if task_key[0] == result.delete:
                            task.cancel()
                    for task_key in list(self.provider_results):
                        if task_key[0] == result.delete:
                            self.provider_results.pop(task_key, None)
                if result.initialize:
                    self.initializers[result.initialize] = asyncio.create_task(
                        self.initialize(result.initialize)
                    )
                for state in result.states:
                    self.ensure_runner(state)
                return response, result.status

    def create(self, owner, request):
        config = request.config.normalized()
        require(
            config.population <= self.config.max_agents,
            "INVALID_REQUEST",
            "Population exceeds configured maximum",
            400,
        )
        profiles = []
        for pid in config.custom_agent_ids:
            template = self.repo.meta["profiles"].get(pid)
            require(
                template is not None and template["owner_id"] == owner,
                "NOT_FOUND",
                "Custom profile not found",
                404,
            )
            profiles.append(template["data"])
        sid = uid("simulation")
        stamp = now()
        simulation = c.Simulation(
            id=sid,
            name=config.name,
            config=config,
            created_at=stamp,
            updated_at=stamp,
            status="initializing",
            pause_reason=None,
            archived=False,
            tick=0,
            revision=0,
            control_version=0,
            sim_time_seconds=0,
            calendar_time_seconds=8 * 3600,
            speed_multiplier=1,
            achieved_ticks_per_second=0,
            agent_count=0,
            parent_simulation_id=None,
            fork_ref=None,
            latest_snapshot_id=None,
            saved_at=None,
            pending_outcome_event_ids=[],
            initialization=c.Job(stage="queued", progress=0, message="Initialization queued", error=None),
            initial_preview=None,
        )
        state = State(owner_id=owner, simulation=simulation, initialization_profiles=profiles)
        state.rng_state = list_tree(random.Random(config.seed).getstate())
        return Transaction(data=simulation, status=202, states=[state], initialize=sid)

    async def initialize(self, sid):
        try:
            from app.simulation.engine import tuple_tree

            # Stage transitions are durable results of completed work, never fake timers.
            stages = [
                ("map", 25),
                ("population", 55),
                ("relationships", 70),
                ("scenario", 80),
                ("persistence", 90),
                ("ready", 100),
            ]
            for stage, progress in stages:
                provider = {}
                if stage == "scenario":
                    head = self.heads.get(sid)
                    premise = head.simulation.config.scenario_description if head else ""
                    if (
                        premise.strip()
                        and self.config.gemini_enabled
                        and head
                        and head.simulation.initialization.stage
                        in {"queued", "map", "population", "relationships"}
                    ):
                        # Provider work and usage recording run outside the writer lock.
                        engine = await interpreter.interpret(
                            self.gateway, head, sid, premise, head.simulation.config.mode
                        )
                        if engine["status"] in {"ready", "unsupported", "needs_clarification"}:
                            provider = dict(engine=engine)
                        else:
                            provider = await self.interpret_premise(sid, premise) | dict(engine=engine)
                async with self.writer:
                    head = self.heads.get(sid)
                    if not head or head.simulation.status != "initializing":
                        return
                    completed = [
                        "queued",
                        "map",
                        "population",
                        "relationships",
                        "scenario",
                        "persistence",
                        "ready",
                    ]
                    if completed.index(head.simulation.initialization.stage) >= completed.index(stage):
                        continue
                    state = head.model_copy(deep=True)
                    rng = random.Random()
                    rng.setstate(tuple_tree(state.rng_state))
                    self.bump(state)
                    if stage == "map":
                        state.map = await asyncio.to_thread(generate_map, state, rng)
                    elif stage == "population":
                        homes = [b for b in state.map.buildings if b.kind == "home"]
                        from app.simulation.building_visits import interior_capacity

                        assigned = {b.id: 0 for b in homes}
                        for i in range(state.simulation.config.population):
                            template = (
                                state.initialization_profiles[i]
                                if i < len(state.initialization_profiles)
                                else None
                            )
                            profile = (
                                c.Profile.model_validate(template["profile"])
                                if template
                                else generated_profile(i, state.simulation.config, rng)
                            )
                            available = [b for b in homes if assigned[b.id] < interior_capacity(b)]
                            residence = min(
                                available or homes, key=lambda b: (assigned[b.id], homes.index(b))
                            )
                            assigned[residence.id] += 1
                            home = residence.entrance
                            position = home
                            if state.simulation.config.population <= 10:
                                for dx, dy in [(-0.55, -0.55), (0.55, 0.55), (-0.55, 0.55), (0.55, -0.55)]:
                                    candidate = c.Vec2(x=home.x + dx, y=home.y + dy)
                                    cell = cell_at(state.map, candidate)
                                    if (
                                        cell
                                        and cell.walkable
                                        and all(
                                            distance(candidate, other.summary.position) >= 1.05
                                            for other in state.citizens.values()
                                        )
                                    ):
                                        position = candidate
                                        break
                            citizen = spawn(state, profile, position, template)
                            citizen.home = home.model_copy()
                            citizen.home_building_id = residence.id
                            citizen.next_deliberation_tick = legacy_ticks(state, i % 8) if i % 8 else 0
                        from app.behavior.classes import initialize_distribution

                        initialize_distribution(state)
                        state.simulation.agent_count = len(state.citizens)
                    elif stage == "relationships":
                        people = list(state.citizens.values())
                        for i, citizen in enumerate(people):
                            for offset, kind in [(1, "family"), (2, "friend"), (3, "acquaintance")]:
                                connect(state, citizen, people[(i + offset) % len(people)], kind, rng)
                    elif stage == "scenario":
                        if state.simulation.config.scenario_description.strip():
                            self.initial_scenario(state, provider)
                    elif stage == "ready":
                        for citizen in state.citizens.values():
                            require(
                                cell_at(state.map, citizen.home).walkable,
                                "INVALID_STATE",
                                "Invalid home placement",
                            )
                            require(
                                any(
                                    pathfind(state.map, citizen.home, r.position) is not None
                                    for r in state.map.resources
                                ),
                                "INVALID_STATE",
                                "A household has no resource access",
                            )
                        state.simulation.status = "paused"
                        state.simulation.pause_reason = "manual"
                        if state.simulation.config.mode in {"policy_lab", "behavior_lab"}:
                            enable_systems(state)
                        update_metrics(state)
                        self.snapshot(state, "initial", "Initial city")
                        if state.simulation.initial_preview:
                            state.simulation.initial_preview.based_on = state.ref()
                        state.initialization_profiles = []
                    state.rng_state = list_tree(rng.getstate())
                    state.simulation.initialization = c.Job(
                        stage=stage, progress=progress, message=f"{stage.title()} complete", error=None
                    )
                await self.persist([state])
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self.repo.degraded:
                return
            async with self.writer:
                if sid not in self.heads:
                    return
                state = self.heads[sid].model_copy(deep=True)
                self.bump(state, True)
                state.simulation.status = "failed"
                state.simulation.pause_reason = "error"
                state.simulation.initialization = c.Job(
                    stage="failed",
                    progress=state.simulation.initialization.progress,
                    message="Initialization failed",
                    error=c.Error(
                        code="INVALID_REQUEST", message=str(error)[:1000], retryable=False, details=[]
                    ),
                )
            await self.persist([state])

    def ensure_runner(self, state):
        sid = state.simulation.id
        if state.simulation.status == "running" and (sid not in self.runners or self.runners[sid].done()):
            self.runners[sid] = asyncio.create_task(self.run(sid))

    async def run(self, sid):
        last = time.perf_counter()
        staging = None
        published = None
        try:
            while not self.closed:
                head = self.heads.get(sid)
                if not head or head.simulation.status != "running" or self.repo.degraded:
                    return
                durable = (self.repo.meta["simulations"].get(sid) or [{"tick": 0}])[-1]["tick"]
                budget = ticks_for(head, self.config.persist_interval_seconds)
                if head.simulation.tick - durable >= budget:
                    self.queue_commit(head)
                    await self.commit_task
                    if self.repo.degraded:
                        return
                interval = head.simulation.config.tick_seconds / (
                    self.config.base_tps * head.simulation.speed_multiplier
                )
                await asyncio.sleep(max(0, interval - (time.perf_counter() - last)))
                # A command locks its simulation before the writer too, so other worlds
                # and provider results remain available during tick computation.
                async with self.locks.setdefault(sid, asyncio.Lock()):
                    async with self.writer:
                        head = self.heads.get(sid)
                        if not head or head.simulation.status != "running":
                            return
                        if staging is None or head is not published:
                            staging = staging_copy(head)
                        self.staging[sid] = staging
                        self.prune_pending(staging)
                        started = time.perf_counter()
                        self.bump(staging)
                        elapsed = started - last
                        staging.simulation.achieved_ticks_per_second = 1 / elapsed if elapsed > 0 else 0
                        proposals = self.take_proposals(staging)
                    start = time.perf_counter()
                    await asyncio.to_thread(tick, staging, proposals)
                    self.stats["tick_seconds"].append(time.perf_counter() - start)
                    self.stats["tick_seconds"] = self.stats["tick_seconds"][-1000:]
                    self.stats["ticks"] += 1
                    autosave = (
                        self.repo.settings(staging.owner_id).autosave
                        and staging.simulation.tick % ticks_for(staging, self.config.autosave_interval) == 0
                    )
                    if autosave:
                        self.snapshot(staging, "autosave", "Periodic autosave")
                    start = time.perf_counter()
                    async with self.writer:
                        jobs = self.prepare_deliberation(staging)
                    published = staging_copy(staging)
                    async with self.writer:
                        self.publish_head(sid, published)
                    self.schedule_lessons(published)
                    self.stats["publish_seconds"].append(time.perf_counter() - start)
                    self.stats["publish_seconds"] = self.stats["publish_seconds"][-1000:]
                    durable = (self.repo.meta["simulations"].get(sid) or [{"tick": 0}])[-1]["tick"]
                    if (
                        autosave
                        or staging.simulation.status != "running"
                        or staging.simulation.tick - durable
                        >= max(1, ticks_for(staging, self.config.persist_interval_seconds) - 1)
                    ):
                        self.queue_commit(published)
                    last = started
                self.schedule_deliberation(jobs)
        except (asyncio.CancelledError, DomainError):
            return
        except Exception as error:
            async with self.writer:
                head = self.heads.get(sid)
                state = None
                if head and not self.repo.degraded and not self.closed:
                    state = staging_copy(head)
                    self.bump(state, True)
                    state.simulation.status = "failed"
                    state.simulation.pause_reason = "error"
                    self.revoke_resume(state)
                    state.simulation.initialization.error = c.Error(
                        code="SERVICE_UNAVAILABLE",
                        message=f"Simulation stopped after {type(error).__name__}; last valid tick retained",
                        retryable=False,
                        details=[],
                    )
            if state:
                await self.persist([state])
        finally:
            self.staging.pop(sid, None)

    def command(self, owner, sid, request):
        state = self.owned(owner, sid).model_copy(deep=True)
        self.version(state, request.expected_control_version)
        cmd = request.command
        self.ready(state)
        if cmd.type not in {"unarchive", "save", "archive"}:
            require(not state.simulation.archived, "INVALID_STATE", "Simulation is archived")
        snapshot = None
        affected = []
        states = []
        if cmd.type == "play":
            self.can_play(state)
            self.bump(state, True)
            state.simulation.status = "running"
            state.simulation.pause_reason = None
            for runtime in state.events.values():
                if runtime.summary.status in {"queued", "active"}:
                    runtime.resume_allowed = True
        elif cmd.type == "pause":
            self.bump(state, True)
            if state.simulation.status != "completed":
                state.simulation.status = "paused"
                state.simulation.pause_reason = "manual"
            self.revoke_resume(state)
        elif cmd.type == "step":
            self.can_play(state, slot=False)
            require(state.simulation.status == "paused", "INVALID_STATE", "Step requires a paused simulation")
            self.revoke_resume(state)
            state.simulation.control_version += 1
            for _ in range(cmd.count):
                self.bump(state)
                tick(state, self.take_proposals(state))
                if (
                    self.repo.settings(owner).autosave
                    and state.simulation.tick % ticks_for(state, self.config.autosave_interval) == 0
                ):
                    snapshot = self.snapshot(state, "autosave", "Periodic autosave")
                states.append(state.model_copy(deep=True))
                if state.simulation.pending_outcome_event_ids or state.simulation.status == "completed":
                    break
            return Transaction(
                c.CommandResult(simulation=state.simulation, snapshot=snapshot, affected_agent_ids=[]),
                states=states,
            )
        elif cmd.type == "set_speed":
            self.bump(state, True)
            state.simulation.speed_multiplier = cmd.value
        elif cmd.type == "save":
            self.bump(state, True)
            if cmd.reason == "navigation":
                if state.simulation.status != "completed":
                    state.simulation.status = "paused"
                    state.simulation.pause_reason = "manual"
                self.revoke_resume(state)
                self.clear_editor(state)
            snapshot = self.snapshot(state, cmd.reason, cmd.label)
        elif cmd.type == "archive":
            self.bump(state, True)
            state.simulation.status = "paused"
            state.simulation.pause_reason = "manual"
            state.simulation.archived = True
            self.revoke_resume(state)
            self.clear_editor(state)
            snapshot = self.snapshot(state, "manual", "Archived city")
        elif cmd.type == "unarchive":
            require(state.simulation.archived, "INVALID_STATE", "Simulation is not archived")
            self.bump(state, True)
            state.simulation.archived = False
            state.simulation.status = "paused"
            state.simulation.pause_reason = "manual"
        elif cmd.type == "add_agents":
            self.ready(state, True)
            require(
                state.intervention is None, "INTERVENTION_OPEN", "Close the editor before adding citizens"
            )
            require(
                len(state.citizens) + len(cmd.custom_agent_ids) <= self.config.max_agents,
                "INVALID_REQUEST",
                "Population cap exceeded",
                400,
            )
            templates = []
            for pid in cmd.custom_agent_ids:
                template = self.repo.meta["profiles"].get(pid)
                require(
                    template is not None and template["owner_id"] == owner,
                    "NOT_FOUND",
                    "Custom profile not found",
                    404,
                )
                templates.append(template["data"])
            self.bump(state, True)
            entrances = [b.entrance for b in state.map.buildings if b.functional]
            for template in templates:
                position = min(
                    entrances,
                    key=lambda p: sum(
                        abs(p.x - citizen.summary.position.x) < 1
                        and abs(p.y - citizen.summary.position.y) < 1
                        for citizen in state.citizens.values()
                    ),
                )
                citizen = spawn(state, c.Profile.model_validate(template["profile"]), position, template)
                for other in list(state.citizens.values())[-4:]:
                    connect(state, citizen, other)
                    connect(state, other, citizen)
                affected.append(citizen.summary.id)
            state.simulation.agent_count = len(state.citizens)
            update_metrics(state)
        elif cmd.type == "set_relationship":
            self.ready(state, True)
            require(state.intervention is None, "INTERVENTION_OPEN", "Close the editor first")
            citizen, target = state.citizens.get(cmd.agent_id), state.citizens.get(cmd.target_id)
            require(citizen is not None and target is not None, "NOT_FOUND", "Citizen not found", 404)
            require(citizen is not target, "INVALID_REQUEST", "Choose two different citizens", 400)
            require(
                citizen.summary.active and target.summary.active,
                "INVALID_STATE",
                "Choose two active citizens",
            )
            presets = {
                "lovers": ("romantic", 95, 80, 0, 60),
                "friends": ("friend", 75, 75, 5, 50),
                "rivals": ("rival", 15, 20, 75, 30),
                "acquaintances": ("acquaintance", 35, 50, 10, 30),
            }
            kind, affection, trust, conflict, familiarity = presets[cmd.preset]
            self.bump(state, True)
            proof = evidence(f"Explicit owner relationship override: {cmd.preset}")
            for actor, other in ((citizen, target), (target, citizen)):
                connect(state, actor, other)
                tie = actor.relationships[other.summary.id]
                tie.kind, tie.affection, tie.trust, tie.conflict = kind, affection, trust, conflict
                tie.familiarity = max(tie.familiarity, familiarity)
                tie.desired_relationship = {
                    "lovers": "Romantic connection",
                    "friends": "Mutual friendship",
                    "rivals": "Rivalry",
                    "acquaintances": "Casual acquaintance",
                }[cmd.preset]
                tie.evidence = proof
                remember(
                    state,
                    actor,
                    f"The owner made {other.summary.name} and me {cmd.preset}.",
                    "injected",
                    70,
                    subjects=[other.summary.id],
                    proof=proof,
                )
            affected = [cmd.agent_id, cmd.target_id]
            update_metrics(state)
        elif cmd.type == "override_agent":
            self.ready(state, True)
            require(
                state.intervention is None,
                "INTERVENTION_OPEN",
                "Close the editor before overriding a citizen",
            )
            citizen = state.citizens.get(cmd.agent_id)
            require(citizen is not None, "NOT_FOUND", "Citizen not found", 404)
            require(
                conscious(citizen) and citizen.condition.care == "none",
                "INVALID_STATE",
                "Citizen cannot accept commands while dead, unconscious or in care",
            )
            self.bump(state, True)
            proof = evidence("Explicit owner override")
            # Derived scores are changed via their underlying state to retain metric invariants.
            for key, value in cmd.metrics.items():
                if key in {"happiness", "stress"}:
                    metric_delta(citizen, key, value - getattr(citizen.summary.metrics, key), proof)
                elif key == "trust":
                    for relationship in citizen.relationships.values():
                        relationship.trust = value
                        relationship.evidence = proof
                elif key == "safety":
                    require(
                        value <= 100 - hazard_severity(state, citizen.summary.position),
                        "INVALID_REQUEST",
                        "Safety cannot exceed the current physical hazard limit",
                        400,
                    )
                    citizen.needs.health = value
                elif key == "resources":
                    current = sum(citizen.inventory.model_dump().values())
                    desired = citizen.target_inventory_units * value / 100
                    delta = desired - current if value < 100 or current < desired else 0
                    sources = [
                        resource
                        for resource in state.map.resources
                        if resource.id in citizen.known_locations
                        and distance(citizen.summary.position, resource.position) <= 3
                    ]
                    transfers = []
                    remaining = abs(delta)
                    planned_inventory = citizen.inventory.model_dump()
                    for resource in sources:
                        available = (
                            resource.available_units if delta > 0 else planned_inventory[resource.kind]
                        )
                        units = min(remaining, available)
                        if units > 0:
                            transfers.append((resource, units if delta > 0 else -units))
                            planned_inventory[resource.kind] += units if delta > 0 else -units
                            remaining -= units
                    require(
                        remaining < 1e-8,
                        "INVALID_REQUEST",
                        "Resource override requires enough known stock or deposit access within 3 meters; inventory is conserved",
                        400,
                    )
                    for resource, units in transfers:
                        resource.available_units -= units
                        setattr(
                            citizen.inventory,
                            resource.kind,
                            getattr(citizen.inventory, resource.kind) + units,
                        )
                        state.external_resource_changes.append(
                            dict(
                                tick=state.simulation.tick,
                                agent_id=citizen.summary.id,
                                resource_id=resource.id,
                                units=units,
                                reason="Conserved owner metric override transfer; not external creation",
                            )
                        )
            if cmd.goal is not None:
                citizen.goals = [cmd.goal, *citizen.goals[1:]]
            if cmd.memory_text is not None:
                remember(state, citizen, cmd.memory_text, "injected", 70, proof=proof)
            citizen.task_generation += 1
            citizen.next_deliberation_tick = state.simulation.tick
            if cmd.intent:
                intent = cmd.intent
                if intent.action == "talk" and intent.parameters.message is not None:
                    require(
                        bool(intent.parameters.message.strip()),
                        "INVALID_REQUEST",
                        "Enter a line to say",
                        400,
                    )
                # Each owner instruction replaces any previously pending social visit.
                citizen.plan = None
                if intent.action != "talk":
                    for interaction in state.interactions.values():
                        if (
                            interaction.kind == "conversation"
                            and interaction.status in {"invited", "accepted"}
                            and citizen.summary.id in interaction.participant_ids
                        ):
                            interaction.status = "ended"
                if intent.action in {"rest", "consume"}:
                    citizen.summary.path = []
                    citizen.plan = None
                    sync_building_location(state, citizen)
                target = state.citizens.get(intent.target_id)
                if (
                    intent.action == "talk"
                    and target
                    and target.summary.active
                    and target is not citizen
                    and (
                        not same_room(citizen, target)
                        or distance(citizen.summary.position, target.summary.position) > 3
                    )
                ):
                    # The owner's invitation supplies an initial destination;
                    # subsequent pursuit can only use the citizen's own sight.
                    facility = next(
                        (b for b in state.map.buildings if b.id == target.inside_building_id), None
                    )
                    decision = apply_intent(
                        state,
                        citizen,
                        make_intent(
                            "move",
                            target=facility.id if facility else target.summary.id,
                            destination=facility.entrance
                            if facility
                            else meeting_point(state.map, citizen.summary.position, target.summary.position),
                            motivation="Walk over for an invited chat",
                        ),
                        "rules",
                    )
                    require(
                        decision.outcome != "rejected", "INVALID_REQUEST", decision.outcome_description, 400
                    )
                    citizen.plan = dict(
                        kind="social_visit",
                        target_id=target.summary.id,
                        message=intent.parameters.message,
                        expires_tick=state.simulation.tick + legacy_ticks(state, 30),
                    )
                else:
                    decision = apply_intent(state, citizen, intent, "rules")
                    require(
                        decision.outcome != "rejected", "INVALID_REQUEST", decision.outcome_description, 400
                    )
            else:
                citizen.summary.path = []
                citizen.plan = None
                sync_building_location(state, citizen)
            remember(
                state,
                citizen,
                "The owner changed my configured state: " + ", ".join(cmd.metrics),
                "injected",
                50,
                proof=proof,
            )
            from app.behavior.vitals import evaluate

            evaluate(state, citizen, "Owner changed canonical condition", proof)
            affected = [cmd.agent_id]
            update_metrics(state)
        elif cmd.type == "acknowledge_outcome":
            require(
                cmd.event_id in state.simulation.pending_outcome_event_ids,
                "INVALID_STATE",
                "Outcome is not pending",
            )
            resume = (
                cmd.resume and state.auto_resume and state.simulation.tick < state.simulation.config.max_ticks
            )
            if resume:
                self.running_slot(sid)
            self.bump(state, True)
            state.simulation.pending_outcome_event_ids.remove(cmd.event_id)
            state.auto_resume = False
            state.simulation.status = (
                "running"
                if resume
                else "completed"
                if state.simulation.tick >= state.simulation.config.max_ticks
                else "paused"
            )
            state.simulation.pause_reason = None if state.simulation.status != "paused" else "manual"
        return Transaction(
            c.CommandResult(simulation=state.simulation, snapshot=snapshot, affected_agent_ids=affected),
            states=[state],
        )

    def initial_scenario(self, state, provider):
        """The setup premise: an engine plan when interpreted, the keyword catalog otherwise."""
        premise = state.simulation.config.scenario_description
        engine = provider.get("engine")
        if engine and engine["status"] == "ready":
            plan, _, warnings = validator.validate_plan(state, engine["plan"])
            if plan:
                preview = validator.compile_preview(state, plan, warnings, source="initial")
                state.simulation.initial_preview = preview
                state.systems.initial_plan = plan.model_dump(mode="json")
                state.systems.initial_preview_id = preview.id
                return
        preview = compile_preview(
            state, "initial", premise, design=provider.get("design"), interpreted=provider.get("interpreted")
        )
        if engine and engine["status"] in {"unsupported", "needs_clarification"}:
            # Explain instead of substituting whatever the keyword catalog happens to match.
            reasons = engine["unsupported"] or [
                engine["clarification"] or "This scenario cannot be simulated."
            ]
            preview.can_commit = False
            preview.unsupported_requests = [r[:2000] for r in reasons]
            preview.interpretation = (
                engine["clarification"]
                or "The scenario engine cannot represent this request: " + "; ".join(reasons)
            )[:2000]
        elif engine:
            preview.warnings.append(
                "The AI scenario interpreter was unavailable, so this was interpreted with the built-in "
                "keyword catalog."
            )
        state.simulation.initial_preview = preview

    def open_intervention(self, owner, sid, body):
        state = self.owned(owner, sid).model_copy(deep=True)
        self.version(state, body.expected_control_version)
        self.ready(state, True)
        require(state.intervention is None, "INTERVENTION_OPEN", "An intervention is already open")
        require(
            state.simulation.initial_preview is None and not state.simulation.pending_outcome_event_ids,
            "INVALID_STATE",
            "Resolve the initial scenario or outcome first",
        )
        require(
            not any(r.summary.status in {"queued", "active"} for r in state.events.values()),
            "EVENT_ACTIVE",
            "Only one major event can be queued or active",
        )
        was_running = state.simulation.status == "running"
        self.bump(state, True)
        state.simulation.status = "paused"
        state.simulation.pause_reason = "intervention"
        state.intervention = c.Intervention(
            id=state.next_id("intervention"),
            simulation_id=sid,
            expires_at=expiry(),
            based_on=state.ref(),
            was_running=was_running,
            control_version=state.simulation.control_version,
        )
        return Transaction(state.intervention, 201, [state])

    def hold(self, state, iid):
        require(
            state.intervention is not None and state.intervention.id == iid,
            "PREVIEW_STALE",
            "Intervention is no longer open",
        )
        require(not expired(state.intervention.expires_at), "PREVIEW_EXPIRED", "Intervention expired", 410)
        return state.intervention

    async def prepare_scene(self, owner, sid, body, request_id):
        if body.source != "custom" or not self.config.gemini_enabled or not (body.prompt or "").strip():
            return None
        identity = f"{owner}:{request_id}"
        if identity in self.repo.meta["idempotency"]:
            return None
        state = self.owned(owner, sid)
        self.hold(state, body.intervention_id)
        if len(self.scene_tasks) >= 64:
            self.scene_tasks = {k: v for k, v in self.scene_tasks.items() if not v.done()}
        if identity not in self.scene_tasks:
            if len(self.scene_tasks) >= 64:
                return None
            self.scene_tasks[identity] = asyncio.create_task(self.interpret_premise(sid, body.prompt or ""))
        return await asyncio.shield(self.scene_tasks[identity])

    async def interpret_premise(self, sid, premise):
        """Provider work for a free-form premise. Runs outside the writer lock."""
        recipes = matches(premise)
        interpreted = None
        if not recipes:
            interpreted = await self.gateway.interpret(sid, premise)
            if interpreted == []:
                return dict(design=None, interpreted=interpreted)
            recipes = [r for r in CATALOG if r["id"] in (interpreted or [])]
        design = await self.gateway.scene(sid, premise, [r["model"] for r in recipes])
        return dict(design=design, interpreted=interpreted)

    def preview(self, owner, sid, body, provider=None):
        provider = provider or {}
        state = self.owned(owner, sid).model_copy(deep=True)
        self.hold(state, body.intervention_id)
        previous_editor = self.repo.meta.get("editors", {}).get(sid, {})
        state.entity_sequence = max(state.entity_sequence, previous_editor.get("sequence", 0))
        try:
            preview = compile_preview(
                state,
                body.source,
                body.prompt,
                body.source_event_id,
                body.policy,
                provider.get("design"),
                provider.get("interpreted"),
            )
        except ValidationError as error:
            reasons = "; ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()
            )
            raise DomainError(
                "VALIDATION_ERROR",
                "Scenario controls are outside the supported ranges",
                422,
                field="prompt",
                reason=reasons,
            ) from error
        # Editing has no world revision, so preview IDs cannot come from a copied counter.
        preview.id = uid("preview")
        # Preview tokens are durable metadata, with no world revision or physics changes.
        state.previews = {preview.id: preview}
        # Persist metadata separately: immutable committed state bytes never get overwritten.
        metadata = copy.deepcopy(self.repo.meta.get("editors", {}))
        metadata[sid] = {
            "hold_id": body.intervention_id,
            "preview": preview.model_dump(),
            "sequence": state.entity_sequence,
        }
        return Transaction(preview, 201, metadata={"editors": metadata})

    def cancel(self, owner, sid, iid, body):
        state = self.owned(owner, sid).model_copy(deep=True)
        self.version(state, body.expected_control_version)
        hold = self.hold(state, iid)
        resume = hold.was_running
        if resume:
            self.running_slot(sid)
        self.bump(state, True)
        self.clear_editor(state)
        state.simulation.status = "running" if resume else "paused"
        state.simulation.pause_reason = None if resume else "manual"
        return Transaction(state.simulation, states=[state])

    def commit_scenario(self, owner, sid, body, initial=False):
        state = self.owned(owner, sid).model_copy(deep=True)
        self.version(state, body.expected_control_version)
        self.ready(state, True)
        if initial:
            preview = state.simulation.initial_preview
            require(
                preview is not None and preview.id == body.preview_id,
                "PREVIEW_STALE",
                "Initial preview is no longer pending",
            )
            resume = False
        else:
            hold = self.hold(state, body.intervention_id)
            record = self.repo.meta.get("editors", {}).get(sid, {})
            preview = (
                c.ScenarioPreview.model_validate(record["preview"])
                if record.get("hold_id") == hold.id
                else None
            )
            require(
                preview is not None and preview.id == body.preview_id,
                "PREVIEW_STALE",
                "Preview was replaced or is no longer available",
            )
            state.entity_sequence = max(state.entity_sequence, record["sequence"])
            resume = hold.was_running
        if initial and body.decision == "skip":
            self.bump(state, True)
            state.simulation.initial_preview = None
            return Transaction(
                c.InitialResult(simulation=state.simulation, event=None, snapshot=None), states=[state]
            )
        require(not expired(preview.expires_at), "PREVIEW_EXPIRED", "Preview expired", 410)
        require(preview.based_on == state.ref(), "PREVIEW_STALE", "World changed after this preview")
        require(preview.can_commit, "INVALID_REQUEST", "Preview contains no supported executable effect", 400)
        require(
            not any(r.summary.status in {"queued", "active"} for r in state.events.values()),
            "EVENT_ACTIVE",
            "Another major event is pending",
        )
        validate_spec(state, preview.spec)
        if resume:
            self.running_slot(sid)
        previous_ref = state.ref()
        self.bump(state, True)
        self.clear_editor(state)
        state.simulation.initial_preview = None
        plan = (
            ScenarioPlan.model_validate(state.systems.initial_plan)
            if initial and state.systems.initial_plan and state.systems.initial_preview_id == preview.id
            else None
        )
        if plan:
            enable_systems(state)
        snapshot = self.snapshot(state, "pre_event", f"Before {preview.spec.title}", previous_ref)
        event = queue_event(state, preview, snapshot.id, resume)
        if plan:
            attach_plan(state, event.id, plan)
            state.systems.initial_plan = None
        state.simulation.status = "running" if resume else "paused"
        state.simulation.pause_reason = None if resume else "manual"
        cls = c.InitialResult if initial else c.ScenarioResult
        return Transaction(
            cls(simulation=state.simulation, event=event, snapshot=snapshot), 200 if initial else 201, [state]
        )

    def branch(self, owner, sid, body):
        head = self.owned(owner, sid)
        self.ready(head)
        kind = body.source.kind
        revision = head.simulation.revision
        if kind == "revision":
            revision = body.source.revision
        elif kind == "snapshot":
            snapshot = next((s for s in head.snapshots if s.id == body.source.snapshot_id), None)
            require(snapshot is not None, "NOT_FOUND", "Snapshot not found", 404)
            revision = snapshot.ref.revision
        state = self.owned(owner, sid, revision).model_copy(deep=True)
        self.ready(state)
        target = uid("simulation")
        source_ref = state.ref()
        state.simulation.id = target
        state.simulation.name = body.name
        state.simulation.config.name = body.name
        state.simulation.created_at = now()
        state.simulation.parent_simulation_id = sid
        state.simulation.fork_ref = source_ref
        self.bump(state)
        state.simulation.control_version = 0
        state.simulation.status = "paused"
        state.simulation.pause_reason = "loaded"
        state.simulation.archived = False
        state.simulation.achieved_ticks_per_second = 0
        state.simulation.initial_preview = None
        state.simulation.initialization.error = None
        state.lineage_generation += 1
        self.clear_editor(state)
        self.revoke_resume(state)
        if head.systems.enabled and not state.systems.enabled:
            # A control branch from a pre-event snapshot runs the same world systems.
            enable_systems(state)
        for citizen in state.citizens.values():
            citizen.task_generation += 1
            citizen.next_deliberation_tick = state.simulation.tick
        for snapshot in state.snapshots:
            snapshot.simulation_id = target
        # Include checkpoint metadata created in the source at the next revision,
        # when the checkpoint itself points to this selected pre-event revision.
        for snapshot in head.snapshots:
            if snapshot.ref.revision <= revision and not any(s.id == snapshot.id for s in state.snapshots):
                copied = snapshot.model_copy(deep=True)
                copied.simulation_id = target
                state.snapshots.append(copied)
        state.entity_sequence = max(
            [state.entity_sequence, *[int(s.id.rsplit("_", 1)[-1]) for s in state.snapshots]]
        )
        snapshot = self.snapshot(state, "branch", f"Branch from {sid} at revision {revision}")
        return Transaction(
            c.BranchResult(simulation=state.simulation, snapshot=snapshot),
            201,
            [state],
            branches={target: (sid, revision)},
        )

    def delete(self, owner, sid, body):
        state = self.owned(owner, sid)
        require(
            state.simulation.archived and state.simulation.status != "running",
            "INVALID_STATE",
            "Archive the simulation before deleting it",
        )
        require(
            body.confirmation_name == state.simulation.name,
            "INVALID_REQUEST",
            "Confirmation name does not match",
            400,
        )
        return Transaction(c.Deleted(deleted_id=sid), delete=sid)

    async def expire_holds(self):
        while not self.closed:
            await asyncio.sleep(1)
            states = []
            async with self.writer:
                for head in list(self.heads.values()):
                    if head.intervention and expired(head.intervention.expires_at) and not self.repo.degraded:
                        state = head.model_copy(deep=True)
                        self.bump(state, True)
                        self.clear_editor(state)
                        state.auto_resume = False
                        state.simulation.status = "paused"
                        state.simulation.pause_reason = "manual"
                        states.append(state)
            if states:
                await self.persist(states)

    def take_proposals(self, state):
        results = ProviderProposals(self, state)
        for key, result in list(self.provider_results.items()):
            sid, aid = key
            if sid != state.simulation.id:
                continue
            self.provider_results.pop(key, None)
            if self.valid_proposal(state, aid, result):
                results[aid] = result
            else:
                self.discard_proposal(state, aid)
        return results

    def valid_proposal(self, state, aid, result):
        citizen = state.citizens.get(aid)
        return (
            citizen is not None
            and conscious(citizen)
            and result.context_tick <= state.simulation.tick
            and time.monotonic() <= result.expires_at
            and result.tag is not None
            and result.tag == relevance(state, citizen)
        )

    def discard_proposal(self, state, aid):
        self.gateway.diagnostics["discarded"] += 1
        citizen = state.citizens.get(aid)
        if citizen and conscious(citizen):
            citizen.next_deliberation_tick = min(citizen.next_deliberation_tick, state.simulation.tick)

    def prepare_deliberation(self, state):
        if not self.config.gemini_enabled or state.simulation.status != "running":
            return []
        due = sorted(
            (
                citizen
                for citizen in state.citizens.values()
                if conscious(citizen)
                and model_available(state, citizen)
                and citizen.condition.care == "none"
                and not (citizen.condition.episode and citizen.condition.episode.end_tick is None)
                and not citizen.summary.path
                and citizen.next_deliberation_tick <= state.simulation.tick
            ),
            key=lambda citizen: (
                citizen.summary.metrics.safety
                - min(
                    200,
                    max(0, state.simulation.tick - citizen.next_deliberation_tick)
                    * 3
                    * state.simulation.config.tick_seconds
                    / 10,
                )
                - citizen.needs.hunger / 4,
                citizen.summary.id,
            ),
        )
        available = max(
            0,
            self.config.llm_concurrency
            - len([task for task in self.provider_tasks.values() if not task.done()]),
        )
        jobs = []
        for citizen in due[:available]:
            key = (state.simulation.id, citizen.summary.id)
            if key in self.provider_tasks and not self.provider_tasks[key].done():
                continue
            context = context_for(state, citizen)
            if context:
                tag = relevance(state, citizen, context)
                created = state.simulation.tick
                citizen.next_deliberation_tick = state.simulation.tick + legacy_ticks(state, 30)
                jobs.append((key, tag, created, context))
        state.schedules = [entry for entry in state.schedules if entry.get("type") != "deliberation"] + [
            dict(type="deliberation", agent_id=citizen.summary.id, next_tick=citizen.next_deliberation_tick)
            for citizen in state.citizens.values()
        ]
        return jobs

    def schedule_deliberation(self, jobs):
        for key, tag, created, context in jobs:
            self.provider_tasks[key] = asyncio.create_task(self.deliberate(key, tag, created, context))

    async def deliberate(self, key, tag, created, context):
        try:
            intent = await self.gateway.decide(key[0], context)
        except DomainError:
            return
        if intent and key[0] in self.heads:
            head = self.heads[key[0]]
            # Request duration is bounded by Gateway.decide's wall-clock deadline.
            # Delivery gets two physical scheduling intervals (2..10 real seconds),
            # rather than four simulated ticks whose lifetime shrinks at high speed.
            interval = head.simulation.config.tick_seconds / (
                self.config.base_tps * head.simulation.speed_multiplier
            )
            window = min(10, max(2, interval * 2))
            self.provider_results[key] = ProviderResult(tag, created, intent, time.monotonic() + window)

    async def record_usage(self, sid, counts):
        async with self.transactions:
            usage = copy.deepcopy(self.repo.meta["usage"])
            for key in ("global", sid):
                record = usage.setdefault(
                    key, dict(input_tokens=0, output_tokens=0, cached_tokens=0, calls=0, failed_calls=0)
                )
                for name, value in counts.items():
                    record[name] = record.get(name, 0) + value
            if not self.repo.degraded:
                await self.persist([], metadata={"usage": usage})

    def usage(self, owner, sid=None):
        if sid:
            self.owned(owner, sid)
        value = self.repo.meta["usage"].get(
            sid or "global", dict(input_tokens=0, output_tokens=0, cached_tokens=0, calls=0, failed_calls=0)
        )
        require(
            not value.get("usage_unavailable"),
            "SERVICE_UNAVAILABLE",
            "Provider token totals are unavailable because one or more calls returned no usage metadata",
            503,
            reason="Known counts are retained internally; no token usage is fabricated. Reconcile with the provider before relying on a total.",
        )
        return c.Usage(
            simulation_id=sid,
            **{
                key: value.get(key, 0)
                for key in ("input_tokens", "output_tokens", "cached_tokens", "calls", "failed_calls")
            },
            estimated_cost_usd=None,
            pricing_as_of=None,
        )
