"""Application orchestration. Every mutation stages copies, persists, then publishes."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app import contracts as c
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
from app.simulation.engine import list_tree, tick
from app.simulation.game_master import apply_intent, make_intent
from app.simulation.lessons import adopt_drafts, lesson_material
from app.simulation.navigation import cell_at, distance, meeting_point, pathfind
from app.simulation.scenario_scene import CATALOG, matches
from app.simulation.scenarios import compile_preview, generate_map, queue_event, validate_spec
from app.simulation.state import State, expired, expiry, now, uid


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
        self.repo = Repository(config.data_dir)
        self.heads = {
            sid: self.repo.read(sid) for sid, entries in self.repo.meta["simulations"].items() if entries
        }
        self.writer = asyncio.Lock()
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
        self.stats = {"ticks": 0, "tick_seconds": [], "commit_seconds": [], "fallbacks": 0, "socket_bytes": 0}
        self.tiger = TigerIngestor(self)

    async def start(self):
        # Recovery adds a new revision; existing committed history is never rewritten.
        for sid, head in list(self.heads.items()):
            if head.simulation.status == "initializing":
                self.initializers[sid] = asyncio.create_task(self.initialize(sid))
                continue
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
        self.tiger.start()

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
        await self.gateway.close()
        await self.tiger.close()
        self.repo.close()

    def owned(self, owner, sid, revision=None):
        head = self.heads.get(sid)
        require(head is not None and head.owner_id == owner, "NOT_FOUND", "Simulation not found", 404)
        if revision is None:
            return head
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

    async def persist(self, states, **kwargs):
        start = time.perf_counter()
        try:
            await asyncio.to_thread(self.repo.commit, states, **kwargs)
        except (OSError, ValueError) as error:
            if not self.repo.degraded:
                self.repo.degraded.append("Persistence commit failed; mutations halted")
            raise DomainError(
                "PERSISTENCE_UNAVAILABLE", "Commit failed; last durable state remains available", 503
            ) from error
        self.stats["commit_seconds"].append(time.perf_counter() - start)
        self.stats["commit_seconds"] = self.stats["commit_seconds"][-1000:]
        for state in states:
            self.heads[state.simulation.id] = state
            self.schedule_lessons(state)
        self.tiger.notify()

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
        async with self.writer:
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
                result = operation()
                data = (
                    result.data.model_dump(mode="json") if isinstance(result.data, c.Model) else result.data
                )
                response = {"schema_version": "1.0.0", "request_id": key, "data": data}
                saved = {"fingerprint": fingerprint, "response": response, "status": result.status}
                await self.persist(
                    result.states,
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
                            home = homes[i % len(homes)].entrance
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
                            citizen.next_deliberation_tick = i % 8
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
        try:
            while not self.closed:
                head = self.heads.get(sid)
                if not head or head.simulation.status != "running" or self.repo.degraded:
                    return
                interval = 1 / (self.config.base_tps * head.simulation.speed_multiplier)
                await asyncio.sleep(max(0, interval - (time.perf_counter() - last)))
                async with self.writer:
                    async with self.locks.setdefault(sid, asyncio.Lock()):
                        head = self.heads.get(sid)
                        if not head or head.simulation.status != "running":
                            return
                        started = time.perf_counter()
                        state = head.model_copy(deep=True)
                        self.bump(state)
                        elapsed = started - last
                        state.simulation.achieved_ticks_per_second = 1 / elapsed if elapsed > 0 else 0
                        proposals = self.take_proposals(state)
                        start = time.perf_counter()
                        await asyncio.to_thread(tick, state, proposals)
                        self.stats["tick_seconds"].append(time.perf_counter() - start)
                        self.stats["tick_seconds"] = self.stats["tick_seconds"][-1000:]
                        self.stats["ticks"] += 1
                        if (
                            self.repo.settings(state.owner_id).autosave
                            and state.simulation.tick % self.config.autosave_interval == 0
                        ):
                            self.snapshot(state, "autosave", "Periodic autosave")
                        jobs = self.prepare_deliberation(state)
                        await self.persist([state])
                        # Cadence includes compute/commit time; overloaded runs report
                        # their actual start interval instead of a nominal speed.
                        last = started
                self.schedule_deliberation(jobs)
        except (asyncio.CancelledError, DomainError):
            return
        except Exception as error:
            # A domain bug must stop this runner without publishing its staged tick.
            async with self.writer:
                head = self.heads.get(sid)
                if head and not self.repo.degraded and not self.closed:
                    state = head.model_copy(deep=True)
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
                    await self.persist([state])

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
                    and state.simulation.tick % self.config.autosave_interval == 0
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
        elif cmd.type == "override_agent":
            self.ready(state, True)
            require(
                state.intervention is None,
                "INTERVENTION_OPEN",
                "Close the editor before overriding a citizen",
            )
            citizen = state.citizens.get(cmd.agent_id)
            require(citizen is not None, "NOT_FOUND", "Citizen not found", 404)
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
                        expires_tick=state.simulation.tick + 30,
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
            reasons = engine["unsupported"] or [engine["clarification"] or "This scenario cannot be simulated."]
            preview.can_commit = False
            preview.unsupported_requests = [r[:2000] for r in reasons]
            preview.interpretation = (
                engine["clarification"] or "The scenario engine cannot represent this request: " + "; ".join(reasons)
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
            async with self.writer:
                for head in list(self.heads.values()):
                    if head.intervention and expired(head.intervention.expires_at) and not self.repo.degraded:
                        state = head.model_copy(deep=True)
                        self.bump(state, True)
                        self.clear_editor(state)
                        state.auto_resume = False
                        state.simulation.status = "paused"
                        state.simulation.pause_reason = "manual"
                        await self.persist([state])

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
            and citizen.summary.active
            and result.context_tick <= state.simulation.tick
            and time.monotonic() <= result.expires_at
            and result.tag is not None
            and result.tag == relevance(state, citizen)
        )

    def discard_proposal(self, state, aid):
        self.gateway.diagnostics["discarded"] += 1
        citizen = state.citizens.get(aid)
        if citizen and citizen.summary.active:
            citizen.next_deliberation_tick = min(citizen.next_deliberation_tick, state.simulation.tick)

    def prepare_deliberation(self, state):
        if not self.config.gemini_enabled or state.simulation.status != "running":
            return []
        due = sorted(
            (
                citizen
                for citizen in state.citizens.values()
                if citizen.summary.active
                and not citizen.summary.path
                and citizen.next_deliberation_tick <= state.simulation.tick
            ),
            key=lambda citizen: (
                citizen.summary.metrics.safety
                - min(200, max(0, state.simulation.tick - citizen.next_deliberation_tick) * 3)
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
                citizen.next_deliberation_tick = state.simulation.tick + 30
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
            interval = 1 / (self.config.base_tps * head.simulation.speed_multiplier)
            window = min(10, max(2, interval * 2))
            self.provider_results[key] = ProviderResult(tag, created, intent, time.monotonic() + window)

    async def record_usage(self, sid, counts):
        async with self.writer:
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
