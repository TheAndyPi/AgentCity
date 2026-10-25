"""AB acceptance: real seeded worlds, GM mutations, persistence and owned API."""

import json
import random
from pathlib import Path

import pytest
from conftest import command, create_city, write

from app.behavior.api import snapshot
from app.behavior.care import eligible, synchronize_transport, treatment
from app.behavior.classes import affinity, classify, encounter, wealth
from app.behavior.crisis import evaluate_crisis, weights
from app.behavior.game_master import act, fire_effects
from app.behavior.models import Episode
from app.behavior.rules import RULES, VERSION, coupling, rest_multiplier, social_multiplier
from app.behavior.vitals import background, conscious, evaluate, living, passive
from app.contracts import Vec2
from app.data.repository import Repository
from app.simulation.agents import connect, perception, update_metrics
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.navigation import distance
from app.simulation.state import State


def world(client, count=2):
    sid = create_city(client)["id"]
    state = client.app.state.service.owned("demo_owner", sid).model_copy(deep=True)
    state.citizens = dict(list(state.citizens.items())[:count])
    state.behavior.initial_population = count
    for i, c in enumerate(state.citizens.values()):
        c.summary.position = Vec2(x=33 + i * 2, y=33)
        c.summary.path = []
        c.inside_building_id = c.entering_building_id = c.leaving_building_id = None
        c.needs.hunger = 20
        c.needs.fatigue = 15
        c.needs.health = 100
        c.inventory.food = c.inventory.water = c.inventory.supplies = 10
        c.profile.traits.empathy = c.profile.traits.cooperation = 85
    for person in state.citizens.values():
        for other in state.citizens.values():
            connect(state, person, other, "friend")
    return state, list(state.citizens.values())


def idle(state):
    tick(state, {aid: (make_intent("idle"), None) for aid in state.citizens})


def totals(state):
    return {
        k: sum(getattr(c.inventory, k) for c in state.citizens.values())
        + sum(r.available_units for r in state.map.resources if r.kind == k)
        + sum(getattr(h.inventory, k) for h in state.behavior.hospitals.values())
        for k in ("food", "water", "supplies")
    }


def episode(c, mode, tick=0):
    c.condition.episode = Episode(
        id="test_episode",
        mode=mode,
        start_tick=tick,
        causes=["low_mental"],
        measurements={"mental": 10},
        rationale="Fixture known grievance",
    )


@pytest.mark.parametrize(
    "health,hunger,causes",
    [(0, 20, ["health"]), (100, 100, ["fullness"]), (0, 100, ["health", "fullness"]), (0.1, 99.9, [])],
)
def test_ab01_raw_independent_death_once(client, health, hunger, causes):
    state, (a, b) = world(client)
    a.needs.health, a.needs.hunger = health, hunger
    before = totals(state)
    evaluate(state, a)
    evaluate(state, a)
    assert living(a) == (not causes)
    assert a.condition.causes == causes
    assert state.behavior.counters.get("death", 0) == bool(causes)
    assert totals(state) == before
    if causes:
        assert a.condition.transition_tick == state.simulation.tick
        assert a.condition.evidence


def test_ab02_death_invalidates_routes_proposals_actions_and_keeps_possessions(client):
    state, (a, b) = world(client)
    a.needs.health = 1
    a.summary.path = [Vec2(x=41, y=33)]
    a.plan = {"kind": "work"}
    b.relationships[a.summary.id].conflict = 90
    episode(b, "aggression")
    before = a.inventory.model_dump()
    assert act(state, b, "attack", a.summary.id).accepted
    position = a.summary.position.model_copy()
    idle(state)
    result = apply_intent(state, a, make_intent("rest"))
    assert result.rejection_code == "INCAPACITATED"
    assert a.condition.life == "dead" and not a.summary.path and a.plan is None
    assert a.inventory.model_dump() == before
    assert a.summary.position == position
    assert not any(d.agent_id == a.summary.id and d.outcome == "accepted" for d in state.decisions)
    assert state.behavior.counters["death"] == 1


def test_ab02_consumption_precedes_decay_but_cannot_cure_initial_fatal_boundary(client):
    state, (a, b) = world(client)
    a.needs.hunger = 99.9
    tick(
        state,
        {
            a.summary.id: (make_intent("consume", kind="food", amount=1), None),
            b.summary.id: (make_intent("idle"), None),
        },
    )
    assert living(a) and a.needs.hunger == pytest.approx(99.9 - 3 * 12 + 4 / 30)
    a.needs.hunger = 100
    assert apply_intent(state, a, make_intent("consume", kind="food", amount=1)).outcome == "rejected"
    assert a.condition.life == "dead"
    b.needs.hunger = 99.9
    b.inventory.food = b.inventory.water = 0
    idle(state)
    assert b.condition.life == "dead" and b.condition.causes == ["fullness"]


def test_ab03_faint_no_actions_hysteretic_passive_wake(client):
    state, (a, b) = world(client)
    a.needs.fatigue = 100
    evaluate(state, a)
    assert a.condition.life == "unconscious" and living(a) and not conscious(a)
    assert apply_intent(state, a, make_intent("consume", kind="food", amount=1)).outcome == "rejected"
    a.needs.fatigue = 80.1
    evaluate(state, a)
    assert not conscious(a)
    passive(state, a)
    assert conscious(a)
    passive(state, a)
    assert state.behavior.counters["faint"] == state.behavior.counters["wake"] == 1


