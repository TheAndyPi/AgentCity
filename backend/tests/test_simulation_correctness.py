"""Machine B regressions: consent, self-safety, and honest scenario effects."""

import pytest
from conftest import create_city

from app import contracts as c
from app.prompts.outputs import SceneDesign
from app.simulation.agents import hazard_severity, perception
from app.simulation.game_master import apply_intent, make_intent, rule_intent
from app.simulation.interactions import expire_interactions
from app.simulation.scenario_scene import matches
from app.simulation.scenarios import (
    INTERPRETATION_FAILURE,
    activate,
    apply_effects,
    compile_preview,
    queue_event,
    rectangle,
)
from app.simulation.state import State


def world(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    a, b = list(state.citizens.values())[:2]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
    a.summary.position, b.summary.position = c.Vec2(x=33, y=33), c.Vec2(x=35, y=33)
    for citizen in (a, b):
        citizen.summary.path = []
        citizen.needs.hunger = citizen.needs.fatigue = 0
        citizen.needs.social = 80
    return state, a, b


def test_initiator_cannot_continue_or_complete_without_recipient_acceptance(client):
    state, a, b = world(client)
    first = apply_intent(state, a, make_intent("talk", target=b.summary.id))
    assert first.outcome == "accepted" and "awaiting" in first.outcome_description
    invitation = next(iter(state.interactions.values()))
    for _ in range(6):
        state.simulation.tick += 1
        result = apply_intent(state, a, make_intent("talk", target=b.summary.id), source="gemini")
        if state.simulation.tick <= invitation.expires_tick:
            assert result.rejection_code == "AWAITING_ACCEPTANCE"
            assert invitation.status == "invited" and invitation.accepted_ids == [a.summary.id]
            assert invitation.turns == 1
            assert len(state.dialogue) == 1 and not state.dialogue[-1].end_conversation
            assert a.needs.social == 80
        else:
            # A fresh invitation is legal once the previous invitation expires.
            assert result.outcome == "accepted"
            break
    expire_interactions(state)
    assert invitation.status == "expired"
    assert b.next_social_tick <= state.simulation.tick


def test_warnings_do_not_accept_or_advance_a_conversation(client):
    state, a, b = world(client)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    invitation = next(iter(state.interactions.values()))
    for actor, target in [(a, b), (b, a)] * 3:
        result = apply_intent(
            state, actor, make_intent("warn", target=target.summary.id, message="Watch the road!")
        )
        assert result.outcome == "accepted"
        line = state.dialogue[-1]
        assert line.text == "Watch the road!" and target.summary.id in line.audible_to_ids
        assert not line.end_conversation
        assert state.interactions[line.interaction_id].status == "ended"
    assert invitation.status == "invited" and invitation.accepted_ids == [a.summary.id]
    assert invitation.turns == 1
    assert any("Watch the road!" in belief.text for belief in b.beliefs)
    for actor, target in [(b, a), (a, b), (b, a)]:
        from conftest import advance_conversation_turn

        advance_conversation_turn(state, actor)
        assert apply_intent(state, actor, make_intent("talk", target=target.summary.id)).outcome == "accepted"
    assert invitation.status == "ended" and invitation.turns == 4
    assert set(invitation.accepted_ids) == {a.summary.id, b.summary.id}
    assert state.dialogue[-1].end_conversation


def test_unobserved_recipient_cannot_accept_an_invitation(client):
    state, a, b = world(client)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    invitation = next(iter(state.interactions.values()))
    b.summary.position = c.Vec2(x=97, y=97)
    result = apply_intent(state, b, make_intent("talk", target=a.summary.id))
    assert result.outcome == "rejected"
    assert invitation.status == "invited" and invitation.accepted_ids == [a.summary.id]
    assert len(state.dialogue) == 1


@pytest.mark.parametrize("threat", ["hazard", "order"])
@pytest.mark.parametrize("reachable_safety", [False, True])
def test_self_safety_precedes_help_even_without_a_safe_route(client, threat, reachable_safety):
    state, helper, victim = world(client)
    helper.profile.traits.empathy = 100
    helper.inventory.supplies = 10
    helper.needs.health = 100
    victim.needs.health = 40
    helper.known_locations.update({b.id: b.entrance for b in state.map.buildings})
    if threat == "hazard":
        preview = compile_preview(state, "custom", "A flood")
        preview.spec.affected_polygon = rectangle(32, 32, 34, 34)
        preview.spec.origin = helper.summary.position.model_copy()
        preview.spec.scene = []
        queue_event(state, preview, state.snapshots[0].id, False)
        activate(state)
        assert hazard_severity(state, helper.summary.position) > 0
    else:
        state.policies.evacuation_order = True
    if not reachable_safety:
        for building in state.map.buildings:
            building.functional = False
    intent = rule_intent(state, helper, perception(state, helper))
    assert intent.action == ("evacuate" if reachable_safety else "rest")
    supplies, health = helper.inventory.supplies, victim.needs.health
    for source in ("rules", "gemini", "replay"):
        result = apply_intent(state, helper, make_intent("help", target=victim.summary.id), source=source)
        assert result.rejection_code == "SELF_SAFETY_REQUIRED"
        assert result.effects == []
        assert helper.inventory.supplies == supplies and victim.needs.health == health
        assert state.counters["cooperation_count"] == 0


def test_safe_helper_can_still_aid_a_nearby_victim_in_a_hazard(client):
    state, helper, victim = world(client)
    helper.profile.traits.empathy = 100
    helper.inventory.supplies = 2
    helper.needs.health = 100
    victim.needs.health = 40
    preview = compile_preview(state, "custom", "A flood")
    preview.spec.affected_polygon = rectangle(34, 32, 36, 34)
    preview.spec.origin = victim.summary.position.model_copy()
    preview.spec.scene = []
    queue_event(state, preview, state.snapshots[0].id, False)
    activate(state)
    assert hazard_severity(state, helper.summary.position) == 0
    assert hazard_severity(state, victim.summary.position) > 0
    intent = rule_intent(state, helper, perception(state, helper))
    assert intent.action == "help" and intent.target_id == victim.summary.id
    result = apply_intent(state, helper, intent)
    assert result.outcome == "accepted"
    assert victim.needs.health == 45 and helper.inventory.supplies == 1


@pytest.mark.parametrize(
    "prompt",
    [
        "There is no flood today",
        "A flood is not expected",
        "There is no severe flood today",
        "No major flooding is expected",
        "A flood will not occur",
        "A flood isn't expected",
        "A festival without any fire",
        "No flood or fire today",
        "There will not be a flood",
        "There won't be a storm",
        "Neither flood nor fire",
        "No floods, fires or storms",
        "A flood or fire won't happen",
    ],
)
def test_negated_hazards_create_neither_damage_nor_hazard_scenery(client, prompt):
    state, a, _ = world(client)
    preview = compile_preview(state, "custom", prompt)
    assert all(effect.type != "hazard" for effect in preview.spec.effects)
    assert all(prop.model not in {"flood", "fire", "cloud"} for prop in preview.spec.scene)
    if not preview.can_commit:
        # A denial with nothing else to simulate asks the user to restate the scenario.
        assert preview.unsupported_requests == [INTERPRETATION_FAILURE]
        return
    before = a.needs.health
    queue_event(state, preview, state.snapshots[0].id, False)
    activate(state)
    apply_effects(state)
    assert a.needs.health == before


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("No flood today, but a severe flood arrives tomorrow", {"flood"}),
        ("A flood is not expected, but a fire starts", {"fire"}),
        ("No severe flood today. A festival opens", {"festival"}),
        ("A severe flood starts without any fire", {"flood"}),
        ("There's no flood and a fire starts", {"fire"}),
        ("No flood, a fire is coming", {"fire"}),
        ("No severe flood or major fire, just a festival", {"festival"}),
        ("A flood and fire hit the east", {"flood", "fire"}),
    ],
)
def test_negation_is_scoped_to_each_mention(prompt, expected):
    assert {recipe["id"] for recipe in matches(prompt)} == expected


