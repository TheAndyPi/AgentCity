"""A ten-second legacy interval and ten one-second intervals share the same rates."""

import pytest
from conftest import create_city

from app.behavior.vitals import rest
from app.scenario_engine import runtime, world
from app.scenario_engine.registry import REGIONS
from app.service import staging_copy


def paired_states(client):
    sid = create_city(client)["id"]
    legacy = staging_copy(client.app.state.service.heads[sid])
    aid = next(iter(legacy.citizens))
    legacy.citizens = {aid: legacy.citizens[aid]}
    # HTTP copies are allowed to edit immutable config/profile records. Avoid
    # changing the fixture's published configuration through the staging fork.
    legacy.simulation.config = legacy.simulation.config.model_copy(deep=True)
    legacy.simulation.config.tick_seconds = 10
    legacy.citizens[aid].profile = legacy.citizens[aid].profile.model_copy(deep=True)
    modern = legacy.model_copy(deep=True)
    modern.simulation.config.tick_seconds = 1
    return legacy, modern, aid


def test_rest_energy_and_mental_recovery_preserve_simulated_rate(client):
    legacy, modern, aid = paired_states(client)
    for state in (legacy, modern):
        state.citizens[aid].needs.fatigue = 60
        state.citizens[aid].condition.mental = 50
    rest(legacy, legacy.citizens[aid])
    for _ in range(10):
        rest(modern, modern.citizens[aid])
    assert modern.citizens[aid].needs.fatigue == pytest.approx(legacy.citizens[aid].needs.fatigue)
    assert modern.citizens[aid].condition.mental == pytest.approx(legacy.citizens[aid].condition.mental)


def test_rent_shop_production_city_costs_and_financial_pressure_preserve_rate(client, monkeypatch):
    legacy, modern, aid = paired_states(client)
    monkeypatch.setattr(runtime.responses, "review", lambda *args: None)
    monkeypatch.setattr(runtime, "wellbeing", lambda *args: None)
    for state in (legacy, modern):
        world.enable(state)
        agent = state.systems.agents[aid]
        agent.wallet = 1
        agent.renter = True
        state.systems.policy.public_services.hospital_funding = 2
    runtime.after_tick(legacy)
    for _ in range(10):
        modern.simulation.tick += 1
        runtime.after_tick(modern)
    assert modern.systems.agents[aid].wallet == pytest.approx(legacy.systems.agents[aid].wallet, abs=0.0006)
    assert modern.systems.treasury == pytest.approx(legacy.systems.treasury, abs=0.0006)
    assert modern.systems.shop_stock == pytest.approx(legacy.systems.shop_stock)
    assert modern.systems.counters["rent_paid"] == pytest.approx(legacy.systems.counters["rent_paid"])
    assert modern.systems.counters["shop_production"] == pytest.approx(
        legacy.systems.counters["shop_production"]
    )
    assert modern.citizens[aid].summary.metrics.stress == pytest.approx(
        legacy.citizens[aid].summary.metrics.stress
    )
    assert modern.citizens[aid].summary.metrics.happiness == pytest.approx(
        legacy.citizens[aid].summary.metrics.happiness
    )


def test_ongoing_illness_age_and_environmental_pressure_preserve_rate(client, monkeypatch):
    legacy, modern, aid = paired_states(client)
    monkeypatch.setattr(runtime, "unit", lambda *args: 1)
    region = next(
        region
        for region, (x0, y0, x1, y1) in REGIONS.items()
        if x0 <= legacy.citizens[aid].summary.position.x <= x1
        and y0 <= legacy.citizens[aid].summary.position.y <= y1
    )
    for state in (legacy, modern):
        world.enable(state)
        state.citizens[aid].profile.age = 70
        state.citizens[aid].needs.health = 70
        state.systems.agents[aid].conditions["illness"] = 0
        state.systems.conditions = [
            dict(op_id="heat", condition="heat", region=region, intensity=50, event_id="event_heat")
        ]
    legacy.simulation.tick = 1
    runtime.wellbeing(legacy, legacy.citizens[aid], legacy.systems.agents[aid], None)
    for tick in range(1, 11):
        modern.simulation.tick = tick
        runtime.wellbeing(modern, modern.citizens[aid], modern.systems.agents[aid], None)
    assert modern.citizens[aid].needs.health == pytest.approx(legacy.citizens[aid].needs.health)
    assert modern.citizens[aid].summary.metrics.stress == pytest.approx(
        legacy.citizens[aid].summary.metrics.stress
    )


def test_illness_probability_preserves_survival_probability_over_equal_simulated_time(client):
    legacy, modern, _ = paired_states(client)
    for chance in (0.003, 0.007, 0.02):
        long_probability = runtime.probability_for_tick(legacy, chance)
        short_probability = runtime.probability_for_tick(modern, chance)
        assert 1 - (1 - short_probability) ** 10 == pytest.approx(long_probability)
