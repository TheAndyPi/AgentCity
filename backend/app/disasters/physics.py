"""Durable, deterministic damage. Only the physical engine invokes advance()."""

import hashlib
import math

from app.contracts import Vec2
from app.disasters.geometry import center_at, envelope, exposure, footprint_exposure, intersects
from app.disasters.models import LIMITS, Condition, DamageRecord, Reaction, TerrainDamage
from app.simulation.navigation import PERSONAL_SPACE, cell_at, distance, polygon_contains

STRUCTURAL_RATES = {"earthquake": 5.0, "tornado": 4.0, "flood": 1.5, "fire": 5.0, "storm": 1.5}
INJURY_RATES = {"earthquake": 1.0, "tornado": 2.0, "flood": 1.0, "fire": 2.0, "storm": 0.5}


def initialize(state):
    if not state.map:
        return
    for b in state.map.buildings:
        if b.id not in state.conditions:
            saved = next(
                (
                    r.infrastructure_before[b.id]
                    for r in sorted(state.events.values(), key=lambda r: r.summary.queued_tick)
                    if r.summary.status == "active" and b.id in r.infrastructure_before
                ),
                None,
            )
            state.conditions[b.id] = Condition(
                design_capacity=saved["capacity"]
                if saved
                else state.systems.base_capacity.get(b.id, b.capacity),
                baseline_functional=saved["functional"]
                if saved
                else (True if b.id in state.systems.closed_by else b.functional),
            )
            # Recover active temporary scenario controls from older checkpoints.
            for entry in state.systems.schedule:
                if (
                    entry.action == "revert"
                    and entry.op.get("type") == "set_service_availability"
                    and b.id in entry.undo
                ):
                    state.systems.service_controls.setdefault(b.id, {})[
                        f"{entry.event_id}:{entry.op['id']}"
                    ] = dict(
                        event_id=entry.event_id,
                        open=entry.op["open"],
                        capacity_multiplier=entry.op.get("capacity_multiplier", 1),
                    )


def effective_services(state):
    initialize(state)
    for b in state.map.buildings:
        c = state.conditions[b.id]
        multipliers = [1.0]
        closed = not c.baseline_functional or c.integrity < 50
        controls = list(state.systems.service_controls.get(b.id, {}).values())
        closed |= any(not control["open"] for control in controls) or (
            not controls and b.id in state.systems.closed_by
        )
        service_multiplier = min((control["capacity_multiplier"] for control in controls), default=1.0)
        policy_multiplier = 1.0
        if state.systems.enabled and b.kind == "hospital":
            from app.scenario_engine.mutations import funding_level

            policy_multiplier = 0.6 + 0.4 * funding_level(state)
        design_capacity = (
            max(1, round(c.design_capacity * policy_multiplier * service_multiplier))
            if state.systems.enabled
            else c.design_capacity
        )
        for runtime in state.events.values():
            if runtime.summary.status != "active":
                continue
            for effect in runtime.spec.effects:
                if effect.type == "infrastructure" and intersects(b.footprint, runtime.spec.affected_polygon):
                    multipliers.append(effect.capacity_multiplier)
                    closed |= not effect.functional
        before = dict(functional=b.functional, capacity=b.capacity)
        b.functional = not closed
        b.capacity = 0 if closed else math.floor(design_capacity * c.integrity / 100 * min(multipliers))
        after = dict(functional=b.functional, capacity=b.capacity)
        if before != after:
            state.service_changes.append(
                dict(
                    id=state.next_id("service"),
                    building_id=b.id,
                    tick=state.simulation.tick,
                    revision=state.simulation.revision,
                    sim_time_seconds=state.simulation.sim_time_seconds,
                    before=before,
                    after=after,
                    integrity=c.integrity,
                    cause_ids=c.cause_ids.copy(),
                    active_closure_ids=list(
                        dict.fromkeys(
                            [
                                r.summary.id
                                for r in state.events.values()
                                if r.summary.status == "active"
                                and any(e.type == "infrastructure" for e in r.spec.effects)
                                and intersects(b.footprint, r.spec.affected_polygon)
                            ]
                            + [control["event_id"] for control in controls if not control["open"]]
                            + ([state.systems.closed_by[b.id]] if b.id in state.systems.closed_by else [])
                        )
                    ),
                )
            )
            hospital = state.behavior.hospitals.get(b.id)
            if hospital:
                from app.behavior.vitals import detach, emit, living

                occupied = {
                    c.summary.id
                    for c in state.citizens.values()
                    if living(c) and c.inside_building_id == b.id
                }
                remaining = max(0, b.capacity - len(occupied | set(hospital.patients))) if b.functional else 0
                for patient_id in sorted(list(hospital.reservations))[remaining:]:
                    patient = state.citizens.get(patient_id)
                    if patient:
                        detach(state, patient)
                        emit(
                            state,
                            "care_cancelled",
                            patient,
                            description="Disaster service capacity no longer supports the hospital claim",
                        )