def test_ab04_unconscious_can_starve_carrier_drops_patient_exactly(client):
    state, (helper, patient) = world(client)
    patient.needs.fatigue = 100
    evaluate(state, patient)
    assert act(state, helper, "rescue", patient.summary.id).accepted
    advance_movement(state, helper)
    synchronize_transport(state, helper)
    assert patient.condition.care == "carried"
    helper.summary.position = Vec2(x=37, y=33)
    helper.needs.fatigue = 100
    evaluate(state, helper)
    assert helper.condition.patient_id is None and patient.condition.helper_id is None
    assert patient.summary.position == helper.summary.position
    assert all(not h.reservations for h in state.behavior.hospitals.values())
    patient.needs.hunger = 99.9
    idle(state)
    assert patient.condition.life == "dead"


@pytest.mark.parametrize(
    "mental,stress,causes",
    [
        (10, 20, ["low_mental"]),
        (10.1, 20, []),
        (70, 80, ["high_stress"]),
        (70, 79.9, []),
        (10, 80, ["low_mental", "high_stress"]),
    ],
)
def test_ab05_ab18_crisis_independent_raw_boundaries(client, mental, stress, causes):
    state, (a, _) = world(client)
    a.condition.mental, a.summary.metrics.stress = mental, stress
    evaluate_crisis(state, a, random.Random(42))
    assert (a.condition.episode is not None) == bool(causes)
    if causes:
        assert a.condition.episode.causes == causes
        assert state.behavior.counters["crisis"] == 1
        identity = a.condition.episode.id
        a.condition.mental = 5
        a.summary.metrics.stress = 90
        evaluate_crisis(state, a, random.Random(13))
        assert a.condition.episode.id == identity
        assert set(a.condition.episode.causes) == {"low_mental", "high_stress"}
        assert state.behavior.counters["crisis"] == 1


def test_ab18_exit_requires_both_and_three_distinct_ticks(client):
    state, (a, _) = world(client)
    a.condition.mental = 10
    evaluate_crisis(state, a, random.Random(42))
    for mental, stress in [(60, 90), (10, 30), (25, 60), (25, 60), (25, 60)]:
        state.simulation.tick += 1
        a.condition.mental, a.summary.metrics.stress = mental, stress
        evaluate_crisis(state, a, random.Random(42))
        evaluate_crisis(state, a, random.Random(42))
    assert a.condition.episode.end_tick == state.simulation.tick
    assert a.condition.cooldown_until == state.simulation.tick + RULES["cooldown_ticks"]


def test_ab06_personality_weights_seeded_modes(client):
    state, (a, b) = world(client)
    a.condition.mental = b.condition.mental = 10
    a.profile.traits.sociability = a.profile.traits.risk_tolerance = 0
    a.profile.traits.empathy = a.profile.traits.cooperation = 100
    b.profile.traits.sociability = b.profile.traits.risk_tolerance = 100
    b.profile.traits.empathy = b.profile.traits.cooperation = 0
    b.relationships[a.summary.id].conflict = 90
    assert weights(a)["withdrawal"] > weights(b)["withdrawal"]
    assert weights(b)["aggression"] > weights(a)["aggression"]
    results = set()
    for seed in range(100):
        clone = state.model_copy(deep=True)
        person = clone.citizens[b.summary.id]
        evaluate_crisis(clone, person, random.Random(seed))
        results.add(person.condition.episode.mode)
        repeated = state.model_copy(deep=True)
        evaluate_crisis(repeated, repeated.citizens[b.summary.id], random.Random(seed))
        assert repeated.citizens[b.summary.id].condition.episode.mode == person.condition.episode.mode
    assert {"withdrawal", "support", "panic", "aggression", "fire"} <= results


def test_ab07_rejected_remote_attack_no_effect_and_once_per_cooldown(client):
    state, (a, b) = world(client)
    episode(a, "aggression")
    a.relationships[b.summary.id].conflict = 90
    b.summary.position = Vec2(x=105, y=105)
    hp = b.needs.health
    assert not act(state, a, "attack", b.summary.id).accepted
    assert b.needs.health == hp
    b.summary.position = Vec2(x=35, y=33)
    assert act(state, a, "attack", b.summary.id).accepted
    assert b.needs.health == hp - RULES["attack_damage"]
    assert not act(state, a, "attack", b.summary.id).accepted
    state.simulation.tick += 1
    assert not act(state, a, "attack", b.summary.id).accepted
    a.needs.fatigue = 100
    assert not act(state, a, "attack", b.summary.id).accepted


def test_ab08_bounded_real_fire_damage_suppression_and_extinction(client):
    state, (a, b) = world(client)
    building = next(x for x in state.map.buildings if x.kind == "home")
    episode(a, "fire")
    assert not act(state, a, "ignite", building.id).accepted
    assert not state.behavior.fires
    a.summary.position = building.entrance.model_copy()
    assert act(state, a, "ignite", building.id).accepted
    assert not act(state, a, "ignite", building.id).accepted
    b.summary.position = building.entrance.model_copy()
    health = b.needs.health
    fire_effects(state)
    assert b.needs.health == pytest.approx(health - 1.2)
    f = next(iter(state.behavior.fires.values()))
    b.summary.position = Vec2(x=f.position.x, y=f.position.y + 4)
    water = b.inventory.water
    assert act(state, b, "suppress", f.id).accepted
    assert f.extinguished and b.inventory.water == water - 1
    state.simulation.tick = f.end_tick
    fire_effects(state)
    assert state.behavior.counters["ignition"] == 1


