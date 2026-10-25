import copy

import pytest
from conftest import commit_preview, create_city, preview

from app import contracts as c
from app.api.views import frame
from app.simulation.engine import tick
from app.simulation.navigation import cell_at, polygon_contains
from app.simulation.scenario_scene import CATALOG
from app.simulation.scenarios import compile_preview, queue_event
from app.simulation.state import State


def world(client):
    sid = create_city(client)["id"]
    return client.app.state.service.owned("demo_owner", sid).model_copy(deep=True)


@pytest.mark.parametrize("recipe", CATALOG, ids=lambda r: r["id"])
def test_recipe_has_bounded_scene_and_simulation_effects(client, recipe):
    state = world(client)
    p = compile_preview(state, "custom", f"A {recipe['terms'][0]} for 2 ticks")
    assert p.can_commit
    assert any(o.model == recipe["model"] for o in p.spec.scene)
    assert 1 <= len(p.spec.scene) <= 24
    for o in p.spec.scene:
        assert polygon_contains(o.position, p.spec.affected_polygon)
        assert cell_at(state.map, o.position).walkable
        assert not any(polygon_contains(o.position, b.footprint) for b in state.map.buildings)
    for effect in recipe["effects"]:
        assert any(e.type == effect["type"] for e in p.spec.effects)


def test_composed_scene_is_deterministic_and_does_not_advance_physics(client):
    state = world(client)
    rng_before = copy.deepcopy(state.rng_state)
    prompt = "Dinosaurs and an alien spacecraft arrive during a festival in the east for 8 ticks"
    first = compile_preview(state, "custom", prompt)
    second = compile_preview(state, "custom", prompt)
    assert first.spec == second.spec
    assert {o.model for o in first.spec.scene} == {"dinosaur", "spacecraft", "stage"}
    assert first.spec.duration_ticks == 8
    assert all(o.position.x >= 64 for o in first.spec.scene)
    assert state.rng_state == rng_before
    assert sum(e.type == "community" for e in first.spec.effects) == 1


def test_uninterpretable_premise_asks_for_parameters_and_negated_fire_is_not_a_hazard(client):
    from app.simulation.scenarios import INTERPRETATION_FAILURE

    state = world(client)
    p = compile_preview(state, "custom", "Gravity reverses for a moment without any fire")
    assert not p.can_commit
    assert p.unsupported_requests == [INTERPRETATION_FAILURE]
    assert p.interpretation == INTERPRETATION_FAILURE
    assert "failed to interpret this scenario input" in INTERPRETATION_FAILURE
    assert {o.model for o in p.spec.scene} == {"monument"}
    assert all(e.type != "hazard" for e in p.spec.effects)


def test_uninterpretable_preview_cannot_be_committed(client):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid, "Gravity reverses for a moment")
    assert not p["can_commit"]
    result = commit_preview(client, sid, hold, p)
    assert result.status_code == 400
    assert client.get(f"/api/v1/simulations/{sid}/state").json()["data"]["events"] == []


def test_model_interpretation_supplies_effects_when_no_keyword_matches(client):
    state = world(client)
    p = compile_preview(state, "custom", "A whale is spotted in the harbor", interpreted=["wildlife"])
    assert p.can_commit and p.unsupported_requests == []
    assert "Interpreted by the model as: wildlife." in p.warnings
    assert any(e.type != "information" for e in p.spec.effects)
    failed = compile_preview(state, "custom", "A whale is spotted in the harbor", interpreted=[])
    assert not failed.can_commit


def test_scene_roundtrips_through_commit_history_and_repeat(client):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid, "Robots open a medical clinic for 1 tick")
    result = commit_preview(client, sid, hold, p)
    assert result.status_code == 201
    event = result.json()["data"]["event"]
    assert event["scene"] == p["spec"]["scene"]
    state = client.app.state.service.owned("demo_owner", sid).model_copy(deep=True)
    tick(state)
    assert frame(state).events[0].scene
    assert frame(state).events[0].status == "active"
    tick(state)
    assert frame(state).events[0].status == "resolved"
    restored = State.model_validate_json(state.model_dump_json())
    repeated = compile_preview(restored, "repeat", source_event_id=event["id"])
    assert repeated.spec.scene == state.events[event["id"]].spec.scene


