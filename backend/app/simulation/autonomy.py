"""Character choices use their own motives, subjective ties and public observations."""

import hashlib

from app.simulation.navigation import distance


def social_choice(state, citizen, candidates):
    busy = {
        aid
        for interaction in state.interactions.values()
        if interaction.kind == "conversation"
        and interaction.status in {"invited", "accepted"}
        and interaction.expires_tick >= state.simulation.tick
        for aid in interaction.participant_ids
    }
    choices = []
    for other in candidates:
        if other.summary.id in busy or other.entering_building_id or other.leaving_building_id:
            continue
        tie = citizen.relationships.get(other.summary.id)
        familiarity = tie.familiarity if tie else 0
        affection = tie.affection if tie else 40
        score = affection * 0.5 + (tie.trust * 0.2 if tie else 0)
        score += citizen.profile.traits.curiosity * (1 - familiarity / 100) * 0.35
        from app.behavior.classes import affinity

        score += affinity(citizen, other) * 6
        score -= distance(citizen.summary.position, other.summary.position) * 0.6
        name = other.summary.name.split()[0]
        if (
            other.summary.emotion in {"worried", "concerned", "sad", "alert"}
            and citizen.profile.traits.empathy >= 50
        ):
            score += citizen.profile.traits.empathy * 0.4
            reason = f"{name} looks {other.summary.emotion}; I want to check how they are doing"
        elif tie and tie.kind in {"friend", "family", "romantic"}:
            score += 18
            reason = f"I want to catch up with {name}, my {tie.kind}, and hear about their day"
        elif familiarity < 30:
            reason = f"I'd like to get to know {name} and ask about their work as a {other.summary.role}"
        else:
            reason = f"I want to talk with {name} about my hope to {citizen.profile.primary_goal.lower().rstrip('.')}"
        # Reproducible variety, independent of world RNG and other people's minds.
        key = f"{citizen.summary.id}:{other.summary.id}:{state.simulation.tick // 24}"
        score += int.from_bytes(hashlib.sha256(key.encode()).digest()[:2]) / 65535 * 12
        choices.append((score, other.summary.id, other, reason))
    if not choices:
        return None
    _, _, other, reason = max(choices, key=lambda item: (item[0], item[1]))
    return other, reason


def routine_destination(state, citizen):
    homes = [b for b in state.map.buildings if b.kind == "home" and b.functional]
    home = min(homes, key=lambda b: distance(citizen.home, b.entrance), default=None)
    if citizen.needs.fatigue >= 45 and home and citizen.inside_building_id != home.id:
        return home, "Go home to rest and regain my energy"
    phase = (
        state.simulation.tick // 16 + int.from_bytes(hashlib.sha256(citizen.summary.id.encode()).digest()[:2])
    ) % 3
    kind = ["work", "community", "shop"][phase]
    facilities = [
        b
        for b in state.map.buildings
        if b.kind == kind and b.functional and b.id != citizen.last_building_id and b.occupancy < b.capacity
    ]
    building = min(facilities, key=lambda b: distance(citizen.summary.position, b.entrance), default=None)
    if building:
        reason = {
            "work": "Spend some time at work and contribute to the neighborhood",
            "community": "Visit the community center and see who is around",
            "shop": "Visit the local shop for household errands",
        }[kind]
        return building, reason
    if home and citizen.inside_building_id != home.id:
        return home, "Head home for a quiet moment"
    return None
