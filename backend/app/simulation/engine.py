"""One staged physical tick; provider work is deliberately outside this function."""

import random

from app.simulation.agents import (
    clamp,
    evidence,
    metric_delta,
    perception,
    remember,
    retrieve,
    update_metrics,
)
from app.simulation.game_master import advance_movement, apply_intent, rule_intent
from app.simulation.interactions import expire_interactions
from app.simulation.navigation import SpatialIndex
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
    state.simulation.tick += 1
    state.simulation.sim_time_seconds = state.simulation.tick * state.simulation.config.tick_seconds
    activate(state)
    index = SpatialIndex(state.citizens)
    contexts = {aid: perception(state, c, index) for aid, c in state.citizens.items() if c.summary.active}
    rng = random.Random()
    rng.setstate(tuple_tree(state.rng_state))
    ordering = sorted(contexts)
    # Seeded shuffle persists its state and avoids repeated stable-ID advantage.
    rng.shuffle(ordering)
    proposals = proposals or {}
    for aid in ordering:
        citizen = state.citizens[aid]
        context = contexts[aid]
        proposed = proposals.get(aid)
        intent = proposed[0] if proposed else rule_intent(state, citizen, context)
        if intent is not None:
            # All participants still have pre-movement positions at this boundary.
            apply_intent(state, citizen, intent, "gemini" if proposed else "rules", context)
        citizen.needs.hunger = clamp(citizen.needs.hunger + RULES["hunger_per_tick"])
        citizen.needs.fatigue = clamp(citizen.needs.fatigue + RULES["fatigue_per_tick"])
        citizen.needs.social = clamp(citizen.needs.social + RULES["social_per_tick"])
        if citizen.needs.hunger > 80:
            metric_delta(citizen, "stress", 0.5, evidence("Hunger exceeds 80 under need-decay rules"))
            metric_delta(citizen, "happiness", -0.4, evidence("Hunger exceeds 80 under need-decay rules"))
    for aid in ordering:
        advance_movement(state, state.citizens[aid])
    apply_effects(state)
    expire_interactions(state)
    if state.simulation.tick % 20 == 0:
        for citizen in state.citizens.values():
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
    if state.simulation.tick >= state.simulation.config.max_ticks and not resolved:
        state.simulation.status = "completed"
        state.simulation.pause_reason = None
        state.simulation.control_version += 1
    if resolved:
        update_metrics(state)
        for runtime in state.events.values():
            if runtime.summary.end_tick == state.simulation.tick:
                runtime.after = state.metric_points[-1].values.model_copy()
