"""Explicit invitations and acceptances, bounded conversation and local hearing."""

import math

from app.contracts import Belief, Dialogue
from app.simulation import calendar
from app.simulation.agents import evidence, remember, social_delta
from app.simulation.building_visits import same_room, sync_building_location
from app.simulation.dialogue import rule_speech
from app.simulation.indexes import spatial_index
from app.simulation.navigation import distance, line_of_sight
from app.simulation.state import Interaction
from app.simulation.timing import legacy_ticks


def active_conversation(state, citizen):
    return next(
        (
            i
            for i in state.interactions.values()
            if i.kind == "conversation"
            and i.status in {"invited", "accepted"}
            and citizen.summary.id in i.participant_ids
            and (i.status == "accepted" or i.expires_tick >= state.simulation.tick)
        ),
        None,
    )


def start_session(state, interaction):
    if interaction.accepted_calendar_seconds is None:
        interaction.accepted_calendar_seconds = calendar.now(state)
        interaction.minimum_end_calendar_seconds = calendar.now(state) + calendar.HOUR
        interaction.next_turn_calendar_seconds = calendar.now(state)
        interaction.last_benefit_calendar_seconds = calendar.now(state)


def end_session(state, interaction, reason):
    interaction.status = "rejected" if interaction.status == "invited" and reason == "separated" else "ended"
    interaction.end_reason = reason
    for aid in interaction.participant_ids:
        citizen = state.citizens.get(aid)
        if citizen is None:
            continue
        citizen.next_social_tick = state.simulation.tick + legacy_ticks(state, 10)
        # Releasing a conversation must not cancel a rescue or evacuation that
        # already claimed the actor at this same decision boundary.
        if (
            not citizen.condition.patient_id
            and citizen.condition.care == "none"
            and citizen.summary.action != "evacuate"
        ):
            citizen.summary.path = []
        if citizen.plan and citizen.plan.get("kind") == "social_visit":
            citizen.plan = None
        if citizen.summary.routine_state == "talking":
            from app.simulation.daily import set_activity

            set_activity(citizen, "free")
        citizen.task_generation += 1


def conversation_intent(state, citizen, context=None):
    from app.simulation.game_master import make_intent

    session = active_conversation(state, citizen)
    if session is None:
        return None, False
    other = next(
        (state.citizens.get(aid) for aid in session.participant_ids if aid != citizen.summary.id), None
    )
    if (
        not other
        or not same_room(citizen, other)
        or distance(citizen.summary.position, other.summary.position) > 3
    ):
        end_session(state, session, "separated")
        return None, False
    if session.status == "accepted":
        start_session(state, session)
    lines = state.dialogue_index().by_interaction.get(session.id, [])
    last = lines[-1] if lines else None
    from app.simulation.daily import set_activity

    set_activity(citizen, "talking", session.minimum_end_calendar_seconds or 0, other.summary.id)
    if (
        last
        and last.speaker_id != citizen.summary.id
        and last.tick < state.simulation.tick
        and (
            session.next_turn_calendar_seconds is None
            or calendar.now(state) >= session.next_turn_calendar_seconds
        )
    ):
        return make_intent(
            "talk", target=other.summary.id, motivation="Reply to my neighbor during our conversation"
        ), True
    return make_intent(
        "idle",
        target=other.summary.id,
        motivation="Listen while my neighbor speaks; take time for our conversation",
    ), True


def interrupt_conversations(state):
    from app.behavior.vitals import conscious
    from app.simulation.agents import hazard_severity
    from app.simulation.daily import curfew_window

    for session in state.interactions.values():
        if session.kind != "conversation" or session.status not in {"invited", "accepted"}:
            continue
        for aid in session.participant_ids:
            citizen = state.citizens.get(aid)
            reason = None
            if citizen is None or not conscious(citizen) or citizen.trapped_building_id:
                reason = "incapacitated"
            elif citizen.condition.care != "none" or citizen.condition.patient_id:
                reason = "medical_care"
            elif hazard_severity(state, citizen.summary.position) or state.policies.evacuation_order:
                reason = "danger"
            elif citizen.needs.hunger > 80 or citizen.needs.fatigue >= 90:
                reason = "urgent_needs"
            else:
                window = curfew_window(state, citizen)
                if window and window[0] <= calendar.now(state) < window[1]:
                    reason = "curfew"
            if reason:
                end_session(state, session, reason)
                break


