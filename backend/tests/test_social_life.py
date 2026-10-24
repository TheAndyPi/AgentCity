import math
from uuid import uuid4

from conftest import create_city

from app import contracts as c
from app.simulation.agents import perception
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent, rule_intent
from app.simulation.navigation import distance, pathfind


def city(client):
    sid = create_city(client, population=10)["id"]
    return client.app.state.service.heads[sid].model_copy(deep=True)


def test_small_cast_has_a_compact_walkable_neighborhood(client):
    state = city(client)
    assert len(state.citizens) == 10
    positions = [citizen.summary.position for citizen in state.citizens.values()]
    assert min(distance(a, b) for i, a in enumerate(positions) for b in positions[i + 1 :]) >= 1.05
    assert len(state.map.buildings) == 24
    assert sum(b.kind == "home" for b in state.map.buildings) >= 10
    assert max(b.height_m for b in state.map.buildings) <= 5.2
    for citizen in state.citizens.values():
        assert any(pathfind(state.map, citizen.home, r.position) is not None for r in state.map.resources)


def test_two_people_stop_face_each_other_and_take_one_turn_per_tick(client):
    state = city(client)
    a, b = list(state.citizens.values())[:2]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
        citizen.needs.hunger = citizen.needs.fatigue = citizen.needs.social = 0
    a.summary.position, b.summary.position = c.Vec2(x=33, y=33), c.Vec2(x=35, y=33)
    b.summary.path = [c.Vec2(x=45, y=33)]
    positions = a.summary.position.model_copy(), b.summary.position.model_copy()
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    assert rule_intent(state, b, perception(state, b)).action == "idle"
    for _ in range(3):
        before = len(state.dialogue)
        tick(state)
        assert len(state.dialogue) == before + 1
        assert (a.summary.position, b.summary.position) == positions
    assert state.dialogue[-1].end_conversation
    assert [d.speaker_id for d in state.dialogue] == [a.summary.id, b.summary.id, a.summary.id, b.summary.id]
    assert [d.tick for d in state.dialogue] == [0, 1, 2, 3]
    assert abs((b.summary.heading_rad - a.summary.heading_rad) % (2 * math.pi) - math.pi) < 0.001
    assert all(not c.summary.path for c in (a, b))


def test_owner_invitation_walks_to_a_person_without_teleporting_or_overlapping(client):
    state = city(client)
    service = client.app.state.service
    a = next(iter(state.citizens.values()))
    b = max(state.citizens.values(), key=lambda c: distance(a.summary.position, c.summary.position))
    origin = a.summary.position.model_copy()
    assert distance(origin, b.summary.position) > 3
    request = c.CommandRequest(
        request_id=str(uuid4()),
        expected_control_version=state.simulation.control_version,
        command=c.OverrideAgent(
            type="override_agent",
            agent_id=a.summary.id,
            metrics={},
            goal=None,
            memory_text=None,
            intent=make_intent("talk", target=b.summary.id),
        ),
    )
    staged = service.command("demo_owner", state.simulation.id, request).states[-1]
    a, b = staged.citizens[a.summary.id], staged.citizens[b.summary.id]
    assert a.summary.position == origin
    assert a.summary.path and a.plan["kind"] == "social_visit"
    for _ in range(100):
        if not a.summary.path:
            break
        before = a.summary.position.model_copy()
        advance_movement(staged, a)
        assert distance(before, a.summary.position) <= a.summary.movement_speed_mps * 10 + 1e-6
    assert not a.summary.path, (
        a.summary.position,
        a.summary.path,
        [(c.summary.id, c.summary.position) for c in staged.citizens.values()],
    )
    assert a.plan["kind"] == "social_visit"
    assert 2 <= distance(a.summary.position, b.summary.position) <= 3
    a.needs.hunger = a.needs.fatigue = 0
    intent = rule_intent(staged, a, perception(staged, a))
    assert intent.action == "talk" and intent.target_id == b.summary.id
    apply_intent(staged, a, intent)
    assert staged.dialogue[-1].recipient_ids == [b.summary.id]
    assert a.plan is None


def test_model_reply_cannot_collapse_a_conversation_into_one_tick(client):
    state = city(client)
    a, b = list(state.citizens.values())[:2]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
        citizen.needs.hunger = citizen.needs.fatigue = citizen.needs.social = 0
    a.summary.position, b.summary.position = c.Vec2(x=33, y=33), c.Vec2(x=35, y=33)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    tick(
        state,
        {
            a.summary.id: (make_intent("talk", target=b.summary.id),),
            b.summary.id: (make_intent("talk", target=a.summary.id),),
        },
    )
    assert len(state.dialogue) == 2
    assert state.dialogue[-1].speaker_id == b.summary.id
