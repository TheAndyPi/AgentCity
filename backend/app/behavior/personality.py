"""Additional local combinations, subordinate to immediate safety and basic needs."""

from app.behavior.rules import RULES
from app.behavior.vitals import conscious, emit
from app.simulation.agents import evidence, hazard_severity, remember
from app.simulation.navigation import distance, line_of_sight


def choice(state, citizen, context):
    from app.simulation.game_master import make_intent

    if citizen.needs.hunger >= 45 or citizen.needs.fatigue >= 65 or citizen.summary.path:
        return None
    t = citizen.profile.traits
    visible = [
        state.citizens[aid]
        for aid in context["nearby_ids"]
        if conscious(state.citizens[aid])
        and distance(citizen.summary.position, state.citizens[aid].summary.position) <= RULES["range"]
    ]
    warning = next(
        (b for b in reversed(citizen.beliefs) if b.confidence < RULES["uncertain_warning_trust"]), None
    )
    trusted = [
        p
        for p in visible
        if p.summary.id in citizen.relationships
        and citizen.relationships[p.summary.id].trust >= RULES["support_trust"]
    ]
    if warning and trusted and "corroboration" not in citizen.condition.class_evidence_tick:
        citizen.condition.class_evidence_tick["corroboration"] = state.simulation.tick
        return make_intent(
            "talk",
            target=trusted[0].summary.id,
            motivation="Ask a trusted neighbor to corroborate an uncertain warning",
        )
    if (
        citizen.condition.mental < RULES["distress_mental"]
        or citizen.summary.metrics.stress >= RULES["distress_stress"]
    ):
        if t.sociability < RULES["quiet_sociability"] and not trusted:
            return make_intent(
                "rest", motivation="Overwhelmed: quiet recovery suits my low sociability", emotion="worried"
            )
        if trusted:
            return make_intent(
                "talk",
                target=trusted[0].summary.id,
                motivation="Ask a reliable friend for support",
                emotion="worried",
            )
    for fire in state.behavior.fires.values():
        if fire.extinguished or fire.end_tick <= state.simulation.tick:
            continue
        if distance(citizen.summary.position, fire.position) > 20 or not line_of_sight(
            state.map, citizen.summary.position, fire.position
        ):
            continue
        key = "fire:" + fire.id
        if key in citizen.condition.class_evidence_tick:
            continue
        citizen.condition.class_evidence_tick[key] = state.simulation.tick
        proof = evidence(f"Observed local fire {fire.id}")
        remember(state, citizen, "I observed a nearby fire; I should keep a safe distance.", proof=proof)
        if t.risk_tolerance <= RULES["cautious_risk"] and visible:
            return make_intent(
                "warn",
                target=visible[0].summary.id,
                motivation="Warn a nearby neighbor about the fire I can see",
                emotion="alert",
            )
        if (
            t.curiosity >= RULES["curiosity_threshold"]
            and hazard_severity(state, citizen.summary.position) == 0
        ):
            emit(
                state,
                "investigation",
                citizen,
                description="Observed an unfamiliar local fire from safety; learned its presence",
                proof=proof,
            )
            if visible:
                return make_intent(
                    "talk",
                    target=visible[0].summary.id,
                    motivation="Ask a nearby witness about this unfamiliar fire",
                )
    return None


def suppress_visible_fire(state, citizen, context):
    from app.behavior.game_master import act

    if (
        citizen.profile.traits.empathy < RULES["helper_empathy"]
        or citizen.profile.traits.cooperation < RULES["helper_cooperation"]
        or citizen.profile.traits.risk_tolerance <= RULES["cautious_risk"]
        or citizen.inventory.water < RULES["suppress_units"]
    ):
        return False
    for fire in state.behavior.fires.values():
        if (
            not fire.extinguished
            and fire.end_tick > state.simulation.tick
            and fire.radius
            < distance(citizen.summary.position, fire.position)
            <= fire.radius + RULES["range"]
            and line_of_sight(state.map, citizen.summary.position, fire.position)
        ):
            return act(state, citizen, "suppress", fire.id, context).accepted
    return False
