"""Seeded town construction and bounded, typed event compilation/lifecycle."""

import random
import re
from statistics import mean

from app.contracts import (
    Building,
    Cell,
    Consequence,
    EventReport,
    EventSpec,
    EventSummary,
    InformationEffect,
    MapData,
    MetricDeltas,
    Metrics,
    ResourceSource,
    ScenarioPreview,
    Vec2,
    Zone,
)
from app.infrastructure.errors import require
from app.simulation.agents import clamp, evidence, hazard_severity, metric_delta, remember
from app.simulation.navigation import polygon_contains, simple_polygon
from app.simulation.scenario_scene import CATALOG, affirmed_mentions, build_scene, matches
from app.simulation.state import EventRuntime, expiry


def rectangle(x0, y0, x1, y1):
    return [Vec2(x=x0, y=y0), Vec2(x=x1, y=y0), Vec2(x=x1, y=y1), Vec2(x=x0, y=y1)]


def generate_map(state, rng):
    config = state.simulation.config
    metrics = Metrics(
        happiness=60, safety=100, trust=config.environment.initial_community_trust, resources=50, stress=20
    )
    zones = [
        Zone(
            id=f"zone_{x}_{y}",
            name=f"{'North' if y else 'South'}{'east' if x else 'west'}",
            polygon=rectangle(x * 64, y * 64, (x + 1) * 64, (y + 1) * 64),
            metrics=metrics.model_copy(),
            population=0,
            population_density_per_km2=0,
        )
        for y in range(2)
        for x in range(2)
    ]
    cells = []
    for row in range(64):
        for col in range(64):
            road = col % 8 == 0 or row % 8 == 0
            water = col >= 60 and row % 16 != 0
            cells.append(
                Cell(
                    col=col,
                    row=row,
                    elevation_m=rng.uniform(0, 2),
                    terrain="water" if water else "road" if road else "land",
                    walkable=not water,
                    zone_id=f"zone_{col // 32}_{row // 32}",
                )
            )
    urban = config.environment.settlement == "urban"
    density = config.environment.population_density
    lots_per_block = 2 + int(density >= 40) + int(urban or density >= 80)
    # Four separate lots per block leave a shared green courtyard and clear
    # approaches to the surrounding streets. The narrow waterfront fits two.
    sites = []
    for row in range(0, 57, 8):
        for col in range(0, 57, 8):
            lots = [0, 2] if col == 56 else list(range(4))
            rng.shuffle(lots)
            for lot in lots[:lots_per_block]:
                dx, dy = (2 if lot % 2 == 0 else 5), (2 if lot < 2 else 5)
                entrance = (
                    Vec2(x=col * 2 + 1, y=(row + dy) * 2 + 1)
                    if lot % 2 == 0
                    else Vec2(x=(col + 8) * 2 + 1, y=(row + dy) * 2 + 1)
                )
                sites.append((col + dx, row + dy, entrance))
    sites.sort(key=lambda p: (abs(p[0] - 32) + abs(p[1] - 32), p[0], p[1]))
    intimate = config.population <= 10
    if intimate:
        # Ten households and the shared amenities fit into a few central blocks.
        # Keep the navigable map extent for existing event/replay geometry.
        sites = sites[:24]
    street_names = ["Maple", "Cedar", "Willow", "Aster", "Harbor", "Oak", "Juniper", "Birch"]
    mixed_use = ["home", "work", "home", "shop", "home", "work", "home", "community"]
    buildings = []
    for i, (col, row, entrance) in enumerate(sites):
        kind = ["shelter", "hospital", "community"][i] if i < 3 else mixed_use[(i - 3) % len(mixed_use)]
        street = street_names[i % len(street_names)]
        purpose = {
            "home": "Apartments" if urban or i % 3 else "Townhouse",
            "work": "Company Offices" if i % 2 else "Studio Offices",
            "shop": "Restaurant" if (i // len(mixed_use)) % 2 else "Market",
            "shelter": "Emergency Shelter",
            "hospital": "Hospital",
            "community": "Community Center",
        }[kind]
        heights = {
            "home": (9, 18) if urban else (5, 11),
            "work": (12, 22) if urban else (8, 15),
            "shop": (3.5, 5),
            "shelter": (4, 6),
            "hospital": (8, 11),
            "community": (5, 8),
        }
        if intimate:
            heights = {key: (3.2, 5.2) for key in heights}
            if kind == "home":
                purpose = "Cottage"
        footprint = rectangle(col * 2, row * 2, (col + 2) * 2, (row + 2) * 2)
        for dy in range(2):
            for dx in range(2):
                cells[(row + dy) * 64 + col + dx].walkable = False
        buildings.append(
            Building(
                id=state.next_id("building"),
                name=f"{street} {purpose} {i + 1}",
                kind=kind,
                footprint=footprint,
                entrance=entrance,
                height_m=round(rng.uniform(*heights[kind]), 2),
                capacity=max(
                    1,
                    round(
                        (100 if kind == "shelter" else 8)
                        * (0.5 + config.environment.infrastructure_capacity / 100)
                    ),
                ),
                occupancy=0,
                functional=True,
            )
        )
    resources = []
    for col, row in (
        [(24, 32), (32, 24), (32, 32), (40, 32)] if intimate else [(16, 16), (32, 16), (16, 32), (48, 48)]
    ):
        for k, kind in enumerate(("food", "water", "supplies")):
            resources.append(
                ResourceSource(
                    id=state.next_id("resource"),
                    kind=kind,
                    position=Vec2(x=col * 2 + 1 + k * 0.6, y=row * 2 + 1),
                    available_units=100 + config.environment.resource_availability * 4,
                )
            )
    return MapData(
        id=state.next_id("map"),
        seed=config.seed,
        width_m=128,
        height_m=128,
        cell_size_m=2,
        columns=64,
        rows=64,
        cells=cells,
        zones=zones,
        buildings=buildings,
        resources=resources,
    )


def validate_spec(state, spec):
    require(
        simple_polygon(spec.affected_polygon),
        "INVALID_REQUEST",
        "Event polygon must be simple with positive area",
        400,
    )
    for point in [spec.origin, *spec.affected_polygon]:
        require(
            0 <= point.x <= state.map.width_m and 0 <= point.y <= state.map.height_m,
            "INVALID_REQUEST",
            "Event geometry is outside the map",
            400,
        )
    require(bool(spec.effects), "INVALID_REQUEST", "Event has no supported effects", 400)
    for prop in spec.scene:
        require(
            0 <= prop.position.x <= state.map.width_m
            and 0 <= prop.position.y <= state.map.height_m
            and polygon_contains(prop.position, spec.affected_polygon),
            "INVALID_REQUEST",
            "Scene object must be inside the affected map region",
            400,
        )


def preset(state, kind, policy=None, prompt=""):
    text = prompt.lower()
    polygon = rectangle(0, 0, state.map.width_m, state.map.height_m)
    if kind in {"flood", "fire", "storm"}:
        # Leave safe facilities outside a default hazard's reach. An explicit
        # citywide prompt can still deliberately test a citywide emergency.
        polygon = rectangle(0, 0, state.map.width_m / 2, state.map.height_m * 0.5625)
    if "north" in text:
        polygon = rectangle(0, 64, 128, 128)
    elif "east" in text:
        polygon = rectangle(64, 0, 128, 128)
    elif "west" in text:
        polygon = rectangle(0, 0, 64, 128)
    elif "south" in text:
        polygon = rectangle(0, 0, 128, 64)
    elif any(term in text for term in ("whole city", "entire city", "citywide")):
        polygon = rectangle(0, 0, 128, 128)
    severity = 50
    severity_match = re.search(r"severity\s*[:=]?\s*(\d+(?:\.\d+)?)", text)
    if severity_match:
        severity = float(severity_match[1])
    elif any(word in text for word in ("severe", "major", "extreme")):
        severity = 85
    elif any(word in text for word in ("mild", "minor", "small")):
        severity = 25
    match = re.search(r"(?:for\s+)?(\d+)\s*ticks?", text)
    duration = int(match[1]) if match else 12
    effects = {
        "flood": [dict(type="hazard", hazard="flood", severity=severity)],
        "fire": [dict(type="hazard", hazard="fire", severity=severity)],
        "storm": [dict(type="hazard", hazard="storm", severity=severity)],
        "shortage": [dict(type="resource_multiplier", resource="food", multiplier=0.4)],
        "outage": [dict(type="infrastructure", functional=False, capacity_multiplier=0)],
        "misinformation": [
            dict(
                type="information",
                message=prompt[:2000] or "An unverified warning about the local supply depot is circulating.",
                reliability=25,
                delivery="local",
            )
        ],
        "festival": [dict(type="community", activity="festival", capacity=state.simulation.agent_count)],
        "policy": [
            dict(
                type="policy",
                **(
                    policy.model_dump()
                    if policy
                    else dict(evacuation_order=True, ration_units_per_agent=2, aid_multiplier=1.5)
                ),
            )
        ],
        "custom": [],
    }
    if kind == "policy":
        polygon = rectangle(0, 0, 128, 128)
    origin = Vec2(x=mean(p.x for p in polygon), y=mean(p.y for p in polygon))
    return EventSpec(
        title=f"{kind.title()} intervention",
        description=prompt[:2000] or f"A bounded {kind} scenario",
        kind=kind,
        origin=origin,
        affected_polygon=polygon,
        severity=severity,
        duration_ticks=duration,
        effects=effects[kind],
        success_condition="duration_elapsed",
    )


def unsupported_physical_requests(description):
    """Building geometry/lifecycle changes have no corresponding simulation effect."""
    buildings = r"\b(?:hospitals?|buildings?|houses?|homes?|shelters?|schools?|bridges?|towers?|offices?)\b"
    actions = {
        "destruction": (
            "destroy",
            "destroys",
            "destroyed",
            "destroying",
            "demolish",
            "demolishes",
            "demolished",
            "demolishing",
            "raze",
            "razes",
            "razed",
            "razing",
            "collapse",
            "collapses",
            "collapsed",
            "collapsing",
            "burn down",
            "burns down",
            "burned down",
            "blow up",
            "blows up",
            "blown up",
            "tear down",
            "torn down",
        ),
        "construction": (
            "build",
            "builds",
            "built",
            "construct",
            "constructs",
            "constructed",
            "constructing",
            "construction",
            "erect",
            "erects",
            "erected",
            "erecting",
            "rebuild",
            "rebuilds",
            "rebuilt",
            "rebuilding",
        ),
    }
    clauses = re.split(r"[.!?;\n]", description.lower())
    unsupported = []
    for kind, verbs in actions.items():
        if any(
            re.search(buildings, clause)
            and (
                any(affirmed_mentions(clause, verb) for verb in verbs)
                or (kind == "construction" and re.search(r"\bbuilding\s+(?:a|an|the|new|another)\b", clause))
            )
            for clause in clauses
        ):
            unsupported.append(
                f"Building {kind} is unsupported; scene illustrations do not alter city buildings."
            )
    return unsupported


def compile_preview(state, source, prompt=None, source_event_id=None, policy=None, design=None):
    unsupported = []
    warnings = []
    recipes = []
    if source == "repeat":
        runtime = state.events.get(source_event_id)
        require(
            runtime is not None and runtime.summary.status == "resolved",
            "INVALID_REQUEST",
            "Repeat requires a resolved event in this history",
            400,
        )
        spec = runtime.spec.model_copy(deep=True)
    elif source == "policy":
        spec = preset(state, "policy", policy)
    elif source == "random":
        # Context keyed: preview creation never advances the world's physical RNG.
        rng = random.Random(
            f"{state.simulation.config.seed}:{state.simulation.revision}:{state.entity_sequence}"
        )
        recipe = rng.choice([r for r in CATALOG if r["id"] != "policy"])
        prompt = f"Unexpected {recipe['terms'][0]} in the neighborhood"
        recipes = [recipe]
        spec = preset(state, recipe["kind"], prompt=prompt)
        spec.title = prompt[:80]
    else:
        text = (prompt or "").lower()
        recipes = matches(text)
        kinds = [r["kind"] for r in recipes]
        spec = preset(state, kinds[0] if kinds else "custom", prompt=prompt or "")
        # Keep every custom premise as citizen-visible world context. Familiar
        # mechanics can accompany it, but a keyword list never gates an event.
        premise = (prompt or "").strip()
        require(bool(premise), "INVALID_REQUEST", "Describe an event first", 400)
        spec.title = " ".join(premise.split())[:80].strip()
        if not kinds and not any(word in text for word in ("north", "east", "west", "south")):
            spec.affected_polygon = rectangle(0, 0, state.map.width_m, state.map.height_m)
            spec.origin = Vec2(x=state.map.width_m / 2, y=state.map.height_m / 2)
        if not recipes and not (design and design.parts):
            warnings.append(
                "This premise is represented by a labeled abstract landmark. Citizens can remember and "
                "discuss it; physical changes beyond the listed effects are not simulated. "
                "Add details such as a market, visitors, wildlife or weather for specific effects."
            )
    if source not in {"repeat", "policy"}:
        # Compose recipes without multiplying duplicate effects from overlapping phrases.
        effects = []
        for recipe in recipes:
            for raw in recipe["effects"]:
                effect = dict(raw)
                if effect["type"] == "hazard":
                    effect["severity"] = spec.severity
                if effect["type"] == "community":
                    effect["capacity"] = state.simulation.agent_count
                if effect not in effects:
                    effects.append(effect)
        effects = effects[:19]
        effects.append(
            InformationEffect(
                type="information",
                message=spec.description,
                reliability=25 if any(r["id"] == "misinformation" for r in recipes) else 100,
                delivery="local",
            ).model_dump()
        )
        spec = EventSpec.model_validate({**spec.model_dump(), "effects": effects[:20]})
    unsupported = unsupported_physical_requests(spec.description)
    if unsupported:
        warnings.extend(unsupported)
        limitation = (
            "This is a narrative illustration. Existing buildings are not destroyed and new buildings are "
            "not constructed; only the listed simulation effects apply."
        )
        # Keep the original request in description for editing/repeat, but never
        # turn its unsupported physical premise into an observed world fact.
        message = f"Narrative request: {spec.description[:1700]}. {limitation}"
        for effect in spec.effects:
            if effect.type == "information":
                effect.message = message
        spec.title = f"Narrative request: {' '.join(spec.description.split())}"[:80]
    if not spec.scene:
        if design and design.parts:
            recipes = [
                dict(
                    model="generated",
                    label=design.label,
                    id=design.label,
                    count=1,
                    color=design.parts[0].color,
                    parts=design.parts,
                ),
                *recipes,
            ]
            warnings.append(
                "The custom object is an AI-composed illustration made from simple shapes. "
                "Its simulation effects are limited to the effects listed below."
            )
        spec.scene = build_scene(state, spec, recipes or matches(spec.description) or matches(spec.kind))
    if unsupported:
        for prop in spec.scene:
            if not prop.label.startswith("Illustration: "):
                prop.label = f"Illustration: {prop.label}"[:80]
    can_commit = bool(spec.effects)
    if can_commit:
        validate_spec(state, spec)
    return ScenarioPreview(
        id=state.next_id("preview"),
        simulation_id=state.simulation.id,
        source=source,
        source_event_id=source_event_id,
        based_on=state.ref(),
        expires_at=expiry(),
        interpretation=(
            f"{limitation} Narrative request: {spec.description[:1700]}"
            if unsupported
            else f"{spec.description[:1900]} Citizens respond in their own way over {spec.duration_ticks} ticks."
        ),
        spec=spec,
        affected_agent_ids=[
            a
            for a, c in state.citizens.items()
            if polygon_contains(c.summary.position, spec.affected_polygon)
        ],
        affected_building_ids=[
            b.id for b in state.map.buildings if polygon_contains(b.entrance, spec.affected_polygon)
        ],
        warnings=warnings,
        unsupported_requests=unsupported,
        can_commit=can_commit,
    )


def queue_event(state, preview, snapshot_id, resume_allowed):
    spec = preview.spec.model_copy(deep=True)
    validate_spec(state, spec)
    event = EventSummary(
        id=state.next_id("event"),
        title=spec.title,
        kind=spec.kind,
        status="queued",
        queued_tick=state.simulation.tick,
        start_tick=None,
        end_tick=None,
        affected_agent_count=len(preview.affected_agent_ids),
        affected_polygon=spec.affected_polygon,
        pre_event_snapshot_id=snapshot_id,
        summary="Event will begin on the next simulation tick",
        scene=spec.scene,
    )
    values = state.metric_points[-1].values.model_copy(deep=True)
    state.events[event.id] = EventRuntime(
        summary=event, spec=spec, before=values, after=values.model_copy(), resume_allowed=resume_allowed
    )
    return event


def activate(state):
    for runtime in state.events.values():
        if runtime.summary.status != "queued":
            continue
        runtime.summary.status = "active"
        runtime.summary.start_tick = state.simulation.tick
        runtime.summary.summary = "Event active"
        runtime.cohort = [
            aid
            for aid, c in state.citizens.items()
            if c.summary.active and polygon_contains(c.summary.position, runtime.spec.affected_polygon)
        ]
        runtime.summary.affected_agent_count = len(runtime.cohort)
        runtime.baseline_conflicts = int(state.counters["conflict_count"])
        runtime.baseline_consumed = state.counters["resources_consumed"]
        proof = evidence("Observed event activation", event_ids=[runtime.summary.id])
        for aid in runtime.cohort:
            citizen = state.citizens[aid]
            citizen.major_event_ids.append(runtime.summary.id)
            for effect in runtime.spec.effects:
                if effect.type == "hazard":
                    remember(
                        state,
                        citizen,
                        f"I observed {effect.hazard} conditions nearby.",
                        importance=80,
                        proof=proof,
                    )
            citizen.summary.path = []
            citizen.plan = None
            citizen.task_generation += 1
            citizen.next_deliberation_tick = state.simulation.tick
        for effect in runtime.spec.effects:
            if effect.type == "resource_multiplier":
                for resource in state.map.resources:
                    if resource.kind == effect.resource and polygon_contains(
                        resource.position, runtime.spec.affected_polygon
                    ):
                        before = resource.available_units
                        resource.available_units *= effect.multiplier
                        state.external_resource_changes.append(
                            dict(
                                event_id=runtime.summary.id,
                                resource_id=resource.id,
                                tick=state.simulation.tick,
                                before=before,
                                after=resource.available_units,
                                reason="scenario external stock change",
                            )
                        )
            elif effect.type == "infrastructure":
                for building in state.map.buildings:
                    if polygon_contains(building.entrance, runtime.spec.affected_polygon):
                        runtime.infrastructure_before[building.id] = dict(
                            functional=building.functional, capacity=building.capacity
                        )
                        building.functional = effect.functional
                        building.capacity = round(building.capacity * effect.capacity_multiplier)
            elif effect.type == "policy":
                from app.contracts import Policies

                state.policies = Policies(**effect.model_dump(exclude={"type"}))
            elif effect.type == "information":
                recipients = (
                    state.citizens.values()
                    if effect.delivery == "broadcast"
                    else [state.citizens[aid] for aid in runtime.cohort]
                )
                for citizen in recipients:
                    memory = remember(
                        state,
                        citizen,
                        f"World event: {effect.message}"
                        if effect.reliability == 100
                        else f"Scenario source reports: {effect.message}",
                        source="observed" if effect.reliability == 100 else "heard",
                        importance=60,
                        proof=proof,
                    )
                    from app.contracts import Belief

                    citizen.beliefs.append(
                        Belief(
                            text=(
                                f"World event: {effect.message}"
                                if effect.reliability == 100
                                else f"Unverified scenario broadcast: {effect.message}"
                            )[:2000],
                            confidence=effect.reliability,
                            evidence=evidence(
                                "Observed world event"
                                if effect.reliability == 100
                                else "Heard information; not verified fact",
                                event_ids=[runtime.summary.id],
                                memory_ids=[memory.id],
                            ),
                        )
                    )


def apply_effects(state):
    for runtime in state.events.values():
        if runtime.summary.status != "active":
            continue
        proof = evidence("Exposure to an active event", event_ids=[runtime.summary.id])
        for citizen in state.citizens.values():
            if not citizen.summary.active or not polygon_contains(
                citizen.summary.position, runtime.spec.affected_polygon
            ):
                continue
            for effect in runtime.spec.effects:
                if effect.type == "hazard":
                    damage = effect.severity / 100 * ({"flood": 1, "fire": 2, "storm": 0.5}[effect.hazard])
                    citizen.needs.health = clamp(citizen.needs.health - damage)
                    metric_delta(citizen, "stress", effect.severity / 100 * 2, proof)
                    metric_delta(citizen, "happiness", -effect.severity / 100, proof)
                elif effect.type == "community":
                    eligible = sorted(
                        c.summary.id
                        for c in state.citizens.values()
                        if polygon_contains(c.summary.position, runtime.spec.affected_polygon)
                    )[: effect.capacity]
                    if citizen.summary.id in eligible:
                        if effect.activity == "festival":
                            metric_delta(citizen, "happiness", 0.8, proof)
                            metric_delta(citizen, "stress", -0.5, proof)
                        else:
                            citizen.inventory.supplies += 0.25 * state.policies.aid_multiplier
                            state.external_resource_changes.append(
                                dict(
                                    event_id=runtime.summary.id,
                                    agent_id=citizen.summary.id,
                                    tick=state.simulation.tick,
                                    resource="supplies",
                                    units=0.25 * state.policies.aid_multiplier,
                                    reason="external community aid",
                                )
                            )
                            state.counters["cooperation_count"] += 1
                elif effect.type == "wellbeing":
                    metric_delta(citizen, "happiness", effect.happiness_delta, proof)
                    metric_delta(citizen, "stress", effect.stress_delta, proof)
                    citizen.needs.health = clamp(citizen.needs.health + effect.health_delta)


def finish_events(state):
    completed = False
    for runtime in state.events.values():
        if runtime.summary.status != "active":
            continue
        runtime.after = state.metric_points[-1].values.model_copy()
        runtime.conflicts = int(state.counters["conflict_count"]) - runtime.baseline_conflicts
        runtime.resources_consumed = state.counters["resources_consumed"] - runtime.baseline_consumed
        hazard = any(effect.type == "hazard" for effect in runtime.spec.effects)
        runtime.exposed_count = (
            sum(
                state.citizens[aid].summary.active
                and hazard_severity(state, state.citizens[aid].summary.position) > 0
                for aid in runtime.cohort
            )
            if hazard
            else 0
        )
        runtime.evacuated_count = (
            sum(
                state.citizens[aid].summary.active
                and hazard_severity(state, state.citizens[aid].summary.position) == 0
                for aid in runtime.cohort
            )
            if hazard
            else 0
        )
        duration_end = state.simulation.tick >= runtime.summary.start_tick + runtime.spec.duration_ticks
        safe_end = (
            hazard
            and bool(runtime.cohort)
            and runtime.spec.success_condition == "all_safe_or_duration"
            and runtime.exposed_count == 0
        )
        if not duration_end and not safe_end:
            continue
        runtime.summary.status = "resolved"
        runtime.summary.end_tick = state.simulation.tick
        runtime.summary.summary = f"Resolved after {state.simulation.tick - runtime.summary.start_tick} ticks; {runtime.evacuated_count} initially exposed citizens now safe"
        proof = evidence("Committed event interval measurements", event_ids=[runtime.summary.id])
        runtime.consequences = [dict(text=runtime.summary.summary, evidence=proof.model_dump())]
        for aid in runtime.cohort:
            remember(state, state.citizens[aid], runtime.summary.summary, importance=75, proof=proof)
        for building in state.map.buildings:
            baseline = runtime.infrastructure_before.get(building.id)
            if baseline:
                building.functional = baseline["functional"]
                building.capacity = baseline["capacity"]
        state.policies = state.baseline_policies.model_copy()
        state.auto_resume = runtime.resume_allowed and state.simulation.status == "running"
        state.simulation.status = "paused"
        state.simulation.pause_reason = "outcome"
        state.simulation.control_version += 1
        state.simulation.pending_outcome_event_ids.append(runtime.summary.id)
        completed = True
    return completed


def event_report(state, runtime):
    delta = MetricDeltas(
        **{key: getattr(runtime.after, key) - getattr(runtime.before, key) for key in Metrics.model_fields}
    )
    return EventReport(
        ref=state.ref(),
        event=runtime.summary,
        spec=runtime.spec,
        before=runtime.before,
        after=runtime.after,
        delta=delta,
        affected_agent_ids=runtime.cohort
        if runtime.summary.status != "queued"
        else [
            aid
            for aid, c in state.citizens.items()
            if polygon_contains(c.summary.position, runtime.spec.affected_polygon)
        ],
        conflicts=runtime.conflicts,
        resources_consumed=runtime.resources_consumed,
        evacuated_count=runtime.evacuated_count,
        exposed_count=runtime.exposed_count,
        consequences=[Consequence.model_validate(c) for c in runtime.consequences],
        community_lessons=[],
        suggested_preparations=["Keep reachable shelter and essential supplies available"]
        if runtime.summary.status == "resolved" and any(e.type == "hazard" for e in runtime.spec.effects)
        else [],
    )


def blocked_cells(state):
    # Deliberately coarse mechanics; roads remain traversable for evacuation.
    hazards = [
        r
        for r in state.events.values()
        if r.summary.status == "active"
        and any(e.type == "hazard" and e.severity >= 80 for e in r.spec.effects)
    ]
    return {
        (cell.col, cell.row)
        for cell in state.map.cells
        if cell.terrain == "land"
        and cell.elevation_m < 0.3
        and any(
            polygon_contains(Vec2(x=(cell.col + 0.5) * 2, y=(cell.row + 0.5) * 2), r.spec.affected_polygon)
            for r in hazards
        )
    }
