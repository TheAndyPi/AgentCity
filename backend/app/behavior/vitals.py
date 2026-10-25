"""Canonical survival transitions and exactly-once time pressure."""

from app.behavior.models import BehaviorEvent, Impact
from app.behavior.rules import RULES, VERSION, bounded, coupling, rest_multiplier
from app.simulation.agents import evidence, remember
from app.simulation.navigation import distance, line_of_sight


def living(citizen):
    return citizen.summary.active and citizen.condition.life != "dead"


def conscious(citizen):
    return living(citizen) and citizen.condition.life == "alive"


def emit(state, kind, actor, target=None, description="", proof=None):
    record = BehaviorEvent(
        id=state.next_id("behavior"),
        tick=state.simulation.tick,
        kind=kind,
        actor_id=actor.summary.id if actor else None,
        target_id=target.summary.id if target else None,
        description=description,
        evidence=proof or evidence(description),
    )
    state.behavior.events.append(record)
    state.behavior.counters[kind] = state.behavior.counters.get(kind, 0) + 1
    return record


def activate_rules(state):
    if state.behavior.version:
        return
    state.behavior.version = VERSION
    state.behavior.activated_tick = state.simulation.tick
    state.behavior.initial_population = len(state.citizens)
    state.rule_version = VERSION
    for c in state.citizens.values():
        if not c.summary.active:
            c.condition.life = "dead"  # compatibility, no retroactive death/history
    emit(state, "rules_activated", None, description=f"Live rules {VERSION}; legacy Mental defaults to 70")


def impact(state, citizen, meter, delta, reason, phase="activity", proof=None):
    if not living(citizen):
        return 0
    attr = {"social": "social", "energy": "fatigue", "health": "health", "fullness": "hunger"}
    inverse = meter in {"social", "energy", "fullness"}
    before = citizen.condition.mental if meter == "mental" else getattr(citizen.needs, attr[meter])
    after = bounded(before + (-delta if inverse else delta))
    actual = (before - after) if inverse else (after - before)
    if meter == "mental":
        citizen.condition.mental = after
    else:
        setattr(citizen.needs, attr[meter], after)
    if actual:
        citizen.condition.impacts.append(
            Impact(
                tick=state.simulation.tick,
                phase=phase,
                meter=meter,
                reason=reason,
                delta=actual,
                evidence=proof or evidence(reason),
            )
        )
        citizen.condition.impacts = citizen.condition.impacts[-120:]
    return actual


def detach(state, citizen):
    condition = citizen.condition
    if condition.patient_id:
        patient = state.citizens.get(condition.patient_id)
        if patient:
            if patient.condition.care in {"carried", "escorted"}:
                patient.summary.position = citizen.summary.position.model_copy()
                patient.inside_building_id = citizen.inside_building_id
            patient.condition.helper_id = None
            patient.condition.care = "none"
            patient.condition.hospital_id = None
        condition.patient_id = None
    if condition.helper_id:
        helper = state.citizens.get(condition.helper_id)
        if helper:
            helper.condition.patient_id = None
            helper.summary.path = []
            helper.entering_building_id = None
        condition.helper_id = None
    for hospital in state.behavior.hospitals.values():
        if citizen.summary.id in hospital.patients:
            hospital.patients.remove(citizen.summary.id)
        hospital.reservations.pop(citizen.summary.id, None)
        for patient_id, helper_id in list(hospital.reservations.items()):
            if helper_id == citizen.summary.id:
                del hospital.reservations[patient_id]
    condition.hospital_id = None
    condition.care = "none"


def stop(state, citizen):
    citizen.summary.path = []
    citizen.plan = None
    citizen.entering_building_id = citizen.leaving_building_id = None
    citizen.task_generation += 1
    citizen.generation += 1
    for i in state.interactions.values():
        if citizen.summary.id in i.participant_ids and i.status in {"invited", "accepted"}:
            i.status = "ended"
    state.schedules = [s for s in state.schedules if s.get("agent_id") != citizen.summary.id]


