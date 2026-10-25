import pytest
from conftest import command, commit_preview, create_city, preview

from app import contracts as c
from app.infrastructure.gemini import context_for
from app.simulation.agents import connect, perception, remember, social_delta
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.navigation import cell_at, distance, pathfind, simple_polygon
from app.simulation.scenarios import compile_preview, rectangle


def world(client):
    sid = create_city(client)["id"]
    return client.app.state.service.owned("demo_owner", sid).model_copy(deep=True)


def nearby_pair(state):
    a, b = list(state.citizens.values())[:2]
    a.summary.position = c.Vec2(x=33, y=33)
    b.summary.position = c.Vec2(x=34, y=33)
    for citizen in (a, b):
        citizen.summary.path = []
        citizen.inside_building_id = citizen.entering_building_id = None
    return a, b


def totals(state):
    return {
        kind: sum(getattr(citizen.inventory, kind) for citizen in state.citizens.values())
        + sum(r.available_units for r in state.map.resources if r.kind == kind)
        for kind in ("food", "water", "supplies")
    }


def test_path_obstacles_and_speed_bound(client):
    state = world(client)
    citizen = next(iter(state.citizens.values()))
    origin = citizen.summary.position.model_copy()
    destination = c.Vec2(x=1, y=1)
    path = pathfind(state.map, origin, destination)
    assert path
    citizen.summary.path = path
    advance_movement(state, citizen)
    assert distance(origin, citizen.summary.position) <= citizen.summary.movement_speed_mps * 10 + 1e-8
    for point in citizen.summary.path:
        cell = state.map.cells[int(point.y // 2) * 64 + int(point.x // 2)]
        assert cell.walkable
    water = next(cell for cell in state.map.cells if cell.terrain == "water")
    assert pathfind(state.map, origin, c.Vec2(x=water.col * 2 + 1, y=water.row * 2 + 1)) is None
    assert pathfind(state.map, origin, c.Vec2(x=999, y=1)) is None
    # A fractional destination within the same cell does not move via a cell centre.
    citizen.summary.position = c.Vec2(x=1.2, y=1.3)
    assert pathfind(state.map, citizen.summary.position, c.Vec2(x=1.4, y=1.5))


def test_routes_prefer_public_roads_over_shorter_lawn_cut_through(client):
    state = world(client)
    origin, destination = c.Vec2(x=1, y=7), c.Vec2(x=17, y=7)
    route = pathfind(state.map, origin, destination)
    assert route and route[-1] == destination
    # The direct eight-cell route crosses grass. Citizens take the longer paved
    # route via the intersection instead of being drawn walking over the lawn.
    assert len(route) > 8
    assert all(cell_at(state.map, point).terrain == "road" for point in route)
    # Walkable land is still reachable for a destination away from the streets.
    lawn_destination = c.Vec2(x=5, y=9)
    approach = pathfind(state.map, origin, lawn_destination)
    assert approach and approach[-1] == lawn_destination
    assert all(cell_at(state.map, point).walkable for point in approach)


def test_invalid_help_has_no_side_effects(client):
    state = world(client)
    a, b = list(state.citizens.values())[:2]
    a.summary.position = c.Vec2(x=1, y=1)
    b.summary.position = c.Vec2(x=100, y=1)
    inventory = a.inventory.model_dump()
    health = b.needs.health
    result = apply_intent(state, a, make_intent("help", target=b.summary.id))
    assert result.outcome == "rejected"
    assert result.rejection_code in {"UNOBSERVED_TARGET", "OUT_OF_RANGE"}
    assert result.effects == []
    assert a.inventory.model_dump() == inventory
    assert b.needs.health == health


def test_competing_resource_claims_conserve_stock(client):
    state = world(client)
    a, b = nearby_pair(state)
    source = state.map.resources[0]
    a.summary.position = source.position.model_copy()
    b.summary.position = source.position.model_copy()
    source.available_units = 1
    before = totals(state)
    intent = make_intent("gather", target=source.id, kind=source.kind, amount=1)
    first = apply_intent(state, a, intent)
    second = apply_intent(state, b, intent)
    assert first.outcome == "accepted"
    assert second.rejection_code == "RESOURCE_CONTESTED"
    assert source.available_units == 0
    assert totals(state) == pytest.approx(before)
    assert state.counters["conflict_count"] == 1


def test_trade_needs_explicit_acceptance_and_is_conserved(client):
    state = world(client)
    a, b = nearby_pair(state)
    before = totals(state)
    ia, ib = a.inventory.model_dump(), b.inventory.model_dump()
    offered = apply_intent(state, a, make_intent("trade", target=b.summary.id, kind="food", amount=1))
    assert offered.outcome == "accepted"
    assert a.inventory.model_dump() == ia and b.inventory.model_dump() == ib
    accepted = apply_intent(state, b, make_intent("trade", target=a.summary.id, kind="water", amount=1))
    assert accepted.outcome == "accepted"
    assert a.inventory.food == ia["food"] - 1
    assert a.inventory.water == ia["water"] + 1
    assert totals(state) == pytest.approx(before)
    assert state.counters["cooperation_count"] == 1


def test_trade_failure_cannot_partly_accept_or_transfer(client):
    state = world(client)
    a, b = nearby_pair(state)
    apply_intent(state, a, make_intent("trade", target=b.summary.id, kind="food", amount=1))
    a.inventory.food = 0
    before = totals(state)
    interaction = next(iter(state.interactions.values()))
    result = apply_intent(state, b, make_intent("trade", target=a.summary.id, kind="water", amount=1))
    assert result.outcome == "rejected"
    assert interaction.status == "invited" and interaction.accepted_ids == [a.summary.id]
    assert totals(state) == pytest.approx(before)


def test_directed_relationships_apply_evidence_once(client):
    state = world(client)
    a, b = nearby_pair(state)
    connect(state, a, b)
    connect(state, b, a)
    reverse = b.relationships[a.summary.id].model_dump()
    before = a.relationships[b.summary.id].trust
    social_delta(state, a, b, "decision_evidence", 3)
    assert a.relationships[b.summary.id].trust == min(100, before + 3)
    after = a.relationships[b.summary.id].model_dump()
    social_delta(state, a, b, "decision_evidence", 3)
    assert a.relationships[b.summary.id].model_dump() == after
    assert b.relationships[a.summary.id].model_dump() == reverse


def test_perception_hides_private_and_remote_information(client):
    state = world(client)
    a, b = nearby_pair(state)
    remember(state, b, "SECRET PRIVATE MEMORY", importance=100)
    b.goals = ["SECRET PRIVATE GOAL"]
    context = context_for(state, a)
    assert "SECRET PRIVATE" not in str(context)
    b.summary.position = c.Vec2(x=110, y=110)
    assert b.summary.id not in perception(state, a)["nearby_ids"]
    assert "110" not in str(context_for(state, a)["observed_facts"])
    # Opaque building footprint blocks sight even inside the 20m sight range.
    building = state.map.buildings[0]
    x, y = building.footprint[0].x, building.footprint[0].y
    a.summary.position = c.Vec2(x=x - 1, y=y + 1)
    b.summary.position = c.Vec2(x=x + 5, y=y + 1)
    assert distance(a.summary.position, b.summary.position) < 20
    assert b.summary.id not in perception(state, a)["nearby_ids"]


def test_hearing_scope_and_sender_provenance(client):
    state = world(client)
    a, b = nearby_pair(state)
    connect(state, b, a)
    b.relationships[a.summary.id].trust = 21
    a.profile.traits.trust = 99
    remote = list(state.citizens.values())[2]
    remote.summary.position = c.Vec2(x=100, y=100)
    before = len(remote.memories)
    result = apply_intent(state, a, make_intent("warn", target=b.summary.id, message="A local warning"))
    assert result.outcome == "accepted"
    assert b.memories[-1].source == "heard"
    assert a.summary.id in b.memories[-1].subject_ids
    assert remote.summary.id not in state.dialogue[-1].audible_to_ids
    assert len(remote.memories) == before
    assert b.beliefs[-1].confidence == 21


def test_information_effect_does_not_reveal_omniscient_event_label(client):
    from app.simulation.scenarios import queue_event

    state = world(client)
    preview = compile_preview(state, "custom", "A rumor in the whole city for 2 ticks")
    event = queue_event(state, preview, state.snapshots[0].id, False)
    tick(state)
    citizen = next(iter(state.citizens.values()))
    context = context_for(state, citizen)
    assert not any("misinformation" in fact for fact in context["observed_facts"])
    assert not any(
        memory.source == "observed" and event.id in memory.evidence.event_ids for memory in citizen.memories
    )
    assert any(
        memory.source == "heard" and event.id in memory.evidence.event_ids for memory in citizen.memories
    )


@pytest.mark.parametrize(
    "kind", ["flood", "fire", "storm", "shortage", "outage", "misinformation", "festival", "policy"]
)
def test_all_scenario_families_complete(client, kind):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid, f"A {kind} for 1 tick")
    assert p["can_commit"]
    committed = commit_preview(client, sid, hold, p)
    assert committed.status_code == 201, committed.text
    event = committed.json()["data"]["event"]
    response = command(client, sid, "step", count=3)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["simulation"]["pause_reason"] == "outcome"
    report = client.get(f"/api/v1/simulations/{sid}/events/{event['id']}").json()["data"]
    assert report["spec"]["kind"] == kind
    assert report["event"]["status"] == "resolved"


def test_seeded_ticks_and_checkpoint_roundtrip(client):
    state = world(client)
    copy = state.model_copy(deep=True)
    for _ in range(4):
        tick(state)
        tick(copy)
    assert state.model_dump() == copy.model_dump()
    from app.simulation.state import State

    assert State.model_validate_json(state.model_dump_json()).model_dump() == state.model_dump()


def test_metric_formulas_and_polygon_validation(client):
    state = world(client)
    from app.simulation.agents import update_metrics

    a, b = nearby_pair(state)
    a.inventory = c.Inventory(food=1, water=2, supplies=3)
    a.target_inventory_units = 12
    a.needs.health = 70
    update_metrics(state)
    assert a.summary.metrics.resources == 50
    assert a.summary.metrics.safety == 70
    assert state.metric_points[-1].values.happiness == pytest.approx(
        sum(c.summary.metrics.happiness for c in state.citizens.values()) / 10
    )
    assert simple_polygon(rectangle(0, 0, 10, 10))
    assert not simple_polygon([c.Vec2(x=0, y=0), c.Vec2(x=10, y=10), c.Vec2(x=0, y=10), c.Vec2(x=10, y=0)])


def test_temporary_policy_and_outage_restore_baselines(client):
    state = world(client)
    from app.simulation.scenarios import queue_event

    p = compile_preview(state, "custom", "An outage and policy for 1 tick")
    before = [b.model_dump() for b in state.map.buildings]
    queue_event(state, p, state.snapshots[0].id, False)
    tick(state)
    assert any(not b.functional for b in state.map.buildings)
    assert state.policies.evacuation_order
    tick(state)
    assert [b.functional for b in state.map.buildings] == [b["functional"] for b in before]
    assert [b.capacity for b in state.map.buildings] == [b["capacity"] for b in before]
    assert not state.policies.evacuation_order


def test_coordinated_aid_records_explicit_acceptances(client):
    state = world(client)
    a, b = nearby_pair(state)
    helper = list(state.citizens.values())[2]
    helper.summary.position = c.Vec2(x=33, y=34)
    b.needs.health = 70
    first = apply_intent(state, a, make_intent("help", target=b.summary.id))
    assert first.outcome == "accepted"
    group = next(group for group in state.interactions.values() if group.kind == "aid_group")
    assert helper.summary.id in group.participant_ids
    assert group.accepted_ids == [a.summary.id]
    second = apply_intent(state, helper, make_intent("help", target=b.summary.id))
    assert second.outcome == "accepted"
    assert set(group.accepted_ids) == {a.summary.id, helper.summary.id}
    assert state.counters["cooperation_count"] == 2


def test_evacuations_reserve_finite_facility_capacity(client):
    state = world(client)
    a, b = nearby_pair(state)
    building = next(building for building in state.map.buildings if building.kind == "shelter")
    building.capacity = 1
    for other in state.citizens.values():
        other.summary.position = c.Vec2(x=1, y=1)
    intent = make_intent("evacuate", target=building.id, destination=building.entrance)
    first = apply_intent(state, a, intent)
    second = apply_intent(state, b, intent)
    assert first.outcome == "accepted"
    assert second.rejection_code == "CAPACITY"


def test_zone_border_counts_each_citizen_once(client):
    state = world(client)
    from app.simulation.agents import update_metrics

    next(iter(state.citizens.values())).summary.position = c.Vec2(x=64, y=64)
    update_metrics(state)
    assert sum(zone.population for zone in state.map.zones) == len(state.citizens)


def test_conversations_reuse_invitation_accept_and_end_with_bounded_turns(client):
    state = world(client)
    a, b = nearby_pair(state)
    for actor, target in [(a, b), (b, a), (a, b), (b, a)]:
        assert apply_intent(state, actor, make_intent("talk", target=target.summary.id)).outcome == "accepted"
    conversations = [i for i in state.interactions.values() if i.kind == "conversation"]
    assert len(conversations) == 1
    assert set(conversations[0].accepted_ids) == {a.summary.id, b.summary.id}
    assert conversations[0].turns == 4 and conversations[0].status == "ended"
    assert state.dialogue[-1].end_conversation


def test_leaving_rejects_unaccepted_invitation(client):
    from app.simulation.interactions import expire_interactions

    state = world(client)
    a, b = nearby_pair(state)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    b.summary.position = c.Vec2(x=100, y=100)
    expire_interactions(state)
    assert next(iter(state.interactions.values())).status == "rejected"


@pytest.mark.parametrize(
    "prompt",
    [
        "A local aid drive opens at the community center",
        "An unverified warning spreads through the city",
        "A tornado threatens the western streets",
    ],
)
def test_frontend_suggested_scenarios_have_real_supported_effects(client, prompt):
    state = world(client)
    result = compile_preview(state, "custom", prompt)
    assert result.can_commit and result.spec.effects
    if "aid" in prompt:
        assert any(effect.type == "community" and effect.activity == "aid" for effect in result.spec.effects)


@pytest.mark.parametrize(
    "prompt",
    [
        "Dinosaurs appear in the town square",
        "Two neighbors discover they are long-lost siblings",
        "A mysterious visitor arrives with a secret",
        "A flood and a dragon visit the whole city for 2 ticks",
    ],
)
def test_open_ended_events_reach_citizens_and_remain_repeatable(client, prompt):
    from app.simulation.scenarios import queue_event

    state = world(client)
    preview = compile_preview(state, "custom", prompt)
    assert preview.can_commit and preview.unsupported_requests == []
    assert preview.spec.description == prompt
    assert preview.spec.title == prompt[:80]
    preview.spec.duration_ticks = 1
    runtime = queue_event(state, preview, state.snapshots[0].id, False)
    tick(state)
    cohort = state.events[runtime.id].cohort
    assert cohort
    for aid in cohort:
        citizen = state.citizens[aid]
        assert any(prompt in memory.text for memory in citizen.memories)
        assert any(prompt in belief.text for belief in citizen.beliefs)
    while state.events[runtime.id].summary.status != "resolved":
        tick(state)
    repeated = compile_preview(state, "repeat", source_event_id=runtime.id)
    assert repeated.spec == preview.spec


def test_rules_reply_to_a_neighbor_and_use_observed_event_in_conversation(client):
    from app.simulation.game_master import rule_intent

    state = world(client)
    a, b = nearby_pair(state)
    remember(state, a, "World event: Dinosaurs appear in the town square")
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    assert "Dinosaurs" in state.dialogue[-1].text
    # Needs that require immediate care still have priority over conversation.
    b.needs.hunger = 0
    b.needs.fatigue = 0
    assert rule_intent(state, b, perception(state, b)).action == "idle"
    state.simulation.tick += 1  # A reply gets its own readable turn.
    reply = rule_intent(state, b, perception(state, b))
    assert reply.action == "talk" and reply.target_id == a.summary.id
    apply_intent(state, b, reply)
    assert state.dialogue[-1].speaker_id == b.summary.id
    assert state.dialogue[-1].interaction_id == state.dialogue[-2].interaction_id
    assert state.dialogue[-1].text != state.dialogue[-2].text


def test_full_length_custom_event_and_empty_event_validation(client):
    from app.infrastructure.errors import DomainError

    state = world(client)
    prompt = "A" * 2000
    result = compile_preview(state, "custom", prompt)
    assert result.can_commit and result.spec.description == prompt
    assert len(result.interpretation) <= 2000
    with pytest.raises(DomainError):
        compile_preview(state, "custom", "   ")


def resolve(state, prompt):
    from app.simulation.scenarios import event_report, queue_event

    preview = compile_preview(state, "custom", prompt)
    assert preview.can_commit
    runtime = queue_event(state, preview, state.snapshots[0].id, False)
    while state.events[runtime.id].summary.status != "resolved":
        tick(state)
    return event_report(state, state.events[runtime.id])


def test_hazard_lesson_tells_what_happened_and_what_was_learned(client):
    state = world(client)
    report = resolve(state, "A flood in the east for 3 ticks")
    safety = next(lesson for lesson in report.community_lessons if "reached safety" in lesson.text)
    assert "The community learned" in safety.text
    assert safety.evidence.event_ids == [report.event.id]
    decisions = {d.id: d for d in state.decisions}
    assert safety.evidence.decision_ids
    for did in safety.evidence.decision_ids:
        assert decisions[did].agent_id in report.affected_agent_ids


def test_outside_aid_lesson_does_not_credit_neighbors(client):
    report = resolve(world(client), "Robots deliver community aid citywide for 2 ticks")
    aid = next(lesson for lesson in report.community_lessons if "Community aid delivered" in lesson.text)
    assert "aid arriving at one shared point" in aid.text
    assert "neighbors can rely" not in aid.text


def test_help_between_neighbors_is_named_in_the_lesson(client):
    from app.simulation.game_master import apply_intent, make_intent
    from app.simulation.lessons import compose_lessons, gather_facts
    from app.simulation.scenarios import queue_event

    state = world(client)
    preview = compile_preview(state, "custom", "A festival citywide for 5 ticks")
    runtime = state.events[queue_event(state, preview, state.snapshots[0].id, False).id]
    tick(state)
    a, b = nearby_pair(state)
    runtime.cohort = list(dict.fromkeys([*runtime.cohort, a.summary.id, b.summary.id]))
    a.inventory.supplies = 2
    decision = apply_intent(state, a, make_intent("help", target=b.summary.id))
    assert decision.outcome == "accepted", decision.outcome_description
    facts = gather_facts(state, runtime)
    help_lesson = next(
        lesson
        for lesson in compose_lessons(runtime, facts)
        if decision.id in lesson["evidence"]["decision_ids"]
    )
    assert a.summary.name in help_lesson["text"] and b.summary.name in help_lesson["text"]
    assert "neighbors can rely on one another" in help_lesson["text"]


def test_conversation_lesson_quotes_recorded_dialogue(client):
    state = world(client)
    report = resolve(state, "A festival citywide for 3 ticks")
    lines = {line.text for line in state.dialogue}
    talk = [lesson for lesson in report.community_lessons if "conversation" in lesson.text]
    assert talk and any(f'"{line}"' in talk[0].text for line in lines)


def test_no_lessons_without_recorded_actions_or_measured_change(client):
    from app.simulation.lessons import compose_lessons, gather_facts
    from app.simulation.scenarios import queue_event

    state = world(client)
    preview = compile_preview(state, "custom", "A mysterious visitor arrives with a secret")
    runtime = state.events[queue_event(state, preview, state.snapshots[0].id, False).id]
    runtime.after = runtime.before.model_copy()
    assert compose_lessons(runtime, gather_facts(state, runtime)) == []


def test_model_lessons_must_cite_recorded_facts(client):
    from app.prompts.outputs import LessonDraft
    from app.simulation.lessons import adopt_drafts

    state = world(client)
    report = resolve(state, "A flood in the east for 3 ticks")
    runtime = state.events[report.event.id]
    adopted = adopt_drafts(
        runtime,
        [
            LessonDraft(text="  Grounded   retelling. The community learned.  ", fact_ids=[0, 0]),
            LessonDraft(text="Invented story.", fact_ids=[len(runtime.lesson_facts)]),
        ],
    )
    assert [lesson["text"] for lesson in adopted] == ["Grounded retelling. The community learned."]
    assert adopted[0]["evidence"]["decision_ids"] == runtime.lesson_facts[0]["decision_ids"]


def test_gemini_rewrite_replaces_template_lessons_after_resolution(client, monkeypatch):
    import dataclasses
    import time

    from conftest import commit_preview, preview

    from app.prompts.outputs import LessonDraft

    sid = create_city(client)["id"]
    service = client.app.state.service
    hold, p = preview(client, sid, "A flood in the east for 2 ticks")
    event = commit_preview(client, sid, hold, p).json()["data"]["event"]
    materials = []

    async def lessons(_, material):
        materials.append(material)
        return [LessonDraft(text="Model retelling. The community learned to move early.", fact_ids=[0])]

    monkeypatch.setattr(service.gateway, "lessons", lessons)
    monkeypatch.setattr(
        service,
        "config",
        dataclasses.replace(service.config, llm_mode="gemini", gemini_api_key="k", gemini_model="m"),
    )
    assert command(client, sid, "step", count=4).status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        report = client.get(f"/api/v1/simulations/{sid}/events/{event['id']}").json()["data"]
        if report["community_lessons"][0]["text"].startswith("Model retelling"):
            break
        time.sleep(0.02)
    assert [lesson["text"] for lesson in report["community_lessons"]] == [
        "Model retelling. The community learned to move early."
    ]
    assert len(materials) == 1 and materials[0]["facts"][0]["id"] == 0
    assert materials[0]["draft_lessons"]
