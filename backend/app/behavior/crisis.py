"""One seeded episode for either independent crisis trigger."""

from app.behavior.models import Episode
from app.behavior.rules import RULES, VERSION
from app.behavior.vitals import conscious, emit, living
from app.simulation.agents import hazard_severity
from app.simulation.navigation import distance


def weights(citizen):
    t = citizen.profile.traits
    k = RULES["mode_trait_weight"]
    w = dict(RULES["mode_weights"])
    w["withdrawal"] += k * (1 - t.sociability / 100) * (1 - t.risk_tolerance / 100)
    w["panic"] += k * (1 - citizen.summary.metrics.safety / 100) * (1 - t.risk_tolerance / 100)
    w["support"] += k * (t.sociability + t.empathy + t.cooperation) / 300
    w["support"] += RULES["mode_need_weight"] * citizen.needs.hunger / 100
    w["panic"] += RULES["mode_stress_weight"] * citizen.summary.metrics.stress / 100
    if any("death" in m.text.lower() for m in citizen.memories[-10:] if m.source in {"observed", "heard"}):
        w["withdrawal"] += RULES["mode_grief_weight"]
    grievance = any(r.conflict >= RULES["violent_grievance"] for r in citizen.relationships.values())
    if grievance:
        propensity = k * t.risk_tolerance / 100 * (1 - (t.empathy + t.cooperation) / 200)
        w["aggression"] += propensity
        w["fire"] += propensity / 2
    else:
        w["aggression"] = 0
        w["fire"] = 0
    return w


def evaluate_crisis(state, citizen, rng=None, recovery=True):
    c = citizen.condition
    if not living(citizen):
        return
    causes = []
    if c.mental <= RULES["mental_trigger"]:
        causes.append("low_mental")
    if citizen.summary.metrics.stress >= RULES["stress_trigger"]:
        causes.append("high_stress")
    episode = c.episode
    if episode and episode.end_tick is None:
        for cause in causes:
            if cause not in episode.causes:
                episode.causes.append(cause)
                episode.measurements[cause + "_tick"] = state.simulation.tick
                episode.measurements[cause + "_value"] = (
                    c.mental if cause == "low_mental" else citizen.summary.metrics.stress
                )
                emit(state, "crisis_evidence", citizen, description=f"{episode.id}: additional {cause}")
        if not recovery or episode.last_checked_tick == state.simulation.tick:
            return
        episode.last_checked_tick = state.simulation.tick
        recovered = (
            c.mental >= RULES["mental_exit"] and citizen.summary.metrics.stress <= RULES["stress_exit"]
        )
        episode.stable_ticks = episode.stable_ticks + 1 if recovered else 0
        if episode.stable_ticks >= RULES["exit_ticks"]:
            episode.end_tick = state.simulation.tick
            c.cooldown_until = state.simulation.tick + RULES["cooldown_ticks"]
            emit(
                state,
                "crisis_end",
                citizen,
                description=f"{episode.id}: both recovery thresholds sustained",
            )
        return
    if not conscious(citizen) or not causes or state.simulation.tick < c.cooldown_until:
        return
    w = weights(citizen)
    persisted = rng is None
    if persisted:
        import random

        from app.simulation.engine import tuple_tree

        rng = random.Random(f"{state.simulation.config.seed}:{VERSION}:crisis")
        if state.behavior.rng_state:
            rng.setstate(tuple_tree(state.behavior.rng_state))
    mode = rng.choices(list(w), weights=list(w.values()), k=1)[0]
    if persisted:
        from app.simulation.engine import list_tree

        state.behavior.rng_state = list_tree(rng.getstate())
    rationale = f"{', '.join(causes)}; personality/context weights {w}"
    c.episode = Episode(
        id=state.next_id("crisis"),
        mode=mode,
        start_tick=state.simulation.tick,
        causes=causes,
        measurements={"mental": c.mental, "stress": citizen.summary.metrics.stress},
        rationale=rationale,
        last_checked_tick=state.simulation.tick if recovery else -1,
    )
    citizen.summary.path = []
    citizen.plan = None
    citizen.task_generation += 1
    emit(state, "crisis", citizen, description=f"{mode}: {rationale}")


