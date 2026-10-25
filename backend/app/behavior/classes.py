"""Objective wealth, public class signals and evidence-paced subjective affinity."""

from app.behavior.rules import RULES
from app.behavior.vitals import conscious, emit
from app.simulation.agents import evidence, social_delta


def wealth(c):
    return c.inventory.food + c.inventory.water + 2 * c.inventory.supplies


def classify(c):
    value, old = wealth(c), c.condition.wealth_band
    low, high, h = RULES["poor_boundary"], RULES["rich_boundary"], RULES["band_hysteresis"]
    if old == "poor" and value < low + h:
        return old
    if old == "rich" and value >= high - h:
        return old
    return (
        "poor"
        if value < low - (h if old == "middle" else 0)
        else "rich"
        if value >= high + (h if old == "middle" else 0)
        else "middle"
    )


def affinity(actor, other):
    perceived = actor.condition.class_beliefs.get(other.summary.id)
    own = actor.condition.wealth_band
    rank = {"poor": 0, "middle": 1, "rich": 2}
    if perceived is None or rank[own] <= rank[perceived]:
        return 0
    traits = actor.profile.traits
    tie = actor.relationships.get(other.summary.id)
    compassion = (traits.empathy + traits.cooperation) / 200
    support = (tie.trust + tie.affection) / 200 if tie else 0.5
    # Compassion and supportive history can outweigh class contempt.
    return max(
        -RULES["class_penalty"],
        min(
            RULES["class_support"],
            RULES["class_support"] * compassion * support - RULES["class_penalty"] * (1 - compassion),
        ),
    )


def encounter(state, actor, context):
    actor.condition.wealth_band = classify(actor)
    for aid in context["nearby_ids"]:
        other = state.citizens[aid]
        # A carried bundle of public goods is an explicit signal, not a raw inventory disclosure.
        # Only a just-committed public transfer/gather/work broadcasts a class band.
        observed = [
            d
            for d in state.decisions[-100:]
            if (
                d.agent_id == aid
                and d.tick >= state.simulation.tick - 1
                and d.outcome == "accepted"
                and d.intent.action in {"gather", "trade", "work"}
            )
        ]
        if other.summary.action not in {"gather", "trade", "work"} or not observed:
            continue
        key = f"signal:{aid}"
        if (
            state.simulation.tick - actor.condition.class_evidence_tick.get(key, -10000)
            < RULES["class_cadence"]
        ):
            continue
        actor.condition.class_evidence_tick[key] = state.simulation.tick
        actor.condition.class_beliefs[aid] = classify(other)
        event = emit(
            state,
            "class_signal",
            actor,
            other,
            f"Observed public resource activity: perceived {classify(other)} class; no raw private stock disclosed",
            evidence("Visible public transfer/activity class signal", decision_ids=[observed[-1].id]),
        )
        bias = affinity(actor, other)
        if (
            actor.condition.wealth_band == "poor"
            and classify(other) == "poor"
            and actor.profile.traits.cooperation >= RULES["helper_cooperation"]
        ):
            bias = RULES["class_support"] * actor.profile.traits.cooperation / 100
        hoarding = (
            actor.condition.wealth_band == "poor"
            and classify(other) == "rich"
            and actor.inventory.food < 1
            and observed[-1].intent.action == "gather"
            and (observed[-1].intent.parameters.amount or 0) >= RULES["hoarding_units"]
        )
        if hoarding:
            bias = -RULES["class_penalty"]
            emit(
                state,
                "class_grievance",
                actor,
                other,
                "While personally short of food, witnessed a publicly affluent neighbor taking a large allocation",
                event.evidence,
            )
        if bias:
            social_delta(state, actor, other, event.id, bias)
            emit(
                state,
                "solidarity" if bias > 0 else "discrimination",
                actor,
                other,
                f"Public class signal and personality/history: directed affinity {bias:+.2f}",
            )


def initialize_distribution(state):
    """Redistribute the existing fixed pool, then fund hospital stocks from depots."""
    from app.behavior.care import fund_hospitals
    from app.behavior.vitals import activate_rules

    activate_rules(state)
    people = sorted(state.citizens.values(), key=lambda c: c.summary.id)
    weights = [RULES["distribution_weights"][i % 3] for i in range(len(people))]
    for kind in ("food", "water", "supplies"):
        total = sum(getattr(c.inventory, kind) for c in people)
        remaining = total
        for i, c in enumerate(people):
            amount = total * weights[i] / sum(weights) if i < len(people) - 1 else remaining
            setattr(c.inventory, kind, amount)
            remaining -= amount
    for c in people:
        c.condition.wealth_band = classify(c)
    emit(
        state,
        "redistribution",
        None,
        description="Fixed household resource pool redistributed by spawn index weights 0.4/0.8/1.8; independent of names and traits",
    )
    fund_hospitals(state)


def mutual_aid(state, actor, context):
    from app.behavior.game_master import act
    from app.simulation.navigation import distance

    if actor.profile.traits.cooperation < RULES["helper_cooperation"]:
        return False
    for aid in context["nearby_ids"]:
        other = state.citizens[aid]
        if (
            conscious(other)
            and other.summary.action == "idle"
            and other.summary.emotion == "worried"
            and distance(actor.summary.position, other.summary.position) <= RULES["range"]
            and actor.inventory.food >= 2
            and affinity(actor, other) >= 0
        ):
            return act(state, actor, "share", aid, context).accepted
    return False
