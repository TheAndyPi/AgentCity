"""Provider proposals must remain useful without outliving their information."""

import asyncio
import time

import pytest
from conftest import create_city

from app import contracts as c
from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway, context_for, relevance
from app.service import ProviderResult
from app.simulation.agents import remember
from app.simulation.engine import tick
from app.simulation.game_master import make_intent
from app.simulation.scenarios import compile_preview, queue_event


def world(client):
    sid = create_city(client)["id"]
    return client.app.state.service, client.app.state.service.heads[sid].model_copy(deep=True)


@pytest.mark.parametrize("changed", ["health", "memory", "belief", "relationship", "observation", "goal"])
def test_relevance_changes_with_citizen_knowledge_and_condition(client, changed):
    _, state = world(client)
    actor, neighbor = list(state.citizens.values())[:2]
    actor.summary.position = c.Vec2(x=33, y=33)
    neighbor.summary.position = c.Vec2(x=35, y=33)
    before = relevance(state, actor)
    if changed == "health":
        actor.needs.health -= 5
    elif changed == "memory":
        remember(state, actor, "My neighbor warned me about a changed situation")
    elif changed == "belief":
        actor.beliefs.append(
            c.Belief(
                text="The bridge may be unsafe",
                confidence=60,
                evidence=actor.relationships[neighbor.summary.id].evidence,
            )
        )
    elif changed == "relationship":
        actor.relationships[neighbor.summary.id].trust -= 5
    elif changed == "observation":
        neighbor.summary.position = c.Vec2(x=37, y=33)
    else:
        actor.goals[0] = "Find medical assistance"
    assert relevance(state, actor) != before


def test_relevance_tolerates_clock_and_small_noncritical_need_decay(client):
    _, state = world(client)
    actor = next(iter(state.citizens.values()))
    actor.needs.hunger, actor.needs.fatigue, actor.needs.social = 21, 21, 21
    before = relevance(state, actor)
    state.simulation.tick += 8
    actor.needs.hunger += 0.6
    actor.needs.fatigue += 0.4
    actor.needs.social += 0.2
    assert relevance(state, actor) == before
    actor.needs.hunger = 46
    assert relevance(state, actor) != before


def test_context_prioritizes_nearby_facilities_without_revealing_remote_status(client):
    _, state = world(client)
    actor = next(iter(state.citizens.values()))
    far = state.map.buildings[0]
    nearest = state.map.buildings[-1]
    actor.summary.position = nearest.entrance.model_copy()
    actor.needs.health = 100
    actor.needs.hunger = actor.needs.fatigue = 0
    before = context_for(state, actor)
    assert nearest.id in {building["id"] for building in before["known_facilities"]}
    assert len(before["known_facilities"]) <= 12
    # Public location knowledge does not reveal a remote facility's live state.
    far.entrance = c.Vec2(x=127, y=127)
    actor.known_locations[far.id] = far.entrance.model_copy()
    actor.summary.position = c.Vec2(x=1, y=1)
    far.functional = False
    context = context_for(state, actor)
    for building in context["known_facilities"]:
        if building["id"] == far.id:
            assert building.get("functional") is None


def test_deliberation_context_is_an_immutable_snapshot(client):
    _, state = world(client)
    actor = next(iter(state.citizens.values()))
    context = context_for(state, actor)
    original = list(context["goals"])
    actor.goals.append("A new obligation")
    assert context["goals"] == original


def result_for(state, actor, *, lifetime=2):
    return ProviderResult(
        relevance(state, actor), state.simulation.tick, make_intent("idle"), time.monotonic() + lifetime
    )


@pytest.mark.parametrize("speed", [0.25, 1, 10])
def test_unchanged_context_can_survive_more_than_four_ticks_but_not_wall_expiry(client, speed):
    service, state = world(client)
    actor = next(iter(state.citizens.values()))
    state.simulation.speed_multiplier = speed
    service.provider_results[(state.simulation.id, actor.summary.id)] = result_for(state, actor)
    state.simulation.tick += 20
    proposals = service.take_proposals(state)
    assert proposals.get(actor.summary.id)[0].action == "idle"
    assert state.provider_references[-1]["accepted_tick"] == state.simulation.tick
    service.provider_results[(state.simulation.id, actor.summary.id)] = result_for(state, actor, lifetime=-1)
    assert service.take_proposals(state) == {}


def test_proposal_is_revalidated_after_another_actor_changes_its_knowledge(client, monkeypatch):
    from app.simulation import engine

    service, state = world(client)
    first, second = list(state.citizens.values())[:2]
    for actor in state.citizens.values():
        actor.summary.active = actor in (first, second)
    service.provider_results[(state.simulation.id, second.summary.id)] = result_for(state, second)
    proposals = service.take_proposals(state)
    monkeypatch.setattr("random.Random.shuffle", lambda self, ordering: ordering.sort())
    monkeypatch.setattr(engine, "rule_intent", lambda *args: make_intent("idle"))
    apply = engine.apply_intent

    def acted(state, actor, intent, source, context):
        if actor is first:
            remember(state, second, "My neighbor has shared a new warning")
        return apply(state, actor, intent, source, context)

    monkeypatch.setattr(engine, "apply_intent", acted)
    tick(state, proposals)
    assert [d.source for d in state.decisions] == ["rules", "rules"]
    assert service.gateway.diagnostics["discarded"] == 1
    assert state.provider_references == []