def evaluate(state, citizen, reason="Canonical threshold check", proof=None):
    """No rounding. Fatal checks always precede fainting, wake and crisis work."""
    c = citizen.condition
    if c.life == "dead":
        citizen.summary.active = False
        return
    if not citizen.summary.active:
        c.life = "dead"
        stop(state, citizen)
        detach(state, citizen)
        return
    causes = []
    if citizen.needs.health <= 0:
        causes.append("health")
    if citizen.needs.hunger >= 100:
        causes.append("fullness")
    if causes:
        c.life = "dead"
        c.causes = causes
        c.transition_tick = state.simulation.tick
        c.evidence = proof or evidence(reason)
        citizen.summary.active = False
        citizen.summary.emotion = "dead"
        stop(state, citizen)
        detach(state, citizen)
        death_room = citizen.inside_building_id
        citizen.inside_building_id = None
        citizen.summary.action = "idle"
        citizen.summary.thought_bubble = f"Dead at tick {state.simulation.tick}: {', '.join(causes)}"
        emit(state, "death", citizen, description=citizen.summary.thought_bubble, proof=c.evidence)
        # Only actual local witnesses learn the death. No world-wide private broadcast.
        for witness in state.citizens.values():
            if (
                conscious(witness)
                and witness.inside_building_id == death_room
                and distance(witness.summary.position, citizen.summary.position) <= 20
                and (
                    death_room or line_of_sight(state.map, witness.summary.position, citizen.summary.position)
                )
            ):
                tie = witness.relationships.get(citizen.summary.id)
                remember(
                    state,
                    witness,
                    f"I witnessed {citizen.summary.name}'s death.",
                    subjects=[citizen.summary.id],
                    proof=c.evidence,
                )
                if tie and (tie.kind in {"family", "friend", "romantic"} or tie.affection >= 60):
                    impact(
                        state,
                        witness,
                        "mental",
                        RULES["grief_mental"],
                        "Witnessed loss of a loved one",
                        proof=c.evidence,
                    )
                    emit(state, "grief", witness, citizen, "Witnessed loss of a known loved one", c.evidence)
        return
    if c.life == "alive" and citizen.needs.fatigue >= 100:
        c.life = "unconscious"
        c.causes = ["energy"]
        c.transition_tick = state.simulation.tick
        c.evidence = proof or evidence(reason)
        stop(state, citizen)
        # A hospital patient keeps their bed; a carrier must safely drop their patient.
        if c.patient_id:
            detach(state, citizen)
        citizen.summary.action = "idle"
        citizen.summary.emotion = "unconscious"
        citizen.summary.thought_bubble = "Unconscious: energy depleted; waiting for passive recovery or care"
        emit(state, "faint", citizen, description=citizen.summary.thought_bubble, proof=c.evidence)
    elif c.life == "unconscious" and 100 - citizen.needs.fatigue >= RULES["wake_energy"]:
        c.life = "alive"
        c.transition_tick = state.simulation.tick
        c.causes = ["energy_recovered"]
        citizen.summary.emotion = "calm"
        citizen.summary.thought_bubble = "Awake after energy recovery"
        emit(state, "wake", citizen, description=citizen.summary.thought_bubble)
        from app.behavior.learning import learn_collapse

        learn_collapse(state, citizen)
    if conscious(citizen):
        from app.behavior.crisis import evaluate_crisis

        evaluate_crisis(state, citizen, recovery=False)


