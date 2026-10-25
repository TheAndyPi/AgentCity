"""V2 actions: validate every prerequisite before atomic physical effects."""

from app.behavior.models import BehaviorDecision, Fire
from app.behavior.rules import RULES
from app.behavior.vitals import conscious, emit, evaluate, impact, living, stop
from app.simulation.agents import evidence, hazard_severity, metric_delta, perception, social_delta
from app.simulation.building_visits import same_room
from app.simulation.navigation import distance, line_of_sight, polygon_contains
from app.simulation.timing import legacy_ticks


def act(state, actor, action, target_id, context=None):
    from app.behavior.care import available_hospital, eligible
    from app.behavior.classes import affinity
    from app.simulation.game_master import Rejected, check

    evaluate(state, actor, "Before v2 action")
    context = context or perception(state, actor)
    d = BehaviorDecision(
        id=state.next_id("behavior_decision"),
        tick=state.simulation.tick,
        actor_id=actor.summary.id,
        action=action,
        target_id=target_id,
        accepted=False,
        reason="",
    )
    proof = evidence(f"Validated {action}", decision_ids=[d.id])
    target = state.citizens.get(target_id)
    if target:
        evaluate(state, target, "Before v2 interaction")
    try:
        check(
            conscious(actor) and not actor.trapped_building_id and actor.condition.care != "hospital",
            "INCAPACITATED",
            "A conscious free actor is required",
        )
        check(
            actor.condition.last_action_tick != state.simulation.tick,
            "ACTION_BUDGET",
            "One v2 action per physical tick",
        )
        if action in {"attack", "rescue", "admit", "comfort", "share"}:
            check(
                target is not None and target is not actor and living(target),
                "UNKNOWN_TARGET",
                "A living other citizen is required",
            )
            if action != "admit":
                check(
                    target_id in context["nearby_ids"],
                    "UNOBSERVED_TARGET",
                    "Target must be publicly perceived",
                )
            check(
                distance(actor.summary.position, target.summary.position) <= RULES["range"]
                and same_room(actor, target),
                "OUT_OF_RANGE",
                "Target must be within interaction range and the same room",
            )
        if action == "attack":
            episode = actor.condition.episode
            check(
                episode and episode.end_tick is None and episode.mode == "aggression",
                "NO_MOTIVE",
                "Attack requires an aggression crisis",
            )
            tie = actor.relationships.get(target_id)
            check(
                tie and tie.conflict >= RULES["violent_grievance"],
                "NO_GRIEVANCE",
                "Attack requires a specific known grievance",
            )
            check(
                episode.acted_tick < 0
                or state.simulation.tick - episode.acted_tick
                >= legacy_ticks(state, RULES["attack_cooldown"]),
                "COOLDOWN",
                "Attack is cooling down",
            )
            episode.acted_tick = state.simulation.tick
            damage = impact(state, target, "health", -RULES["attack_damage"], "Local attack", proof=proof)
            d.effects["health"] = damage
            evaluate(state, target, "Attack damage", proof)
            impact(state, target, "mental", RULES["attack_mental"], "Assault distress", proof=proof)
            social_delta(state, target, actor, d.id, -5)
            state.counters["conflict_count"] += 1
            from app.simulation.agents import remember

            for witness in state.citizens.values():
                if (
                    conscious(witness)
                    and same_room(actor, witness)
                    and distance(actor.summary.position, witness.summary.position) <= 20
                    and (
                        actor.inside_building_id
                        or line_of_sight(state.map, actor.summary.position, witness.summary.position)
                    )
                ):
                    remember(
                        state,
                        witness,
                        f"I witnessed {actor.summary.name} attack {target.summary.name}.",
                        subjects=[actor.summary.id, target_id],
                        proof=proof,
                    )
            evaluate(state, target, "Attack damage", proof)
        elif action == "ignite":
            episode = actor.condition.episode
            check(
                episode and episode.end_tick is None and episode.mode == "fire" and not episode.ignited,
                "NO_MOTIVE",
                "One ignition per destructive crisis",
            )
            b = next((b for b in state.map.buildings if b.id == target_id), None)
            check(
                b and b.functional and b.kind in {"home", "work", "shop", "community"},
                "NOT_FLAMMABLE",
                "Target must be an open wood/furnishing-bearing home/work/shop/community building",
            )
            check(
                distance(actor.summary.position, b.entrance) <= RULES["range"]
                and (
                    actor.inside_building_id == b.id
                    or line_of_sight(state.map, actor.summary.position, b.entrance)
                ),
                "OUT_OF_RANGE",
                "Ignition requires visible local entrance access",
            )
            fires = [
                f
                for f in state.behavior.fires.values()
                if not f.extinguished and f.end_tick > state.simulation.tick
            ]
            check(
                len(fires) < RULES["fire_cap"] and not any(f.target_id == b.id for f in fires),
                "FIRE_CAP",
                "Fire cap or duplicate target",
            )
            f = Fire(
                id=state.next_id("fire"),
                actor_id=actor.summary.id,
                target_id=b.id,
                position=b.entrance.model_copy(),
                radius=RULES["fire_radius"],
                severity=RULES["fire_severity"],
                start_tick=state.simulation.tick,
                end_tick=state.simulation.tick + legacy_ticks(state, RULES["fire_ticks"]),
            )
            state.behavior.fires[f.id] = f
            episode.ignited = True
            d.effects["fire_severity"] = f.severity
        elif action == "suppress":
            f = state.behavior.fires.get(target_id)
            check(
                f and not f.extinguished and f.end_tick > state.simulation.tick,
                "UNKNOWN_TARGET",
                "Active fire required",
            )
            check(
                distance(actor.summary.position, f.position) <= f.radius + RULES["range"]
                and hazard_severity(state, actor.summary.position) == 0,
                "SELF_SAFETY_REQUIRED",
                "Suppress only from a safe nearby position",
            )
            check(
                line_of_sight(state.map, actor.summary.position, f.position)
                or actor.inside_building_id == f.target_id,
                "UNOBSERVED_TARGET",
                "Suppression requires visible local fire access",
            )
            check(
                actor.inventory.water >= RULES["suppress_units"],
                "INSUFFICIENT_INVENTORY",
                "Suppression consumes water",
            )
            actor.inventory.water -= RULES["suppress_units"]
            state.counters["resources_consumed"] += RULES["suppress_units"]
            f.extinguished = True
        elif action == "rescue":
            check(
                eligible(state, actor),
                "SELF_SAFETY_REQUIRED",
                "Helper must meet health/energy/fullness/mobility/mental/safety thresholds",
            )
            check(
                not actor.condition.patient_id and target.condition.care == "none",
                "CLAIMED",
                "One helper/patient claim",
            )
            check(
                not conscious(target) or target.needs.health <= RULES["injured_health"],
                "NO_CARE_NEEDED",
                "Patient must be unconscious or badly injured",
            )
            if conscious(target):
                tie = target.relationships.get(actor.summary.id)
                check(
                    tie and tie.trust >= 50 and target.profile.traits.cooperation >= 40,
                    "CONSENT_REQUIRED",
                    "Conscious patient accepts only a known trusted cooperative escort",
                )
            check(
                affinity(actor, target) >= -1, "CLASS_REFUSAL", "Perceived class/history bias prevented aid"
            )
            available = available_hospital(state, actor)
            check(
                available is not None,
                "NO_BED_ROUTE",
                "No functioning known hospital with a reachable free bed",
            )
            b, route = available
            from app.simulation.building_visits import trip_route
            from app.simulation.scenarios import blocked_cells

            if actor.inside_building_id and same_room(actor, target):
                room = next(b for b in state.map.buildings if b.id == actor.inside_building_id)
                origin, destination = actor.summary.position, target.summary.position
                from app.contracts import Vec2

                floor_segment = [
                    Vec2(
                        x=origin.x + (destination.x - origin.x) * i / 30,
                        y=origin.y + (destination.y - origin.y) * i / 30,
                    )
                    for i in range(31)
                ]
                pickup = (
                    [destination.model_copy()]
                    if all(polygon_contains(p, room.footprint) for p in floor_segment)
                    else None
                )
            else:
                pickup = trip_route(state, actor, target.summary.position, blocked=blocked_cells(state))
            check(pickup is not None, "UNREACHABLE", "Patient pickup has no legal route")
            hospital = state.behavior.hospitals[b.id]
            hospital.reservations[target_id] = actor.summary.id
            actor.condition.patient_id = target_id
            target.condition.helper_id = actor.summary.id
            target.condition.care = "claimed"
            target.condition.hospital_id = b.id
            stop(state, target)
            actor.summary.path = pickup
            actor.entering_building_id = target.inside_building_id
            actor.leaving_building_id = actor.inside_building_id
            actor.plan = {"kind": "rescue", "target_id": target_id}
            from app.simulation.interactions import coordinate_aid

            if actor.profile.traits.cooperation >= RULES["helper_cooperation"]:
                coordinate_aid(state, actor, target, d.id)
            emit(
                state,
                "rescue_claim",
                actor,
                target,
                "Observed/assessed patient; atomic claim and hospital reservation; physical transport begins",
                proof,
            )
        elif action == "admit":
            bid = target.condition.hospital_id
            hospital = state.behavior.hospitals.get(bid)
            b = next((b for b in state.map.buildings if b.id == bid), None)
            check(
                actor.condition.patient_id == target_id and target.condition.helper_id == actor.summary.id,
                "NO_CLAIM",
                "Admission requires the active carrier",
            )
            check(
                b
                and b.functional
                and actor.inside_building_id == bid
                and hospital
                and hospital.reservations.get(target_id) == actor.summary.id,
                "NO_BED",
                "Admission requires physical hospital arrival and reserved bed",
            )
            hospital.reservations.pop(target_id)
            hospital.patients.append(target_id)
            actor.condition.patient_id = None
            target.condition.helper_id = None
            target.condition.care = "hospital"
            actor.summary.path = []
            actor.plan = None
            state.counters["cooperation_count"] += 1
        elif action == "comfort":
            check(conscious(target), "INCAPACITATED", "Comfort requires conscious acceptance")
            tie = target.relationships.get(actor.summary.id)
            accepted = any(
                i.kind == "conversation"
                and i.status == "accepted"
                and set(i.participant_ids) == {actor.summary.id, target_id}
                for i in state.interactions.values()
            )
            check(
                accepted and (not tie or tie.conflict < 50),
                "CONSENT_REQUIRED",
                "Comfort requires a mutually accepted non-hostile conversation",
            )
            from app.behavior.rules import social_multiplier

            impact(
                state,
                target,
                "social",
                RULES["comfort_social"] * social_multiplier(target, actor),
                "Accepted trusted comfort",
                proof=proof,
            )
            impact(state, target, "mental", RULES["comfort_mental"], "Accepted comfort", proof=proof)
            metric_delta(target, "stress", RULES["comfort_stress"], proof)
            social_delta(state, target, actor, d.id, 2)
        elif action == "share":
            check(
                eligible(state, actor) and conscious(target),
                "SELF_SAFETY_REQUIRED",
                "Safe conscious sharing required",
            )
            check(
                actor.inventory.food >= RULES["share_units"] and affinity(actor, target) >= 0,
                "REFUSAL",
                "Available food and nonnegative aid willingness required",
            )
            actor.inventory.food -= RULES["share_units"]
            target.inventory.food += RULES["share_units"]
            d.effects["food_transferred"] = RULES["share_units"]
            social_delta(state, target, actor, d.id, 3)
            social_delta(state, actor, target, d.id, 1)
            state.counters["cooperation_count"] += 1
        actor.condition.last_action_tick = state.simulation.tick
        actor.summary.thought_bubble = f"{action}: validated local action toward {target_id}"
        d.accepted = True
        d.reason = actor.summary.thought_bubble
        emit(
            state,
            {"ignite": "ignition", "admit": "admission"}.get(action, action),
            actor,
            target,
            d.reason,
            proof,
        )
        evaluate(state, actor, "After v2 action", proof)
    except Rejected as exc:
        d.reason = f"{exc.code}: {exc.message}"
    state.behavior.decisions.append(d)
    return d


def fire_effects(state):
    for f in state.behavior.fires.values():
        if f.extinguished:
            continue
        if state.simulation.tick >= f.end_tick:
            f.extinguished = True
            emit(state, "fire_resolved", None, description=f"{f.id}: bounded lifetime expired; no spread")
            continue
        for c in state.citizens.values():
            if living(c) and distance(c.summary.position, f.position) <= f.radius:
                proof = evidence(f"Exposure to engine fire {f.id}")
                impact(
                    state,
                    c,
                    "health",
                    -RULES["fire_damage"] * f.severity / 100 * state.simulation.config.tick_seconds / 10,
                    "Fire exposure",
                    "environment",
                    proof,
                )
                metric_delta(c, "stress", f.severity / 100 * 2, proof)
                evaluate(state, c, "Fire exposure", proof)