def record_loss(state, runtime, entity_id, before, amount, local, units):
    amount = max(0, min(before, amount))
    if amount <= 1e-8:
        return before
    after = max(0, round(before - amount, 6))
    state.damage_records.append(
        DamageRecord(
            id=state.next_id("damage"),
            event_id=runtime.summary.id,
            entity_id=entity_id,
            tick=state.simulation.tick,
            revision=state.simulation.revision,
            sim_time_seconds=state.simulation.sim_time_seconds,
            exposure=local,
            before=before,
            after=after,
            units=units,
        )
    )
    return after


def structural_loss(state, runtime, building, amount, local):
    """Exact actual-loss primitive: 80 - 5 = 75, with one evidence record."""
    initialize(state)
    condition = state.conditions[building.id]
    before = condition.integrity
    condition.integrity = record_loss(state, runtime, building.id, before, amount, local, "integrity")
    if before != condition.integrity and runtime.summary.id not in condition.cause_ids:
        condition.cause_ids.append(runtime.summary.id)
    return before != condition.integrity


def reaction(state, runtime, citizen, local, acute=False):
    from app.behavior.vitals import conscious

    if not conscious(citizen) or citizen.needs.health <= 0 or citizen.needs.fatigue >= 100:
        return
    if local < 0.65 and not acute:
        return
    episode = f"{runtime.summary.id}:{citizen.summary.id}"
    previous = state.reaction_cooldowns.get(episode, -1e9)
    if state.simulation.sim_time_seconds - previous < 30:
        return
    profile = citizen.profile
    risk = profile.traits.risk_tolerance
    digest = (
        hashlib.sha256(
            f"{runtime.physical.seed}:{episode}:{state.simulation.tick}:reactions-1".encode()
        ).digest()[0]
        / 255
    )
    if risk >= 75 and digest < 0.65 and not acute:
        return
    empathetic = profile.traits.empathy >= 60 or profile.traits.cooperation >= 60
    kind = "warning" if empathetic else "scream" if risk < 45 or digest < 0.5 else "help"
    text = {
        "scream": "Aah! Help!",
        "help": "Help! I need help!",
        "warning": "Watch out! Get away from the danger!",
    }[kind]
    source = Reaction(
        id=state.next_id("reaction"),
        event_id=runtime.summary.id,
        agent_id=citizen.summary.id,
        tick=state.simulation.tick,
        revision=state.simulation.revision,
        sim_time_seconds=state.simulation.sim_time_seconds,
        position=citizen.summary.position.model_copy(),
        threat=local,
        kind=kind,
        text=text,
        episode_id=episode,
        evidence_ids=[
            r.id
            for r in state.damage_records[-20:]
            if r.event_id == runtime.summary.id
            and r.entity_id in {citizen.summary.id, citizen.inside_building_id}
        ],
    )
    state.reactions.append(source)
    state.reaction_cooldowns[episode] = state.simulation.sim_time_seconds


def reconcile_occupants(state):
    """Keep people inside unsafe rooms until a legal doorway egress exists.

    No remote relocation. A blocked approach leaves a persistent rescue need.
    Existing safe beds are retained when capacity falls; no new admission.
    """
    blocked = {(t.col, t.row) for t in state.terrain_damage.values() if t.blocked}
    from app.behavior.vitals import conscious, detach, living

    for citizen in state.citizens.values():
        if not living(citizen):
            citizen.trapped_building_id = None
            continue
        bid = citizen.inside_building_id
        if not bid or state.conditions[bid].integrity >= 50:
            continue
        building = next(b for b in state.map.buildings if b.id == bid)
        # An unsafe room cannot retain canonical beds/claims or move a patient as
        # an ordinary actor. Detachment drops carried patients at actual positions.
        if citizen.condition.care != "none" or citizen.condition.patient_id:
            detach(state, citizen)
        cell = cell_at(state.map, building.entrance)
        clear = cell and cell.walkable and (cell.col, cell.row) not in blocked
        clear = clear and all(
            distance(building.entrance, c.summary.position) >= PERSONAL_SPACE
            for c in state.citizens.values()
            if c is not citizen and c.summary.active
        )
        if clear and citizen.leaving_building_id == bid and citizen.summary.path:
            citizen.trapped_building_id = None
            continue
        if clear and conscious(citizen) and citizen.needs.health > 0 and citizen.needs.fatigue < 100:
            from app.simulation.building_visits import doorway

            citizen.summary.path = [doorway(building), building.entrance.model_copy()]
            citizen.leaving_building_id = bid
            citizen.entering_building_id = None
            citizen.trapped_building_id = None
        else:
            citizen.trapped_building_id = bid
            citizen.summary.path = []


