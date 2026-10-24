"""Profile lifecycle, bounded perception, evidence-backed cognition and metrics."""

from statistics import mean

from app.contracts import (
    AgentSummary,
    Evidence,
    Inventory,
    Memory,
    MetricPoint,
    MetricReason,
    Metrics,
    Needs,
    Profile,
    Relationship,
    Traits,
)
from app.simulation.characters import OCCUPATIONS, character_details, character_name
from app.simulation.navigation import (
    SpatialIndex,
    cell_at,
    distance,
    line_of_sight,
    polygon_area,
    polygon_contains,
)
from app.simulation.state import Citizen


def clamp(value):
    return min(100, max(0, value))


def evidence(description, event_ids=None, decision_ids=None, memory_ids=None):
    return Evidence(
        event_ids=event_ids or [],
        decision_ids=decision_ids or [],
        memory_ids=memory_ids or [],
        description=description[:2000],
    )


def generated_profile(index, config, rng):
    traits = Traits(
        **{
            key: clamp(
                value + rng.uniform(-config.personality_diversity / 2, config.personality_diversity / 2)
            )
            for key, value in config.population_traits.model_dump().items()
        }
    )
    role = rng.choice(list(OCCUPATIONS))
    return Profile(
        name=character_name(index, config.seed),
        age=rng.randint(18, 80),
        role=role,
        traits=traits,
        **character_details(role, traits, rng),
        intelligence=rng.uniform(30, 90),
        mobility=50,
        physical_attributes="Walks at an ordinary pace",
        social_needs=traits.sociability,
    )


def spawn(state, profile, position, template=None):
    aid = state.next_id("agent")
    supplies = state.simulation.config.household_supplies / 100 * 6
    base = Metrics(
        happiness=60,
        safety=100,
        trust=state.simulation.config.environment.initial_community_trust,
        resources=0,
        stress=20,
    )
    citizen = Citizen(
        summary=AgentSummary(
            id=aid,
            name=profile.name,
            role=profile.role,
            position=position.model_copy(),
            heading_rad=0,
            path=[],
            movement_speed_mps=1.4 * (0.5 + profile.mobility / 100),
            metrics=base,
            emotion="calm",
            action="idle",
            action_target_id=None,
            latest_decision_id=None,
            thought_bubble=None,
            active=True,
        ),
        profile=profile.model_copy(deep=True),
        home=position.model_copy(),
        needs=Needs(hunger=20, fatigue=15, health=100, social=profile.social_needs / 2),
        inventory=Inventory(food=supplies, water=supplies, supplies=supplies),
        goals=[profile.primary_goal, *profile.secondary_goals],
        known_locations={b.id: b.entrance.model_copy() for b in state.map.buildings}
        | {r.id: r.position.model_copy() for r in state.map.resources},
    )
    if template:
        citizen.profile_template_id, citizen.profile_template_version = template["id"], template["version"]
    state.citizens[aid] = citizen
    return citizen


def connect(state, citizen, other, kind="acquaintance", rng=None):
    if other.summary.id == citizen.summary.id or other.summary.id in citizen.relationships:
        return
    base = state.simulation.config.environment.initial_community_trust
    jitter = rng.uniform(-10, 10) if rng else 0
    citizen.relationships[other.summary.id] = Relationship(
        from_agent_id=citizen.summary.id,
        to_agent_id=other.summary.id,
        kind=kind,
        trust=clamp(base + jitter),
        affection=clamp(60 + jitter if kind == "family" else 35 + jitter),
        respect=clamp(50 - jitter),
        familiarity=70 if kind == "family" else 30,
        conflict=clamp(10 - jitter),
        desired_relationship="Mutual support",
        shared_history=[],
        evidence=evidence("Initial known relationship from household/community history"),
    )


def remember(state, citizen, text, source="observed", importance=50, subjects=None, proof=None):
    memory = Memory(
        id=state.next_id("memory"),
        tick=state.simulation.tick,
        text=text[:2000],
        importance=importance,
        source=source,
        subject_ids=subjects or [],
        evidence=proof or evidence(text),
    )
    citizen.memories.append(memory)
    return memory


def retrieve(citizen, tick, query="", limit=8):
    words = set(query.lower().split())

    def score(m):
        return (
            m.importance * 0.5
            + 30 / (1 + max(0, tick - m.tick) / 10)
            + 20 * len(words & set(m.text.lower().split())) / max(1, len(words))
        )

    return sorted(citizen.memories, key=lambda m: (score(m), m.id), reverse=True)[:limit]


def social_delta(state, citizen, other, decision_id, delta=2):
    # Deduplicate one directed change per evidence set, including reflection proposals.
    key = f"{citizen.summary.id}:{other.summary.id}:{decision_id}"
    if key in state.applied_social_evidence:
        return
    connect(state, citizen, other)
    relationship = citizen.relationships[other.summary.id]
    for field, change in {
        "trust": delta,
        "affection": delta / 2,
        "respect": delta / 2,
        "familiarity": 1,
        "conflict": -delta / 2,
    }.items():
        setattr(relationship, field, clamp(getattr(relationship, field) + max(-5, min(5, change))))
    relationship.shared_history.append(decision_id)
    relationship.evidence = evidence("Treatment during a validated interaction", decision_ids=[decision_id])
    state.applied_social_evidence.append(key)


def metric_delta(citizen, metric, delta, proof):
    before = getattr(citizen.summary.metrics, metric)
    after = clamp(before + delta)
    setattr(citizen.summary.metrics, metric, after)
    if abs(after - before) > 1e-10:
        citizen.metric_reasons.append(MetricReason(metric=metric, delta=after - before, evidence=proof))