def conversation_benefits(state):
    from app.behavior.rules import RULES, social_multiplier
    from app.behavior.vitals import impact
    from app.simulation.daily import RATES

    for session in state.interactions.values():
        if session.kind != "conversation" or session.status != "accepted":
            continue
        start_session(state, session)
        hours = max(0, calendar.now(state) - session.last_benefit_calendar_seconds) / calendar.HOUR
        session.last_benefit_calendar_seconds = calendar.now(state)
        people = [state.citizens[aid] for aid in session.participant_ids]
        for citizen, other in (people, list(reversed(people))):
            tie = citizen.relationships.get(other.summary.id)
            if tie and tie.conflict >= 50:
                continue
            impact(
                state,
                citizen,
                "social",
                RATES["conversation_social"] * hours * social_multiplier(citizen, other),
                "Time spent in accepted conversation",
            )
            impact(state, citizen, "mental", RULES["comfort_mental"] * hours, "Accepted social support")
            from app.simulation.agents import metric_delta

            metric_delta(
                citizen,
                "stress",
                RULES["comfort_stress"] * hours,
                evidence("Time spent talking with a neighbor"),
            )


def accept_invitation(state, actor, target, kind, proposal=None):
    for interaction in state.interactions.values():
        if (
            kind == "conversation"
            and interaction.kind == kind
            and interaction.status in {"invited", "accepted"}
            and set(interaction.participant_ids) == {actor.summary.id, target.summary.id}
            and (interaction.status == "accepted" or interaction.expires_tick >= state.simulation.tick)
        ):
            if actor.summary.id not in interaction.accepted_ids:
                interaction.accepted_ids.append(actor.summary.id)
            interaction.status = (
                "accepted" if set(interaction.participant_ids) <= set(interaction.accepted_ids) else "invited"
            )
            if interaction.status == "accepted":
                start_session(state, interaction)
            return interaction, interaction.status == "accepted"
        if (
            interaction.kind == kind
            and interaction.status == "invited"
            and interaction.initiator_id == target.summary.id
            and actor.summary.id in interaction.participant_ids
            and interaction.expires_tick >= state.simulation.tick
        ):
            interaction.accepted_ids.append(actor.summary.id)
            interaction.status = "accepted"
            return interaction, True
    interaction = Interaction(
        id=state.next_id("interaction"),
        kind=kind,
        initiator_id=actor.summary.id,
        participant_ids=[actor.summary.id, target.summary.id],
        accepted_ids=[actor.summary.id],
        expires_tick=state.simulation.tick + legacy_ticks(state, 3),
        proposal=proposal or {},
    )
    state.interactions[interaction.id] = interaction
    return interaction, False