def finish_repairs(state):
    for job in state.repairs:
        if job.status != "pending" or state.simulation.tick < job.finish_tick:
            continue
        b = next(b for b in state.map.buildings if b.id == job.building_id)
        occupied = any(
            b.id
            in {c.inside_building_id, c.entering_building_id, c.leaving_building_id, c.trapped_building_id}
            for c in state.citizens.values()
        )
        active = any(
            r.summary.status in {"queued", "active"} and intersects(b.footprint, r.spec.affected_polygon)
            for r in state.events.values()
        )
        if (occupied and job.action == "repair") or active:
            job.status = "blocked"
            continue
        if job.action == "repair":
            state.conditions[b.id].integrity = min(100, state.conditions[b.id].integrity + 25)
        job.after = state.conditions[b.id].integrity
        job.status = "completed"
        # A repair clears only debris attributed to this building. Terrain damage
        # with another cause remains a separate obstruction.
        for key, t in list(state.terrain_damage.items()):
            if f"building:{b.id}" in t.cause_ids:
                t.cause_ids.remove(f"building:{b.id}")
                if not any(c.startswith("building:") for c in t.cause_ids):
                    t.blocked = False
        for c in state.citizens.values():
            c.summary.path = []
            c.plan = None
            c.task_generation += 1


def advance(state):
    initialize(state)
    changed = False
    dt = state.simulation.config.tick_seconds / 5  # rates per five simulation seconds
    for runtime in state.events.values():
        p = runtime.physical
        if not p or runtime.summary.status != "active" or runtime.last_physical_tick == state.simulation.tick:
            continue
        runtime.last_physical_tick = state.simulation.tick
        elapsed = state.simulation.tick - runtime.summary.start_tick
        polygon = runtime.spec.affected_polygon
        for b in state.map.buildings:
            local = footprint_exposure(p, b.footprint, elapsed, polygon)
            if not local:
                continue
            # Squared normalized exposure, deterministic construction resistance.
            before_stage = state.conditions[b.id].stage
            structural_loss(
                state,
                runtime,
                b,
                STRUCTURAL_RATES[p.kind] * local**2 * dt / state.conditions[b.id].resistance,
                local,
            )
            changed |= before_stage != state.conditions[b.id].stage
            if state.conditions[b.id].integrity < 50 and before_stage != state.conditions[b.id].stage:
                radius = 3 if state.conditions[b.id].integrity == 0 else 1.5
                for cell in state.map.cells:
                    point = Vec2(
                        x=(cell.col + 0.5) * state.map.cell_size_m, y=(cell.row + 0.5) * state.map.cell_size_m
                    )
                    if (
                        cell.walkable
                        and distance(point, b.entrance) <= radius
                        and polygon_contains(point, polygon)
                    ):
                        key = f"{cell.col}:{cell.row}"
                        terrain = state.terrain_damage.setdefault(
                            key, TerrainDamage(col=cell.col, row=cell.row, stage="rubble", blocked=True)
                        )
                        terrain.blocked = True
                        for cause in (runtime.summary.id, f"building:{b.id}"):
                            if cause not in terrain.cause_ids:
                                terrain.cause_ids.append(cause)
        for resource in state.map.resources:
            local = exposure(p, resource.position, elapsed, polygon)
            resource.available_units = record_loss(
                state,
                runtime,
                resource.id,
                resource.available_units,
                min(resource.available_units, local**2 * dt * 2),
                local,
                "stock",
            )
        # Sparse durable terrain state; base map cells are never rewritten.
        for cell in state.map.cells:
            if cell.terrain == "water":
                continue
            point = Vec2(
                x=(cell.col + 0.5) * state.map.cell_size_m, y=(cell.row + 0.5) * state.map.cell_size_m
            )
            local = exposure(p, point, elapsed, polygon)
            if local < 0.25:
                continue
            key = f"{cell.col}:{cell.row}"
            terrain = state.terrain_damage.setdefault(
                key,
                TerrainDamage(
                    col=cell.col,
                    row=cell.row,
                    stage={
                        "fire": "charred",
                        "flood": "water damaged",
                        "earthquake": "cracked",
                        "tornado": "debris",
                        "storm": "wind damaged",
                    }[p.kind],
                    blocked=False,
                ),
            )
            if runtime.summary.id not in terrain.cause_ids:
                terrain.cause_ids.append(runtime.summary.id)
        for citizen in state.citizens.values():
            if not citizen.summary.active or citizen.needs.health <= 0:
                continue
            local = exposure(p, citizen.summary.position, elapsed, polygon)
            if not local:
                continue
            protection = 0.4 if citizen.inside_building_id else 1.0
            acute = bool(
                citizen.inside_building_id and state.conditions[citizen.inside_building_id].integrity < 50
            )
            if acute:
                protection = 1.4
            after_health = record_loss(
                state,
                runtime,
                citizen.summary.id,
                citizen.needs.health,
                INJURY_RATES[p.kind] * local**2 * dt * protection,
                local,
                "health",
            )
            if citizen.summary.id not in runtime.cohort:
                runtime.cohort.append(citizen.summary.id)
                citizen.major_event_ids.append(runtime.summary.id)
            from app.simulation.agents import evidence, metric_delta, remember

            proof = evidence("Local physical disaster exposure", event_ids=[runtime.summary.id])
            from app.behavior.vitals import evaluate, impact, living

            impact(
                state,
                citizen,
                "health",
                after_health - citizen.needs.health,
                "Local physical disaster exposure",
                "disaster",
                proof,
            )
            evaluate(state, citizen, "Local physical disaster exposure", proof)
            if not living(citizen):
                continue
            metric_delta(citizen, "stress", local * dt * 2, proof)
            if not any(m.evidence and runtime.summary.id in m.evidence.event_ids for m in citizen.memories):
                remember(
                    state,
                    citizen,
                    f"I encountered {p.kind} at this location; damaged routes may be unsafe.",
                    importance=85,
                    proof=proof,
                )
            reaction(state, runtime, citizen, local, acute)
        runtime.summary.affected_agent_count = len(runtime.cohort)
    finish_repairs(state)
    effective_services(state)
    if changed:
        for citizen in state.citizens.values():
            if not citizen.leaving_building_id:
                citizen.summary.path = []
            citizen.plan = None
            citizen.task_generation += 1
    reconcile_occupants(state)