def test_ab09_full_engine_physical_rescue_admission_and_conserved_care(client):
    state, (helper, patient) = world(client)
    # Put patient close to the hospital so even a short test must traverse its door.
    hospital = next(b for b in state.map.buildings if b.kind == "hospital")
    helper.summary.position = hospital.entrance.model_copy()
    patient.summary.position = Vec2(x=helper.summary.position.x + 1.1, y=helper.summary.position.y)
    patient.needs.fatigue = 100
    patient.needs.health = 40
    patient.needs.hunger = 40
    evaluate(state, patient)
    helper.profile.traits.empathy = helper.profile.traits.cooperation = 100
    before = totals(state)
    positions = []
    admitted = False
    for _ in range(50):
        origin = patient.summary.position.model_copy()
        tick(state)
        positions.append(patient.summary.position.model_dump())
        # Patient never moves faster than the helper (with a tiny pickup tolerance).
        assert distance(origin, patient.summary.position) <= helper.summary.movement_speed_mps * 10 + 1e-6
        admitted |= patient.condition.care == "hospital"
        if state.behavior.counters.get("hospital_release"):
            break
    assert admitted, (helper.model_dump(), patient.model_dump(), state.behavior.model_dump())
    assert state.behavior.counters["admission"] == 1
    assert state.behavior.counters["hospital_release"] == 1
    assert conscious(patient) and patient.needs.health >= RULES["release_health"]
    consumed = state.counters["resources_consumed"]
    assert sum(before.values()) - sum(totals(state).values()) == pytest.approx(consumed)
    assert len({json.dumps(p, sort_keys=True) for p in positions}) > 1


def test_ab10_atomic_claim_full_closed_unsafe_and_supplies(client):
    state, (a, b, patient) = world(client, 3)
    patient.needs.fatigue = 100
    evaluate(state, patient)
    a.summary.position = Vec2(x=34, y=33)
    b.summary.position = Vec2(x=35, y=33)
    assert act(state, a, "rescue", patient.summary.id).accepted
    assert not act(state, b, "rescue", patient.summary.id).accepted
    assert patient.condition.helper_id == a.summary.id and b.condition.patient_id is None
    hospital = state.behavior.hospitals[patient.condition.hospital_id]
    building = next(x for x in state.map.buildings if x.id == patient.condition.hospital_id)
    building.functional = False
    synchronize_transport(state, a)
    assert patient.condition.helper_id is None and not hospital.reservations
    assert not act(state, b, "rescue", patient.summary.id).accepted
    building.functional = True
    building.capacity = 0
    assert not act(state, b, "rescue", patient.summary.id).accepted
    a.needs.health = 40
    assert not eligible(state, a)
    # A bed without supplies confers rest only, never fabricated healing/nutrition.
    building.capacity = 10
    hospital.patients = [patient.summary.id]
    patient.condition.care = "hospital"
    patient.condition.hospital_id = building.id
    patient.inside_building_id = building.id
    hospital.inventory.food = hospital.inventory.water = hospital.inventory.supplies = 0
    hp, hunger = patient.needs.health, patient.needs.hunger
    treatment(state)
    assert patient.needs.health == hp and patient.needs.hunger == hunger


def test_ab11_local_grief_and_mutually_accepted_support(client):
    state, (a, b, remote) = world(client, 3)
    remote.summary.position = Vec2(x=110, y=110)
    connect(state, remote, a, "friend")
    before = remote.condition.mental
    a.needs.health = 0
    evaluate(state, a)
    assert remote.condition.mental == before and not remote.memories
    assert b.condition.mental < 70
    # Grief is charged once; supportive conversation requires a conscious reply.
    mental = b.condition.mental
    evaluate(state, a)
    assert b.condition.mental == mental
    remote.summary.position = Vec2(x=37, y=33)
    b.condition.mental = 30
    apply_intent(state, b, make_intent("talk", target=remote.summary.id))
    assert b.condition.mental == 30
    assert remote.condition.mental == before + RULES["grief_mental"]
    assert any(a.summary.id in m.subject_ids and m.source == "heard" for m in remote.memories)
    from conftest import advance_conversation_turn

    advance_conversation_turn(state, remote)
    apply_intent(state, remote, make_intent("talk", target=b.summary.id))
    assert act(state, remote, "comfort", b.summary.id).accepted
    assert b.condition.mental == 33