def background(state, citizen):
    c = citizen.condition
    if not living(citizen) or c.last_coupling_tick == state.simulation.tick:
        return
    c.last_coupling_tick = state.simulation.tick
    outputs = coupling(
        citizen.summary.metrics.model_copy(), state.simulation.config.calendar_seconds_per_tick / 60
    )
    # Clamp the aggregate once, then apportion the actual contribution including meter bounds.
    for meter, parts in outputs.items():
        total = sum(parts.values())
        before = (
            c.mental
            if meter == "mental"
            else 100 - getattr(citizen.needs, "social" if meter == "social" else "fatigue")
        )
        actual = bounded(before + total) - before
        scale = actual / total if total else 1
        # Apply outputs simultaneously, avoiding intermediate clamping of opposite signs.
        after = bounded(before + total)
        if meter == "mental":
            c.mental = after
        else:
            setattr(citizen.needs, "social" if meter == "social" else "fatigue", 100 - after)
        for key, delta in parts.items():
            if delta * scale:
                c.impacts.append(
                    Impact(
                        tick=state.simulation.tick,
                        phase="metric_pressure",
                        meter=meter,
                        reason=f"{key} pressure",
                        delta=delta * scale,
                        evidence=evidence(f"Frozen-input {key} pressure"),
                    )
                )
        c.impacts = c.impacts[-120:]
    evaluate(state, citizen, "End-of-tick metric pressure")


def passive(state, citizen):
    c = citizen.condition
    if not living(citizen) or c.last_passive_tick == state.simulation.tick:
        return
    c.last_passive_tick = state.simulation.tick
    if c.life == "unconscious" and c.care != "hospital":
        impact(
            state,
            citizen,
            "energy",
            RULES["passive_energy"] * state.simulation.config.tick_seconds / 10,
            "Passive unconscious recovery",
            "passive",
        )
        evaluate(state, citizen, "Passive unconscious recovery")


def rest(state, citizen, base=None, phase="activity"):
    if not living(citizen):
        return
    if base is None:
        from app.simulation.agents import metric_delta
        from app.simulation.calendar import hours_per_tick
        from app.simulation.daily import RATES

        hours = hours_per_tick(state)
        asleep = citizen.summary.routine_state == "sleeping"
        base = RATES["sleep_energy" if asleep else "rest_energy"] * hours
        impact(state, citizen, "mental", RATES["rest_mental"] * hours, "Quiet rest", phase)
        metric_delta(citizen, "stress", RATES["rest_stress"] * hours, evidence("Time spent resting"))
    else:
        dt = state.simulation.config.tick_seconds / 10
        base *= dt
        impact(state, citizen, "mental", RULES["rest_mental"] * dt, "Quiet rest", phase)
    impact(state, citizen, "energy", base * rest_multiplier(citizen), "Rest quality", phase)


def share_loss(state, actor, listener, text, proof):
    """A confirmed loss spreads only through an actual audible recorded report."""
    if not conscious(listener) or not any(word in text.lower() for word in ("death", "died")):
        return
    for memory in list(actor.memories):
        if (
            memory.source not in {"observed", "heard"}
            or not memory.text.startswith(("I witnessed ", "I heard about "))
            or "death" not in memory.text.lower()
        ):
            continue
        for aid in memory.subject_ids:
            deceased = state.citizens.get(aid)
            if not deceased or living(deceased) or deceased.summary.name not in text:
                continue
            known = any(
                aid in m.subject_ids
                and m.text.startswith(("I witnessed ", "I heard about "))
                and "death" in m.text.lower()
                for m in listener.memories
            )
            if known:
                continue
            remember(
                state,
                listener,
                f"I heard about {deceased.summary.name}'s death from {actor.summary.name}.",
                source="heard",
                subjects=[aid],
                proof=proof,
            )
            tie = listener.relationships.get(aid)
            if tie and (tie.kind in {"family", "friend", "romantic"} or tie.affection >= 60):
                impact(
                    state,
                    listener,
                    "mental",
                    RULES["grief_mental"],
                    "Heard a witnessed loss from a nearby speaker",
                    proof=proof,
                )
                emit(
                    state,
                    "grief",
                    listener,
                    deceased,
                    "Learned a loved one's death through local communication",
                    proof,
                )
