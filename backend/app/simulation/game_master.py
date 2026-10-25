"""Deterministic intent validation and atomic, conserved consequences."""

import math

from app.contracts import Decision, EffectChange, Intent, Parameters, Vec2
from app.scenario_engine import responses
from app.simulation.agents import (
    clamp,
    evidence,
    hazard_severity,
    metric_delta,
    perception,
    remember,
    social_delta,
)
from app.simulation.autonomy import routine_destination, social_choice
from app.simulation.building_visits import (
    interior_slot,
    same_room,
    sync_building_location,
    trip_route,
    walkable_segment,
)
from app.simulation.interactions import accept_invitation, coordinate_aid, speak
from app.simulation.navigation import (
    cell_at,
    clear_travel,
    crowd_detour,
    distance,
    line_of_sight,
    meeting_point,
    pathfind,
    polygon_contains,
)
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
    from app.behavior.vitals import conscious, evaluate

    evaluate(state, citizen, "Before ordinary action")
    context = context or perception(state, citizen)
    before_energy = 100 - citizen.needs.fatigue
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
        check(
            conscious(citizen)
            and not citizen.trapped_building_id
            and citizen.condition.care not in {"hospital", "claimed", "carried", "escorted"},
            "INCAPACITATED",
            "Only a conscious free citizen can perform ordinary actions",
        )
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
        if target:
            evaluate(state, target, "Before interaction")
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
        if action in {"talk", "trade", "warn"}:
            check(conscious(target), "INCAPACITATED", "Target cannot participate while unconscious")
        if action in {"help", "trade"}:
            from app.behavior.classes import affinity

            check(
                affinity(citizen, target) >= -1,
                "CLASS_REFUSAL",
                "Perceived class and prior treatment reduced willingness to share",
            )
        if registry.get("target") == "agent":
            check(
                same_room(citizen, target),
                "OUT_OF_RANGE",
                "People must be in the same indoor or outdoor space",
            )
        if action in {"move", "evacuate"}:
            destination = intent.destination
            if destination is None and intent.target_id:
                destination = citizen.known_locations.get(intent.target_id)
                if target is not None and target.summary.id in context["nearby_ids"]:
                    destination = meeting_point(
                        state.map,
                        citizen.summary.position,
                        target.summary.position,
                        [
                            c.summary.position
                            for c in state.citizens.values()
                            if c.summary.active and c is not citizen
                        ],
                    )
            check(
                destination is not None,
                "MISSING_DESTINATION",
                "Movement requires a destination or a known target location",
            )
            facility = next(
                (
                    b
                    for b in state.map.buildings
                    if b.id == intent.target_id and distance(destination, b.entrance) < 0.1
                ),
                None,
            )
            if facility:
                check(facility.functional, "INFRASTRUCTURE_UNAVAILABLE", "Building is closed")
                check(
                    interior_slot(state, citizen, facility) is not None,
                    "CAPACITY",
                    "Building has no available room",
                )
            route = trip_route(state, citizen, destination, facility, blocked_cells(state))
            check(route is not None, "UNREACHABLE", "No reachable route or available room at the destination")
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
            citizen.leaving_building_id = citizen.inside_building_id
            citizen.entering_building_id = facility.id if facility else None
            citizen.summary.path = route
            if not (
                citizen.plan
                and citizen.plan.get("kind") == "social_visit"
                and citizen.plan.get("target_id") == intent.target_id
            ):
                citizen.plan = intent.model_dump()
            decision.outcome_description = "Path accepted; movement is bounded by speed and tick duration"
        elif action == "rest":
            from app.behavior.vitals import rest

            before = citizen.needs.fatigue
            rest(state, citizen)
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
                citizen.inside_building_id == workplace.id
                or distance(citizen.summary.position, workplace.entrance) <= 3,
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
            check(
                hazard_severity(state, citizen.summary.position) == 0 and not state.policies.evacuation_order,
                "SELF_SAFETY_REQUIRED",
                "Reach safety before offering optional help; no exception applies during an evacuation order",
            )
            from app.behavior.care import eligible

            check(
                eligible(state, citizen),
                "HELPER_INELIGIBLE",
                "Helper must meet own health, energy, fullness, mobility and Mental thresholds",
            )
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
            interaction, accepted = accept_invitation(
                state,
                citizen,
                target,
                "warning" if action == "warn" else "conversation",
                {"approach_reason": intent.motivation},
            )
            check(
                action == "warn" or accepted or interaction.turns == 0,
                "AWAITING_ACCEPTANCE",
                "The recipient must accept before the initiator can continue the conversation",
            )
            # Warning is one-way speech; a conversation begins with an invitation.
            speak(state, citizen, target, intent, did, interaction)
            if action == "warn":
                decision.outcome_description = "One-way warning delivered; no conversation acceptance implied"
            elif not accepted:
                decision.outcome_description = "Conversation invited; awaiting explicit recipient acceptance"
            else:
                decision.outcome_description = "Both participants accepted the conversation"
                from app.behavior.rules import RULES as BEHAVIOR_RULES
                from app.behavior.rules import social_multiplier
                from app.behavior.vitals import impact

                tie = citizen.relationships.get(target.summary.id)
                if not tie or tie.conflict < 50:
                    impact(
                        state,
                        citizen,
                        "social",
                        5 * social_multiplier(citizen, target),
                        "Accepted friendly conversation",
                        proof=proof,
                    )
                    impact(
                        state,
                        citizen,
                        "mental",
                        BEHAVIOR_RULES["comfort_mental"],
                        "Accepted social support",
                        proof=proof,
                    )
                    metric_delta(citizen, "stress", BEHAVIOR_RULES["comfort_stress"], proof)
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
    if decision.outcome == "accepted":
        from app.behavior.learning import applied

        applied(state, citizen, intent, did, before_energy)
    if decision.outcome != "rejected" and intent.action not in {"idle", "move", "rest"}:
        remember(
            state,
            citizen,
            f"I chose to {intent.action}: {decision.outcome_description}",
            importance=40,
            proof=proof,
        )
    for affected in (citizen, state.citizens.get(intent.target_id)):
        if affected is not None:
            evaluate(state, affected, "After ordinary action", proof)
    return decision