def test_ab12_ab13_class_beliefs_require_public_evidence_and_hysteresis(client):
    state, (rich, poor) = world(client)
    rich.inventory.food = rich.inventory.water = rich.inventory.supplies = 20
    poor.inventory.food = poor.inventory.water = poor.inventory.supplies = 1
    rich.condition.wealth_band = classify(rich)
    rich.profile.traits.empathy = rich.profile.traits.cooperation = 0
    encounter(state, rich, perception(state, rich))
    assert poor.summary.id not in rich.condition.class_beliefs
    poor.summary.position = state.map.resources[0].position.model_copy()
    rich.summary.position = Vec2(x=poor.summary.position.x + 1.1, y=poor.summary.position.y)
    source = state.map.resources[0]
    assert (
        apply_intent(
            state, poor, make_intent("gather", target=source.id, kind=source.kind, amount=0.1)
        ).outcome
        == "accepted"
    )
    old_trust = rich.relationships[poor.summary.id].trust
    encounter(state, rich, perception(state, rich))
    assert rich.condition.class_beliefs[poor.summary.id] == "poor"
    assert rich.relationships[poor.summary.id].trust < old_trust
    assert affinity(rich, poor) < 0
    after = rich.relationships[poor.summary.id].model_dump()
    encounter(state, rich, perception(state, rich))
    assert rich.relationships[poor.summary.id].model_dump() == after
    poor.inventory.food = 200
    assert rich.condition.class_beliefs[poor.summary.id] == "poor"
    rich.profile.traits.empathy = rich.profile.traits.cooperation = 100
    assert affinity(rich, poor) > 0
    rich.condition.wealth_band = "rich"
    rich.inventory.food, rich.inventory.water, rich.inventory.supplies = 22, 0, 0
    assert classify(rich) == "rich"
    rich.inventory.food = 21.9
    assert classify(rich) == "middle"
    assert wealth(rich) == 21.9


def test_ab13_conserved_sharing_does_not_feed_without_consumption(client):
    state, (a, b) = world(client)
    before = totals(state)
    hunger = b.needs.hunger
    assert act(state, a, "share", b.summary.id).accepted
    assert totals(state) == before and b.needs.hunger == hunger


def test_ab14_checkpoint_roundtrip_during_crisis_carry_and_care(client, tmp_path):
    state, (a, b) = world(client)
    b.needs.fatigue = 100
    evaluate(state, b)
    assert act(state, a, "rescue", b.summary.id).accepted
    advance_movement(state, a)
    synchronize_transport(state, a)
    assert b.condition.care == "carried"
    episode(a, "support")
    repo = Repository(tmp_path / "checkpoint")
    state.simulation.revision = 0
    repo.commit([state])
    repo.close()
    repo = Repository(tmp_path / "checkpoint")
    restored = repo.read(state.simulation.id)
    assert restored.model_dump() == state.model_dump()
    branch = restored.model_copy(deep=True)
    branch.citizens[a.summary.id].condition.mental = 15
    assert restored.citizens[a.summary.id].condition.mental == 70
    before = restored.model_dump()
    snapshot(restored)
    update_metrics(restored)
    # Read metrics are deterministic and do not run coupling or advance RNG.
    assert restored.rng_state == before["rng_state"]
    assert restored.behavior.model_dump() == before["behavior"]
    repo.close()


def test_ab15_ab16_owned_pinned_versioned_api_all_dead_and_legacy(client):
    state, (a, b) = world(client)
    service = client.app.state.service
    sid = state.simulation.id
    # Commit through the actual public command lifecycle to exercise read-back.
    service.heads[sid] = state
    for c in state.citizens.values():
        c.needs.health = 0
    assert command(client, sid, "step", count=1).status_code == 200
    live = service.heads[sid]
    tick_number = live.simulation.tick
    tick(live)
    assert live.simulation.tick == tick_number
    result = client.get(f"/api/v1/integrations/behavior/v2/simulations/{sid}")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["schema_version"] == VERSION
    assert body["data"]["analytics"]["survival_fraction"] == 0
    assert body["data"]["analytics"]["living"] == 0
    assert body["data"]["analytics"]["deaths_by_cause"]["health"] == 2
    assert not body["data"]["analytics"]["snowflake_behavior_supported"]
    assert client.get(f"/api/v1/integrations/behavior/v2/simulations/{sid}?revision=-1").status_code == 422
    original_owner = live.owner_id
    live.owner_id = "other"
    assert client.get(f"/api/v1/integrations/behavior/v2/simulations/{sid}").status_code == 404
    live.owner_id = original_owner
    denied = command(
        client,
        sid,
        "override_agent",
        agent_id=a.summary.id,
        metrics={},
        goal=None,
        memory_text=None,
        intent=make_intent("rest").model_dump(),
    )
    assert denied.status_code == 409
    # Legacy parsing supplies deterministic defaults without startup actions/events.
    raw = state.model_dump()
    raw.pop("behavior")
    for c in raw["citizens"].values():
        c.pop("condition")
    legacy = State.model_validate(raw)
    assert legacy.behavior.version is None and not legacy.behavior.events
    assert all(c.condition.mental == 70 for c in legacy.citizens.values())


@pytest.mark.parametrize("meter", ["happiness", "safety", "trust", "resources", "stress"])
def test_ab20_exact_neutral_band_and_independent_directions(meter):
    neutral = dict(happiness=50, safety=50, trust=50, resources=50, stress=40)
    assert all(not v for v in coupling(neutral, 10).values())
    low = neutral | {meter: 0}
    high = neutral | {meter: 100}
    a, b = coupling(low, 10), coupling(high, 10)
    for output in ("mental", "social", "energy"):
        da, db = sum(a[output].values()), sum(b[output].values())
        assert da >= db if meter == "stress" else da <= db
    if meter == "stress":
        assert a == coupling(neutral, 10)
        assert b["mental"]["stress"] == -0.55
        assert b["social"]["stress"] == -0.20
        assert b["energy"]["stress"] == -0.30
    for output, parts in coupling(high, 20).items():
        assert sum(parts.values()) == pytest.approx(sum(b[output].values()) * 2)


