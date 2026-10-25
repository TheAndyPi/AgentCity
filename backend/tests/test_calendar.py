"""Calendar, routine and conversation acceptance tests against the real engine."""

import math

import pytest
from conftest import command, create_city

from app import contracts as c
from app.api.views import frame
from app.behavior.vitals import rest
from app.infrastructure.gemini import context_for, relevance
from app.scenario_engine.mutations import apply_set_curfew, revert_set_curfew
from app.scenario_engine.registry import SetCurfew
from app.simulation import calendar
from app.simulation.building_visits import interior_slot
from app.simulation.daily import commitment_intent, curfew_window, decay, home_building, model_available
from app.simulation.engine import tick
from app.simulation.game_master import advance_movement, apply_intent, make_intent
from app.simulation.interactions import conversation_benefits, interrupt_conversations
from app.simulation.navigation import distance
from app.simulation.state import State


def city(client, population=10):
    sid = create_city(client, population=population)["id"]
    return client.app.state.service.heads[sid].model_copy(deep=True)


def pair(state):
    a, b = list(state.citizens.values())[:2]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
    a.summary.position, b.summary.position = c.Vec2(x=33, y=33), c.Vec2(x=35, y=33)
    for citizen in (a, b):
        citizen.needs.hunger = citizen.needs.fatigue = 0
        citizen.needs.social = 50
        citizen.summary.path = []
    return a, b


@pytest.mark.parametrize("tick_seconds,calendar_seconds", [(1, 12), (10, 120)])
def test_calendar_defaults_preserve_real_time_pace(client, tick_seconds, calendar_seconds):
    simulation = create_city(client, tick_seconds=tick_seconds)
    assert simulation["config"]["calendar_seconds_per_tick"] == calendar_seconds
    assert calendar_seconds * (20 / tick_seconds) == 240
    explicit = c.ConfigRequest(
        name="Explicit clock", seed=42, tick_seconds=tick_seconds, calendar_seconds_per_tick=600
    )
    assert explicit.calendar_seconds_per_tick == 600


def test_calendar_advances_thirty_minutes_in_fifteen_physical_ticks(client):
    state = city(client)
    original = state.simulation.calendar_time_seconds
    for _ in range(15):
        tick(state)
    assert state.simulation.calendar_time_seconds == original + 1800
    assert state.simulation.sim_time_seconds == 150
    assert state.calendar_activated_tick == 1
    assert sum(e.kind == "calendar_rules_activated" for e in state.behavior.events) == 1
    assert 15 / 2 == 7.5


def test_calendar_rate_never_changes_physical_walking(client):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    citizen.summary.position = c.Vec2(x=33, y=33)
    citizen.summary.path = [c.Vec2(x=53, y=33)]
    faster = state.model_copy(deep=True)
    faster.simulation.config.calendar_seconds_per_tick = 600
    advance_movement(state, citizen)
    advance_movement(faster, faster.citizens[citizen.summary.id])
    assert citizen.summary.position == faster.citizens[citizen.summary.id].summary.position
    assert distance(c.Vec2(x=33, y=33), citizen.summary.position) <= citizen.summary.movement_speed_mps * 10


def test_conversation_listens_between_turns_and_lasts_an_accepted_hour(client):
    state = city(client)
    a, b = pair(state)
    assert apply_intent(state, a, make_intent("talk", target=b.summary.id)).outcome == "accepted"
    tick(state)
    session = next(iter(state.interactions.values()))
    assert session.status == "accepted"
    assert len(state.dialogue) == 2
    assert not model_available(state, a)
    premature = apply_intent(state, a, make_intent("talk", target=b.summary.id), "gemini")
    assert premature.rejection_code == "AWAITING_TURN"
    for _ in range(9):
        tick(state)
        assert len(state.dialogue) == 2
        assert session.status == "accepted"
    restored = State.model_validate_json(state.model_dump_json())
    for simulation in (state, restored):
        for _ in range(21):
            tick(simulation)
        ended = simulation.interactions[session.id]
        assert ended.status == "ended" and ended.end_reason == "completed"
        assert simulation.simulation.calendar_time_seconds - ended.accepted_calendar_seconds == 3600
        assert len(simulation.dialogue) == 5
        assert simulation.dialogue[-1].end_conversation
        assert all(x.speaker_id != y.speaker_id for x, y in zip(simulation.dialogue, simulation.dialogue[1:]))
    assert state.model_dump() == restored.model_dump()


