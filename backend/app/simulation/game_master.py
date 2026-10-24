"""Deterministic intent validation and atomic, conserved consequences."""

import math

from app.contracts import Decision, EffectChange, Intent, Parameters, Vec2
from app.simulation.agents import (
    clamp,
    evidence,
    hazard_severity,
    metric_delta,
    perception,
    remember,
    social_delta,
)
from app.simulation.interactions import accept_invitation, coordinate_aid, speak
from app.simulation.navigation import cell_at, distance, line_of_sight, pathfind
from app.simulation.scenarios import blocked_cells

ACTION_REGISTRY = {
    "idle": {"local": True},
    "rest": {"local": True},
    "move": {"destination": True},
    "evacuate": {"destination": True},
    "work": {"target": "building"},
    "gather": {"target": "resource", "resource": True, "amount": True},
    "consume": {"resource": True, "amount": True},
    "help": {"target": "agent"},
    "talk": {"target": "agent"},
    "warn": {"target": "agent"},
    "trade": {"target": "agent", "resource": True, "amount": True},
}


def make_intent(
    action,
    *,
    target=None,
    destination=None,
    kind=None,
    amount=None,
    message=None,
    motivation="Meet my current needs",
    emotion="calm",
):
    return Intent(
        action=action,
        target_id=target,
        destination=destination,
        parameters=Parameters(resource_kind=kind, amount=amount, message=message),
        motivation=motivation,
        emotion=emotion,
    )