def hazard_severity(state, position):
    return max(
        [
            effect.severity
            for runtime in state.events.values()
            if runtime.summary.status == "active"
            and polygon_contains(position, runtime.spec.affected_polygon)
            for effect in runtime.spec.effects
            if effect.type == "hazard"
        ]
        or [0]
    )


def perception(state, citizen, index=None):
    index = index or SpatialIndex(state.citizens)
    p = citizen.summary.position
    nearby = sorted(
        [
            c
            for c in index.nearby(p, 20)
            if c.summary.id != citizen.summary.id
            and c.inside_building_id == citizen.inside_building_id
            and (citizen.inside_building_id or line_of_sight(state.map, p, c.summary.position))
        ],
        key=lambda c: (distance(p, c.summary.position), c.summary.id),
    )[:8]
    memories = retrieve(citizen, state.simulation.tick, " ".join(citizen.goals))
    ties = sorted(
        citizen.relationships.values(),
        key=lambda r: (r.kind == "family", r.affection + r.trust),
        reverse=True,
    )[:6]
    messages = [
        d
        for d in state.dialogue
        if citizen.summary.id in d.audible_to_ids
        or citizen.summary.id in d.recipient_ids
        or citizen.summary.id == d.speaker_id
    ][-6:]
    facts = [
        f"Position ({p.x:.1f}, {p.y:.1f}) meters",
        f"Hunger {citizen.needs.hunger:.1f}, fatigue {citizen.needs.fatigue:.1f}",
    ]
    facts += [
        f"Observed {c.summary.name} ({c.summary.id}) at ({c.summary.position.x:.1f}, {c.summary.position.y:.1f}), {distance(p, c.summary.position):.1f}m away, doing {c.summary.action}"
        for c in nearby
    ]
    facts += [
        f"Observed {resource.kind} source {resource.id} at ({resource.position.x:.1f}, {resource.position.y:.1f}) with {resource.available_units:g} units"
        for resource in state.map.resources
        if distance(p, resource.position) <= 20 and line_of_sight(state.map, p, resource.position)
    ]
    facts += [
        f"Neighbor {group.initiator_id} proposed voluntary nearby aid"
        for group in state.interactions.values()
        if group.kind == "aid_group"
        and citizen.summary.id in group.participant_ids
        and group.expires_tick >= state.simulation.tick
        and group.status in {"invited", "accepted"}
    ]
    for runtime in state.events.values():
        if runtime.summary.status == "active" and (
            polygon_contains(p, runtime.spec.affected_polygon)
            or distance(p, runtime.spec.origin) <= 20
            and line_of_sight(state.map, p, runtime.spec.origin)
        ):
            for effect in runtime.spec.effects:
                if effect.type == "hazard":
                    facts.append(f"Observed {effect.hazard} conditions nearby")
                elif effect.type == "community":
                    facts.append(f"Observed a local {effect.activity} activity")
                elif effect.type == "information" and effect.reliability == 100:
                    facts.append(f"World event: {effect.message}")
    return {
        "facts": facts,
        "nearby_ids": [c.summary.id for c in nearby],
        "memories": memories,
        "relationships": ties,
        "messages": messages,
    }


def update_metrics(state):
    active = [c for c in state.citizens.values() if c.summary.active]
    for citizen in active:
        m = citizen.summary.metrics
        m.resources = 100 * min(
            1, sum(citizen.inventory.model_dump().values()) / max(1, citizen.target_inventory_units)
        )
        known = [r.trust for r in citizen.relationships.values() if r.kind != "stranger"]
        m.trust = mean(known) if known else state.simulation.config.environment.initial_community_trust
        m.safety = clamp(
            100 - max(hazard_severity(state, citizen.summary.position), 100 - citizen.needs.health)
        )
    values = Metrics(
        **{
            key: mean(getattr(c.summary.metrics, key) for c in active) if active else 0
            for key in Metrics.model_fields
        }
    )
    if state.initial_metrics is None and active:
        state.initial_metrics = values.model_copy()
    exposed = sum(hazard_severity(state, c.summary.position) > 0 for c in active)
    evacuated = sum(
        sum(
            aid in state.citizens
            and state.citizens[aid].summary.active
            and hazard_severity(state, state.citizens[aid].summary.position) == 0
            for aid in runtime.cohort
        )
        for runtime in state.events.values()
        if runtime.summary.status == "active" and any(e.type == "hazard" for e in runtime.spec.effects)
    )
    point = MetricPoint(
        tick=state.simulation.tick,
        revision=state.simulation.revision,
        values=values,
        cooperation_count=int(state.counters["cooperation_count"]),
        conflict_count=int(state.counters["conflict_count"]),
        resources_consumed=state.counters["resources_consumed"],
        exposed_count=exposed,
        evacuated_count=evacuated,
    )
    if state.metric_points and state.metric_points[-1].tick == point.tick:
        state.metric_points[-1] = point
    else:
        state.metric_points.append(point)
    for zone in state.map.zones:
        members = [c for c in active if cell_at(state.map, c.summary.position).zone_id == zone.id]
        zone.population = len(members)
        zone.population_density_per_km2 = len(members) / (polygon_area(zone.polygon) / 1_000_000)
        zone.metrics = (
            Metrics(
                **{
                    key: mean(getattr(c.summary.metrics, key) for c in members)
                    for key in Metrics.model_fields
                }
            )
            if members
            else values.model_copy()
        )
    for building in state.map.buildings:
        building.occupancy = sum(c.inside_building_id == building.id for c in active)
    return point
