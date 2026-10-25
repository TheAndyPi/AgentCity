import pytest
from conftest import create_city
from test_social_life import city

from app.contracts import Vec2
from app.simulation.agents import update_metrics
from app.simulation.autonomy import routine_destination, social_choice
from app.simulation.building_visits import interior_slot, walkable_segment
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.navigation import distance, polygon_contains
from app.simulation.scenarios import compile_preview, queue_event


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


@pytest.mark.parametrize(("population", "settlement"), [(10, "suburb"), (10, "urban"), (80, "urban")])
def test_citizens_keep_moving_after_scenario_outcome_and_resume(client, population, settlement):
    sid = create_city(
        client, population=population, environment=dict(population_density=75, settlement=settlement)
    )["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    preview = compile_preview(state, "custom", "An alien arrival during a festival for 2 ticks")
    event = queue_event(state, preview, state.snapshots[0].id, True)
    state.simulation.status = "running"
    while event.status != "resolved":
        tick(state)
    assert state.simulation.pause_reason == "outcome"
    assert state.auto_resume
    # The owner continues after reading the outcome; the event itself is over.
    state.simulation.pending_outcome_event_ids.clear()
    state.simulation.status = "running"
    state.simulation.pause_reason = None
    state.auto_resume = False
    for _ in range(60):
        tick(state)
    for _ in range(3):
        positions = {aid: citizen.summary.position.model_copy() for aid, citizen in state.citizens.items()}
        moved = set()
        acted = set()
        for _ in range(40):
            tick(state)
            moved.update(
                aid
                for aid, citizen in state.citizens.items()
                if distance(positions[aid], citizen.summary.position) > 1
            )
            acted.update(
                decision.agent_id
                for decision in state.decisions
                if decision.tick == state.simulation.tick
                and decision.outcome == "accepted"
                and decision.intent.action
                in {"rest", "work", "gather", "consume", "help", "talk", "trade", "warn"}
            )
        # Citizens can legitimately stay put to eat, rest or work. A majority
        # must still travel, and every other citizen must complete useful actions.
        assert len(moved) > len(state.citizens) // 2
        assert moved | acted == set(state.citizens), {
            citizen.summary.name: (citizen.summary.position, citizen.summary.path[:2])
            for aid, citizen in state.citizens.items()
            if aid not in moved | acted
        }


def test_indoor_detours_cannot_cut_across_a_wall(client):
    state = city(client)
    actor = next(iter(state.citizens.values()))
    building = next(b for b in state.map.buildings if b.kind == "home")
    actor.inside_building_id = building.id
    xs, ys = [p.x for p in building.footprint], [p.y for p in building.footprint]
    middle = Vec2(x=sum(xs) / len(xs), y=sum(ys) / len(ys))
    corner = Vec2(x=min(xs) + 0.8, y=min(ys) + 0.8)
    assert walkable_segment(state, actor, middle, corner)
    # The lawn beyond the wall is walkable, but leaving must use the doorway.
    outside = Vec2(x=max(xs) + 1, y=middle.y)
    assert not walkable_segment(state, actor, middle, outside)


def test_routine_skips_a_physically_full_facility_even_below_declared_capacity(client):
    state = city(client)
    actor, *visitors = list(state.citizens.values())
    actor.needs.fatigue = 0
    buildings = [b for b in state.map.buildings if b.kind in {"work", "community", "shop"}]
    for building in buildings:
        building.functional = False
    chosen = buildings[0]
    chosen.functional = True
    chosen.capacity = 100
    for visitor in visitors:
        slot = interior_slot(state, visitor, chosen)
        if slot is None:
            break
        visitor.summary.position = slot
        visitor.inside_building_id = chosen.id
    assert interior_slot(state, actor, chosen) is None
    assert chosen.occupancy < chosen.capacity
    for phase in range(3):
        state.simulation.tick = phase * 16
        result = routine_destination(state, actor)
        assert result is None or result[0].id != chosen.id
