"""World mutation engine: generic, parameterized operations on shared world state.

Every handler records its exact prior values so a temporary operation can be
reverted without disturbing changes made by citizens or later operations.
"""

from pydantic import TypeAdapter

from app.scenario_engine import responses
from app.scenario_engine.registry import POLICY_TARGETS, Operation
from app.scenario_engine.systems import bump, in_region, unit
from app.scenario_engine.world import change, select, trace
from app.simulation.agents import clamp, connect, evidence, remember

OPERATION = TypeAdapter(Operation)


def parse(op):
    return OPERATION.validate_python(op)


def policy_result(current, operation, value, target):
    low, high, _, nullable, _, _ = POLICY_TARGETS[target]
    if operation == "clear":
        return None
    base = current if current is not None else (high if target == "housing.rent_cap" else low)
    result = {
        "set": value,
        "increase": base + value,
        "decrease": base - value,
        "multiply": base * value,
    }[operation]
    return round(min(high, max(low, result)), 6)


def sync_policy(state, target, permanent):
    """Mirror resource-distribution policies into the mechanics that already read them."""
    systems = state.systems
    distribution = systems.policy.resource_distribution
    targets = [state.policies, state.baseline_policies] if permanent else [state.policies]
    for policies in targets:
        policies.ration_units_per_agent = distribution.ration_units_per_agent
        policies.aid_multiplier = distribution.aid_multiplier
        policies.evacuation_order = distribution.evacuation_order >= 0.5
    if target == "public_services.hospital_funding":
        from app.disasters.physics import effective_services

        effective_services(state)


def funding_level(state):
    funding = state.systems.policy.public_services.hospital_funding
    return funding if state.systems.treasury > -30 or funding <= 1 else 1.0


def apply(state, entry, permanent):
    op = parse(entry.op)
    handler = globals()[f"apply_{op.type}"]
    undo = handler(state, op, entry.event_id, permanent, entry.repetition) or {}
    bump(state.systems, "operations_applied")
    return undo


def revert(state, entry):
    op = parse(entry.op)
    handler = globals().get(f"revert_{op.type}")
    if handler:
        handler(state, op, entry.event_id, entry.undo)
        trace(
            state,
            "operation",
            f"Ended: {describe(op)}",
            event_id=entry.event_id,
            op_id=op.id,
            motivation="Temporary change reached the end of its duration",
        )


def describe(op):
    t = op.type
    if t == "set_curfew":
        return f"{'announce' if op.enabled else 'lift'} curfew {op.start_minute // 60:02d}:{op.start_minute % 60:02d}–{op.end_minute // 60:02d}:{op.end_minute % 60:02d}"
    if t == "modify_policy":
        label = op.target.replace(".", " ").replace("_", " ")
        return f"{op.operation} {label}" + ("" if op.value is None else f" {op.value:g}")
    if t == "set_service_availability":
        subject = op.building_id or f"{op.building_kind} buildings in {op.region}"
        return f"{'open' if op.open else 'close'} {subject}" + (
            f" at {op.capacity_multiplier * 100:.0f}% capacity"
            if op.open and op.capacity_multiplier != 1
            else ""
        )
    if t == "modify_resource_stock":
        return f"{op.resource} stock x{op.multiplier:g} in {op.region}"
    if t == "modify_housing_supply":
        return f"{op.available_share * 100:.0f}% of homes available in {op.region}"
    if t == "broadcast_information":
        return f"{op.channel} message to {op.audience.kind}: {op.message[:80]}"
    if t == "adjust_institutional_credibility":
        return f"institutional credibility {op.delta:+g} for {op.audience.kind}"
    if t == "introduce_social_norm":
        return f"promote norm {op.norm} at strength {op.strength:g}"
    if t == "create_organization":
        return f"create {op.kind} '{op.name}'"
    if t == "remove_organization":
        return f"dissolve organization {op.organization_id}"
    if t == "set_incentive":
        return f"{op.incentive} of {op.amount:g} credits for {op.audience.kind}"
    if t == "adjust_population_traits":
        return f"{op.trait} {op.delta:+g} for {op.audience.share * 100:.0f}% of {op.audience.kind}"
    if t == "modify_social_network":
        return f"{op.action.replace('_', ' ')} for {op.audience.share * 100:.0f}% of {op.audience.kind}"
    if t == "physical_hazard":
        return f"{op.hazard} of severity {op.severity:g} in {op.region}"
    if t == "community_gathering":
        return f"{op.activity} in {op.region}"
    if t == "catalog_event":
        return f"{op.recipe.replace('_', ' ')} scenery and catalog effects in {op.region}"
    return f"{op.condition} of intensity {op.intensity:g} in {op.region}"


