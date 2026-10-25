"""Dynamic scenario engine: interpretation, validation, mutation, responses and outcomes."""

from dataclasses import replace
from statistics import mean

import pytest
from conftest import command, create_city, write

from app.scenario_engine import runtime
from app.scenario_engine.interpreter import PlanDraft
from app.scenario_engine.validator import compile_preview, validate_plan
from app.scenario_engine.world import enable
from app.simulation.engine import tick
from app.simulation.scenarios import queue_event

ACCEPTANCE = "The government doubles public transportation fares and uses the money to improve hospitals"


def op(type, id, **fields):
    return dict(type=type, id=id, rationale=fields.pop("rationale", "requested"), **fields)


def draft(operations, **fields):
    value = dict(
        status="ready",
        title="Plan",
        category="policy",
        description="A requested change.",
        public_description="Something changed in town.",
        duration="temporary",
        measurement_ticks=24,
        affected_systems=[],
        operations=operations,
        agent_knowledge="",
        metrics=["happiness"],
        assumptions=[],
        unsupported=[],
        clarification="",
    )
    value.update(fields)
    return value


def transit_hospital_draft():
    return draft(
        [
            op("modify_policy", "fare", target="transportation.transit_fare", operation="multiply", value=2),
            op(
                "modify_policy",
                "hospitals",
                target="public_services.hospital_funding",
                operation="increase",
                value=0.5,
            ),
            op(
                "broadcast_information",
                "announce",
                channel="official",
                topic="policy_change",
                message="Transit fares double today; the revenue will fund hospital improvements.",
                credibility=85,
                accurate=True,
                audience_kind="all_citizens",
            ),
        ],
        title="Transit fares fund hospitals",
        description="Transit fares double and the city spends the revenue on hospital funding.",
        public_description="The city announced new transit fares and hospital funding.",
        duration="permanent",
        affected_systems=["transportation", "public_services", "healthcare", "economy"],
        metrics=[
            "transit_usage",
            "car_usage",
            "walking_trips",
            "city_treasury",
            "hospital_care",
            "household_wallets",
            "financial_strain",
            "happiness",
        ],
        agent_knowledge="Everyone hears the official announcement; some doubt it.",
    )


def fake_gemini(client, monkeypatch, answers):
    """Serve PlanDraft answers in order (the last one repeats); other schemas get no answer."""
    service = client.app.state.service
    config = replace(service.config, llm_mode="gemini", gemini_api_key="test-key", gemini_model="test-model")
    service.config = config
    service.gateway.config = config
    calls = []

    async def structured(sid, prompt, output_model, max_output_tokens=None, timeout=None):
        if output_model is not PlanDraft:
            return None
        calls.append(prompt)
        answer = answers[min(len(calls) - 1, len(answers) - 1)]
        return None if answer is None else PlanDraft.model_validate(answer)

    monkeypatch.setattr(service.gateway, "structured", structured)
    return calls