def advance_movement(state, citizen):
    from app.behavior.vitals import conscious, evaluate

    evaluate(state, citizen, "Before movement")
    if (
        citizen.trapped_building_id
        or not conscious(citizen)
        or citizen.condition.care in {"hospital", "claimed", "carried", "escorted"}
    ):
        return
    origin_at_tick = citizen.summary.position.model_copy()
    # Pause at a greeting long enough to answer it. Urgent evacuation/help still
    # takes precedence; an invitation never teleports or accepts for its recipient.
    if (
        not citizen.condition.patient_id
        and citizen.summary.action not in {"evacuate", "help"}
        and hazard_severity(state, citizen.summary.position) == 0
    ):
        for interaction in state.interactions.values():
            if (
                interaction.kind == "conversation"
                and interaction.status in {"invited", "accepted"}
                and interaction.expires_tick >= state.simulation.tick
                and citizen.summary.id in interaction.participant_ids
            ):
                other = next(
                    (state.citizens[aid] for aid in interaction.participant_ids if aid != citizen.summary.id),
                    None,
                )
                if other and distance(citizen.summary.position, other.summary.position) <= 3:
                    citizen.blocked_movement_ticks = 0
                    return
    speed = citizen.summary.movement_speed_mps
    patient = state.citizens.get(citizen.condition.patient_id)
    if patient:
        speed = min(speed, patient.summary.movement_speed_mps) * 0.5
    remaining = speed * state.simulation.config.tick_seconds
    blocked = blocked_cells(state)
    while remaining > 1e-8 and citizen.summary.path:
        destination = citizen.summary.path[0]
        cell = cell_at(state.map, destination)
        indoor_waypoint = any(
            b.id in {citizen.inside_building_id, citizen.entering_building_id, citizen.leaving_building_id}
            and polygon_contains(destination, b.footprint)
            for b in state.map.buildings
        )
        if cell is None or (not cell.walkable and not indoor_waypoint) or (cell.col, cell.row) in blocked:
            citizen.summary.path = []
            citizen.plan = None
            citizen.task_generation += 1
            break
        origin = citizen.summary.position
        length = distance(origin, destination)
        citizen.summary.heading_rad = math.atan2(destination.x - origin.x, destination.y - origin.y) % (
            2 * math.pi
        )
        if length < 1e-8:
            citizen.summary.path.pop(0)
            continue
        step = min(length, remaining)
        candidate = Vec2(
            x=origin.x + (destination.x - origin.x) * step / length,
            y=origin.y + (destination.y - origin.y) * step / length,
        )
        occupied = [
            c.summary.position
            for c in state.citizens.values()
            if c.summary.active and c is not citizen and c.summary.id != citizen.condition.patient_id
        ]
        fraction = clear_travel(origin, candidate, occupied)
        citizen.summary.position = Vec2(
            x=origin.x + (candidate.x - origin.x) * fraction,
            y=origin.y + (candidate.y - origin.y) * fraction,
        )
        remaining -= step * fraction
        if fraction < 1:
            p = citizen.summary.position
            # Grid routes may pass through an occupied cell center before their
            # final approach. Skip it when the next segment is already clear.
            if len(citizen.summary.path) > 1:
                onward = citizen.summary.path[1]
                if (
                    walkable_segment(state, citizen, p, onward, blocked)
                    and clear_travel(p, onward, occupied) == 1
                ):
                    citizen.summary.path.pop(0)
                    continue
            # Shared resources and entrances are reached from personal space.
            if len(citizen.summary.path) == 1 and distance(p, destination) <= 2.4:
                citizen.summary.path = []
            else:
                for i, onward in enumerate(citizen.summary.path[:6]):
                    route = crowd_detour(
                        p,
                        onward,
                        occupied,
                        lambda a, b: walkable_segment(state, citizen, a, b, blocked),
                    )
                    if route:
                        citizen.summary.path[: i + 1] = route
                        break
            break
        if step >= length - 1e-8:
            citizen.summary.path.pop(0)
    if citizen.summary.path and distance(origin_at_tick, citizen.summary.position) < 0.01:
        citizen.blocked_movement_ticks += 1
        if citizen.blocked_movement_ticks >= 6:
            # A stale route must not suppress autonomy forever. Release its room
            # reservation and let the next tick choose again from current facts.
            citizen.summary.path = []
            citizen.plan = None
            citizen.task_generation += 1
            citizen.next_deliberation_tick = state.simulation.tick + 1
            citizen.blocked_movement_ticks = 0
    else:
        citizen.blocked_movement_ticks = 0
    sync_building_location(state, citizen)
    if not citizen.summary.path and not (citizen.plan and citizen.plan.get("kind") == "social_visit"):
        citizen.plan = None


