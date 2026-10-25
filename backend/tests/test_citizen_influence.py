from uuid import uuid4

import pytest
from conftest import command, create_city

from app import contracts as c
from app.simulation.agents import perception
from app.simulation.game_master import advance_movement, apply_intent, make_intent, rule_intent
from app.simulation.navigation import distance


def override(service, state, actor, intent):
    request = c.CommandRequest(
        request_id=str(uuid4()),
        expected_control_version=state.simulation.control_version,
        command=c.OverrideAgent(
            type="override_agent",
            agent_id=actor.summary.id,
            metrics={},
            goal=None,
            memory_text=None,
            intent=intent,
        ),
    )
    return service.command("demo_owner", state.simulation.id, request).states[-1]


@pytest.mark.parametrize(
    "preset,values",
    [
        ("lovers", ("romantic", 95, 80, 0, 60)),
        ("friends", ("friend", 75, 75, 5, 50)),
        ("rivals", ("rival", 15, 20, 75, 30)),
        ("acquaintances", ("acquaintance", 35, 50, 10, 30)),
    ],
)
def test_presets_are_mutual_durable_and_preserve_tasks_and_history(client, preset, values):
    sid = create_city(client)["id"]
    service = client.app.state.service
    state = service.heads[sid]
    a, b = list(state.citizens.values())[:2]
    # One direction exists; the other must be created.
    tie = a.relationships[b.summary.id]
    tie.respect, tie.familiarity = 83, 90
    tie.shared_history = ["remembered-event"]
    b.relationships.pop(a.summary.id, None)
    a.plan = {"kind": "social_visit", "target_id": b.summary.id, "expires_tick": 100}
    plan, generation, tick = a.plan.copy(), a.task_generation, state.simulation.tick
    response = command(
        client, sid, "set_relationship", agent_id=a.summary.id, target_id=b.summary.id, preset=preset
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["affected_agent_ids"] == [a.summary.id, b.summary.id]
    restored = service.repo.read(sid)
    a, b = restored.citizens[a.summary.id], restored.citizens[b.summary.id]
    assert restored.simulation.tick == tick
    assert restored.simulation.status == "paused"
    assert a.plan == plan and a.task_generation == generation
    for actor, other in ((a, b), (b, a)):
        tie = actor.relationships[other.summary.id]
        assert (tie.kind, tie.affection, tie.trust, tie.conflict) == values[:4]
        assert tie.familiarity >= values[4]
        assert "owner" in tie.evidence.description
        assert actor.memories[-1].source == "injected"
        assert other.summary.id in actor.memories[-1].subject_ids
    assert a.relationships[b.summary.id].respect == 83
    assert a.relationships[b.summary.id].shared_history == ["remembered-event"]
    assert a.relationships[b.summary.id].familiarity == 90


def test_invalid_relationship_pairs_are_atomic(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    a, b = list(service.heads[sid].citizens.values())[:2]
    before = service.heads[sid].simulation.revision
    for target, expected in ((a.summary.id, 400), ("missing-citizen", 404)):
        response = command(
            client, sid, "set_relationship", agent_id=a.summary.id, target_id=target, preset="lovers"
        )
        assert response.status_code == expected, response.text
    b.summary.active = False
    response = command(
        client, sid, "set_relationship", agent_id=a.summary.id, target_id=b.summary.id, preset="friends"
    )
    assert response.status_code == 409
    assert service.heads[sid].simulation.revision == before


def test_typed_line_survives_walking_and_is_spoken_once(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    state = service.heads[sid]
    a = next(iter(state.citizens.values()))
    b = max(state.citizens.values(), key=lambda other: distance(a.summary.position, other.summary.position))
    text = "  Meet me under the neon lights.\nI have something to tell you!  "
    staged = override(service, state, a, make_intent("talk", target=b.summary.id, message=text))
    a, b = staged.citizens[a.summary.id], staged.citizens[b.summary.id]
    assert a.plan["message"] == text
    assert not staged.dialogue
    for _ in range(100):
        if not a.summary.path:
            break
        advance_movement(staged, a)
    a.needs.hunger = a.needs.fatigue = 0
    intent = rule_intent(staged, a, perception(staged, a))
    assert intent.action == "talk" and intent.parameters.message == text
    assert apply_intent(staged, a, intent).outcome == "accepted"
    assert staged.dialogue[-1].text == text
    assert a.plan is None
    staged.simulation.tick += 1
    apply_intent(staged, b, make_intent("talk", target=a.summary.id))
    staged.simulation.tick += 1
    intent = rule_intent(staged, a, perception(staged, a))
    assert intent.parameters.message is None
    apply_intent(staged, a, intent)
    assert sum(line.text == text for line in staged.dialogue) == 1
    assert any(text in memory.text for memory in b.memories)


@pytest.mark.parametrize("replacement", ["cancel", "expire", "replace"])
def test_pending_line_cannot_leak_after_cancellation_or_replacement(client, replacement):
    sid = create_city(client)["id"]
    service = client.app.state.service
    state = service.heads[sid]
    a = next(iter(state.citizens.values()))
    b = max(state.citizens.values(), key=lambda other: distance(a.summary.position, other.summary.position))
    # Stage against the real owner command handler without publishing.
    staged = override(service, state, a, make_intent("talk", target=b.summary.id, message="Old line"))
    if replacement == "expire":
        actor = staged.citizens[a.summary.id]
        staged.simulation.tick = actor.plan["expires_tick"] + 1
        actor.needs.hunger = actor.needs.fatigue = 0
        intent = rule_intent(staged, actor, perception(staged, actor))
        assert actor.plan is None
        assert intent is None or intent.parameters.message is None
    else:
        # Publish staged state as the head so a subsequent command replaces it.
        service.heads[sid] = staged
        intent = (
            make_intent("rest")
            if replacement == "cancel"
            else make_intent(
                "talk",
                target=b.summary.id,
                message="New line",
            )
        )
        updated = override(service, staged, staged.citizens[a.summary.id], intent)
        plan = updated.citizens[a.summary.id].plan
        assert plan is None if replacement == "cancel" else plan["message"] == "New line"
    assert not staged.dialogue


def test_nearby_exact_line_and_invalid_text(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    a, b = list(service.heads[sid].citizens.values())[:2]
    a.summary.position, b.summary.position = c.Vec2(x=33, y=33), c.Vec2(x=35, y=33)
    for text, expected in ((" \n ", 400), ("x" * 2001, 422), ("I choose these exact words!", 200)):
        response = command(
            client,
            sid,
            "override_agent",
            agent_id=a.summary.id,
            metrics={},
            goal=None,
            memory_text=None,
            intent=dict(
                action="talk",
                target_id=b.summary.id,
                destination=None,
                parameters=dict(message=text, resource_kind=None, amount=None),
                motivation="Owner supplied speech",
                emotion="calm",
            ),
        )
        assert response.status_code == expected, response.text
    assert service.heads[sid].dialogue[-1].text == "I choose these exact words!"
