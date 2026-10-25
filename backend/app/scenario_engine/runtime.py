"""Tick integration: schedule operations, run world systems and feed the analyzer."""

from app.scenario_engine import mutations, outcomes, responses
from app.scenario_engine.registry import OPERATIONS, ScenarioPlan
from app.scenario_engine.systems import (
    FOOD_PRICE,
    HOSPITAL_UPKEEP,
    SHOP_PRODUCTION,
    SHOP_STOCK_MAX,
    STRAIN_WALLET,
    TRANSIT_OPERATING_COST,
    PlanRecord,
    Scheduled,
    bump,
    in_region,
    unit,
)
from app.scenario_engine.world import enable, rent_for, sync_agents, trace, walking_speed
from app.simulation.agents import clamp, evidence, metric_delta, remember
from app.simulation.timing import legacy_ticks

SERVICE_FAILURES = {"CAPACITY", "INFRASTRUCTURE_UNAVAILABLE", "UNREACHABLE"}
IRREVERSIBLE = {
    "broadcast_information",
    "adjust_institutional_credibility",
    "modify_resource_stock",
    "modify_social_network",
    "remove_organization",
    "physical_hazard",
    "community_gathering",
    "catalog_event",
}


def attach(state, event_id, plan):
    """Queue a validated plan with its event. Systems start now so the baseline is measured."""
    enable(state)
    state.systems.plans[event_id] = PlanRecord(event_id=event_id, plan=plan.model_dump(mode="json"))
    trace(
        state,
        "operation",
        f"Scenario queued: {plan.title}",
        event_id=event_id,
        motivation=plan.description,
        significance=3,
    )


def on_tick_start(state):
    systems = state.systems
    if not systems.enabled:
        return
    sync_agents(state)
    for event_id, record in systems.plans.items():
        runtime = state.events.get(event_id)
        if record.status == "queued" and runtime and runtime.summary.status == "active":
            activate_plan(state, record, runtime)
    process_schedule(state)


def activate_plan(state, record, runtime):
    from app.snowflake.observations_projection import capture_baseline

    # The core activation path records earlier, before any physical effects.
    # Preserve that baseline when a scenario plan shares the same event.
    if runtime.observation_baseline is None:
        runtime.observation_baseline = capture_baseline(state)
    systems = state.systems
    plan = ScenarioPlan.model_validate(record.plan)
    now = state.simulation.tick
    record.counters = outcomes.snapshot_counters(state)
    record.baseline = outcomes.baseline(state)
    record.policy_before = systems.policy.model_dump()
    record.activated_tick = now
    record.status = "active"
    record.cohort = [aid for aid, c in state.citizens.items() if c.summary.active]
    # Plan timings are authored in ten-second steps.
    k = legacy_ticks(state, 1)
    for op in plan.operations:
        timing = op.timing
        every = timing.repeat_every or 0
        repetitions = 1 + (timing.repeat_count or 0) if every else 1
        duration = timing.duration_ticks or (None if plan.duration == "permanent" else plan.measurement_ticks)
        permanent = duration is None
        data = op.model_dump(mode="json")
        for repetition in range(repetitions):
            systems.schedule.append(
                Scheduled(
                    tick=now + (timing.start_tick + repetition * every) * k,
                    event_id=record.event_id,
                    op=data,
                    action="apply",
                    repetition=repetition,
                    permanent=permanent,
                )
            )
        if duration and op.type not in IRREVERSIBLE:
            systems.schedule.append(
                Scheduled(
                    tick=now + (timing.start_tick + (repetitions - 1) * every + duration) * k,
                    event_id=record.event_id,
                    op=data,
                    action="revert",
                )
            )
    trace(
        state,
        "operation",
        f"Scenario active: {plan.title}",
        event_id=record.event_id,
        motivation=plan.description,
        significance=3,
    )


def process_schedule(state):
    systems = state.systems
    now = state.simulation.tick
    due = [entry for entry in systems.schedule if entry.tick <= now]
    if not due:
        return
    systems.schedule = [entry for entry in systems.schedule if entry.tick > now]
    for entry in sorted(due, key=lambda e: (e.tick, e.action == "revert")):
        if entry.action == "apply":
            undo = mutations.apply(state, entry, entry.permanent)
            for pending in systems.schedule:
                if (
                    pending.action == "revert"
                    and pending.event_id == entry.event_id
                    and pending.op["id"] == entry.op["id"]
                ):
                    merge_undo(pending.undo, undo)
        else:
            mutations.revert(state, entry)


def merge_undo(target, undo):
    if "after" in undo:
        target.setdefault("before", undo.get("before"))
        target["after"] = undo["after"]
        return
    for key, value in undo.items():
        target.setdefault(key, value)