@pytest.mark.parametrize("reason", ["danger", "urgent_needs", "medical_care", "curfew"])
def test_conversations_release_both_participants_on_interrupt(client, reason):
    state = city(client)
    a, b = pair(state)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    tick(state)
    session = next(iter(state.interactions.values()))
    if reason == "danger":
        state.policies.evacuation_order = True
    elif reason == "urgent_needs":
        a.needs.hunger = 81
    elif reason == "medical_care":
        a.condition.care = "claimed"
    else:
        state.simulation.calendar_time_seconds = 22 * 3600
        state.curfew_revision = 1
        state.curfew_controls["test"] = c.CurfewPolicy(enabled=True, informed_agent_ids=[a.summary.id])
        a.curfew_choice_key = "1:0"
        a.curfew_complies = True
    interrupt_conversations(state)
    assert session.status == "ended" and session.end_reason == reason
    assert all(not citizen.summary.path and citizen.summary.routine_state != "talking" for citizen in (a, b))


def test_conversation_reward_depends_on_contact_time_and_is_not_duplicated(client):
    state = city(client)
    a, b = pair(state)
    apply_intent(state, a, make_intent("talk", target=b.summary.id))
    tick(state)
    before = a.needs.social
    state.simulation.calendar_time_seconds += 1200
    conversation_benefits(state)
    assert a.needs.social < before
    after = a.model_dump()
    conversation_benefits(state)
    assert a.model_dump() == after


def test_night_sleep_is_sustained_until_six_and_distinct_from_unconsciousness(client):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    home = home_building(state, citizen)
    citizen.summary.position = interior_slot(state, citizen, home)
    citizen.inside_building_id = home.id
    citizen.needs.hunger = 0
    citizen.needs.fatigue = 0
    state.simulation.calendar_time_seconds = 23 * 3600
    intent, handled = commitment_intent(state, citizen)
    assert handled and intent.action == "rest"
    apply_intent(state, citizen, intent)
    assert citizen.summary.routine_state == "sleeping"
    assert citizen.condition.life == "alive"
    assert not model_available(state, citizen)
    stale = apply_intent(state, citizen, make_intent("move", destination=c.Vec2(x=33, y=33)), "gemini")
    assert stale.rejection_code == "ACTIVITY_COMMITMENT"
    state.simulation.calendar_time_seconds = 86400 + 6 * 3600
    _, handled = commitment_intent(state, citizen)
    assert not handled and citizen.summary.routine_state == "free"


def test_destroyed_or_full_home_uses_shelter_and_missing_routes_retry(client, monkeypatch):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    state.simulation.calendar_time_seconds = 23 * 3600
    home = home_building(state, citizen)
    home.functional = False
    intent, handled = commitment_intent(state, citizen)
    assert handled and intent.action == "move"
    shelter = next(b for b in state.map.buildings if b.id == intent.target_id)
    assert shelter.kind == "shelter"
    home.functional = True
    home.capacity = 0
    assert commitment_intent(state, citizen)[0].target_id == shelter.id
    monkeypatch.setattr("app.simulation.daily.trip_route", lambda *args: None)
    intent, handled = commitment_intent(state, citizen)
    assert handled and intent.action == "rest" and "retry" in intent.motivation
    assert citizen.routine_retry_tick == state.simulation.tick + 10
    monkeypatch.setattr("app.simulation.daily.trip_route", lambda *args: pytest.fail("Retried too soon"))
    commitment_intent(state, citizen)


def test_hourly_needs_sleep_recovery_and_meals_are_bounded(client):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    citizen.needs.hunger = 30
    citizen.needs.fatigue = 30
    citizen.needs.social = 30
    before = citizen.needs.model_copy()
    decay(state, citizen)
    assert citizen.needs.hunger - before.hunger == pytest.approx(4 / 30)
    assert citizen.needs.fatigue - before.fatigue == pytest.approx(4 / 30)
    citizen.summary.routine_state = "sleeping"
    citizen.summary.action = "rest"
    before = citizen.needs.model_copy()
    decay(state, citizen)
    assert citizen.needs.hunger - before.hunger == pytest.approx(2 / 30)
    assert citizen.needs.fatigue == before.fatigue
    rest(state, citizen)
    assert citizen.needs.fatigue < before.fatigue
    citizen.summary.routine_state = "free"
    citizen.needs.hunger = 60
    state.simulation.calendar_time_seconds = 13 * 3600
    intent, handled = commitment_intent(state, citizen)
    assert handled and intent.action == "consume" and 0 < intent.parameters.amount <= 3
    apply_intent(state, citizen, intent)
    assert commitment_intent(state, citizen)[1] is False