def event_view(state, runtime):
    p = runtime.physical
    elapsed = max(0, state.simulation.tick - (runtime.summary.start_tick or state.simulation.tick))
    current = (
        envelope(p, state.map, center_at(p, elapsed))
        if p.kind == "tornado"
        else runtime.spec.affected_polygon
    )
    return dict(
        id=runtime.summary.id,
        phase="cancel" if runtime.cancelled else runtime.summary.status,
        phase_id=f"{runtime.summary.id}:{'cancel' if runtime.cancelled else runtime.summary.status}",
        legacy_projection=runtime.physical_legacy,
        parameters=p.model_dump(),
        normalized_intensity=p.normalized,
        unit=LIMITS[p.kind]["unit"],
        start_tick=runtime.summary.start_tick,
        end_tick=runtime.summary.end_tick,
        footprint=[v.model_dump() for v in runtime.spec.affected_polygon],
        current_footprint=[v.model_dump() for v in current] if runtime.summary.status == "active" else [],
        current_origin=center_at(p, elapsed).model_dump(),
        exposure_count=len(runtime.cohort),
        damage_ids=[r.id for r in state.damage_records if r.event_id == runtime.summary.id],
    )


def view(state):
    from app.behavior.vitals import conscious, living

    return dict(
        schema_version="2.0.0",
        rule_version="disasters-2.0.0",
        simulation_id=state.simulation.id,
        ref=state.ref().model_dump(),
        sim_time_seconds=state.simulation.sim_time_seconds,
        events=[event_view(state, r) for r in state.events.values() if r.physical],
        service_changes=state.service_changes,
        vocal_states={
            aid: dict(
                alive=living(c) and c.needs.health > 0,
                conscious=conscious(c) and c.needs.health > 0 and c.needs.fatigue < 100,
            )
            for aid, c in state.citizens.items()
        },
        conditions={bid: dict(**c.model_dump(), stage=c.stage) for bid, c in state.conditions.items()},
        terrain=[t.model_dump() for t in state.terrain_damage.values()],
        damage=[d.model_dump() for d in state.damage_records],
        reactions=[r.model_dump() for r in state.reactions[-100:]],
        repairs=[r.model_dump() for r in state.repairs],
        rescue_needs=[
            dict(agent_id=c.summary.id, building_id=c.trapped_building_id)
            for c in state.citizens.values()
            if c.trapped_building_id and living(c)
        ],
    )