def test_ab19_ab21_ab22_once_per_tick_canonical_inputs_rest_and_no_free_nutrition(client):
    state, (a, b) = world(client)
    a.needs.health = 50  # canonical Safety = 50
    a.inventory.food = a.inventory.water = a.inventory.supplies = 2  # Resources = 50
    for tie in a.relationships.values():
        tie.trust = 50
    a.summary.metrics.happiness = 50
    a.summary.metrics.stress = 100
    update_metrics(state)
    expected = coupling(a.summary.metrics, state.simulation.config.calendar_seconds_per_tick / 60)
    before = a.condition.mental
    background(state, a)
    assert a.condition.mental - before == pytest.approx(sum(expected["mental"].values()))
    saved = a.model_dump()
    background(state, a)
    update_metrics(state)
    assert a.model_dump() == saved
    # Directed partner trust differs even when the displayed mean is unchanged.
    a.relationships[b.summary.id].trust = 100
    trusted = social_multiplier(a, b)
    a.relationships[b.summary.id].trust = 0
    assert social_multiplier(a, b) < trusted
    a.needs.hunger = 100
    a.inventory.food = a.inventory.water = 0
    a.inventory.supplies = 100
    update_metrics(state)
    assert a.summary.metrics.resources == 100
    assert rest_multiplier(a) <= 1
    evaluate(state, a)
    assert not living(a)


def test_ab22_clamped_component_reasons_sum_exactly_and_snapshot_does_not_advance(client):
    state, (a, _) = world(client)
    a.condition.mental = 99.99
    update_metrics(state)
    before = a.condition.mental
    background(state, a)
    reasons = [i.delta for i in a.condition.impacts if i.meter == "mental"]
    assert sum(reasons) == pytest.approx(a.condition.mental - before)
    value = state.model_dump()
    for _ in range(4):
        snapshot(state)
    assert state.model_dump() == value


def test_ab23_record_seeded_long_run_curves(client, tmp_path):
    state, (a, b) = world(client)
    state.simulation.config.max_ticks = 1000
    curves = {}
    setups = {
        "neutral": (50, 50, 50, 50, 40),
        "deprived": (0, 0, 0, 0, 40),
        "stressed": (50, 50, 50, 50, 100),
        "recovering": (100, 100, 100, 100, 0),
    }
    for label, values in setups.items():
        clone = state.model_copy(deep=True)
        person = clone.citizens[a.summary.id]
        person.condition.mental = 40
        metrics = dict(zip(("happiness", "safety", "trust", "resources", "stress"), values))
        points = []
        for n in range(300):
            clone.simulation.tick = n
            person.summary.metrics = person.summary.metrics.model_validate(metrics)
            background(clone, person)
            points.append([person.condition.mental, 100 - person.needs.social, 100 - person.needs.fatigue])
        assert all(0 <= v <= 100 for point in points for v in point)
        curves[label] = points
    assert curves["neutral"][-1][0] == 40
    assert curves["recovering"][-1][0] > 40
    assert curves["stressed"][-1][0] == pytest.approx(7)
    assert curves["deprived"][-1][0] == 0
    # An actual supported routine can recover independently of the synthetic curves.
    a.needs.fatigue = 75
    a.condition.mental = 30
    a.summary.metrics.stress = 50
    for _ in range(10):
        tick(state, {a.summary.id: (make_intent("rest"), None), b.summary.id: (make_intent("idle"), None)})
    assert a.condition.mental > 30 and a.needs.fatigue < 75
    artifact = {"seed": 42, "rule_version": VERSION, "rules": RULES, "curves": curves}
    (tmp_path / "balance.json").write_text(json.dumps(artifact))
    # Keep a reproducible export in the ignored build artifacts directory.
    output = Path(__file__).parents[1] / "artifacts" / "behavior-balance.json"
    output.write_text(json.dumps(artifact, indent=2) + "\n")


def test_ab23_three_hundred_real_ticks_supported_recovery_and_conservation(client):
    state, (a, b) = world(client)
    state.simulation.config.max_ticks = 1000
    for c in (a, b):
        c.inventory.food = c.inventory.water = c.inventory.supplies = 100
        c.condition.mental = 30
        c.needs.fatigue = 75
        c.summary.metrics.stress = 50
    initial = sum(totals(state).values())
    curves = []
    for _ in range(300):
        proposals = {}
        for actor, partner in ((a, b), (b, a)):
            intent = (
                make_intent("consume", kind="food", amount=1)
                if actor.needs.hunger >= 45
                else make_intent("rest")
                if actor.needs.fatigue >= 40
                else make_intent("talk", target=partner.summary.id)
            )
            proposals[actor.summary.id] = (intent, None)
        tick(state, proposals)
        curves.append([a.condition.mental, 100 - a.needs.fatigue, 100 - a.needs.social, a.needs.health])
        assert living(a) and living(b)
    assert curves[-1][0] > curves[0][0]
    assert curves[-1][1] > 50
    assert curves[-1][2] > curves[0][2] - 30  # Better than ten hours of uninterrupted isolation.
    assert initial - sum(totals(state).values()) == pytest.approx(state.counters["resources_consumed"])
    output = Path(__file__).parents[1] / "artifacts" / "behavior-engine-balance.json"
    output.write_text(json.dumps({"seed": 42, "rule_version": VERSION, "curves": curves}, indent=2) + "\n")