def speak(state, actor, target, intent, decision_id, interaction):
    previous = state.dialogue_index().by_interaction.get(interaction.id, [])
    text = (intent.parameters.message or rule_speech(state, actor, target, intent, interaction, previous))[
        :2000
    ]
    from app.behavior.vitals import conscious, share_loss

    # Physical filtering occurs independently for each message, including overhearers.
    audible = [
        c.summary.id
        for c in spatial_index(state).nearby(actor.summary.position, 8)
        if conscious(c)
        and same_room(actor, c)
        and (actor.inside_building_id or line_of_sight(state.map, actor.summary.position, c.summary.position))
    ]
    dialogue = Dialogue(
        id=state.next_id("dialogue"),
        interaction_id=interaction.id,
        tick=state.simulation.tick,
        speaker_id=actor.summary.id,
        recipient_ids=[target.summary.id],
        audible_to_ids=audible,
        text=text,
        intent=intent.action,
        emotion=intent.emotion,
        end_conversation=interaction.kind == "conversation"
        and interaction.status == "accepted"
        and interaction.turns >= 3
        and interaction.minimum_end_calendar_seconds is not None
        and calendar.now(state) >= interaction.minimum_end_calendar_seconds,
    )
    actor.summary.path = []
    actor.plan = None
    sync_building_location(state, actor)
    actor.summary.heading_rad = math.atan2(
        target.summary.position.x - actor.summary.position.x,
        target.summary.position.y - actor.summary.position.y,
    ) % (2 * math.pi)
    if interaction.status == "accepted":
        target.summary.heading_rad = (actor.summary.heading_rad + math.pi) % (2 * math.pi)
    interaction.expires_tick = state.simulation.tick + legacy_ticks(state, 5)
    if interaction.kind == "conversation" and interaction.status == "accepted":
        interaction.next_turn_calendar_seconds = calendar.now(state) + 20 * 60
        interaction.expires_tick += math.ceil(
            calendar.HOUR / state.simulation.config.calendar_seconds_per_tick
        )
    interaction.turns += 1
    if interaction.kind == "warning":
        interaction.status = "ended"
    if dialogue.end_conversation:
        end_session(state, interaction, "completed")
    state.dialogue.append(dialogue)
    if not intent.parameters.message:
        interaction.proposal["last_rule_line"] = dialogue.id
    proof = evidence(
        f"Heard {actor.summary.name} ({actor.summary.id}) speak nearby; reported information can be uncertain",
        decision_ids=[decision_id],
    )
    for aid in audible:
        if aid == actor.summary.id:
            continue
        citizen = state.citizens[aid]
        memory = remember(
            state,
            citizen,
            f"{actor.summary.name} said: {text}",
            source="heard",
            subjects=[actor.summary.id],
            proof=proof,
        )
        share_loss(state, actor, citizen, text, proof)
        if intent.action == "warn":
            citizen.beliefs.append(
                Belief(
                    text=f"{actor.summary.id} reports: {text}"[:2000],
                    confidence=citizen.relationships[actor.summary.id].trust
                    if actor.summary.id in citizen.relationships
                    else state.simulation.config.environment.initial_community_trust,
                    evidence=evidence(proof.description, decision_ids=[decision_id], memory_ids=[memory.id]),
                )
            )
            citizen.next_deliberation_tick = state.simulation.tick
    social_delta(state, target, actor, decision_id, 1)
    return dialogue


def expire_interactions(state):
    for interaction in state.interactions.values():
        if interaction.status in {"ended", "expired", "rejected"}:
            continue
        participants = [state.citizens[aid] for aid in interaction.participant_ids if aid in state.citizens]
        if len(participants) != len(interaction.participant_ids) or any(
            not same_room(participants[0], c)
            or distance(participants[0].summary.position, c.summary.position) > 3
            for c in participants[1:]
        ):
            if interaction.kind == "conversation":
                end_session(state, interaction, "separated")
            else:
                interaction.status = "rejected" if interaction.status == "invited" else "ended"
        elif interaction.expires_tick < state.simulation.tick and not (
            interaction.kind == "conversation" and interaction.status == "accepted"
        ):
            interaction.status = "expired"
            interaction.end_reason = "invitation_expired"


def coordinate_aid(state, actor, target, decision_id):
    """Membership is an invitation; only an actual helper explicitly accepts."""
    group = next(
        (
            interaction
            for interaction in state.interactions.values()
            if interaction.kind == "aid_group"
            and interaction.status in {"invited", "accepted"}
            and interaction.proposal.get("target_id") == target.summary.id
            and actor.summary.id in interaction.participant_ids
            and interaction.expires_tick >= state.simulation.tick
        ),
        None,
    )
    if group is None:
        candidates = [
            citizen.summary.id
            for citizen in spatial_index(state).nearby(actor.summary.position, 3)
            if citizen.summary.id != target.summary.id
            and line_of_sight(state.map, actor.summary.position, citizen.summary.position)
        ][:8]
        if actor.summary.id not in candidates:
            candidates.append(actor.summary.id)
        group = Interaction(
            id=state.next_id("group"),
            kind="aid_group",
            initiator_id=actor.summary.id,
            participant_ids=candidates,
            accepted_ids=[],
            expires_tick=state.simulation.tick + legacy_ticks(state, 5),
            proposal=dict(
                target_id=target.summary.id, description="Offer local aid; participation is voluntary"
            ),
        )
        state.interactions[group.id] = group
    if actor.summary.id not in group.accepted_ids:
        group.accepted_ids.append(actor.summary.id)
    group.status = "accepted"
    group.proposal.setdefault("decision_ids", []).append(decision_id)
