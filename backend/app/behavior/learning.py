"""Small behavior-owned learning seam for the companion progression assignment."""

from typing import Literal

from app.contracts import Model


class RestLesson(Model):
    id: str
    learner_id: str
    topic: Literal["rest_energy"] = "rest_energy"
    context: str = "Personal recovery after energy collapse"
    supporting_source_ids: list[str]
    contradicting_source_ids: list[str]
    origin: Literal["observed"] = "observed"
    outcome_tick: int
    outcome_revision: int
    confidence: float
    baseline: float
    before: float
    after: float
    last_applied_tick: int | None = None
    rule_version: str


BASELINE = 35  # Existing v1 voluntary rest policy: fatigue >=65.
STEP = 5
CAP = 45


def threshold(citizen):
    return citizen.rest_lessons[-1].after if citizen.rest_lessons else BASELINE


def learn_collapse(state, citizen):
    from app.behavior.vitals import conscious, emit

    if not conscious(citizen):
        return
    source = next(
        (
            e
            for e in reversed(state.behavior.events)
            if e.kind == "faint" and e.actor_id == citizen.summary.id
        ),
        None,
    )
    if not source or any(source.id in lesson.supporting_source_ids for lesson in citizen.rest_lessons):
        return
    before = threshold(citizen)
    if before >= CAP:
        return
    lesson = RestLesson(
        id=state.next_id("rest_lesson"),
        learner_id=citizen.summary.id,
        supporting_source_ids=[source.id],
        contradicting_source_ids=[],
        outcome_tick=state.simulation.tick,
        outcome_revision=state.simulation.revision,
        confidence=100,
        baseline=BASELINE,
        before=before,
        after=min(CAP, before + STEP),
        rule_version="2.0.0",
    )
    citizen.rest_lessons.append(lesson)
    emit(
        state,
        "lesson_learned",
        citizen,
        description=f"Survived personal energy collapse {source.id}: voluntary rest Energy threshold {before:g} -> {lesson.after:g}; physical faint/death thresholds unchanged",
    )


def applied(state, citizen, intent, decision_id, before_energy):
    from app.behavior.vitals import emit

    if (
        not intent.motivation.startswith("Learned rest threshold: ")
        or not citizen.rest_lessons
        or not BASELINE < before_energy <= threshold(citizen)
    ):
        return
    home_move = intent.action == "move" and any(
        b.id == intent.target_id and b.kind == "home" for b in state.map.buildings
    )
    if intent.action != "rest" and not home_move:
        return
    lesson = citizen.rest_lessons[-1]
    if lesson.last_applied_tick == state.simulation.tick:
        return
    from app.simulation.agents import evidence

    lesson.last_applied_tick = state.simulation.tick
    emit(
        state,
        "lesson_applied",
        citizen,
        description=f"{lesson.id}: Energy {before_energy:g}; learned rest threshold {lesson.after:g} instead of baseline {BASELINE:g}",
        proof=evidence("A survived collapse changed the validated rest choice", decision_ids=[decision_id]),
    )


def rest_reason(citizen, reason):
    return (
        "Learned rest threshold: " + reason
        if citizen.rest_lessons and BASELINE < 100 - citizen.needs.fatigue <= threshold(citizen)
        else reason
    )