@pytest.mark.parametrize(
    ("prompt", "limitation"),
    [
        ("Destroy the hospital during a festival", "destruction"),
        ("A dragon destroys the hospital during a fire", "destruction"),
        ("The hospital was demolished during a storm", "destruction"),
        ("Build a new hospital during a festival", "construction"),
        ("A new building is constructed. A festival opens", "construction"),
        ("Workers are building a new school during a festival", "construction"),
        ("Create a new building. A market opens", "construction"),
        ("Add two houses. A concert starts", "construction"),
        ("A new hospital appears. Visitors arrive", "construction"),
    ],
)
def test_unsupported_building_actions_remain_narrative_and_survive_repeat(client, prompt, limitation):
    state, a, _ = world(client)
    buildings_before = [b.model_dump() for b in state.map.buildings]
    cells_before = [cell.model_dump() for cell in state.map.cells]
    preview = compile_preview(state, "custom", prompt)
    assert preview.can_commit and preview.spec.description == prompt
    assert any(limitation in item for item in preview.unsupported_requests)
    assert "not destroyed" in preview.interpretation and "not constructed" in preview.interpretation
    assert all(prop.label.startswith("Illustration: ") for prop in preview.spec.scene)
    information = next(effect for effect in preview.spec.effects if effect.type == "information")
    assert information.message.startswith("Narrative request: ")
    assert "not destroyed" in information.message and "not constructed" in information.message
    event = queue_event(state, preview, state.snapshots[0].id, False)
    activate(state)
    apply_effects(state)
    assert [b.model_dump() for b in state.map.buildings] == buildings_before
    assert [cell.model_dump() for cell in state.map.cells] == cells_before
    assert any("Narrative request:" in m.text and prompt in m.text for m in a.memories)
    assert any("not constructed" in belief.text for belief in a.beliefs)
    state.events[event.id].summary.status = "resolved"
    restored = State.model_validate_json(state.model_dump_json())
    repeated = compile_preview(restored, "repeat", source_event_id=event.id)
    assert repeated.unsupported_requests == preview.unsupported_requests
    assert repeated.spec == preview.spec