def after_decision(state, citizen, decision):
    systems = state.systems
    if not systems.enabled:
        return
    agent = systems.agents.get(citizen.summary.id)
    if agent is None:
        return
    action = decision.intent.action
    target = decision.intent.target_id or ""
    if action in {"move", "evacuate"} and target.startswith("building"):
        bump(systems, "service_attempts")
        if decision.outcome != "rejected":
            bump(systems, "service_success")
    if decision.outcome == "rejected":
        if (
            action in {"move", "evacuate"}
            and target.startswith("building")
            and decision.rejection_code not in SERVICE_FAILURES
        ):
            bump(systems, "service_attempts", -1)
        return
    if action in {"move", "evacuate"}:
        responses.choose_trip_mode(state, citizen, agent, decision)
    elif action == "work":
        responses.on_work(state, citizen, agent, decision)
    elif action == "gather" and decision.intent.parameters.resource_kind == "food":
        bump(systems, "food_gathered", decision.intent.parameters.amount or 0)
    elif action in {"help", "trade"} and (action == "help" or "Both parties" in decision.outcome_description):
        reward = systems.policy.community_programs.cooperation_reward + agent.incentives.get("help_reward", 0)
        if reward and systems.treasury > -30:
            agent.wallet = round(agent.wallet + reward, 4)
            systems.treasury -= reward
            bump(systems, "cooperation_rewards", reward)
    elif action == "talk" and "Both participants accepted" in decision.outcome_description:
        other = state.citizens.get(target)
        if other is not None:
            responses.share_in_conversation(state, citizen, other, decision)


def after_tick(state):
    from app.behavior.rules import RULES
    from app.behavior.vitals import conscious, evaluate, impact, living

    systems = state.systems
    if not systems.enabled:
        return
    policy = systems.policy
    dt = state.simulation.config.tick_seconds / 10
    buildings = {b.id: b for b in state.map.buildings}
    funding = mutations.funding_level(state)
    shortfall = systems.treasury < -30
    for citizen in state.citizens.values():
        agent = systems.agents.get(citizen.summary.id)
        evaluate(state, citizen, "Before city-system effects")
        if not living(citizen) or agent is None:
            continue
        if agent.trip_mode and not citizen.summary.path:
            citizen.summary.movement_speed_mps = walking_speed(citizen)
            agent.trip_mode = None
        rent = rent_for(state, agent) * dt
        if rent:
            paid = min(rent, max(0.0, agent.wallet))
            agent.wallet = round(agent.wallet - paid, 4)
            systems.businesses["landlords"] = systems.businesses.get("landlords", 0) + paid
            bump(systems, "rent_paid", paid)
        if (
            agent.housing_status == "seeking_assistance"
            and policy.housing.assistance_per_tick
            and not shortfall
        ):
            agent.wallet += policy.housing.assistance_per_tick
            systems.treasury -= policy.housing.assistance_per_tick
            bump(systems, "assistance_paid", policy.housing.assistance_per_tick)
        if (
            agent.incentives.get("conservation_bonus")
            and sum(citizen.inventory.model_dump().values()) <= citizen.target_inventory_units
        ):
            bonus = agent.incentives["conservation_bonus"] * 0.1 * dt
            agent.wallet += bonus
            systems.treasury -= bonus
        inside = buildings.get(citizen.inside_building_id or "")
        if inside and inside.functional and inside.kind == "shop" and conscious(citizen):
            shop(state, citizen, agent, inside)
        # Admitted patients use the physical care engine exactly once. Conscious
        # walk-in care also consumes real hospital supplies; location alone is
        # never permission to heal an unconscious or terminal patient for free.
        if (
            inside
            and inside.functional
            and inside.kind == "hospital"
            and conscious(citizen)
            and citizen.condition.care != "hospital"
        ):
            hospital = state.behavior.hospitals.get(inside.id)
            units = RULES["treatment_units"] * funding * dt
            if hospital and units > 0 and hospital.inventory.supplies >= units and citizen.needs.health < 100:
                hospital.inventory.supplies -= units
                state.counters["resources_consumed"] += units
                impact(
                    state, citizen, "health", 0.35 * funding * dt, "Funded walk-in hospital supplies", "care"
                )
                bump(systems, "hospital_care")
                if agent.conditions.get("illness") is not None and state.simulation.tick - agent.conditions[
                    "illness"
                ] >= legacy_ticks(state, 6):
                    agent.conditions.pop("illness")
        wellbeing(state, citizen, agent, inside)
        if not living(citizen):
            continue
        if agent.wallet < STRAIN_WALLET:
            proof = evidence(f"Financial strain: wallet below {STRAIN_WALLET:g} credits")
            metric_delta(citizen, "stress", 0.25 * dt, proof)
            metric_delta(citizen, "happiness", -0.15 * dt, proof)
        if conscious(citizen):
            responses.review(state, citizen)
    organizations(state)
    systems.treasury -= TRANSIT_OPERATING_COST * policy.transportation.transit_service_level * dt
    systems.treasury -= HOSPITAL_UPKEEP * max(0.0, funding - 1) * dt
    for building_id, stock in systems.shop_stock.items():
        building = buildings.get(building_id)
        if building and building.functional and stock < SHOP_STOCK_MAX:
            systems.shop_stock[building_id] = min(SHOP_STOCK_MAX, stock + SHOP_PRODUCTION * dt)
            bump(systems, "shop_production", SHOP_PRODUCTION * dt)
    if systems.treasury < -30:
        bump(systems, "shortfall_ticks")
    systems.treasury = round(systems.treasury, 4)