def apply_modify_policy(state, op, event_id, permanent, repetition):
    policy = state.systems.policy
    before = policy.get(op.target)
    after = policy_result(before, op.operation, op.value, op.target)
    policy.set(op.target, after)
    state.systems.counters[f"changed:{op.target}"] = state.simulation.tick
    sync_policy(state, op.target, permanent)
    trace(
        state,
        "operation",
        f"Policy: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=[change("policy", op.target, before, after)],
        significance=3,
    )
    return dict(before=before, after=after)


def apply_set_curfew(state, op, event_id, permanent, repetition):
    from app.contracts import CurfewPolicy

    key = f"{event_id}:{op.id}"
    before = state.curfew_controls.get(key)
    informed = [c.summary.id for c in select(state, op.audience, key)]
    state.curfew_revision += 1
    state.curfew_controls.pop(key, None)
    state.curfew_controls[key] = CurfewPolicy(
        enabled=op.enabled,
        start_minute=op.start_minute,
        end_minute=op.end_minute,
        revision=state.curfew_revision,
        informed_agent_ids=informed,
    )
    for aid in informed:
        citizen = state.citizens[aid]
        remember(
            state,
            citizen,
            f"Official announcement: {describe(op)}. Emergency care and evacuation take priority.",
            "heard",
            65,
            proof=evidence("Announced curfew policy", event_ids=[event_id]),
        )
        citizen.task_generation += 1
        citizen.next_deliberation_tick = state.simulation.tick
    trace(
        state,
        "operation",
        describe(op),
        event_id=event_id,
        op_id=op.id,
        affected=informed,
        motivation=op.rationale,
        significance=3,
    )
    return dict(before=before.model_dump() if before else None)


def revert_set_curfew(state, op, event_id, undo):
    from app.contracts import CurfewPolicy

    key = f"{event_id}:{op.id}"
    state.curfew_controls.pop(key, None)
    if undo.get("before"):
        state.curfew_controls[key] = CurfewPolicy.model_validate(undo["before"])
    state.curfew_revision += 1


def revert_modify_policy(state, op, event_id, undo):
    policy = state.systems.policy
    if policy.get(op.target) == undo.get("after"):
        policy.set(op.target, undo.get("before"))
        state.systems.counters[f"changed:{op.target}"] = state.simulation.tick
        sync_policy(state, op.target, False)


def targeted_buildings(state, op):
    if op.building_id:
        return [b for b in state.map.buildings if b.id == op.building_id]
    return [b for b in state.map.buildings if b.kind == op.building_kind and in_region(b.entrance, op.region)]


def apply_set_service_availability(state, op, event_id, permanent, repetition):
    from app.disasters.physics import effective_services, initialize

    initialize(state)
    systems = state.systems
    undo, changes = {}, []
    buildings = targeted_buildings(state, op)
    for building in buildings:
        undo[building.id] = dict(functional=building.functional, capacity=building.capacity)
        controls = systems.service_controls.setdefault(building.id, {})
        controls[f"{event_id}:{op.id}"] = dict(
            event_id=event_id, open=op.open, capacity_multiplier=op.capacity_multiplier
        )
        closed = [control["event_id"] for control in controls.values() if not control["open"]]
        if closed:
            systems.closed_by[building.id] = closed[-1]
        else:
            systems.closed_by.pop(building.id, None)
    effective_services(state)
    for building in buildings:
        before = undo[building.id]
        changes.append(change(building.id, "functional", before["functional"], building.functional))
        if before["capacity"] != building.capacity:
            changes.append(change(building.id, "capacity", before["capacity"], building.capacity))
    trace(
        state,
        "operation",
        f"Service: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=changes,
        affected=[b.id for b in buildings],
        significance=3,
    )
    if not op.open:
        for building in buildings:
            users = [
                state.citizens[aid]
                for aid, agent in systems.agents.items()
                if aid in state.citizens
                and state.citizens[aid].summary.active
                and (
                    agent.regular_shop == building.id
                    or agent.shop_visits.get(building.id)
                    or state.citizens[aid].last_building_id == building.id
                )
            ][:30]
            for citizen in users:
                responses.seek_alternative(state, citizen, building, event_id, op.id)
    return undo


def revert_set_service_availability(state, op, event_id, undo):
    from app.disasters.physics import effective_services, initialize

    initialize(state)
    for building in state.map.buildings:
        if building.id in undo:
            controls = state.systems.service_controls.get(building.id, {})
            controls.pop(f"{event_id}:{op.id}", None)
            closed = [control["event_id"] for control in controls.values() if not control["open"]]
            if closed:
                state.systems.closed_by[building.id] = closed[-1]
            else:
                state.systems.closed_by.pop(building.id, None)
    effective_services(state)