def hold(client, sid):
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    response = write(
        client,
        f"/simulations/{sid}/interventions",
        dict(expected_control_version=simulation["control_version"]),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def step_until_outcome(client, sid, limit=8):
    for _ in range(limit):
        response = command(client, sid, "step", count=10)
        assert response.status_code == 200, response.text
        if response.json()["data"]["simulation"]["pause_reason"] == "outcome":
            return response
    raise AssertionError("The scenario did not resolve")


def engine(client, path, body=None):
    if body is None:
        return client.get("/api/v1/integrations/scenarios" + path)
    return write(client, "/integrations/scenarios" + path, body)


def test_acceptance_doubled_fares_fund_hospitals_end_to_end(client, monkeypatch):
    calls = fake_gemini(client, monkeypatch, [transit_hospital_draft()])
    sid = create_city(client, population=30)["id"]
    intervention = hold(client, sid)
    response = engine(
        client, f"/simulations/{sid}/plans", dict(intervention_id=intervention["id"], prompt=ACCEPTANCE)
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["status"] == "ready", result
    assert ACCEPTANCE in calls[0] and "transportation.transit_fare" in calls[0]
    summary = result["summary"]
    assert {"transportation", "healthcare"} <= set(summary["affected_systems"])
    assert [o["type"] for o in summary["operations"]] == [
        "modify_policy",
        "modify_policy",
        "broadcast_information",
    ]
    assert summary["event_kind"] == "policy"

    # Nothing changes before confirmation, and a paused city keeps the scenario queued.
    service = client.app.state.service
    assert not service.heads[sid].systems.enabled
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    committed = engine(
        client,
        f"/simulations/{sid}/commits",
        dict(
            intervention_id=intervention["id"],
            expected_control_version=simulation["control_version"],
            plan=result["plan"],
        ),
    )
    assert committed.status_code == 201, committed.text
    data = committed.json()["data"]
    assert data["queued_until_play"] and data["simulation"]["status"] == "paused"
    event_id = data["event"]["id"]
    head = service.heads[sid]
    assert head.events[event_id].summary.status == "queued"
    assert head.systems.policy.transportation.transit_fare == 0.3
    hospital = next(b for b in head.map.buildings if b.kind == "hospital")
    capacity = hospital.capacity

    step_until_outcome(client, sid)
    head = service.heads[sid]
    assert head.systems.policy.transportation.transit_fare == pytest.approx(0.6)
    assert head.systems.policy.public_services.hospital_funding == pytest.approx(1.5)
    assert next(b for b in head.map.buildings if b.id == hospital.id).capacity > capacity

    report = engine(client, f"/simulations/{sid}/events/{event_id}").json()["data"]
    assert report["status"] == "resolved"
    assert report["policy_after"]["transportation"]["transit_fare"] == pytest.approx(0.6)
    titles = [t["title"] for t in report["operation_traces"]]
    assert any("transit fare" in t for t in titles) and any("hospital funding" in t for t in titles)
    assert report["series"] and report["findings"]
    assert any("not proof of cause" in f["text"] for f in report["findings"])
    assert any("recorded trips" in f["text"] for f in report["findings"])
    assert report["decisions"], "citizens decided individually about the announcement and travel"
    decision = report["decisions"][0]
    assert decision["candidates"] and decision["selected"] and decision["agent_id"]
    beliefs = [
        t
        for t in report["decisions"] + report["operation_traces"]
        if "announcement" in t["title"].lower() or "believe" in t["title"].lower()
    ]
    assert beliefs or report["decision_count"] > 0

    agent = engine(client, f"/simulations/{sid}/agents/{decision['agent_id']}/traces").json()["data"]
    assert agent["systems"]["income"] in {"low", "middle", "high"}
    assert any(t["id"] == decision["id"] for t in agent["traces"]) or agent["traces"]
    state = engine(client, f"/simulations/{sid}/state").json()["data"]
    assert state["enabled"] and state["plans"][0]["status"] == "resolved"
    # The core event report and chronicle still describe the same event.
    core = client.get(f"/api/v1/simulations/{sid}/events/{event_id}").json()["data"]
    assert core["event"]["status"] == "resolved"
    assert any(c["text"] in {f["text"] for f in report["findings"]} for c in core["consequences"])


def queue(state, raw):
    plan, errors, warnings = validate_plan(state, raw)
    assert plan is not None, errors
    enable(state)
    preview = compile_preview(state, plan, warnings)
    event = queue_event(state, preview, "snapshot_test", False)
    runtime.attach(state, event.id, plan)
    return event.id


def city(client, **config):
    sid = create_city(client, population=30, **config)["id"]
    return client.app.state.service.heads[sid].model_copy(deep=True)


def plan_from(state, answer):
    from app.scenario_engine.interpreter import normalize

    return normalize(PlanDraft.model_validate(answer), "test")


def run(state, ticks):
    for _ in range(ticks):
        tick(state)
    return state


def test_policy_lab_fares_and_taxes_change_state_and_behavior(client):
    base = city(client, mode="policy_lab")
    assert base.systems.enabled, "policy lab cities start with their economy running"
    control = base.model_copy(deep=True)
    treated = base.model_copy(deep=True)
    queue(
        control,
        plan_from(
            control,
            draft(
                [
                    op(
                        "modify_policy",
                        "noop",
                        target="taxation.business_tax_rate",
                        operation="set",
                        value=0.1,
                    )
                ],
                measurement_ticks=60,
            ),
        ),
    )
    queue(
        treated,
        plan_from(
            treated,
            draft(
                [
                    op(
                        "modify_policy",
                        "fare",
                        target="transportation.transit_fare",
                        operation="multiply",
                        value=4,
                    ),
                    op(
                        "modify_policy",
                        "tax",
                        target="taxation.business_tax_rate",
                        operation="set",
                        value=0.4,
                    ),
                ],
                measurement_ticks=60,
            ),
        ),
    )
    run(control, 60)
    run(treated, 60)

    def share(state):
        c = state.systems.counters
        trips = c.get("trips_walk", 0) + c.get("trips_transit", 0) + c.get("trips_car", 0)
        return c.get("trips_transit", 0) / trips

    assert share(treated) < share(control)
    assert treated.systems.counters["business_tax"] > control.systems.counters["business_tax"]
    switched = [
        t for t in treated.systems.traces if t.kind == "decision" and "instead of my usual transit" in t.title
    ]
    assert switched and all(t.candidates and t.selected != "transit" for t in switched)
    assert any("transit trip cost" in m.text for c in treated.citizens.values() for m in c.memories)


def test_behavior_lab_institutional_trust_changes_belief_and_sharing(client):
    base = city(client, mode="behavior_lab")
    announcement = op(
        "broadcast_information",
        "notice",
        channel="official",
        topic="services",
        start_tick=2,
        message="The clinic now offers free checkups.",
        credibility=80,
        accurate=True,
    )
    runs = {}
    for name, delta in (("scandal", -45), ("transparency", 40)):
        state = base.model_copy(deep=True)
        queue(
            state,
            plan_from(
                state,
                draft(
                    [
                        op(
                            "adjust_institutional_credibility",
                            "cred",
                            delta=delta,
                            reason=f"{name} condition",
                        ),
                        announcement,
                    ],
                    category="behavioral",
                    measurement_ticks=40,
                ),
            ),
        )
        runs[name] = run(state, 40)
    trust = {k: mean(a.institutional_trust for a in s.systems.agents.values()) for k, s in runs.items()}
    believers = {k: sum("notice" in a.beliefs for a in s.systems.agents.values()) for k, s in runs.items()}
    assert trust["scandal"] < trust["transparency"]
    assert believers["scandal"] < believers["transparency"]
    decisions = [t for t in runs["scandal"].systems.traces if t.op_id == "notice" and t.kind == "decision"]
    assert {t.selected for t in decisions} >= {"doubt"}
    # Trait edits are labeled as changing people rather than conditions.
    _, _, warnings = validate_plan(
        base,
        plan_from(
            base,
            draft([op("adjust_population_traits", "kind", trait="empathy", delta=20)], category="behavioral"),
        ),
    )
    assert any("changes who citizens are" in w for w in warnings)


def test_crisis_lab_closes_services_and_citizens_adapt(client):
    state = city(client, mode="crisis_lab")
    shops = [b for b in state.map.buildings if b.kind == "shop"]
    event_id = queue(
        state,
        plan_from(
            state,
            draft(
                [
                    op(
                        "set_service_availability",
                        "shops",
                        building_kind="shop",
                        region="citywide",
                        open=False,
                        duration_ticks=12,
                    ),
                    op("environmental_condition", "heat", condition="heat", region="citywide", intensity=70),
                ],
                category="infrastructure",
                measurement_ticks=20,
            ),
        ),
    )
    run(state, 3)
    assert all(not b.functional for b in state.map.buildings if b.kind == "shop")
    assert state.systems.conditions
    run(state, 15)
    assert all(b.functional for b in state.map.buildings if b.id in {s.id for s in shops})
    titles = [t.title for t in state.systems.traces if t.event_id == event_id]
    assert any(t.startswith("Ended:") for t in titles)
    run(state, 3)
    assert state.events[event_id].summary.status == "resolved"
    assert not state.systems.conditions


def test_custom_multi_domain_plan_composes_housing_resources_and_organizations(client):
    state = city(client)
    before = mean(state.citizens[a].summary.metrics.resources for a in state.citizens)
    assert before >= 0
    event_id = queue(
        state,
        plan_from(
            state,
            draft(
                [
                    op("modify_policy", "rent", target="housing.rent_level", operation="multiply", value=2.5),
                    op("modify_housing_supply", "homes", available_share=0.5),
                    op(
                        "create_organization",
                        "aid",
                        kind="mutual_aid",
                        name="Neighbors Pantry",
                        mission="Share food",
                        founding_share=0.3,
                    ),
                    op(
                        "broadcast_information",
                        "rumor",
                        channel="rumor",
                        topic="prices",
                        accurate=False,
                        credibility=60,
                        message="Food prices will triple next week.",
                    ),
                    op(
                        "modify_policy",
                        "campaign",
                        target="community_programs.conservation_campaign",
                        operation="set",
                        value=1,
                    ),
                ],
                category="mixed",
                measurement_ticks=40,
            ),
        ),
    )
    run(state, 41)
    record = state.systems.plans[event_id]
    assert record.status == "resolved"
    org = next(o for o in state.systems.organizations.values() if o.name == "Neighbors Pantry")
    assert org.members
    assert any(t.title == "Decided whether to stockpile food" for t in state.systems.traces)
    assert record.series[-1]["rent_burden"] > record.baseline["rent_burden"]
    # A temporary plan restores rents and housing; the organization was founded and persists as history.
    assert state.systems.policy.housing.rent_level == 1


def test_validator_rejects_unregistered_out_of_range_and_conflicting_operations(client):
    state = city(client)
    bad = plan_from(
        state,
        draft(
            [
                op(
                    "modify_policy",
                    "fare",
                    target="transportation.transit_fare",
                    operation="multiply",
                    value=50,
                )
            ]
        ),
    )
    plan, errors, _ = validate_plan(state, bad)
    assert plan is None and any("allowed range" in e for e in errors)
    unknown = plan_from(
        state,
        draft([op("modify_policy", "x", target="transportation.transit_fare", operation="set", value=1)]),
    )
    unknown["operations"][0]["target"] = "simulation.tick"
    assert validate_plan(state, unknown)[0] is None
    missing = plan_from(
        state, draft([op("set_service_availability", "b", building_id="building_99999999", open=False)])
    )
    assert any("does not exist" in e for e in validate_plan(state, missing)[1])
    homes = plan_from(state, draft([op("set_service_availability", "h", building_kind="home", open=False)]))
    assert any("homes cannot be closed" in e for e in validate_plan(state, homes)[1])
    clash = plan_from(
        state,
        draft(
            [
                op("modify_policy", "a", target="transportation.transit_fare", operation="set", value=1),
                op("modify_policy", "b", target="transportation.transit_fare", operation="set", value=2),
            ]
        ),
    )
    assert any("conflicts" in e for e in validate_plan(state, clash)[1])
    split = plan_from(
        state,
        draft(
            [
                op("physical_hazard", "f", hazard="flood", region="north", severity=50),
                op("community_gathering", "g", activity="festival", region="south"),
            ]
        ),
    )
    assert any("single region" in e for e in validate_plan(state, split)[1])
    code = plan_from(
        state,
        draft([op("modify_policy", "fare", target="transportation.transit_fare", operation="set", value=1)]),
    )
    code["operations"][0]["script"] = "process.exit()"
    assert validate_plan(state, code)[0] is None


def test_unsupported_request_is_explained_not_substituted(client, monkeypatch):
    fake_gemini(
        client,
        monkeypatch,
        [draft([], status="unsupported", unsupported=["Building a subway line needs new construction."])],
    )
    sid = create_city(client)["id"]
    intervention = hold(client, sid)
    result = engine(
        client,
        f"/simulations/{sid}/plans",
        dict(intervention_id=intervention["id"], prompt="Build a subway line"),
    ).json()["data"]
    assert result["status"] == "unsupported" and result["plan"] is None
    assert "construction" in result["unsupported"][0]
    assert not client.app.state.service.heads[sid].events


def test_interpreter_gets_one_correction_attempt(client, monkeypatch):
    invalid = draft(
        [op("modify_policy", "fare", target="transportation.transit_fare", operation="multiply", value=99)]
    )
    calls = fake_gemini(client, monkeypatch, [invalid, transit_hospital_draft()])
    sid = create_city(client)["id"]
    intervention = hold(client, sid)
    result = engine(
        client, f"/simulations/{sid}/plans", dict(intervention_id=intervention["id"], prompt=ACCEPTANCE)
    ).json()["data"]
    assert result["status"] == "ready" and result["attempts"] == 2
    assert "failed validation" in calls[1] and "allowed range" in calls[1]
    calls = fake_gemini(client, monkeypatch, [invalid])
    result = engine(
        client, f"/simulations/{sid}/plans", dict(intervention_id=intervention["id"], prompt=ACCEPTANCE)
    ).json()["data"]
    assert result["status"] == "invalid" and result["errors"] and len(calls) == 2


def test_interpreter_unavailable_without_gemini_and_manual_plans_validate(client):
    sid = create_city(client)["id"]
    intervention = hold(client, sid)
    result = engine(
        client, f"/simulations/{sid}/plans", dict(intervention_id=intervention["id"], prompt=ACCEPTANCE)
    ).json()["data"]
    assert result["status"] == "unavailable"
    capabilities = engine(client, "/capabilities").json()["data"]
    assert capabilities["interpreter"] is False
    assert any(t["target"] == "transportation.transit_fare" for t in capabilities["policy_targets"])
    from app.scenario_engine.interpreter import normalize

    manual = normalize(PlanDraft.model_validate(transit_hospital_draft()), ACCEPTANCE) | dict(source="manual")
    checked = engine(client, f"/simulations/{sid}/plans/validate", dict(plan=manual)).json()["data"]
    assert checked["status"] == "ready" and checked["summary"]["operations"]


def test_running_city_resumes_and_legacy_events_still_work(client):
    sid = create_city(client)["id"]
    intervention = hold(client, sid)
    from app.scenario_engine.interpreter import normalize

    manual = normalize(
        PlanDraft.model_validate(
            draft(
                [op("physical_hazard", "flood", hazard="flood", region="west", severity=60)],
                category="environmental",
                measurement_ticks=4,
            )
        ),
        "A flood in the west",
    )
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    committed = engine(
        client,
        f"/simulations/{sid}/commits",
        dict(
            intervention_id=intervention["id"],
            expected_control_version=simulation["control_version"],
            plan=manual,
        ),
    )
    assert committed.status_code == 201, committed.text
    event = committed.json()["data"]["event"]
    assert event["kind"] == "flood" and event["scene"]
    step_until_outcome(client, sid)
    report = client.get(f"/api/v1/simulations/{sid}/events/{event['id']}").json()["data"]
    assert (
        report["exposed_count"] + report["evacuated_count"] >= 0 and report["event"]["status"] == "resolved"
    )


def test_initial_setup_scenario_uses_the_engine(client, monkeypatch):
    fake_gemini(client, monkeypatch, [transit_hospital_draft()])
    simulation = create_city(client, population=12, scenario_description=ACCEPTANCE)
    preview = simulation["initial_preview"]
    assert preview["can_commit"] and preview["spec"]["kind"] == "policy"
    sid = simulation["id"]
    initial = engine(client, f"/simulations/{sid}/initial-plan").json()["data"]
    assert initial["plan"]["title"] == "Transit fares fund hospitals"
    response = write(
        client,
        f"/simulations/{sid}/initial-scenario",
        dict(
            expected_control_version=simulation["control_version"],
            preview_id=preview["id"],
            decision="confirm",
        ),
    )
    assert response.status_code == 200, response.text
    head = client.app.state.service.heads[sid]
    assert head.systems.enabled and head.systems.plans and head.systems.initial_plan is None


def test_one_second_cities_keep_plan_timings_in_simulated_seconds(client):
    for tick_seconds in (10, 1):
        state = city(client, tick_seconds=tick_seconds)
        plan, errors, warnings = validate_plan(state, plan_from(state, transit_hospital_draft()))
        assert plan is not None, errors
        preview = compile_preview(state, plan, warnings)
        assert preview.spec.duration_ticks * tick_seconds == plan.measurement_ticks * 10