def test_ab15_behavior_schema_matches_versioned_contract(client):
    from app.behavior.api import BehaviorResponse

    expected = Path(__file__).parents[2] / "contracts" / "v2" / "behavior.schema.json"
    assert BehaviorResponse.model_json_schema() == json.loads(expected.read_text())
    child = client.get("/api/v1/integrations/openapi.json").json()
    assert "/behavior/v2/simulations/{sid}" in child["paths"]
    assert "BehaviorResponse" in child["components"]["schemas"]


def test_ab10_reserved_bed_cannot_be_taken_by_ordinary_visitor_and_blocked_route(client):
    state, (a, b, patient) = world(client, 3)
    patient.needs.fatigue = 100
    evaluate(state, patient)
    hospital = next(h for h in state.map.buildings if h.kind == "hospital")
    hospital.capacity = 1
    a.summary.position = Vec2(x=35, y=33)
    assert act(state, a, "rescue", patient.summary.id).accepted
    result = apply_intent(state, b, make_intent("move", target=hospital.id, destination=hospital.entrance))
    assert result.outcome == "rejected" and result.rejection_code == "CAPACITY"
    # Independent world: no reachable hospital cannot produce a successful rescue.
    second, (helper, victim) = world(client)
    victim.needs.fatigue = 100
    evaluate(second, victim)
    for cell in second.map.cells:
        cell.walkable = False
    assert not act(second, helper, "rescue", victim.summary.id).accepted
    assert victim.condition.helper_id is None and not helper.condition.patient_id


def test_ab18_episode_never_claims_recovery_on_timeout_with_high_stress(client):
    state, (a, _) = world(client)
    a.summary.metrics.stress = 90
    evaluate_crisis(state, a, random.Random(42))
    original = a.condition.episode.id
    for i in range(RULES["episode_ticks"] + 10):
        state.simulation.tick += 1
        evaluate_crisis(state, a, random.Random(i))
    assert a.condition.episode.id == original
    assert a.condition.episode.end_tick is None
    assert a.condition.episode.stable_ticks == 0


@pytest.mark.parametrize("stage", ["carried", "hospital"])
def test_ab14_real_restart_branch_and_source_deletion_preserve_behavior(tmp_path, stage):
    from fastapi.testclient import TestClient

    from app.infrastructure.config import AppConfig
    from app.main import create_app

    config = AppConfig(data_dir=tmp_path / "store")
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        state, (a, b, distressed) = world(client, 3)
        hospital = next(h for h in state.map.buildings if h.kind == "hospital")
        a.summary.position = hospital.entrance.model_copy()
        b.summary.position = Vec2(x=a.summary.position.x + 1.1, y=a.summary.position.y)
        b.needs.fatigue = 100
        b.needs.health = 30
        evaluate(state, b)
        assert act(state, a, "rescue", b.summary.id).accepted
        advance_movement(state, a)
        synchronize_transport(state, a)
        assert b.condition.care == "carried"
        if stage == "hospital":
            for _ in range(5):
                state.simulation.tick += 1
                advance_movement(state, a)
                synchronize_transport(state, a)
                if a.inside_building_id == hospital.id and not a.summary.path:
                    assert act(state, a, "admit", b.summary.id).accepted
                    break
            assert b.condition.care == "hospital"
        distressed.condition.mental = 10
        evaluate(state, distressed)
        assert distressed.condition.episode
        sid = state.simulation.id
        service = client.app.state.service
        service.heads[sid] = state
        assert command(client, sid, "save", reason="manual", label="Behavior checkpoint").status_code == 200
        saved = service.heads[sid]
        checkpoint = saved.behavior.model_dump()
        conditions = {aid: c.condition.model_dump() for aid, c in saved.citizens.items()}
        result = write(
            client, f"/simulations/{sid}/branches", dict(name="Behavior branch", source=dict(kind="whole"))
        )
        assert result.status_code == 201, result.text
        bid = result.json()["data"]["simulation"]["id"]
        branch = service.heads[bid]
        assert branch.behavior.model_dump() == checkpoint
        assert {aid: c.condition.model_dump() for aid, c in branch.citizens.items()} == conditions
        # A new branch must own independent mutable condition/claim/RNG structures.
        copy = branch.model_copy(deep=True)
        copy.citizens[a.summary.id].condition.mental = 0
        assert saved.citizens[a.summary.id].condition.mental == 70
        assert command(client, sid, "archive").status_code == 200
        assert (
            write(
                client, f"/simulations/{sid}", {"confirmation_name": saved.simulation.name}, method="DELETE"
            ).status_code
            == 200
        )
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        result = client.get(f"/api/v1/integrations/behavior/v2/simulations/{bid}")
        assert result.status_code == 200, result.text
        loaded = client.app.state.service.heads[bid]
        assert loaded.behavior.model_dump() == checkpoint
        assert {aid: c.condition.model_dump() for aid, c in loaded.citizens.items()} == conditions
        before = loaded.model_dump()
        for _ in range(3):
            assert (
                client.get(f"/api/v1/integrations/behavior/v2/simulations/{bid}/export").json()["data"]
                == result.json()["data"]
            )
        assert loaded.model_dump() == before