def apply_modify_resource_stock(state, op, event_id, permanent, repetition):
    changes = []
    for resource in state.map.resources:
        if resource.kind == op.resource and in_region(resource.position, op.region):
            before = resource.available_units
            resource.available_units = round(before * op.multiplier, 4)
            changes.append(change(resource.id, "available_units", before, resource.available_units))
            state.external_resource_changes.append(
                dict(
                    event_id=event_id,
                    resource_id=resource.id,
                    tick=state.simulation.tick,
                    before=before,
                    after=resource.available_units,
                    reason="scenario operation stock change",
                )
            )
    trace(
        state,
        "operation",
        f"Resources: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=changes,
        significance=3,
    )
    return {}


def apply_modify_housing_supply(state, op, event_id, permanent, repetition):
    systems = state.systems
    homes = sorted(
        (b for b in state.map.buildings if b.kind == "home" and in_region(b.entrance, op.region)),
        key=lambda b: (unit(op.id, b.id), b.id),
    )
    withdrawn = homes[: round(len(homes) * (1 - op.available_share))]
    undo = {b.id: systems.housing_available.get(b.id, True) for b in withdrawn}
    from app.scenario_engine.world import housing_share, rent_multiplier

    share_before, rent_before = housing_share(state), rent_multiplier(state)
    for building in withdrawn:
        systems.housing_available[building.id] = False
    trace(
        state,
        "operation",
        f"Housing: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=[
            change("housing", "available_share", round(share_before, 3), round(housing_share(state), 3)),
            change("housing", "rent_multiplier", round(rent_before, 3), round(rent_multiplier(state), 3)),
        ],
        affected=[b.id for b in withdrawn],
        significance=3,
    )
    return undo


def revert_modify_housing_supply(state, op, event_id, undo):
    for building_id, available in undo.items():
        state.systems.housing_available[building_id] = available


def apply_broadcast_information(state, op, event_id, permanent, repetition):
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    believed = sum(
        responses.receive_information(state, citizen, op, event_id, repetition) for citizen in audience
    )
    trace(
        state,
        "operation",
        f"Information: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        affected=[c.summary.id for c in audience],
        observations=[f"{believed} of {len(audience)} recipients believed it"],
        significance=3,
    )
    return {}


def apply_adjust_institutional_credibility(state, op, event_id, permanent, repetition):
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    for citizen in audience:
        responses.credibility_shift(state, citizen, op, event_id)
    trace(
        state,
        "operation",
        f"Credibility: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.reason,
        affected=[c.summary.id for c in audience],
        significance=3,
    )
    return {}


def apply_introduce_social_norm(state, op, event_id, permanent, repetition):
    systems = state.systems
    before = systems.norms.get(op.norm, 0)
    systems.norms[op.norm] = max(before, op.strength)
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    for citizen in audience:
        responses.evaluate_norm(state, citizen, op.norm, op.strength, event_id, op.id)
    adopters = sum(1 for c in audience if systems.agents[c.summary.id].norms.get(op.norm, 0) > 0)
    trace(
        state,
        "operation",
        f"Norm: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=[change("norms", op.norm, before, systems.norms[op.norm])],
        affected=[c.summary.id for c in audience],
        observations=[f"{adopters} of {len(audience)} exposed citizens adopted it"],
        significance=3,
    )
    return dict(before=before)


def revert_introduce_social_norm(state, op, event_id, undo):
    state.systems.norms[op.norm] = undo.get("before", 0)


def apply_create_organization(state, op, event_id, permanent, repetition):
    from app.scenario_engine.systems import Organization

    systems = state.systems
    org = Organization(
        id=systems.next_id("organization"),
        kind=op.kind,
        name=op.name,
        mission=op.mission,
        eligibility=op.eligibility,
        region=op.region,
        budget_per_tick=op.budget_per_tick,
        rally_every=op.rally_every,
        created_tick=state.simulation.tick,
        event_id=event_id,
    )
    systems.organizations[org.id] = org
    candidates = [
        c
        for c in state.citizens.values()
        if c.summary.active and responses.eligible(state, c, systems.agents[c.summary.id], org)
    ]
    candidates.sort(
        key=lambda c: (-responses.join_score(state, c, systems.agents[c.summary.id], org), c.summary.id)
    )
    for citizen in (
        candidates[: max(1, round(len(candidates) * op.founding_share))] if op.founding_share else []
    ):
        responses.consider_joining(state, citizen, systems.agents[citizen.summary.id], org, founding=True)
    trace(
        state,
        "operation",
        f"Organization: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.mission or op.rationale,
        affected=[org.id, *org.members],
        observations=[f"{len(org.members)} founding members joined"],
        significance=3,
    )
    return dict(org_id=org.id)


def revert_create_organization(state, op, event_id, undo):
    org = state.systems.organizations.get(undo.get("org_id", ""))
    if org:
        org.active = False