def crisis_intent(state, citizen, context):
    """Return a normal v1 movement/rest intent or execute one v2 legal action."""
    from app.behavior.game_master import act
    from app.simulation.game_master import make_intent
    from app.simulation.navigation import meeting_point

    episode = citizen.condition.episode
    if not episode or episode.end_tick is not None:
        return None, False
    # Nutrition and immediate safety take precedence even in withdrawal.
    if hazard_severity(state, citizen.summary.position) or state.policies.evacuation_order:
        return None, False
    if citizen.needs.hunger >= 45:
        for kind in ("food", "water"):
            if getattr(citizen.inventory, kind) >= 1:
                return make_intent(
                    "consume", kind=kind, amount=1, motivation="Meet basic needs during distress"
                ), True
    if state.simulation.tick >= episode.start_tick + RULES["episode_ticks"]:
        return make_intent(
            "rest",
            motivation="Crisis active phase ended; continue recovery until both thresholds are sustained",
        ), True
    mode = episode.mode
    nearby = [state.citizens[aid] for aid in context["nearby_ids"] if conscious(state.citizens[aid])]
    if mode == "aggression":
        targets = [
            p
            for p in nearby
            if p.summary.id in citizen.relationships
            and citizen.relationships[p.summary.id].conflict >= RULES["violent_grievance"]
        ]
        if targets:
            target = max(targets, key=lambda p: citizen.relationships[p.summary.id].conflict)
            if distance(citizen.summary.position, target.summary.position) <= RULES["range"]:
                act(state, citizen, "attack", target.summary.id, context)
                return None, True
            return make_intent(
                "move",
                target=target.summary.id,
                destination=meeting_point(state.map, citizen.summary.position, target.summary.position),
                motivation="Approach a visible person associated with my grievance",
                emotion="angry",
            ), True
    if mode == "fire" and not episode.ignited:
        buildings = [
            b
            for b in state.map.buildings
            if b.kind in {"home", "work", "shop", "community"}
            and b.functional
            and distance(citizen.summary.position, b.entrance) <= 20
            and b.id in citizen.known_locations
        ]
        if buildings:
            b = min(buildings, key=lambda b: distance(citizen.summary.position, b.entrance))
            if distance(citizen.summary.position, b.entrance) <= RULES["range"]:
                act(state, citizen, "ignite", b.id, context)
                return None, True
            return make_intent(
                "move",
                target=b.id,
                destination=b.entrance,
                motivation="Destructive crisis: approach a nearby flammable building",
            ), True
    if mode == "support":
        friends = [
            p
            for p in nearby
            if p.summary.id in citizen.relationships and citizen.relationships[p.summary.id].trust >= 50
        ]
        if friends:
            p = max(friends, key=lambda p: citizen.relationships[p.summary.id].trust)
            if distance(citizen.summary.position, p.summary.position) <= RULES["range"]:
                return make_intent(
                    "talk",
                    target=p.summary.id,
                    motivation="Ask a trusted neighbor for comfort",
                    emotion="worried",
                ), True
            return make_intent(
                "move",
                target=p.summary.id,
                destination=meeting_point(state.map, citizen.summary.position, p.summary.position),
                motivation="Seek support from a visible trusted neighbor",
            ), True
    buildings = [
        b
        for b in state.map.buildings
        if b.functional
        and b.id in citizen.known_locations
        and hazard_severity(state, b.entrance) == 0
        and b.capacity > b.occupancy
        and (mode != "withdrawal" or b.kind == "home")
    ]
    current = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
    needs_home = mode == "withdrawal" and current is not None and current.kind != "home"
    if buildings and (not citizen.inside_building_id or needs_home) and not citizen.summary.path:
        b = min(
            buildings,
            key=lambda b: distance(
                citizen.home if mode == "withdrawal" else citizen.summary.position, b.entrance
            ),
        )
        return make_intent(
            "move",
            target=b.id,
            destination=b.entrance,
            motivation=f"{mode}: seek a known quiet safe room",
            emotion="worried",
        ), True
    if citizen.summary.path:
        return None, True
    return make_intent(
        "rest", motivation=f"{mode}: recover quietly and avoid optional work", emotion="worried"
    ), True
