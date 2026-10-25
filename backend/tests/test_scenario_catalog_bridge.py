"""The AI registry must expose the same bounded catalog scenes as the older preview flow."""

import copy

import pytest
from conftest import command, create_city, write
from test_scenario_engine import draft, engine, fake_gemini, hold, op, plan_from

from app.scenario_engine.validator import compile_preview, validate_plan
from app.simulation.scenario_scene import CATALOG, COLORS
from app.simulation.scenarios import compile_preview as catalog_preview
from app.simulation.state import State


@pytest.mark.parametrize("recipe", CATALOG, ids=lambda recipe: recipe["id"])
def test_each_catalog_recipe_has_identical_effects_through_the_ai_registry(client, recipe):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    prompt = f"A {recipe['terms'][0]} in the north with severity 75 for 8 ticks"
    raw = plan_from(
        state,
        draft(
            [op("catalog_event", "scene", recipe=recipe["id"], region="north", severity=75)],
            measurement_ticks=8,
        ),
    )
    raw["prompt"] = prompt
    plan, errors, warnings = validate_plan(state, raw)
    assert plan is not None, errors
    preview = compile_preview(state, plan, warnings)
    # Select the same recipe through the older model-interpretation path, without
    # overlapping keywords selecting extra recipes. Only the final narrative differs.
    legacy = catalog_preview(
        state,
        "custom",
        "An unfamiliar event in the north with severity 75 for 8 ticks",
        interpreted=[recipe["id"]],
    )
    actual = [effect.model_dump() for effect in preview.spec.effects[:-1]]
    expected = [effect.model_dump() for effect in legacy.spec.effects[:-1]]
    assert actual == expected
    assert preview.can_commit and preview.spec.duration_ticks == 8
    assert any(prop.model == recipe["model"] for prop in preview.spec.scene)
    assert len(preview.spec.scene) <= 24