@pytest.mark.parametrize(
    "prompt",
    [
        "Aid workers add supplies to the shelter",
        "Don't create a new building",
        "Create a festival near the school",
    ],
)
def test_non_construction_mentions_of_buildings_are_supported(prompt):
    from app.simulation.scenarios import unsupported_physical_requests

    assert unsupported_physical_requests(prompt) == []


def test_regional_construction_request_gets_specific_notice(client):
    state, _, _ = world(client)
    preview = compile_preview(state, "custom", "Create a new building in the north")
    assert preview.unsupported_requests == [
        "Building construction is unsupported; scene illustrations do not alter city buildings.",
        INTERPRETATION_FAILURE,
    ]
    assert any("construction is unsupported" in warning for warning in preview.warnings)
    assert not preview.can_commit and preview.interpretation == INTERPRETATION_FAILURE


@pytest.mark.parametrize(
    ("prompt", "region"),
    [
        ("A feast in the square", None),
        ("A beast wanders the streets", None),
        ("A festival in the eastern blocks", "east"),
        ("A storm in the northeast", "north"),
        ("Snow falls on the south-west", "west"),
    ],
)
def test_regions_require_whole_direction_words(prompt, region):
    from app.simulation.scenarios import region as named_region

    assert named_region(prompt.lower()) == region


def test_custom_illustrations_do_not_claim_construction(client):
    state, _, _ = world(client)
    design = SceneDesign(
        label="New hospital",
        parts=[
            c.ScenePart(
                shape="box",
                offset=c.SceneOffset(x=0, y=1, z=0),
                size=c.SceneSize(x=2, y=2, z=2),
                color="#ffffff",
            )
        ],
    )
    preview = compile_preview(state, "custom", "Build a new hospital", design=design)
    assert preview.unsupported_requests
    assert all(prop.label.startswith("Illustration: ") for prop in preview.spec.scene)
    assert any(prop.model == "generated" for prop in preview.spec.scene)
