"""Explicit invitations and acceptances, bounded conversation and local hearing."""

from app.contracts import Belief, Dialogue
from app.simulation.agents import evidence, remember, social_delta
from app.simulation.navigation import SpatialIndex, distance, line_of_sight
from app.simulation.state import Interaction


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
                interaction.status = "accepted"
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
        expires_tick=state.simulation.tick + 3,
        proposal=proposal or {},
    )
    state.interactions[interaction.id] = interaction
    return interaction, False


def speak(state, actor, target, intent, decision_id, interaction):
    previous = [d for d in state.dialogue if d.interaction_id == interaction.id]
    events = [m for m in actor.memories if m.text.startswith("World event:")]
    if intent.action == "warn":
        fallback = "There is danger nearby; please find a safe route."
    elif not previous:
        fallback = (
            f"Did you see what happened? {events[-1].text.removeprefix('World event: ')}"
            if events
            else f"Hi {target.summary.name.split()[0]}! How is your day going?"
        )
    elif len(previous) == 1:
        fallback = (
            "I heard you. I'd like to see how we can help each other."
            if actor.profile.traits.empathy >= 60
            else f"I've been thinking about my own plans. {actor.profile.primary_goal}"
        )
    elif len(previous) == 2:
        fallback = f"That makes sense. For me, what matters is {', '.join(actor.profile.values[:2]) or 'getting through the day'}."
    else:
        fallback = f"Thanks for talking, {target.summary.name.split()[0]}. See you around!"
    text = (intent.parameters.message or fallback)[:2000]
    # Physical filtering occurs independently for each message, including overhearers.
    audible = [
        c.summary.id
        for c in SpatialIndex(state.citizens).nearby(actor.summary.position, 8)
        if line_of_sight(state.map, actor.summary.position, c.summary.position)
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
        end_conversation=interaction.turns >= 3,
    )
    interaction.turns += 1
    if dialogue.end_conversation:
        interaction.status = "ended"
    state.dialogue.append(dialogue)
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
            for citizen in SpatialIndex(state.citizens).nearby(actor.summary.position, 3)
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
            expires_tick=state.simulation.tick + 5,
            proposal=dict(
                target_id=target.summary.id, description="Offer local aid; participation is voluntary"
            ),
        )
        state.interactions[group.id] = group
    if actor.summary.id not in group.accepted_ids:
        group.accepted_ids.append(actor.summary.id)
    group.status = "accepted"
    group.proposal.setdefault("decision_ids", []).append(decision_id)