def test_selected_recipes_preserve_styling_without_adding_negated_hazards(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    raw = plan_from(state, draft([op("catalog_event", "dinos", recipe="dinosaurs")]))
    raw["prompt"] = "2 red dinosaurs appear without any fire"
    plan, errors, warnings = validate_plan(state, raw)
    assert plan is not None, errors
    preview = compile_preview(state, plan, warnings)
    assert len(preview.spec.scene) == 2
    assert {prop.model for prop in preview.spec.scene} == {"dinosaur"}
    assert {prop.color for prop in preview.spec.scene} == {COLORS["red"]}
    assert not any(effect.type == "hazard" for effect in preview.spec.effects)


def test_dinosaur_plan_interprets_commits_runs_and_roundtrips(client, monkeypatch):
    calls = fake_gemini(
        client,
        monkeypatch,
        [
            draft(
                [
                    op(
                        "catalog_event",
                        "dinos",
                        recipe="dinosaurs",
                        region="citywide",
                        count=2,
                        color="#ff0000",
                    )
                ],
                title="Dinosaurs in the square",
                category="environmental",
                measurement_ticks=4,
            )
        ],
    )
    sid = create_city(client)["id"]
    intervention = hold(client, sid)
    result = engine(
        client,
        f"/simulations/{sid}/plans",
        dict(
            intervention_id=intervention["id"], prompt="2 red dinosaurs appear in the town square for 4 ticks"
        ),
    ).json()["data"]
    assert result["status"] == "ready" and result["unsupported"] == []
    assert '"id":"dinosaurs"' in calls[0] and "scene_catalog" in calls[0]
    assert any("not autonomous" in warning for warning in result["warnings"])
    service = client.app.state.service
    assert not service.heads[sid].events
    committed = engine(
        client,
        f"/simulations/{sid}/commits",
        dict(
            intervention_id=intervention["id"],
            expected_control_version=intervention["control_version"],
            plan=result["plan"],
        ),
    )
    assert committed.status_code == 201, committed.text
    event = committed.json()["data"]["event"]
    assert len(event["scene"]) == 2 and {prop["model"] for prop in event["scene"]} == {"dinosaur"}
    command(client, sid, "step", count=5)
    state = service.heads[sid]
    assert state.events[event["id"]].summary.status == "resolved"
    assert any(t.op_id == "dinos" and t.kind == "operation" for t in state.systems.traces)
    assert any(effect.type == "wellbeing" for effect in state.events[event["id"]].spec.effects)
    restored = State.model_validate_json(state.model_dump_json())
    repeated = catalog_preview(restored, "repeat", source_event_id=event["id"])
    assert repeated.spec.scene == state.events[event["id"]].spec.scene


def test_catalog_scenes_compose_with_policy_without_losing_either_change(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    raw = plan_from(
        state,
        draft(
            [
                op("catalog_event", "dinos", recipe="dinosaurs", region="north", count=2),
                op("catalog_event", "aliens", recipe="aliens", region="north"),
                op("catalog_event", "festival", recipe="festival", region="north"),
                op(
                    "modify_policy",
                    "fare",
                    target="transportation.transit_fare",
                    operation="multiply",
                    value=2,
                ),
            ]
        ),
    )
    plan, errors, warnings = validate_plan(state, raw)
    assert plan is not None, errors
    preview = compile_preview(state.model_copy(deep=True), plan, warnings)
    assert {prop.model for prop in preview.spec.scene} == {"dinosaur", "spacecraft", "stage"}
    assert any(effect.type == "wellbeing" for effect in preview.spec.effects)
    assert any(effect.type == "community" for effect in preview.spec.effects)
    assert any(operation.type == "modify_policy" for operation in plan.operations)


@pytest.mark.parametrize(
    "change",
    [
        {"recipe": "autonomous_predator"},
        {"count": 9},
        {"count": 0},
        {"color": "red"},
        {"region": "outside_the_map"},
        {"timing": {"start_tick": 2}},
    ],
)
def test_catalog_operation_rejects_unknown_or_out_of_bounds_parameters(client, change):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    raw = plan_from(state, draft([op("catalog_event", "dinos", recipe="dinosaurs")]))
    raw["operations"][0].update(copy.deepcopy(change))
    plan, errors, _ = validate_plan(state, raw)
    assert plan is None and errors


def test_initial_scenario_can_use_the_catalog_through_gemini(client, monkeypatch):
    fake_gemini(
        client,
        monkeypatch,
        [
            draft(
                [op("catalog_event", "dinos", recipe="dinosaurs")],
                category="environmental",
                measurement_ticks=4,
            )
        ],
    )
    simulation = create_city(client, scenario_description="Dinosaurs appear in town for 4 ticks")
    preview = simulation["initial_preview"]
    assert preview["can_commit"] and preview["unsupported_requests"] == []
    assert {prop["model"] for prop in preview["spec"]["scene"]} == {"dinosaur"}
    result = write(
        client,
        f"/simulations/{simulation['id']}/initial-scenario",
        dict(
            expected_control_version=simulation["control_version"],
            preview_id=preview["id"],
            decision="confirm",
        ),
    )
    assert result.status_code == 200


def test_catalog_misinformation_preserves_unreliable_information_and_effect_limits(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    raw = plan_from(state, draft([op("catalog_event", "rumor", recipe="misinformation")]))
    plan, errors, warnings = validate_plan(state, raw)
    assert plan is not None, errors
    preview = compile_preview(state.model_copy(deep=True), plan, warnings)
    assert preview.spec.effects[-1].reliability == 25
    oversized = plan_from(
        state,
        draft(
            [
                op("physical_hazard", f"fire{i}", hazard="fire", region="north", severity=i)
                for i in range(1, 25)
            ]
        ),
    )
    rejected, errors, _ = validate_plan(state, oversized)
    assert rejected is None and any("19-effect" in error for error in errors)
