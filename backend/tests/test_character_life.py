"""Distinct casts, contextual speech, and safe upgrades of saved placeholders."""

import random

from conftest import create_city

from app import contracts as c
from app.simulation.agents import generated_profile, remember
from app.simulation.characters import LEGACY_NAMES, upgrade_placeholder_citizens
from app.simulation.game_master import apply_intent, make_intent
from app.simulation.state import State


def cast(seed):
    config = c.ConfigRequest(name="Cast", seed=seed, population=100).normalized()
    rng = random.Random(seed)
    return [generated_profile(i, config, rng) for i in range(config.population)]


def world(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    a, b = list(state.citizens.values())[:2]
    a.summary.position = c.Vec2(x=33, y=33)
    b.summary.position = c.Vec2(x=34, y=33)
    a.summary.path = b.summary.path = []
    return state, a, b


def talk(state, a, b, message=None):
    intent = make_intent("talk", target=b.summary.id)
    intent.parameters.message = message
    decision = apply_intent(state, a, intent)
    assert decision.outcome == "accepted"
    return state.dialogue[-1]


def legacy(citizen, index):
    """Exact original generated text, retaining the person's physical state."""
    profile = citizen.profile
    profile.name = f"{LEGACY_NAMES[index % 10]} {index + 1}"
    profile.role = "teacher"
    profile.background = "A resident with local work and family responsibilities."
    profile.personality = (
        "Community-minded" if profile.traits.cooperation >= 50 else "Independent and cautious"
    )
    profile.values = ["security", "community" if profile.traits.empathy >= 50 else "independence"]
    profile.primary_goal = "Keep my household safe and supplied"
    profile.secondary_goals = ["Maintain friendships", "Finish my work"]
    profile.desires = ["A stable home"]
    profile.fears = ["Losing essential supplies"]
    profile.personal_history = "Has lived in this settlement and knows its public facilities."
    profile.skills = [profile.role]
    citizen.summary.name = profile.name
    citizen.goals = [profile.primary_goal, *profile.secondary_goals]


def test_cast_is_distinct_seeded_and_respects_population_traits():
    people = cast(42)
    assert people == cast(42)
    assert {p.name for p in people} != {p.name for p in cast(43)}
    assert len({p.name for p in people}) == 100
    assert all(not any(char.isdigit() for char in p.name) for p in people)
    assert len({p.background for p in people}) > 50
    assert len({p.personal_history for p in people}) > 30
    assert len({p.primary_goal for p in people}) >= 10
    config = c.ConfigRequest(name="Uniform", seed=1, personality_diversity=0).normalized()
    profile = generated_profile(0, config, random.Random(1))
    assert profile.traits == config.population_traits


def test_rule_conversation_tracks_disclosure_and_does_not_read_listener_profile(client):
    state, a, b = world(client)
    a.profile.primary_goal = "restore the old clock tower"
    a.profile.secondary_goals = []
    a.profile.personal_history = "I arrived here to restore the old clock tower"
    a.profile.skills = ["clock repair", "restoring the old clock tower"]
    # Ensure whichever nonurgent topic is chosen contains the speaker's project.
    b.profile.primary_goal = "SECRET PRIVATE GOAL"
    b.profile.personal_history = "SECRET PRIVATE HISTORY"
    first = talk(state, a, b)
    assert "clock tower" in first.text
    assert "SECRET" not in first.text
    reply = talk(state, b, a)
    assert reply.text != first.text
    assert reply.interaction_id == first.interaction_id
    third = talk(state, a, b)
    last = talk(state, b, a)
    assert "clock tower" in third.text or "clock tower" in last.text
    assert last.end_conversation
    assert state.interactions[first.interaction_id].status == "ended"
    assert len({line.text for line in state.dialogue}) == 4


def test_same_pair_changes_subject_on_later_meetings(client):
    state, a, b = world(client)
    openings, topics = [], []
    for _ in range(5):
        first = talk(state, a, b)
        openings.append(first.text)
        topics.append(state.interactions[first.interaction_id].proposal["dialogue_topic"]["detail"])
        talk(state, b, a)
        talk(state, a, b)
        talk(state, b, a)
    assert len(set(topics)) >= 3
    assert len(set(openings)) >= 4


def test_speech_uses_observed_events_needs_and_preserves_provider_words(client):
    state, a, b = world(client)
    remember(state, a, "World event: A mysterious violinist visits the square")
    first = talk(state, a, b)
    assert "mysterious violinist" in first.text
    assert "mysterious violinist" in talk(state, b, a).text
    message = "I think we should ask the violinist about the missing music."
    assert talk(state, a, b, message).text == message
    assert "missing music" in talk(state, b, a).text
    a.inventory.food = 0
    first = talk(state, a, b)
    assert "food" in first.text
    assert "food" in talk(state, b, a).text.lower()


def test_dialogue_continuation_is_identical_after_checkpoint(client):
    state, a, b = world(client)
    talk(state, a, b)
    restored = State.model_validate_json(state.model_dump_json())
    expected = talk(state, b, a)
    actual = talk(restored, restored.citizens[b.summary.id], restored.citizens[a.summary.id])
    assert actual == expected


def test_upgrade_is_idempotent_preserves_custom_profiles_and_physical_state(client):
    state, a, b = world(client)
    legacy(a, 0)
    legacy(b, 1)
    b.profile_template_id = "custom-template"
    before_custom = b.model_dump()
    before = a.model_dump()
    historical = state.model_copy(deep=True)
    assert upgrade_placeholder_citizens(state)
    assert a.summary.name != "Alex 1"
    assert a.summary.name == a.profile.name
    assert a.profile.primary_goal != "Keep my household safe and supplied"
    assert a.goals == [a.profile.primary_goal, *a.profile.secondary_goals]
    assert a.profile.traits.model_dump() == before["profile"]["traits"]
    assert a.inventory.model_dump() == before["inventory"]
    assert a.summary.position.model_dump() == before["summary"]["position"]
    assert b.model_dump() == before_custom
    assert historical.citizens[a.summary.id].profile.name == "Alex 1"
    assert not upgrade_placeholder_citizens(state)


def test_saved_placeholder_upgrade_is_durable_and_keeps_historical_revision(tmp_path):
    from fastapi.testclient import TestClient

    from app.infrastructure.config import AppConfig
    from app.main import create_app

    config = AppConfig(data_dir=tmp_path / "saved-city")
    options = dict(base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    with TestClient(create_app(config), **options) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        sid = create_city(client)["id"]
        service = client.app.state.service

        async def save_original_cast():
            async with service.writer:
                state = service.heads[sid].model_copy(deep=True)
                for i, citizen in enumerate(state.citizens.values()):
                    legacy(citizen, i)
                service.bump(state)
                await service.persist([state])
                return state.simulation.revision

        original_revision = client.portal.call(save_original_cast)
    with TestClient(create_app(config), **options) as client:
        service = client.app.state.service
        state = service.heads[sid]
        assert state.simulation.revision == original_revision + 1
        assert state.simulation.status == "paused"
        assert next(iter(state.citizens.values())).summary.name != "Alex 1"
        old = service.repo.read(sid, original_revision)
        assert next(iter(old.citizens.values())).summary.name == "Alex 1"
        upgraded = state.model_dump()
    with TestClient(create_app(config), **options) as client:
        assert client.app.state.service.heads[sid].model_dump() == upgraded


def test_rule_reply_answers_provider_resource_question_without_changing_subject(client):
    state, a, b = world(client)
    b.inventory.water = 2
    first = talk(state, a, b, "How much water do you have left?")
    reply = talk(state, b, a)
    assert "2 units of water" in reply.text
    assert reply.interaction_id == first.interaction_id
    talk(state, a, b)
    assert talk(state, b, a).end_conversation
