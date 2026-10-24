from test_social_life import city

from app.contracts import Vec2
from app.simulation.agents import update_metrics
from app.simulation.autonomy import social_choice
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.navigation import distance, polygon_contains


def arrive(state, actor):
    for _ in range(40):
        if not actor.summary.path:
            break
        advance_movement(state, actor)
    assert not actor.summary.path, (actor.summary.position, actor.summary.path)


def test_walk_into_building_count_occupants_and_exit_through_door(client):
    state = city(client)
    actor = next(iter(state.citizens.values()))
    for c in state.citizens.values():
        c.summary.active = c is actor
    building = next(b for b in state.map.buildings if b.kind == "home")
    actor.summary.position = building.entrance.model_copy()
    before = actor.summary.position.model_copy()
    decision = apply_intent(state, actor, make_intent("move", target=building.id))
    assert decision.outcome == "accepted", decision.outcome_description
    assert actor.summary.position == before
    assert len(actor.summary.path) >= 2
    assert polygon_contains(actor.summary.path[-1], building.footprint)
    arrive(state, actor)
    assert actor.inside_building_id == building.id
    assert polygon_contains(actor.summary.position, building.footprint)
    update_metrics(state)
    assert building.occupancy == 1
    saved = state.model_copy(deep=True)
    assert saved.citizens[actor.summary.id].inside_building_id == building.id
    decision = apply_intent(state, actor, make_intent("move", destination=before))
    assert decision.outcome == "accepted"
    assert actor.leaving_building_id == building.id
    arrive(state, actor)
    assert actor.summary.position == before
    assert actor.inside_building_id is None
    update_metrics(state)
    assert building.occupancy == 0


def test_reserve_room_capacity_and_reject_closed_buildings(client):
    state = city(client)
    a, b = list(state.citizens.values())[:2]
    building = next(b for b in state.map.buildings if b.kind == "home")
    building.capacity = 1
    a.summary.position = building.entrance.model_copy()
    assert apply_intent(state, a, make_intent("move", target=building.id)).outcome == "accepted"
    assert apply_intent(state, b, make_intent("move", target=building.id)).outcome == "rejected"
    building.functional = False
    assert (
        apply_intent(state, b, make_intent("move", target=building.id)).rejection_code
        == "INFRASTRUCTURE_UNAVAILABLE"
    )


def test_people_choose_a_friend_for_a_reason_without_reading_their_private_profile(client):
    state = city(client)
    a, b, c = list(state.citizens.values())[:3]
    a.summary.position, b.summary.position, c.summary.position = (
        Vec2(x=30, y=33),
        Vec2(x=36, y=33),
        Vec2(x=32, y=33),
    )
    tie = next(iter(a.relationships.values())).model_copy(deep=True)
    tie.to_agent_id, tie.kind, tie.affection, tie.trust = b.summary.id, "friend", 95, 95
    a.relationships = {b.summary.id: tie}
    chosen, reason = social_choice(state, a, [b, c])
    assert chosen is b and "friend" in reason
    b.profile.primary_goal = "PRIVATE SECRET"
    assert social_choice(state, a, [b, c])[1] == reason
    assert "PRIVATE" not in reason


def test_neighborhood_talks_and_visits_facilities_without_owner_commands(client):
    state = city(client)
    for citizen in state.citizens.values():
        citizen.needs.hunger = citizen.needs.fatigue = 0
        citizen.needs.social = 70
    for _ in range(40):
        tick(state)
    assert state.dialogue
    assert any(d.intent.action == "talk" and d.source == "rules" for d in state.decisions)
    assert any(c.last_building_id for c in state.citizens.values())
    assert all(d.intent.motivation for d in state.decisions if d.intent.action == "talk")


def test_two_people_can_enter_and_talk_inside_without_being_heard_through_walls(client):
    state = city(client)
    a, b, outsider = list(state.citizens.values())[:3]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b, outsider)
    facility = next(b for b in state.map.buildings if b.kind == "community")
    a.summary.position = facility.entrance.model_copy()
    b.summary.position, outsider.summary.position = Vec2(x=1, y=1), Vec2(x=3, y=1)
    for actor in (a, b):
        result = apply_intent(state, actor, make_intent("move", target=facility.id))
        assert result.outcome == "accepted"
        arrive(state, actor)
        assert actor.inside_building_id == facility.id
    assert distance(a.summary.position, b.summary.position) >= 1.6
    result = apply_intent(state, a, make_intent("talk", target=b.summary.id))
    assert result.outcome == "accepted", result.outcome_description
    assert b.summary.id in state.dialogue[-1].audible_to_ids
    assert outsider.summary.id not in state.dialogue[-1].audible_to_ids
