"""One staged physical tick; provider work is deliberately outside this function."""

import random

from app.scenario_engine import runtime as systems
from app.simulation.agents import (
    evidence,
    metric_delta,
    perception,
    remember,
    retrieve,
    update_metrics,
)
from app.simulation.characters import upgrade_placeholder_citizens
from app.simulation.game_master import advance_movement, apply_intent, rule_intent
from app.simulation.interactions import expire_interactions
from app.simulation.navigation import SpatialIndex, restore_personal_space
from app.simulation.scenarios import activate, apply_effects, finish_events

RULES = {
    "version": "1.0.0",
    "hunger_per_tick": 0.6,
    "fatigue_per_tick": 0.4,
    "social_per_tick": 0.2,
    "rest_fatigue": -6,
    "consume_hunger_per_unit": -12,
    "help_supply_units": 1,
    "help_health": 5,
    "sight_m": 20,
    "hearing_m": 8,
    "interaction_m": 3,
    "default_walk_mps": 1.4,
}


def tuple_tree(value):
    return tuple(tuple_tree(item) for item in value) if isinstance(value, (tuple, list)) else value


def list_tree(value):
    return [list_tree(item) for item in value] if isinstance(value, (tuple, list)) else value


def tick(state, proposals=None):
    from app.behavior.care import fund_hospitals, rescue_choice, synchronize_transport, treatment
    from app.behavior.classes import encounter, mutual_aid
    from app.behavior.crisis import crisis_intent, evaluate_crisis
    from app.behavior.game_master import fire_effects
    from app.behavior.vitals import activate_rules, background, conscious, evaluate, impact, living, passive

    upgrade_placeholder_citizens(state)
    activate_rules(state)
    fund_hospitals(state)
    # Fatal initial conditions cannot be cured by selecting an eating/rest action.
    for citizen in state.citizens.values():
        evaluate(state, citizen, "Pre-selection canonical thresholds")
    if not any(living(c) for c in state.citizens.values()):
        state.simulation.status = "completed"
        state.simulation.pause_reason = None
        update_metrics(state)
        return
    state.simulation.tick += 1
    state.simulation.sim_time_seconds = state.simulation.tick * state.simulation.config.tick_seconds
    activate(state)
    systems.on_tick_start(state)
    restore_personal_space(state)
    rng = random.Random()
    rng.setstate(tuple_tree(state.rng_state))
    ordering = sorted(aid for aid, c in state.citizens.items() if living(c))
    rng.shuffle(ordering)
    proposals = proposals or {}
    for aid in ordering:
        citizen = state.citizens[aid]
        evaluate(state, citizen)
        evaluate_crisis(state, citizen, recovery=False)
        if not conscious(citizen) or citizen.condition.care in {"hospital", "claimed", "carried", "escorted"}:
            continue
        candidate = proposals.get(aid)
        context = perception(state, citizen, SpatialIndex(state.citizens))
        encounter(state, citizen, context)
        # Urgent safety is always handled by the existing legal evacuation policy.
        from app.simulation.agents import hazard_severity

        threatened = hazard_severity(state, citizen.summary.position) > 0 or state.policies.evacuation_order
        intent, handled = (None, False) if threatened else rescue_choice(state, citizen, context)
        if not handled and not threatened:
            intent, handled = crisis_intent(state, citizen, context)
        from app.behavior.personality import suppress_visible_fire

        if not handled and not threatened and suppress_visible_fire(state, citizen, context):
            handled = True
        if not handled and not threatened and mutual_aid(state, citizen, context):
            handled = True
        proposed = candidate if not handled and not threatened else None
        if proposed and proposed[0].action == "talk":
            current_lines = [line for line in state.dialogue if aid in [line.speaker_id, *line.recipient_ids]]
            if current_lines:
                last = current_lines[-1]
                interaction = state.interactions.get(last.interaction_id)
                if (
                    interaction
                    and interaction.status in {"invited", "accepted"}
                    and (last.tick >= state.simulation.tick or last.speaker_id == aid)
                ):
                    proposed = None
        if not handled:
            from app.behavior.personality import choice

            personality = choice(state, citizen, context) if not threatened and not proposed else None
            intent = proposed[0] if proposed else personality or rule_intent(state, citizen, context)
        if intent is not None:
            # All participants still have pre-movement positions at this boundary.
            decision = apply_intent(state, citizen, intent, "gemini" if proposed else "rules", context)
            systems.after_decision(state, citizen, decision)
        evaluate(state, citizen, "After actor action")
    for aid in ordering:
        citizen = state.citizens[aid]
        if conscious(citizen) and citizen.condition.care not in {
            "hospital",
            "claimed",
            "carried",
            "escorted",
        }:
            advance_movement(state, citizen)
            synchronize_transport(state, citizen)
    # Consumption/rest happens before decay. Patients still decay and can die.
    dt = state.simulation.config.tick_seconds / 10
    for citizen in state.citizens.values():
        if not living(citizen):
            continue
        passive(state, citizen)
        impact(state, citizen, "fullness", -RULES["hunger_per_tick"] * dt, "Baseline hunger", "base_decay")
        impact(state, citizen, "energy", -RULES["fatigue_per_tick"] * dt, "Baseline fatigue", "base_decay")
        impact(state, citizen, "social", -RULES["social_per_tick"] * dt, "Baseline isolation", "base_decay")
        if citizen.needs.hunger > 80:
            metric_delta(citizen, "stress", 0.5 * dt, evidence("Hunger exceeds 80 under need-decay rules"))
            metric_delta(
                citizen, "happiness", -0.4 * dt, evidence("Hunger exceeds 80 under need-decay rules")
            )
        evaluate(state, citizen, "End-of-tick need decay")
    apply_effects(state)
    fire_effects(state)
    systems.after_tick(state)
    treatment(state)
    # Refresh derived canonical inputs, then freeze/apply exactly one coupling phase.
    update_metrics(state)
    for citizen in state.citizens.values():
        background(state, citizen)
        evaluate_crisis(state, citizen)
    expire_interactions(state)
    if state.simulation.tick % 20 == 0:
        for citizen in state.citizens.values():
            if not conscious(citizen):
                continue
            episodes = [
                memory
                for memory in retrieve(citizen, state.simulation.tick, " ".join(citizen.goals))
                if memory.source != "reflection"
            ]
            if episodes:
                remember(
                    state,
                    citizen,
                    "My recent experiences: " + "; ".join(memory.text[:160] for memory in episodes),
                    "reflection",
                    60,
                    proof=evidence(
                        "Batched subjective summary; original episodes retained",
                        memory_ids=[memory.id for memory in episodes],
                    ),
                )
    state.rng_state = list_tree(rng.getstate())
    update_metrics(state)
    resolved = finish_events(state)
    systems.after_finish(state, resolved)
    if (
        state.simulation.tick >= state.simulation.config.max_ticks
        or not any(living(c) for c in state.citizens.values())
    ) and not resolved:
        state.simulation.status = "completed"
        state.simulation.pause_reason = None
        state.simulation.control_version += 1
    if resolved:
        update_metrics(state)
        for runtime in state.events.values():
            if runtime.summary.end_tick == state.simulation.tick:
                runtime.after = state.metric_points[-1].values.model_copy()