def test_ab19_acute_stress_threshold_enters_before_calming_and_mental_jitter_preserves_provider(client):
    from app.infrastructure.gemini import relevance

    state, (a, b) = world(client)
    a.summary.metrics.stress = 80
    before = relevance(state, b)
    b.condition.mental += 0.1
    assert relevance(state, b) == before
    b.condition.mental = 10
    assert relevance(state, b) != before
    a.condition.mental = b.condition.mental = 70
    # Ordinary help lowers stress but cannot erase the fact that the independent
    # high-stress trigger was met before the treatment action.
    result = apply_intent(state, b, make_intent("help", target=a.summary.id))
    assert result.outcome == "accepted"
    assert a.condition.episode and "high_stress" in a.condition.episode.causes
    assert a.summary.metrics.stress == 78


def test_ab12_poor_grievance_needs_observed_unfair_allocation(client):
    state, (rich, poor) = world(client)
    rich.inventory.food = rich.inventory.water = rich.inventory.supplies = 20
    poor.inventory.food = poor.inventory.water = poor.inventory.supplies = 0
    source = next(r for r in state.map.resources if r.kind == "food")
    rich.summary.position = source.position.model_copy()
    poor.summary.position = Vec2(x=source.position.x + 1.1, y=source.position.y)
    encounter(state, poor, perception(state, poor))
    assert not state.behavior.counters.get("class_grievance")
    assert (
        apply_intent(state, rich, make_intent("gather", target=source.id, kind="food", amount=2)).outcome
        == "accepted"
    )
    encounter(state, poor, perception(state, poor))
    assert state.behavior.counters["class_grievance"] == 1
    signal = next(e for e in state.behavior.events if e.kind == "class_signal")
    assert signal.evidence.decision_ids


def test_ab10_cooperative_team_has_one_carrier_and_one_conserved_stabilization(client):
    from app.behavior.care import rescue_choice

    state, (carrier, assistant, patient) = world(client, 3)
    carrier.summary.position = Vec2(x=35, y=33)
    patient.needs.fatigue = 100
    patient.needs.health = 40
    evaluate(state, patient)
    assert act(state, carrier, "rescue", patient.summary.id).accepted
    before = totals(state)
    intent, handled = rescue_choice(state, assistant, perception(state, assistant))
    assert handled and intent.action == "help"
    assert apply_intent(state, assistant, intent).outcome == "accepted"
    assert assistant.condition.patient_id is None
    assert patient.condition.helper_id == carrier.summary.id
    assert patient.needs.health == 45
    assert before["supplies"] - totals(state)["supplies"] == 1
    assert state.counters["cooperation_count"] == 1
    _, handled = rescue_choice(state, assistant, perception(state, assistant))
    assert not handled


@pytest.mark.parametrize("key", ["happiness", "safety", "trust", "resources", "stress"])
def test_ab20_canonical_derived_inputs_match_exact_physical_pressure(client, key):
    original, (citizen, _) = world(client)
    results = []
    for value in (20, 80):
        state = original.model_copy(deep=True)
        c = state.citizens[citizen.summary.id]
        c.needs.health = 50
        c.inventory.food = c.inventory.water = c.inventory.supplies = 2
        for tie in c.relationships.values():
            tie.trust = 50
        c.summary.metrics.happiness = 50
        c.summary.metrics.stress = 40
        if key == "safety":
            c.needs.health = value
        elif key == "trust":
            for tie in c.relationships.values():
                tie.trust = value
        elif key == "resources":
            for kind in ("food", "water", "supplies"):
                setattr(c.inventory, kind, c.target_inventory_units * value / 300)
        else:
            setattr(c.summary.metrics, key, value)
        update_metrics(state)
        assert getattr(c.summary.metrics, key) == pytest.approx(value)
        expected = coupling(c.summary.metrics, state.simulation.config.calendar_seconds_per_tick / 60)
        before = (c.condition.mental, 100 - c.needs.social, 100 - c.needs.fatigue)
        background(state, c)
        after = (c.condition.mental, 100 - c.needs.social, 100 - c.needs.fatigue)
        assert tuple(b - a for a, b in zip(before, after)) == pytest.approx(
            tuple(sum(expected[k].values()) for k in ("mental", "social", "energy"))
        )
        results.append(after)
    assert all(a >= b if key == "stress" else a <= b for a, b in zip(*results))


def test_ab22_different_real_tick_duration_and_reads_do_not_advance_pressure(client):
    state, (a, b) = world(client)
    state.simulation.config.tick_seconds = 20
    a.needs.health = 50
    a.inventory.food = a.inventory.water = a.inventory.supplies = 2
    for tie in a.relationships.values():
        tie.trust = 50
    a.summary.metrics.happiness = 50
    a.summary.metrics.stress = 70
    before = (a.condition.mental, a.needs.fatigue, a.needs.social)
    idle(state)
    assert a.condition.mental == pytest.approx(before[0] - 0.055)
    assert a.needs.fatigue == pytest.approx(before[1] + 4 / 30 + 0.03)
    assert a.needs.social == pytest.approx(before[2] + 3 / 30 + 0.02)
    state_before = a.model_dump()
    update_metrics(state)
    background(state, a)
    assert a.model_dump() == state_before


