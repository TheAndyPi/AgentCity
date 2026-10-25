"""Initialization and shared helpers for the persistent world systems."""

import math

from app.scenario_engine.systems import (
    RENT_PER_TICK,
    TRACE_LIMIT,
    AgentSystems,
    Trace,
    in_region,
    unit,
)
from app.simulation.agents import clamp, remember
from app.simulation.navigation import distance

CENTER = (64, 64)


def walking_speed(citizen):
    return 1.4 * (0.5 + citizen.profile.mobility / 100)


def enable(state):
    """Start the economy, services and institutions. Idempotent; never rewinds history."""
    systems = state.systems
    if systems.enabled:
        sync_agents(state)
        return
    systems.enabled = True
    systems.enabled_tick = state.simulation.tick
    distribution = systems.policy.resource_distribution
    distribution.ration_units_per_agent = state.policies.ration_units_per_agent
    distribution.aid_multiplier = state.policies.aid_multiplier
    distribution.evacuation_order = float(state.policies.evacuation_order)
    tallest = max((b.height_m for b in state.map.buildings), default=1) or 1
    for building in state.map.buildings:
        systems.base_capacity[building.id] = (
            state.conditions[building.id].design_capacity
            if building.id in state.conditions
            else building.capacity
        )
        if building.kind == "home":
            centrality = 1 - min(1, math.dist((building.entrance.x, building.entrance.y), CENTER) / 90)
            systems.home_rent[building.id] = round(
                0.65 + 0.55 * centrality + 0.3 * building.height_m / tallest, 3
            )
            systems.housing_available[building.id] = True
        elif building.kind in {"work", "shop"}:
            systems.businesses[building.id] = 20.0
            if building.kind == "shop":
                systems.shop_stock[building.id] = 20.0
    systems.businesses.setdefault("landlords", 0.0)
    sync_agents(state)


def sync_agents(state):
    for citizen in state.citizens.values():
        if citizen.summary.id not in state.systems.agents:
            state.systems.agents[citizen.summary.id] = new_agent(state, citizen)


def new_agent(state, citizen):
    config = state.simulation.config
    aid = citizen.summary.id
    roll = unit(config.seed, aid, "income")
    income = "low" if roll < 0.32 else "high" if roll > 0.76 else "middle"
    base = {"low": 6, "middle": 14, "high": 28}[income]
    wallet = base * (0.5 + config.household_supplies / 100) * (0.85 + 0.3 * unit(config.seed, aid, "wallet"))
    owns_car = unit(config.seed, aid, "car") < {"low": 0.2, "middle": 0.55, "high": 0.85}[income]
    trust = clamp(
        0.5 * config.environment.initial_community_trust
        + 0.5 * citizen.profile.traits.trust
        + (unit(config.seed, aid, "institutions") - 0.5) * 10
    )
    home = home_building(state, citizen.home)
    agent = AgentSystems(
        wallet=round(wallet, 3),
        income=income,
        owns_car=owns_car,
        habit="walk",
        institutional_trust=round(trust, 3),
        rent_factor=state.systems.home_rent.get(home.id, 1.0) if home else 1.0,
        home_id=home.id if home else None,
        renter=not (income == "high" and unit(config.seed, aid, "owner") < 0.45),
        next_review_tick=state.simulation.tick + int(unit(config.seed, aid, "review") * 12),
    )
    from app.scenario_engine.responses import habitual_mode

    agent.habit = habitual_mode(state, citizen, agent)
    return agent


def home_building(state, point):
    homes = [b for b in state.map.buildings if b.kind == "home"]
    return min(homes, key=lambda b: (distance(point, b.entrance), b.id), default=None)


def housing_share(state):
    flags = state.systems.housing_available
    return sum(flags.values()) / len(flags) if flags else 1.0


def rent_multiplier(state):
    housing = state.systems.policy.housing
    market = housing.rent_level * (1 + 1.5 * (1 - housing_share(state)))
    return min(market, housing.rent_cap) if housing.rent_cap is not None else market


def rent_for(state, agent):
    if not agent.renter:
        return 0.0
    rent = RENT_PER_TICK * rent_multiplier(state) * agent.rent_factor
    return rent * (0.5 if agent.housing_status == "sharing" else 1)