class Rejected(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def check(condition, code, message):
    if not condition:
        raise Rejected(code, message)


def apply_intent(state, citizen, intent, source="rules", context=None):
    context = context or perception(state, citizen)
    did = state.next_id("decision")
    decision = Decision(
        id=did,
        agent_id=citizen.summary.id,
        tick=state.simulation.tick,
        source=source,
        intent=intent,
        observed_facts=context["facts"],
        memory_ids=[m.id for m in context["memories"]],
        relationship_agent_ids=[r.to_agent_id for r in context["relationships"]],
        concise_rationale=intent.motivation,
        outcome="accepted",
        outcome_description="Action completed",
        rejection_code=None,
        effects=[],
        event_ids=[],
    )
    proof = evidence(intent.motivation, decision_ids=[did])
    changes = []

    def change(entity, field, before, after):
        if before != after:
            changes.append(EffectChange(entity_id=entity, field=field, before=before, after=after))

    def inventory_delta(actor, kind, delta):
        before = getattr(actor.inventory, kind)
        setattr(actor.inventory, kind, max(0, before + delta))
        change(actor.summary.id, "inventory." + kind, before, getattr(actor.inventory, kind))

    try:
        registry = ACTION_REGISTRY[intent.action]
        if registry.get("amount"):
            check(
                intent.parameters.amount is not None and intent.parameters.amount > 0,
                "MISSING_AMOUNT",
                "A positive amount is required",
            )
        if registry.get("resource"):
            check(
                intent.parameters.resource_kind is not None, "MISSING_RESOURCE", "A resource kind is required"
            )
        kind, amount = intent.parameters.resource_kind, intent.parameters.amount
        target = state.citizens.get(intent.target_id)
        if registry.get("target") == "agent":
            check(
                target is not None and target.summary.active and target.summary.id != citizen.summary.id,
                "UNKNOWN_TARGET",
                "Target must be another active citizen",
            )
            check(
                target.summary.id in context["nearby_ids"],
                "UNOBSERVED_TARGET",
                "Target is not currently visible",
            )
            check(
                distance(citizen.summary.position, target.summary.position) <= 3,
                "OUT_OF_RANGE",
                "Physical interactions require a distance of at most 3 meters",
            )
        action = intent.action
        if action in {"move", "evacuate"}:
            destination = intent.destination
            if destination is None and intent.target_id:
                destination = citizen.known_locations.get(intent.target_id)
                if target is not None and target.summary.id in context["nearby_ids"]:
                    destination = target.summary.position
            check(
                destination is not None,
                "MISSING_DESTINATION",
                "Movement requires a destination or a known target location",
            )
            route = pathfind(state.map, citizen.summary.position, destination, blocked_cells(state))
            check(route is not None, "UNREACHABLE", "Destination is not reachable through navigable cells")
            if action == "evacuate":
                check(
                    hazard_severity(state, destination) == 0,
                    "UNSAFE_DESTINATION",
                    "Evacuation destination is hazardous",
                )
                building = next(
                    (b for b in state.map.buildings if distance(destination, b.entrance) <= 0.1), None
                )
                if building:
                    reserved = {
                        other.summary.id
                        for other in state.citizens.values()
                        if other.summary.active
                        and other.summary.id != citizen.summary.id
                        and (
                            distance(other.summary.position, building.entrance) <= 3
                            or (
                                other.summary.action == "evacuate"
                                and other.summary.action_target_id == building.id
                                and other.summary.path
                            )
                        )
                    }
                    check(
                        building.functional and len(reserved) < building.capacity,
                        "CAPACITY",
                        "Safe facility is unavailable or full",
                    )
            citizen.summary.path = route
            citizen.plan = intent.model_dump()
            decision.outcome_description = "Path accepted; movement is bounded by speed and tick duration"
        elif action == "rest":
            before = citizen.needs.fatigue
            citizen.needs.fatigue = clamp(before - 6)
            change(citizen.summary.id, "needs.fatigue", before, citizen.needs.fatigue)
            metric_delta(citizen, "stress", -0.6, proof)
        elif action == "consume":
            check(
                getattr(citizen.inventory, kind) >= amount,
                "INSUFFICIENT_INVENTORY",
                "Not enough personal inventory",
            )
            inventory_delta(citizen, kind, -amount)
            state.counters["resources_consumed"] += amount
            if kind in {"food", "water"}:
                before = citizen.needs.hunger
                citizen.needs.hunger = clamp(before - amount * 12)
                change(citizen.summary.id, "needs.hunger", before, citizen.needs.hunger)
            else:
                before = citizen.needs.health
                citizen.needs.health = clamp(before + amount * 2)
                change(citizen.summary.id, "needs.health", before, citizen.needs.health)
            metric_delta(citizen, "happiness", 0.4, proof)
        elif action == "gather":
            resource = next((r for r in state.map.resources if r.id == intent.target_id), None)
            check(
                resource is not None and resource.id in citizen.known_locations,
                "UNKNOWN_TARGET",
                "Unknown resource source",
            )
            check(resource.kind == kind, "RESOURCE_MISMATCH", "Resource source has a different kind")
            check(
                distance(citizen.summary.position, resource.position) <= 3,
                "OUT_OF_RANGE",
                "Gather requires proximity to the source",
            )
            if state.policies.ration_units_per_agent is not None:
                already = sum(
                    d.intent.parameters.amount or 0
                    for d in state.decisions
                    if d.agent_id == citizen.summary.id
                    and d.tick == state.simulation.tick
                    and d.intent.action == "gather"
                    and d.outcome == "accepted"
                )
                check(
                    amount + already <= state.policies.ration_units_per_agent,
                    "RATION_LIMIT",
                    "Amount exceeds the per-tick ration",
                )
            check(
                resource.available_units >= amount,
                "RESOURCE_CONTESTED",
                "The requested stock is no longer available",
            )
            before = resource.available_units
            resource.available_units -= amount
            change(resource.id, "available_units", before, resource.available_units)
            inventory_delta(citizen, kind, amount)
        elif action == "work":
            workplace = next((b for b in state.map.buildings if b.id == intent.target_id), None)
            check(
                workplace is not None and workplace.kind == "work",
                "UNKNOWN_TARGET",
                "Work needs a known workplace",
            )
            check(workplace.functional, "INFRASTRUCTURE_UNAVAILABLE", "Workplace is not functional")
            check(
                distance(citizen.summary.position, workplace.entrance) <= 3,
                "OUT_OF_RANGE",
                "Work requires proximity to a workplace",
            )
            # Rotate conflict ordering in engine; capacities are checked at the atomic boundary.
            working = sum(
                d.tick == state.simulation.tick
                and d.intent.action == "work"
                and d.intent.target_id == workplace.id
                and d.outcome == "accepted"
                for d in state.decisions
            )
            check(working < workplace.capacity, "CAPACITY", "Workplace is at capacity")
            # Work draws stock from the supply depot; it never creates unlogged resources.
            depot = next(
                (r for r in state.map.resources if r.kind == "supplies" and r.available_units >= 0.25), None
            )
            check(depot is not None, "RESOURCE_CONTESTED", "No supply stock remains for work yield")
            before = depot.available_units
            depot.available_units -= 0.25
            change(depot.id, "available_units", before, depot.available_units)
            inventory_delta(citizen, "supplies", 0.25)
            metric_delta(citizen, "happiness", 0.2, proof)
        elif action == "help":
            check(citizen.inventory.supplies >= 1, "INSUFFICIENT_INVENTORY", "Help requires one supply unit")
            inventory_delta(citizen, "supplies", -1)
            state.counters["resources_consumed"] += 1
            before = target.needs.health
            target.needs.health = clamp(before + 5 * state.policies.aid_multiplier)
            change(target.summary.id, "needs.health", before, target.needs.health)
            metric_delta(target, "stress", -2, proof)
            metric_delta(citizen, "happiness", 1, proof)
            social_delta(state, target, citizen, did, 3)
            social_delta(state, citizen, target, did, 1)
            remember(
                state,
                target,
                f"{citizen.summary.name} helped me with supplies.",
                subjects=[citizen.summary.id],
                proof=proof,
            )
            state.counters["cooperation_count"] += 1
            coordinate_aid(state, citizen, target, did)
        elif action == "trade":
            check(
                getattr(citizen.inventory, kind) >= amount,
                "INSUFFICIENT_INVENTORY",
                "Trade offer exceeds personal inventory",
            )
            pending = next(
                (
                    i
                    for i in state.interactions.values()
                    if i.kind == "trade"
                    and i.status == "invited"
                    and i.initiator_id == target.summary.id
                    and citizen.summary.id in i.participant_ids
                    and i.expires_tick >= state.simulation.tick
                ),
                None,
            )
            if pending:
                check(
                    getattr(target.inventory, pending.proposal["resource"]) >= pending.proposal["amount"],
                    "INSUFFICIENT_INVENTORY",
                    "The original offer is no longer available",
                )
            interaction, accepted = accept_invitation(
                state, citizen, target, "trade", dict(resource=kind, amount=amount)
            )
            if not accepted:
                decision.outcome_description = (
                    "Trade offered; no transfer occurs until explicit recipient acceptance"
                )
            else:
                offered_kind, offered_amount = (
                    interaction.proposal["resource"],
                    interaction.proposal["amount"],
                )
                check(
                    getattr(target.inventory, offered_kind) >= offered_amount,
                    "INSUFFICIENT_INVENTORY",
                    "The original offer is no longer available",
                )
                # Both sides are fully validated before either debit.
                inventory_delta(target, offered_kind, -offered_amount)
                inventory_delta(citizen, offered_kind, offered_amount)
                inventory_delta(citizen, kind, -amount)
                inventory_delta(target, kind, amount)
                interaction.status = "ended"
                state.counters["cooperation_count"] += 1
                social_delta(state, target, citizen, did, 2)
                social_delta(state, citizen, target, did, 2)
                decision.outcome_description = "Both parties accepted; resource exchange committed atomically"
        elif action in {"talk", "warn"}:
            interaction, accepted = accept_invitation(state, citizen, target, "conversation")
            # Warning is one-way speech; a conversation begins with an invitation.
            speak(state, citizen, target, intent, did, interaction)
            citizen.needs.social = clamp(citizen.needs.social - 5)
            metric_delta(citizen, "happiness", 0.3, proof)
        citizen.summary.action = action
        citizen.summary.action_target_id = intent.target_id
        citizen.summary.emotion = intent.emotion
        citizen.summary.thought_bubble = intent.motivation[:2000]
    except Rejected as rejection:
        decision.outcome = "rejected"
        decision.outcome_description = rejection.message
        decision.rejection_code = rejection.code
        if rejection.code == "RESOURCE_CONTESTED":
            state.counters["conflict_count"] += 1
        changes = []
    decision.effects = changes
    citizen.summary.latest_decision_id = did
    state.decisions.append(decision)
    if decision.outcome != "rejected" and intent.action not in {"idle", "move", "rest"}:
        remember(
            state,
            citizen,
            f"I chose to {intent.action}: {decision.outcome_description}",
            importance=40,
            proof=proof,
        )
    return decision


def advance_movement(state, citizen):
    remaining = citizen.summary.movement_speed_mps * state.simulation.config.tick_seconds
    blocked = blocked_cells(state)
    while remaining > 1e-8 and citizen.summary.path:
        destination = citizen.summary.path[0]
        cell = cell_at(state.map, destination)
        if cell is None or not cell.walkable or (cell.col, cell.row) in blocked:
            citizen.summary.path = []
            citizen.plan = None
            citizen.task_generation += 1
            break
        origin = citizen.summary.position
        length = distance(origin, destination)
        citizen.summary.heading_rad = math.atan2(destination.x - origin.x, destination.y - origin.y) % (
            2 * math.pi
        )
        if length <= remaining + 1e-8:
            citizen.summary.position = destination.model_copy()
            citizen.summary.path.pop(0)
            remaining -= length
        else:
            scale = remaining / length
            citizen.summary.position = Vec2(
                x=origin.x + (destination.x - origin.x) * scale,
                y=origin.y + (destination.y - origin.y) * scale,
            )
            remaining = 0
    if not citizen.summary.path:
        citizen.plan = None


def rule_intent(state, citizen, context):
    p = citizen.summary.position
    nearby = [state.citizens[aid] for aid in context["nearby_ids"]]
    threatened = hazard_severity(state, p) > 0 or state.policies.evacuation_order
    visible_victims = [
        other
        for other in nearby
        if distance(p, other.summary.position) <= 3
        and (other.needs.health < 95 or hazard_severity(state, other.summary.position) > 0)
    ]
    if (
        visible_victims
        and citizen.inventory.supplies >= 1
        and citizen.needs.health > 60
        and citizen.profile.traits.empathy >= 65
    ):
        victim = max(
            visible_victims,
            key=lambda other: (
                citizen.relationships.get(other.summary.id).affection
                if other.summary.id in citizen.relationships
                else 0
            ),
        )
        # Never access unknown remote positions; help is limited to perceived nearby targets.
        return make_intent(
            "help",
            target=victim.summary.id,
            motivation="Someone I can see needs help and I have supplies",
            emotion="concerned",
        )
    if threatened:
        safe = [
            b
            for b in state.map.buildings
            if b.functional
            and b.capacity > b.occupancy
            and hazard_severity(state, b.entrance) == 0
            and b.id in citizen.known_locations
        ]
        for building in sorted(safe, key=lambda b: distance(p, b.entrance)):
            if pathfind(state.map, p, building.entrance, blocked_cells(state)) is not None:
                return make_intent(
                    "evacuate",
                    target=building.id,
                    destination=building.entrance,
                    motivation="Reach a known safe facility",
                    emotion="alert",
                )
        return make_intent(
            "rest", motivation="No safe reachable route is currently available", emotion="worried"
        )
    if citizen.summary.path:
        return None
    if citizen.needs.hunger >= 45:
        for kind in ("food", "water"):
            if getattr(citizen.inventory, kind) >= 1:
                return make_intent("consume", kind=kind, amount=1, motivation="I need to eat or drink")
    if citizen.needs.fatigue >= 65:
        return make_intent("rest", motivation="I need to recover my energy")
    # Explicit recipient acceptance of a remembered nearby invitation.
    for invitation in state.interactions.values():
        if (
            invitation.kind == "trade"
            and invitation.status == "invited"
            and citizen.summary.id in invitation.participant_ids
            and citizen.summary.id != invitation.initiator_id
            and invitation.initiator_id in context["nearby_ids"]
        ):
            other = state.citizens[invitation.initiator_id]
            if (
                distance(p, other.summary.position) <= 3
                and citizen.inventory.water >= 1
                and citizen.profile.traits.cooperation >= 40
            ):
                return make_intent(
                    "trade",
                    target=other.summary.id,
                    kind="water",
                    amount=1,
                    motivation="Accept a nearby exchange of essential supplies",
                )
    # Give a nearby speaker a reply before starting another routine task.
    for conversation in state.interactions.values():
        if (
            conversation.kind == "conversation"
            and conversation.status in {"invited", "accepted"}
            and conversation.expires_tick >= state.simulation.tick
            and citizen.summary.id in conversation.participant_ids
        ):
            lines = [d for d in state.dialogue if d.interaction_id == conversation.id]
            if lines and lines[-1].speaker_id != citizen.summary.id:
                speaker = state.citizens.get(lines[-1].speaker_id)
                if (
                    speaker is not None
                    and speaker.summary.id in context["nearby_ids"]
                    and distance(p, speaker.summary.position) <= 3
                ):
                    return make_intent(
                        "talk",
                        target=speaker.summary.id,
                        motivation="Reply to the neighbor who just spoke to me",
                    )
    scarce = min(("food", "water", "supplies"), key=lambda kind: getattr(citizen.inventory, kind))
    if getattr(citizen.inventory, scarce) < 2:
        sources = [
            r
            for r in state.map.resources
            if r.kind == scarce
            and r.id in citizen.known_locations
            and (
                distance(p, r.position) > 20
                or not line_of_sight(state.map, p, r.position)
                or r.available_units > 0
            )
        ]
        for resource in sorted(sources, key=lambda r: distance(p, r.position)):
            if distance(p, resource.position) <= 3:
                amount = min(
                    1,
                    resource.available_units,
                    state.policies.ration_units_per_agent
                    if state.policies.ration_units_per_agent is not None
                    else 1,
                )
                if amount > 0:
                    return make_intent(
                        "gather",
                        target=resource.id,
                        kind=scarce,
                        amount=amount,
                        motivation="Replenish essential household supplies",
                    )
            elif pathfind(state.map, p, resource.position, blocked_cells(state)) is not None:
                return make_intent(
                    "move",
                    target=resource.id,
                    destination=resource.position,
                    motivation="Walk to a known resource source",
                )
    if nearby and citizen.profile.traits.sociability > 40 and citizen.needs.social > 20:
        close = [c for c in nearby if distance(p, c.summary.position) <= 3]
        if close:
            return make_intent("talk", target=close[0].summary.id, motivation="Check on a nearby neighbor")
    if citizen.profile.traits.cooperation >= 40:
        workplace = min(
            (b for b in state.map.buildings if b.kind == "work" and b.functional),
            key=lambda b: distance(p, b.entrance),
            default=None,
        )
        if workplace:
            if distance(p, workplace.entrance) <= 3:
                return make_intent(
                    "work", target=workplace.id, motivation="Contribute to local work and household supplies"
                )
            return make_intent(
                "move",
                target=workplace.id,
                destination=workplace.entrance,
                motivation="Travel to my workplace",
            )
    return make_intent(
        "rest" if citizen.needs.fatigue > 20 else "idle",
        motivation="Take a quiet moment before the next task",
    )