def test_ab11_generic_death_discussion_does_not_reveal_unwitnessed_remote_death(client):
    from app.simulation.agents import remember

    state, (speaker, deceased, listener) = world(client, 3)
    remember(
        state,
        speaker,
        f"{deceased.summary.name} said: I do not fear death.",
        source="heard",
        subjects=[deceased.summary.id],
    )
    deceased.summary.position = Vec2(x=110, y=110)
    deceased.needs.health = 0
    evaluate(state, deceased)
    listener.summary.position = Vec2(x=35, y=33)
    before = listener.condition.mental
    assert apply_intent(state, speaker, make_intent("talk", target=listener.summary.id)).outcome == "accepted"
    assert "has died" not in state.dialogue[-1].text
    assert listener.condition.mental == before


def test_ab15_behavior_extension_requires_authenticated_session_and_allowed_origin(tmp_path):
    from fastapi.testclient import TestClient

    from app.infrastructure.config import AppConfig
    from app.main import create_app

    config = AppConfig(
        data_dir=tmp_path / "auth",
        auth_mode="session",
        session_secret="x" * 40,
        demo_passphrase="test passphrase",
        allowed_origins=("https://city.example",),
    )
    with TestClient(create_app(config), base_url="https://city.example") as client:
        path = "/api/v1/integrations/behavior/v2/simulations/unknown"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert (
            client.post(
                path, json={}, headers={"Idempotency-Key": "00000000-0000-4000-8000-000000000001"}
            ).status_code
            == 403
        )


def test_persisted_personal_collapse_lesson_changes_later_choice_not_physical_boundary(client):
    from app.behavior.learning import threshold
    from app.simulation.building_visits import interior_slot
    from app.simulation.game_master import rule_intent

    state, (survivor, other) = world(client)
    baseline = survivor.model_copy(deep=True)
    survivor.needs.fatigue = 100
    evaluate(state, survivor)
    survivor.needs.fatigue = 80
    evaluate(state, survivor)
    assert conscious(survivor) and threshold(survivor) == 40
    assert len(survivor.rest_lessons) == 1
    assert survivor.rest_lessons[0].before == 35
    assert survivor.rest_lessons[0].supporting_source_ids
    evaluate(state, survivor)
    assert len(survivor.rest_lessons) == 1
    workplace = next(b for b in state.map.buildings if b.kind == "work")
    survivor.summary.position = interior_slot(state, survivor, workplace)
    survivor.inside_building_id = workplace.id
    survivor.visit_until_tick = 99
    survivor.routine_until = state.simulation.calendar_time_seconds + 3600
    survivor.routine_target_id = workplace.id
    survivor.summary.routine_state = "visiting"
    survivor.inventory.supplies = 2
    survivor.needs.fatigue = 62  # Energy 38: learned threshold 40 versus baseline 35.
    baseline.summary.position = survivor.summary.position.model_copy()
    baseline.inside_building_id = workplace.id
    baseline.visit_until_tick = 99
    baseline.routine_until = state.simulation.calendar_time_seconds + 3600
    baseline.routine_target_id = workplace.id
    baseline.summary.routine_state = "visiting"
    baseline.inventory.supplies = 2
    baseline.needs.fatigue = 62
    context = {"nearby_ids": [], "facts": [], "memories": [], "relationships": [], "messages": []}
    original = rule_intent(state, baseline, context)
    learned = rule_intent(state, survivor, context)
    assert original.action == "work" and learned.action == "move"
    assert learned.motivation.startswith("Learned rest threshold:")
    assert apply_intent(state, survivor, learned, context=context).outcome == "accepted"
    assert state.behavior.counters["lesson_applied"] == 1
    restored = State.model_validate_json(state.model_dump_json())
    assert restored.citizens[survivor.summary.id].rest_lessons == survivor.rest_lessons
    assert snapshot(restored).learned_rules[survivor.summary.id][0].after == 40
    assert other.rest_lessons == []


def test_ab09_indoor_neighbor_pickup_uses_floor_then_real_doorway(client):
    from app.simulation.building_visits import interior_slot

    state, (helper, patient) = world(client)
    home = next(b for b in state.map.buildings if b.kind == "home" and b.capacity >= 2)
    helper.summary.position = interior_slot(state, helper, home)
    helper.inside_building_id = home.id
    patient.summary.position = interior_slot(state, patient, home)
    patient.inside_building_id = home.id
    assert helper.summary.position and patient.summary.position
    assert distance(helper.summary.position, patient.summary.position) <= 3
    patient.needs.fatigue = 100
    patient.needs.health = 40
    evaluate(state, patient)
    origin = patient.summary.position.model_copy()
    assert act(state, helper, "rescue", patient.summary.id).accepted
    assert patient.summary.position == origin  # Claiming does not teleport a patient.
    advance_movement(state, helper)
    synchronize_transport(state, helper)
    assert patient.condition.care == "carried"
    assert patient.summary.position == origin
    assert helper.leaving_building_id == home.id
    assert helper.summary.path  # The hospital trip still must traverse the door.