def apply_remove_organization(state, op, event_id, permanent, repetition):
    org = state.systems.organizations.get(op.organization_id)
    org.active = False
    for aid in org.members:
        if aid in state.citizens:
            remember(
                state,
                state.citizens[aid],
                f"{org.name} was dissolved.",
                "observed",
                55,
                proof=evidence("Organization dissolved", event_ids=[event_id] if event_id else None),
            )
    trace(
        state,
        "operation",
        f"Organization: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        affected=[org.id, *org.members],
        significance=3,
    )
    return {}


def apply_set_incentive(state, op, event_id, permanent, repetition):
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    undo = {}
    for citizen in audience:
        agent = state.systems.agents[citizen.summary.id]
        undo[citizen.summary.id] = agent.incentives.get(op.incentive, 0)
        agent.incentives[op.incentive] = op.amount
    trace(
        state,
        "operation",
        f"Incentive: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        affected=[c.summary.id for c in audience],
        significance=3,
    )
    return undo


def revert_set_incentive(state, op, event_id, undo):
    for aid, before in undo.items():
        if aid in state.systems.agents:
            state.systems.agents[aid].incentives[op.incentive] = before


def apply_adjust_population_traits(state, op, event_id, permanent, repetition):
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    if op.selection != "random":
        everyone = select(state, op.audience.model_copy(update=dict(share=1)), op.id)
        everyone.sort(
            key=lambda c: (getattr(c.profile.traits, op.trait), c.summary.id),
            reverse=op.selection == "highest",
        )
        audience = everyone[: len(audience)]
    undo, changes = {}, []
    for citizen in audience:
        before = getattr(citizen.profile.traits, op.trait)
        after = clamp(before + op.delta)
        setattr(citizen.profile.traits, op.trait, after)
        undo[citizen.summary.id] = after - before
        changes.append(change(citizen.summary.id, f"traits.{op.trait}", before, after))
    trace(
        state,
        "operation",
        f"Personality modification: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=changes,
        affected=list(undo),
        significance=3,
    )
    return undo


def revert_adjust_population_traits(state, op, event_id, undo):
    for aid, delta in undo.items():
        citizen = state.citizens.get(aid)
        if citizen:
            setattr(
                citizen.profile.traits, op.trait, clamp(getattr(citizen.profile.traits, op.trait) - delta)
            )


def apply_modify_social_network(state, op, event_id, permanent, repetition):
    audience = select(state, op.audience, f"{op.id}:{repetition}")
    changes = []
    people = sorted(state.citizens.values(), key=lambda c: c.summary.id)
    for citizen in audience:
        if op.action == "connect_strangers":
            strangers = sorted(
                (o for o in people if o is not citizen and o.summary.id not in citizen.relationships),
                key=lambda o: (unit(op.id, citizen.summary.id, o.summary.id), o.summary.id),
            )[: op.ties_per_agent]
            for other in strangers:
                connect(state, citizen, other, "acquaintance")
                connect(state, other, citizen, "acquaintance")
                changes.append(change(citizen.summary.id, "relationship", None, other.summary.id))
        else:
            for tie in citizen.relationships.values():
                before = tie.trust
                tie.trust = clamp(tie.trust - 10)
                tie.affection = clamp(tie.affection - 5)
                tie.evidence = evidence(
                    "Scenario weakened existing ties", event_ids=[event_id] if event_id else None
                )
                changes.append(change(citizen.summary.id, f"trust:{tie.to_agent_id}", before, tie.trust))
    trace(
        state,
        "operation",
        f"Network: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        changes=changes,
        affected=[c.summary.id for c in audience],
        significance=3,
    )
    return {}


def apply_physical_hazard(state, op, event_id, permanent, repetition):
    trace(
        state,
        "operation",
        f"Hazard: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        observations=["Physical effects run through the event's hazard mechanics"],
        significance=3,
    )
    return {}


def apply_community_gathering(state, op, event_id, permanent, repetition):
    trace(
        state,
        "operation",
        f"Gathering: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        observations=["Runs through the event's community mechanics"],
        significance=3,
    )
    return {}


def apply_catalog_event(state, op, event_id, permanent, repetition):
    trace(
        state,
        "operation",
        f"Catalog event: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        observations=["Scenery and the registered effects run through the event's existing mechanics"],
        significance=3,
    )
    return {}


def apply_environmental_condition(state, op, event_id, permanent, repetition):
    state.systems.conditions.append(
        dict(op_id=op.id, condition=op.condition, region=op.region, intensity=op.intensity, event_id=event_id)
    )
    trace(
        state,
        "operation",
        f"Condition: {describe(op)}",
        event_id=event_id,
        op_id=op.id,
        motivation=op.rationale,
        significance=3,
    )
    return {}


def revert_environmental_condition(state, op, event_id, undo):
    state.systems.conditions = [c for c in state.systems.conditions if c["op_id"] != op.id]
    for agent in state.systems.agents.values():
        agent.conditions.pop(op.id, None)