def test_new_event_activation_invalidates_a_selected_proposal(client):
    service, state = world(client)
    actor = next(iter(state.citizens.values()))
    preview = compile_preview(state, "custom", "A flood across the whole city for 2 ticks")
    queue_event(state, preview, state.snapshots[0].id, False)
    service.provider_results[(state.simulation.id, actor.summary.id)] = result_for(state, actor)
    proposals = service.take_proposals(state)
    assert actor.summary.id in proposals
    tick(state, proposals)
    assert all(d.source == "rules" for d in state.decisions)
    assert service.gateway.diagnostics["discarded"] == 1
    assert state.provider_references == []


def test_unchanged_proposal_still_uses_game_master_legality_checks(client):
    service, state = world(client)
    actor = next(iter(state.citizens.values()))
    for other in state.citizens.values():
        other.summary.active = other is actor
    result = result_for(state, actor)
    from dataclasses import replace

    # Syntactically valid, physically impossible: validation must still reject it.
    result = replace(result, intent=make_intent("help", target="missing_person"))
    service.provider_results[(state.simulation.id, actor.summary.id)] = result
    tick(state, service.take_proposals(state))
    decision = next(d for d in state.decisions if d.agent_id == actor.summary.id)
    assert decision.source == "gemini"
    assert decision.outcome == "rejected"
    assert decision.rejection_code == "UNKNOWN_TARGET"


def test_deliberation_completion_keeps_context_tick_and_has_a_delivery_deadline(client, monkeypatch):
    service, state = world(client)
    actor = next(iter(state.citizens.values()))
    state.simulation.speed_multiplier = 10
    service.heads[state.simulation.id] = state

    async def decide(sid, context):
        await asyncio.sleep(0)
        return make_intent("idle")

    monkeypatch.setattr(service.gateway, "decide", decide)
    client.portal.call(
        service.deliberate,
        (state.simulation.id, actor.summary.id),
        relevance(state, actor),
        state.simulation.tick,
        context_for(state, actor),
    )
    result = service.provider_results[(state.simulation.id, actor.summary.id)]
    assert result.context_tick == state.simulation.tick
    assert 1 < result.expires_at - time.monotonic() <= 2


def test_decision_has_an_overall_wall_deadline_including_a_blocked_provider():
    import httpx

    async def run():
        usage = []

        async def record(sid, counts):
            usage.append(counts)

        async def handler(request):
            await asyncio.sleep(10)
            raise AssertionError("The decision deadline must interrupt this provider")

        gateway = Gateway(
            AppConfig(llm_mode="gemini", gemini_api_key="test", gemini_model="test", llm_timeout=0.01),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            async with asyncio.timeout(1):
                assert await gateway.decide("test_city", {"profile": {"name": "Test citizen"}}) is None
            assert gateway.reserved == 0
            assert gateway.diagnostics["fallbacks"] == 1
        finally:
            await gateway.close()
        assert len(usage) == 1 and usage[0]["failed_calls"] == 1

    asyncio.run(run())


def test_context_never_supplies_hidden_overhearer_ids(client):
    _, state = world(client)
    actor = next(iter(state.citizens.values()))
    state.dialogue.append(
        c.Dialogue(
            id="dialogue_test",
            interaction_id="interaction_test",
            tick=0,
            speaker_id=actor.summary.id,
            recipient_ids=[],
            audible_to_ids=[actor.summary.id, "hidden_listener"],
            text="A public greeting",
            intent="talk",
            emotion="calm",
            end_conversation=False,
        )
    )
    assert "hidden_listener" not in str(context_for(state, actor))


@pytest.mark.parametrize("waiting_on", ["provider", "usage"])
def test_deadline_keeps_usage_durable_without_waiting_for_its_writer(waiting_on):
    import httpx

    async def run():
        recording, release, recorded = asyncio.Event(), asyncio.Event(), []

        async def record(sid, counts):
            recording.set()
            await release.wait()
            recorded.append(counts)

        async def handler(request):
            if waiting_on == "provider":
                await asyncio.sleep(10)
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": make_intent("idle").model_dump_json()}]}}],
                    "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10},
                },
            )

        gateway = Gateway(
            AppConfig(llm_mode="gemini", gemini_api_key="test", gemini_model="test", llm_timeout=0.01),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        task = asyncio.create_task(gateway.decide("test_city", {"profile": {"name": "Test citizen"}}))
        try:
            async with asyncio.timeout(1):
                await recording.wait()
                assert await asyncio.shield(task) is None
            assert gateway.reserved == 0
            assert recorded == []
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await gateway.close()
        assert len(recorded) == 1
        if waiting_on == "usage":
            assert recorded[0]["input_tokens"] == 20
            assert recorded[0]["output_tokens"] == 10
        else:
            assert recorded[0]["failed_calls"] == 1

    asyncio.run(run())