def shop(state, citizen, agent, building):
    systems = state.systems
    agent.shop_visits[building.id] = agent.shop_visits.get(building.id, 0) + 1
    agent.regular_shop = max(agent.shop_visits, key=lambda k: (agent.shop_visits[k], k))
    limit = 5 if responses.inventory_floor(state, citizen) > 2 else 3
    if (
        state.simulation.tick - agent.last_purchase_tick < legacy_ticks(state, 8)
        or citizen.inventory.food >= limit
    ):
        return
    price = round(FOOD_PRICE * systems.policy.business.price_level, 4)
    bump(systems, "service_attempts")
    if systems.shop_stock.get(building.id, 0) < 1:
        bump(systems, "sold_out")
        return
    if agent.wallet < price:
        return
    bump(systems, "service_success")
    expected = agent.last_paid.get("food", FOOD_PRICE)
    agent.wallet = round(agent.wallet - price, 4)
    tax = price * systems.policy.taxation.business_tax_rate
    systems.businesses[building.id] = systems.businesses.get(building.id, 0) + price - tax
    systems.treasury += tax
    systems.shop_stock[building.id] -= 1
    citizen.inventory.food += 1
    agent.last_purchase_tick = state.simulation.tick
    agent.last_paid["food"] = price
    bump(systems, "food_bought")
    if abs(expected - price) > 1e-9:
        remember(
            state,
            citizen,
            f"Food at {building.name} cost {price:.2f} credits; it used to be {expected:.2f}.",
            "observed",
            50,
            proof=evidence("Paid a changed shop price"),
        )


def probability_for_tick(state, legacy_probability):
    """Preserve the event hazard per simulated second across tick sizes."""
    return 1 - (1 - legacy_probability) ** (state.simulation.config.tick_seconds / 10)


def wellbeing(state, citizen, agent, inside):
    """Everyday illness, ageing and regional conditions; care and shelter mitigate them."""
    from app.behavior.vitals import evaluate, impact, living

    def health(delta, reason, proof=None):
        impact(state, citizen, "health", delta, reason, "scenario", proof)
        evaluate(state, citizen, reason, proof)
        return living(citizen)

    tick = state.simulation.tick
    dt = state.simulation.config.tick_seconds / 10
    age = citizen.profile.age
    if "illness" not in agent.conditions:
        chance = 0.003 + 0.004 * max(0, age - 50) / 30
        if unit(citizen.summary.id, tick, "illness") < probability_for_tick(state, chance):
            agent.conditions["illness"] = tick
            if not health(-12, "Fell ill"):
                return
            remember(state, citizen, "I am feeling unwell.", "observed", 60, proof=evidence("Fell ill"))
            bump(state.systems, "illnesses")
    elif not (inside and inside.kind == "hospital"):
        since = tick - agent.conditions["illness"]
        if not health((-0.1 if since < legacy_ticks(state, 40) else 0.3) * dt, "Ongoing illness"):
            return
        if since >= legacy_ticks(state, 70):
            agent.conditions.pop("illness")
    if age > 60:
        if not health(-0.01 * (age - 60) / 20 * dt, "Age-related city-system pressure"):
            return
    for condition in state.systems.conditions:
        here = in_region(citizen.summary.position, condition["region"])
        key = condition["op_id"]
        if not here:
            agent.conditions.pop(key, None)
            continue
        agent.conditions[key] = tick
        strength = condition["intensity"] / 100
        proof = evidence(f"Exposure to {condition['condition']}", event_ids=[condition["event_id"]])
        sheltered = inside is not None
        kind = condition["condition"]
        if kind in {"heat", "cold"} and not sheltered:
            if not health(-0.05 * strength * dt, f"Exposure to {kind}", proof):
                return
            metric_delta(citizen, "stress", 0.3 * strength * dt, proof)
        elif kind == "pollution":
            if not health(-0.03 * strength * dt, "Exposure to pollution", proof):
                return
            metric_delta(citizen, "stress", 0.15 * strength * dt, proof)
        elif kind == "noise" and not sheltered:
            metric_delta(citizen, "stress", 0.3 * strength * dt, proof)
        elif kind == "illness" and "illness" not in agent.conditions:
            if unit(citizen.summary.id, tick, key) < probability_for_tick(state, 0.02 * strength):
                agent.conditions["illness"] = tick
                if not health(-12, "Scenario illness", proof):
                    return
                bump(state.systems, "illnesses")