def rule_intent(state, citizen, context):
    if citizen.trapped_building_id or not citizen.summary.active or citizen.needs.health <= 0:
        return None
    p = citizen.summary.position
    from app.behavior.care import eligible
    from app.behavior.vitals import conscious

    if not conscious(citizen):
        return None
    nearby = [state.citizens[aid] for aid in context["nearby_ids"] if conscious(state.citizens[aid])]
    threatened = hazard_severity(state, p) > 0 or (
        state.policies.evacuation_order
        and (not state.systems.enabled or responses.complies_with_evacuation(state, citizen))
    )
    # Self-safety has no helping exception, even if no safe route can be found.
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
    visible_victims = [
        other
        for other in nearby
        if distance(p, other.summary.position) <= 3
        and same_room(citizen, other)
        and (other.needs.health < 95 or hazard_severity(state, other.summary.position) > 0)
    ]
    if (
        visible_victims
        and citizen.inventory.supplies >= 1
        and citizen.needs.health > 60
        and citizen.profile.traits.empathy >= responses.help_threshold(state, citizen)
        and eligible(state, citizen)
    ):
        victim = max(
            visible_victims,
            key=lambda other: (
                citizen.relationships.get(other.summary.id).affection
                if other.summary.id in citizen.relationships
                else 0
            ),
        )
        # A safe helper may aid a perceived, nearby victim; never use remote positions.
        return make_intent(
            "help",
            target=victim.summary.id,
            motivation="Someone I can see needs help and I have supplies",
            emotion="concerned",
        )
    if citizen.needs.hunger >= 45:
        for kind in ("food", "water"):
            if getattr(citizen.inventory, kind) >= 1:
                return make_intent("consume", kind=kind, amount=1, motivation="I need to eat or drink")
    from app.behavior.learning import rest_reason, threshold

    if 100 - citizen.needs.fatigue <= threshold(citizen):
        home_trip = routine_destination(state, citizen)
        if home_trip and home_trip[0].kind == "home" and not citizen.summary.path:
            building, reason = home_trip
            return make_intent(
                "move",
                target=building.id,
                destination=building.entrance,
                motivation=rest_reason(citizen, reason),
            )
        if not citizen.summary.path:
            return make_intent("rest", motivation=rest_reason(citizen, "I need to recover my energy"))
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
            other_id = next((aid for aid in conversation.participant_ids if aid != citizen.summary.id), None)
            speaker = state.citizens.get(other_id)
            if (
                speaker is not None
                and speaker.summary.id in context["nearby_ids"]
                and distance(p, speaker.summary.position) <= 3
            ):
                if (
                    lines
                    and lines[-1].speaker_id != citizen.summary.id
                    and lines[-1].tick < state.simulation.tick
                ):
                    return make_intent(
                        "talk",
                        target=speaker.summary.id,
                        motivation="Reply to the neighbor who just spoke to me",
                    )
                return make_intent(
                    "idle", target=speaker.summary.id, motivation="Listen while my neighbor has their turn"
                )
    visit = citizen.plan if citizen.plan and citizen.plan.get("kind") == "social_visit" else None
    if visit:
        other = state.citizens.get(visit["target_id"])
        if not other or not other.summary.active or visit["expires_tick"] < state.simulation.tick:
            citizen.summary.path = []
            citizen.plan = None
        elif other.summary.id in context["nearby_ids"] and distance(p, other.summary.position) <= 3:
            return make_intent(
                "talk",
                target=other.summary.id,
                motivation=visit.get("motivation", "Say hello after walking over to my neighbor"),
            )
        elif citizen.summary.path:
            return None
        elif other.summary.id in context["nearby_ids"]:
            return make_intent(
                "move",
                target=other.summary.id,
                destination=meeting_point(state.map, p, other.summary.position),
                motivation="Walk toward the neighbor I can see",
            )
        else:
            citizen.plan = None
    if citizen.summary.path:
        return None
    scarce = min(("food", "water", "supplies"), key=lambda kind: getattr(citizen.inventory, kind))
    if getattr(citizen.inventory, scarce) < responses.inventory_floor(state, citizen):
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
    if nearby and citizen.needs.social > 20 and state.simulation.tick >= citizen.next_social_tick:
        recent_partners = {
            aid
            for interaction in state.interactions.values()
            if interaction.kind == "conversation"
            and citizen.summary.id in interaction.participant_ids
            and interaction.expires_tick + 8 >= state.simulation.tick
            for aid in interaction.participant_ids
            if aid != citizen.summary.id
        }
        available = [other for other in nearby if other.summary.id not in recent_partners]
        choice = social_choice(state, citizen, available)
        if choice and (citizen.profile.traits.sociability > 40 or citizen.needs.social > 55):
            other, reason = choice
            if distance(p, other.summary.position) <= 3:
                return make_intent("talk", target=other.summary.id, motivation=reason)
            if (
                not citizen.inside_building_id
                and pathfind(state.map, p, other.summary.position, blocked_cells(state)) is not None
            ):
                citizen.plan = dict(
                    kind="social_visit",
                    target_id=other.summary.id,
                    expires_tick=state.simulation.tick + 30,
                    motivation=reason,
                )
                return make_intent(
                    "move",
                    target=other.summary.id,
                    destination=meeting_point(state.map, p, other.summary.position),
                    motivation=reason,
                )
    if citizen.inside_building_id and citizen.visit_until_tick > state.simulation.tick:
        building = next(b for b in state.map.buildings if b.id == citizen.inside_building_id)
        if building.kind == "work" and citizen.inventory.supplies < citizen.target_inventory_units:
            return make_intent("work", target=building.id, motivation="Do a short shift at my workplace")
        return make_intent(
            "rest" if building.kind == "home" else "idle",
            target=building.id,
            motivation=f"Spend a little time inside {building.name}",
        )
    if citizen.inside_building_id and responses.staying_for_care(state, citizen):
        return make_intent(
            "rest", target=citizen.inside_building_id, motivation="Stay for treatment until I recover"
        )
    destination = routine_destination(state, citizen)
    if destination:
        building, reason = destination
        return make_intent("move", target=building.id, destination=building.entrance, motivation=reason)
    return make_intent(
        "rest" if citizen.needs.fatigue > 20 else "idle",
        motivation="Take a quiet moment before the next task",
    )