def test_curfew_announcements_audience_stack_and_reversion(client):
    from app.scenario_engine.validator import validate_plan
    from app.scenario_engine.world import enable

    state = city(client)
    enable(state)
    op = SetCurfew(type="set_curfew")
    undo = apply_set_curfew(state, op, "event1", False, 0)
    assert len(calendar.effective_curfew(state).informed_agent_ids) == 10
    replacement = SetCurfew(type="set_curfew", start_minute=1200)
    second = apply_set_curfew(state, replacement, "event2", False, 0)
    assert calendar.effective_curfew(state).start_minute == 1200
    revert_set_curfew(state, replacement, "event2", second)
    assert calendar.effective_curfew(state).start_minute == 1320
    revert_set_curfew(state, op, "event1", undo)
    assert not calendar.effective_curfew(state).enabled
    raw = dict(
        title="Curfew",
        category="policy",
        description="Night curfew",
        public_description="Night curfew",
        duration="temporary",
        affected_systems=["safety"],
        operations=[dict(type="set_curfew", start_minute=600, end_minute=600)],
        metrics=["policy_compliance"],
    )
    assert validate_plan(state, raw)[1]


def test_curfew_compliance_is_stable_through_midnight_and_emergency_overrides(client):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    state.curfew_revision = 1
    state.curfew_controls["test"] = c.CurfewPolicy(enabled=True, informed_agent_ids=[citizen.summary.id])
    state.simulation.calendar_time_seconds = 22 * 3600
    first = curfew_window(state, citizen)
    choice = citizen.curfew_choice_key, citizen.curfew_complies
    count = len(state.systems.traces)
    state.simulation.calendar_time_seconds = 86400 + 3600
    assert curfew_window(state, citizen) == first
    assert (citizen.curfew_choice_key, citizen.curfew_complies) == choice
    assert len(state.systems.traces) == count
    state.policies.evacuation_order = True
    assert commitment_intent(state, citizen)[1] is False


def test_clock_alone_does_not_invalidate_model_context_but_commitments_do(client):
    state = city(client)
    citizen = next(iter(state.citizens.values()))
    context = context_for(state, citizen)
    before = relevance(state, citizen, context)
    state.simulation.calendar_time_seconds += 120
    assert relevance(state, citizen) == before
    citizen.summary.routine_state = "sleeping"
    citizen.task_generation += 1
    assert relevance(state, citizen) != before


def test_legacy_calendar_falls_back_without_rewriting_history(client):
    state = city(client)
    old = state.model_dump()
    old["simulation"].pop("calendar_time_seconds")
    old["simulation"]["sim_time_seconds"] = 150
    restored = State.model_validate(old)
    assert restored.simulation.calendar_time_seconds == 150
    tick(restored)
    assert restored.simulation.calendar_time_seconds == 270
    assert "calendar_time_seconds" not in old["simulation"]
    assert frame(restored).simulation.calendar_time_seconds == 270
    assert restored.calendar_rules_version == "3.0.0"


def test_pause_step_and_saved_calendar_round_trip(client):
    simulation = create_city(client)
    sid = simulation["id"]
    start = simulation["calendar_time_seconds"]
    command(client, sid, "step", count=2)
    command(client, sid, "save", reason="manual", label="Calendar")
    state = client.app.state.service.heads[sid]
    assert state.simulation.calendar_time_seconds == start + 240
    restored = State.model_validate_json(state.model_dump_json())
    assert restored.simulation.calendar_time_seconds == state.simulation.calendar_time_seconds
    assert restored.model_dump() == state.model_dump()


@pytest.mark.parametrize("population", [10, 30, 100])
def test_three_days_of_safe_supplied_daily_life(client, population):
    state = city(client, population)
    meals = 0
    sleepers = set()
    daytime = set()
    fatigue_at_bed = {}
    recovered = set()
    for citizen in state.citizens.values():
        citizen.inventory.food = citizen.inventory.water = 30
        citizen.inventory.supplies = 12
    for _ in range(2160):
        tick(state)
        hour = calendar.now(state) % calendar.DAY / calendar.HOUR
        for citizen in state.citizens.values():
            aid = citizen.summary.id
            if citizen.summary.routine_state == "sleeping":
                sleepers.add(aid)
                fatigue_at_bed.setdefault(aid, citizen.needs.fatigue)
            if 9 <= hour < 17 and citizen.summary.routine_state != "sleeping":
                daytime.add(aid)
            if aid in fatigue_at_bed and citizen.needs.fatigue < fatigue_at_bed[aid] - 5:
                recovered.add(aid)
        meals += sum(
            d.intent.action == "consume" and d.outcome == "accepted"
            for d in reversed(state.decisions[-population:])
            if d.tick == state.simulation.tick
        )
    assert calendar.now(state) == (3 * 24 + 8) * 3600
    assert all(citizen.condition.life == "alive" for citizen in state.citizens.values())
    assert len(sleepers) >= math.ceil(population * 0.9)
    assert len(daytime) == population
    assert len(recovered) >= math.ceil(population * 0.8)
    assert 3 * population <= meals < 18 * population
