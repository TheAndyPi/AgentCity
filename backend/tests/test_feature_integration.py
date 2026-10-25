"""Regression boundaries where the separately implemented feature branches meet."""

from types import SimpleNamespace

import pytest
from conftest import create_city

from app.behavior.care import treatment
from app.behavior.vitals import conscious
from app.scenario_engine import responses, runtime
from app.scenario_engine.world import enable
from app.simulation.engine import tick
from app.simulation.game_master import make_intent


def world(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    citizen = next(iter(state.citizens.values()))
    state.citizens = {citizen.summary.id: citizen}
    enable(state)
    return state, citizen


def no_illness(monkeypatch):
    monkeypatch.setattr(runtime, "wellbeing", lambda *args: None)
    monkeypatch.setattr(responses, "review", lambda *args: None)


def test_city_systems_do_not_heal_a_terminal_hospital_occupant(client):
    state, citizen = world(client)
    hospital = next(b for b in state.map.buildings if b.kind == "hospital")
    citizen.inside_building_id = hospital.id
    citizen.needs.health = 0
    runtime.after_tick(state)
    assert citizen.condition.life == "dead"
    assert citizen.needs.health == 0
    assert state.systems.counters.get("hospital_care", 0) == 0


def test_unconscious_citizens_do_not_shop_review_or_hear_broadcasts(client, monkeypatch):
    state, citizen = world(client)
    shop = next(b for b in state.map.buildings if b.kind == "shop")
    citizen.inside_building_id = shop.id
    citizen.condition.life = "unconscious"
    citizen.needs.fatigue = 100
    calls = []
    monkeypatch.setattr(runtime, "shop", lambda *args: calls.append("shop"))
    monkeypatch.setattr(responses, "review", lambda *args: calls.append("review"))
    monkeypatch.setattr(runtime, "wellbeing", lambda *args: None)
    runtime.after_tick(state)
    assert not calls
    before = len(citizen.memories), len(state.systems.traces)
    # Ineligible listeners return before reading or interpreting any message.
    responses.receive_information(state, citizen, SimpleNamespace(), "event_unheard")
    responses.evaluate_norm(state, citizen, "unsupported", 1)
    assert not responses.consider_joining(state, citizen, None, None, founding=True)
    assert (len(citizen.memories), len(state.systems.traces)) == before


def test_scenario_illness_commits_death_at_the_damage_boundary(client, monkeypatch):
    state, citizen = world(client)
    citizen.needs.health = 5
    monkeypatch.setattr(runtime, "unit", lambda *args: 0)
    agent = state.systems.agents[citizen.summary.id]
    runtime.wellbeing(state, citizen, agent, None)
    assert citizen.needs.health == 0
    assert not conscious(citizen)
    assert citizen.condition.life == "dead"
    deaths = [event for event in state.behavior.events if event.kind == "death"]
    assert len(deaths) == 1
    runtime.after_tick(state)
    assert len([event for event in state.behavior.events if event.kind == "death"]) == 1


def test_admitted_patient_has_one_stock_backed_treatment_phase(client, monkeypatch):
    state, citizen = world(client)
    no_illness(monkeypatch)
    building = next(b for b in state.map.buildings if b.kind == "hospital")
    hospital = state.behavior.hospitals[building.id]
    citizen.needs.health = 50
    citizen.inside_building_id = building.id
    citizen.condition.care = "hospital"
    citizen.condition.hospital_id = building.id
    hospital.patients.append(citizen.summary.id)
    hospital.inventory.supplies = 1
    hospital.inventory.food = hospital.inventory.water = 0
    before = state.counters["resources_consumed"]
    runtime.after_tick(state)
    assert citizen.needs.health == 50
    assert hospital.inventory.supplies == 1
    treatment(state)
    assert citizen.needs.health == pytest.approx(53)
    assert hospital.inventory.supplies == pytest.approx(0.75)
    assert state.counters["resources_consumed"] - before == pytest.approx(0.25)
    assert state.systems.counters["hospital_care"] == 1


@pytest.mark.parametrize("supplies, expected_health, remaining", [(1, 50.35, 0.75), (0.1, 50, 0.1)])
def test_walk_in_care_requires_real_hospital_stock(client, monkeypatch, supplies, expected_health, remaining):
    state, citizen = world(client)
    no_illness(monkeypatch)
    building = next(b for b in state.map.buildings if b.kind == "hospital")
    citizen.inside_building_id = building.id
    citizen.needs.health = 50
    hospital = state.behavior.hospitals[building.id]
    hospital.inventory.supplies = supplies
    runtime.after_tick(state)
    assert citizen.needs.health == pytest.approx(expected_health)
    assert hospital.inventory.supplies == pytest.approx(remaining)


def test_combined_tick_applies_baseline_hunger_once(client, monkeypatch):
    state, citizen = world(client)
    no_illness(monkeypatch)
    citizen.needs.hunger = 20
    citizen.inside_building_id = None
    tick(state, {citizen.summary.id: (make_intent("idle"), None)})
    assert citizen.needs.hunger == pytest.approx(20.6)


def test_both_extensions_share_the_authenticated_integration_mount(client):
    schema = client.get("/api/v1/integrations/openapi.json").json()
    paths = schema["paths"]
    assert any(path.startswith("/scenarios/") for path in paths)
    assert any("behavior" in path for path in paths)
    assert not any("integrations" in path for path in client.get("/openapi.json").json()["paths"])
