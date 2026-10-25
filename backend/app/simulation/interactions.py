"""Explicit invitations and acceptances, bounded conversation and local hearing."""

import math

from app.contracts import Belief, Dialogue
from app.simulation.agents import evidence, remember, social_delta
from app.simulation.building_visits import same_room, sync_building_location
from app.simulation.dialogue import rule_speech
from app.simulation.indexes import spatial_index
from app.simulation.navigation import distance, line_of_sight
from app.simulation.state import Interaction
from app.simulation.timing import legacy_ticks


def accept_invitation(state, actor, target, kind, proposal=None):
    for interaction in state.interactions.values():
        if (
            kind == "conversation"
            and interaction.kind == kind
            and interaction.status in {"invited", "accepted"}
            and set(interaction.participant_ids) == {actor.summary.id, target.summary.id}
            and interaction.expires_tick >= state.simulation.tick
        ):
            if actor.summary.id not in interaction.accepted_ids:
                interaction.accepted_ids.append(actor.summary.id)
            interaction.status = (
                "accepted" if set(interaction.participant_ids) <= set(interaction.accepted_ids) else "invited"
            )
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
        and interaction.turns >= 3,
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
    interaction.turns += 1
    if interaction.kind == "warning":
        interaction.status = "ended"
    if dialogue.end_conversation:
        interaction.status = "ended"
        for citizen in (actor, target):
            citizen.next_social_tick = state.simulation.tick + legacy_ticks(state, 10)
            citizen.summary.path = []
            if citizen.plan and citizen.plan.get("kind") == "social_visit":
                citizen.plan = None
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
            distance(participants[0].summary.position, c.summary.position) > 3 for c in participants[1:]
        ):
            interaction.status = "rejected" if interaction.status == "invited" else "ended"
        elif interaction.expires_tick < state.simulation.tick:
            interaction.status = "expired"


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