def organizations(state):
    from app.behavior.vitals import conscious

    systems = state.systems
    tick = state.simulation.tick
    dt = state.simulation.config.tick_seconds / 10
    for org in systems.organizations.values():
        if not org.active or not org.members:
            continue
        members = [
            state.citizens[aid]
            for aid in org.members
            if aid in state.citizens and conscious(state.citizens[aid])
        ]
        if org.kind == "mutual_aid" and (tick - org.created_tick) % legacy_ticks(state, 6) == 0:
            for donor in members:
                surplus = max(("supplies", "food"), key=lambda k: getattr(donor.inventory, k))
                if donor.inventory.supplies + donor.inventory.food > 8:
                    setattr(donor.inventory, surplus, getattr(donor.inventory, surplus) - 1)
                    org.pool += 1
            for recipient in sorted(members, key=lambda c: (c.summary.metrics.resources, c.summary.id)):
                if org.pool < 1 or recipient.summary.metrics.resources >= 35:
                    break
                org.pool -= 1
                recipient.inventory.supplies += 1
                bump(systems, "aid_transfers")
                remember(
                    state,
                    recipient,
                    f"{org.name} gave me supplies from its shared pool.",
                    "observed",
                    55,
                    proof=evidence("Mutual aid transfer", event_ids=[org.event_id] if org.event_id else None),
                )
        elif org.kind in {"tenant_union", "protest_group"} and responses.rallying(state, org):
            center_ids = {b.id for b in state.map.buildings if b.kind == "community"}
            present = [c for c in members if c.inside_building_id in center_ids]
            proof = evidence(
                f"Took part in the {org.name} gathering", event_ids=[org.event_id] if org.event_id else None
            )
            for citizen in present:
                citizen.needs.social = clamp(citizen.needs.social - 2 * dt)
                metric_delta(citizen, "happiness", 0.2 * dt, proof)
            if (tick - org.created_tick) % legacy_ticks(state, org.rally_every) == legacy_ticks(
                state, 3
            ) and present:
                observers = [
                    c
                    for c in state.citizens.values()
                    if c.summary.active
                    and c.summary.id not in org.members
                    and c.inside_building_id in center_ids
                    and systems.agents.get(c.summary.id)
                    and systems.agents[c.summary.id].institutional_trust > 60
                ]
                for observer in observers:
                    member = min(present, key=lambda c: c.summary.id)
                    tie = observer.relationships.get(member.summary.id)
                    if tie:
                        tie.conflict = clamp(tie.conflict + 2)
                    metric_delta(
                        observer, "stress", 0.5, evidence(f"Disagreed with the {org.name} gathering")
                    )
                    bump(systems, "rally_conflicts")
                    trace(
                        state,
                        "decision",
                        f"Disagreed with the {org.name} gathering",
                        event_id=org.event_id,
                        agent=observer,
                        selected="object",
                        motivation="I trust the institutions they criticize",
                        affected=[member.summary.id],
                        significance=1,
                    )
                bump(systems, "rally_demands", len(present))
        elif (
            org.kind in {"community_program", "assistance_office"}
            and org.budget_per_tick
            and systems.treasury > -30
        ):
            recipients = [
                c
                for c in members
                if org.kind == "community_program"
                or systems.agents[c.summary.id].housing_status == "seeking_assistance"
            ] or members
            share = org.budget_per_tick / len(recipients)
            for citizen in recipients:
                systems.agents[citizen.summary.id].wallet += share
            systems.treasury -= org.budget_per_tick
            org.paid += org.budget_per_tick


def after_finish(state, resolved):
    systems = state.systems
    if not systems.enabled:
        return
    for event_id, record in systems.plans.items():
        runtime = state.events.get(event_id)
        if record.status != "active" or runtime is None:
            continue
        outcomes.record_point(state, record)
        if runtime.summary.status == "resolved":
            outcomes.finalize(state, record, runtime)
    if resolved:
        distribution = systems.policy.resource_distribution
        state.policies.ration_units_per_agent = distribution.ration_units_per_agent
        state.policies.aid_multiplier = distribution.aid_multiplier
        state.policies.evacuation_order = distribution.evacuation_order >= 0.5


def physical(op_type):
    return OPERATIONS[op_type][2]