def select(state, audience, salt):
    """Deterministic audience: filter by kind, then take the requested share in seeded order."""
    systems = state.systems
    people = [c for c in state.citizens.values() if c.summary.active]
    kind = audience.kind
    if kind == "region" and audience.region:
        people = [c for c in people if in_region(c.summary.position, audience.region)]
    elif kind in {"low_income", "middle_income", "high_income"}:
        level = kind.split("_")[0]
        people = [c for c in people if systems.agents[c.summary.id].income == level]
    elif kind == "renters":
        people = [c for c in people if systems.agents[c.summary.id].renter]
    elif kind == "workers":
        people = [c for c in people if c.profile.role.lower() not in {"retired", "retiree", "student"}]
    elif kind == "transit_riders":
        people = [c for c in people if systems.agents[c.summary.id].habit == "transit"]
    elif kind == "car_users":
        people = [c for c in people if systems.agents[c.summary.id].habit == "car"]
    elif kind == "organization_members":
        org = systems.organizations.get(audience.organization_id or "")
        people = [c for c in people if org and c.summary.id in org.members]
    if audience.region and kind != "region":
        people = [c for c in people if in_region(c.summary.position, audience.region)]
    people.sort(key=lambda c: (unit(salt, c.summary.id), c.summary.id))
    return people[: math.ceil(audience.share * len(people))]


def trace(
    state,
    kind,
    title,
    *,
    event_id=None,
    op_id=None,
    agent=None,
    observations=(),
    candidates=(),
    selected=None,
    motivation="",
    memory_ids=(),
    changes=(),
    affected=(),
    significance=0.0,
):
    systems = state.systems
    record = Trace(
        id=systems.next_id("trace"),
        tick=state.simulation.tick,
        kind=kind,
        event_id=event_id,
        op_id=op_id,
        agent_id=agent.summary.id if agent else None,
        title=title[:300],
        observations=[o[:300] for o in observations][:8],
        candidates=list(candidates)[:6],
        selected=selected,
        motivation=motivation[:500],
        memory_ids=list(memory_ids),
        changes=list(changes)[:100],
        affected_ids=list(affected)[:100],
        significance=significance,
    )
    systems.traces.append(record)
    if len(systems.traces) > TRACE_LIMIT:
        # Keep every operation record; drop the oldest minor decisions first.
        minor = next(
            (i for i, t in enumerate(systems.traces) if t.kind == "decision" and t.significance < 1), 0
        )
        systems.traces.pop(minor)
    return record


def decide(
    state,
    citizen,
    title,
    candidates,
    *,
    event_id=None,
    op_id=None,
    observations=(),
    motivation=None,
    memory=None,
    changes=(),
    affected=(),
    significance=1.0,
    source="heard",
):
    """Pick the highest-scoring candidate, remember it, and record the full decision trace."""
    ranked = sorted(candidates, key=lambda c: (-c["score"], c["action"]))
    chosen = ranked[0]
    proof_ids = [m.id for m in citizen.memories[-3:]]
    memory_ids = []
    if memory:
        from app.simulation.agents import evidence

        record = remember(
            state,
            citizen,
            memory.format(choice=chosen["label"]),
            source,
            55,
            proof=evidence(title, event_ids=[event_id] if event_id else None),
        )
        memory_ids.append(record.id)
    record = trace(
        state,
        "decision",
        title,
        event_id=event_id,
        op_id=op_id,
        agent=citizen,
        observations=observations,
        candidates=[dict(action=c["action"], label=c["label"], score=round(c["score"], 3)) for c in ranked],
        selected=chosen["action"],
        motivation=motivation or chosen.get("why", chosen["label"]),
        memory_ids=[*memory_ids, *proof_ids],
        changes=changes,
        affected=affected,
        significance=significance,
    )
    return chosen["action"], record


def change(entity, field, before, after):
    return dict(entity_id=entity, field=field, before=before, after=after)


def current_event(state):
    """The event whose plan is active now, for attributing reactions."""
    for event_id, record in state.systems.plans.items():
        if record.status == "active":
            return event_id
    return None