def test_wellbeing_changes_are_real_bounded_and_geographically_scoped(client):
    state = world(client)
    citizens = list(state.citizens.values())
    local, remote = citizens[:2]
    local.summary.position = c.Vec2(x=33, y=33)
    remote.summary.position = c.Vec2(x=97, y=97)
    local.needs.health = remote.needs.health = 70
    p = compile_preview(state, "custom", "A medical clinic in the west for 1 tick")
    queue_event(state, p, state.snapshots[0].id, False)
    from app.simulation.scenarios import activate, apply_effects

    activate(state)
    apply_effects(state)
    assert local.needs.health == pytest.approx(70.6)
    assert remote.needs.health == 70
    local.needs.health = 99.9
    apply_effects(state)
    assert local.needs.health == 100


def test_random_previews_vary_without_consuming_world_rng(client):
    state = world(client)
    rng_before = copy.deepcopy(state.rng_state)
    titles = {compile_preview(state, "random").spec.title for _ in range(32)}
    assert len(titles) > 10
    assert state.rng_state == rng_before


def test_scene_budget_keeps_each_composed_family_visible(client):
    state = world(client)
    p = compile_preview(state, "custom", "A flood fire storm dinosaur alien robot market and garden appear")
    assert len(p.spec.scene) <= 24
    assert {o.model for o in p.spec.scene} == {
        "flood",
        "fire",
        "cloud",
        "dinosaur",
        "spacecraft",
        "robot",
        "stall",
        "tree",
    }


def test_prompt_controls_prop_count_color_and_specific_resource(client):
    state = world(client)
    p = compile_preview(state, "custom", "2 red robots bring relief during a water shortage")
    robots = [o for o in p.spec.scene if o.model == "robot"]
    assert len(robots) == 2
    assert all(o.color == "#db7567" for o in robots)
    stock_changes = [e for e in p.spec.effects if e.type == "resource_multiplier"]
    assert len(stock_changes) == 1 and stock_changes[0].resource == "water"


@pytest.mark.parametrize("opening", [False, True])
def test_freeform_provider_geometry_is_previewed_outside_writer_lock_and_persisted(client, opening):
    import json
    from dataclasses import replace
    from uuid import uuid4

    import httpx
    from conftest import write

    service = client.app.state.service
    sid = None if opening else create_city(client)["id"]
    config = replace(service.config, llm_mode="gemini", gemini_api_key="test-key", gemini_model="test-model")
    service.config = config
    service.gateway.config = config
    calls = []
    part = dict(shape="sphere", offset=dict(x=0, y=1, z=0), size=dict(x=4, y=2, z=2), color="#8bb9db")

    async def handler(request):
        assert not service.writer.locked()
        schema = json.loads(request.content)["generationConfig"]["responseJsonSchema"]
        kind = "interpretation" if "recipe_ids" in schema["properties"] else "scene"
        calls.append(kind)
        answer = (
            dict(recipe_ids=["wildlife"]) if kind == "interpretation" else dict(label="Whale", parts=[part])
        )
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}],
                "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 40},
            },
        )

    client.portal.call(service.gateway.client.aclose)
    service.gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    if opening:
        simulation = create_city(client, scenario_description="A whale arrives in the square")
        p = simulation["initial_preview"]
    else:
        simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        hold = write(
            client,
            f"/simulations/{sid}/interventions",
            dict(expected_control_version=simulation["control_version"]),
        ).json()["data"]
        body = dict(
            intervention_id=hold["id"],
            source="custom",
            source_event_id=None,
            prompt="A whale arrives in the square",
            policy=None,
        )
        key = str(uuid4())
        response = write(client, f"/simulations/{sid}/scenario-previews", body, key=key)
        assert response.status_code == 201, response.text
        p = response.json()["data"]
        again = write(client, f"/simulations/{sid}/scenario-previews", body, key=key)
        assert again.json()["data"] == p
        result = commit_preview(client, sid, hold, p)
        assert result.status_code == 201
        assert result.json()["data"]["event"]["scene"] == p["spec"]["scene"]
        # A committed/closed editor must not break idempotent preview retries.
        again = write(client, f"/simulations/{sid}/scenario-previews", body, key=key)
        assert again.status_code == 201 and again.json()["data"] == p
    assert calls == ["interpretation", "scene"]
    assert p["can_commit"]
    assert "Interpreted by the model as: wildlife." in p["warnings"]
    assert p["spec"]["scene"][0]["model"] == "generated"
    assert p["spec"]["scene"][0]["parts"] == [part]
    assert any("AI-composed" in w for w in p["warnings"])
