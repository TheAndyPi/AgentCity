"""Complete, deterministic observations from real persisted simulation fixtures."""

import json

import pytest
from conftest import commit_preview, create_city, preview

from app.behavior.models import Impact
from app.contracts import Belief, Relationship
from app.scenario_engine.systems import Belief as InformationBelief
from app.scenario_engine.world import enable
from app.simulation.agents import connect, evidence, metric_delta, social_delta
from app.simulation.scenarios import activate
from app.snowflake.observations_projection import capture_baseline, digest, project


@pytest.fixture
def world(client):
    simulation = create_city(client)
    return client.app.state.service.repo.read(simulation["id"])


def payloads(envelope, kind):
    return [f["payload"] for f in envelope["facts"] if f["kind"] == kind]


def advance(state):
    state.simulation.revision += 1
    return state


def test_health_and_directed_trust_exact_changes_without_private_memory(world):
    a, b = list(world.citizens.values())[:2]
    connect(world, a, b)
    connect(world, b, a)
    previous = world.model_copy(deep=True)
    before = a.relationships[b.summary.id].trust
    a.needs.health = 60
    social_delta(world, a, b, "decision_test", -4)
    projected = project(previous, advance(world))
    changes = payloads(projected, "change")
    health = next(c for c in changes if c["field"] == "health")
    assert health["before"] == 100
    assert health["after"] == 60
    assert health["link"] == "temporal"
    trust = next(c for c in changes if c["entity_kind"] == "relationship" and c["field"] == "trust")
    assert trust["before"] == before and trust["after"] == before - 4
    assert trust["decision_ids"] == ["decision_test"]
    assert trust["link"] == "explicit"
    assert len(payloads(projected, "relationship")) == 1
    assert previous.citizens[b.summary.id].relationships[a.summary.id] == b.relationships[a.summary.id]
    raw = json.dumps(projected)
    assert "memories" not in raw and "desired_relationship" not in raw


def test_existing_beliefs_stable_confidence_and_addition_removal(world):
    a = next(iter(world.citizens.values()))
    a.beliefs = [Belief(text="The clinic is helpful", confidence=35, evidence=evidence("Saw treatment"))]
    previous = world.model_copy(deep=True)
    a.beliefs[0].confidence = 80
    projected = project(previous, advance(world))
    change = next(c for c in payloads(projected, "change") if c["entity_kind"] == "opinion")
    assert (change["field"], change["before"], change["after"]) == ("confidence", 35, 80)
    identity = payloads(projected, "opinion")[0]["key"]
    previous = world.model_copy(deep=True)
    a.beliefs[0].text = "The clinic is crowded"
    projected = project(previous, advance(world))
    changes = [c for c in payloads(projected, "change") if c["entity_kind"] == "opinion"]
    assert len(changes) == 2
    assert {c["field"] for c in changes} == {"__entity__"}
    assert any(o.get("deleted") and o["key"] == identity for o in payloads(projected, "opinion"))


def test_information_class_and_norm_values_keep_source_scales(world):
    enable(world)
    a = next(iter(world.citizens.values()))
    systems = world.systems.agents[a.summary.id]
    systems.beliefs["clinic"] = InformationBelief(
        topic="care",
        message="Clinic open",
        confidence=0.65,
        channel="broadcast",
        source_op="information_1",
        accurate=True,
        tick=0,
    )
    systems.norms["sharing"] = 0.3
    a.condition.class_beliefs["rich"] = "helpful"
    a.condition.class_evidence_tick["rich"] = 0
    records = payloads(project(None, world), "opinion")
    assert next(o for o in records if o["category"] == "information")["confidence"] == 0.65
    assert next(o for o in records if o["category"] == "norm")["value"] == 0.3
    assert next(o for o in records if o["category"] == "class")["value"] == "helpful"


def test_city_denominators_exclude_dead_but_preserve_death_count(world):
    citizens = list(world.citizens.values())
    citizens[0].needs.health = 0
    citizens[0].condition.life = "dead"
    citizens[0].summary.active = False
    for a in citizens[1:]:
        a.needs.health = 80
    city = payloads(project(None, world), "city")[0]
    assert city["health"] == 80
    assert city["denominators"]["health"] == len(citizens) - 1
    assert city["deaths"] == 1
    for a in citizens:
        a.condition.life = "dead"
    city = payloads(project(None, world), "city")[0]
    assert city["population"] == 0
    assert city["health"] is None
    assert city["relationship_trust"] is None
    assert city["denominators"]["health"] == 0


def test_baseline_sparse_relationships_and_no_read_side_mutation(world):
    before = world.model_dump(mode="json")
    baseline = capture_baseline(world)
    assert len(baseline["relationships"]) == sum(len(c.relationships) for c in world.citizens.values())
    assert len(baseline["relationships"]) < len(world.citizens) ** 2
    projected = project(None, world)
    assert world.model_dump(mode="json") == before
    assert not payloads(projected, "change")
    assert project(None, world) == projected


def test_same_tick_revisions_distinct_ids_and_branch_lineage(world):
    before = world.model_copy(deep=True)
    a = next(iter(world.citizens.values()))
    a.needs.health = 90
    first = project(before, advance(world))
    previous = world.model_copy(deep=True)
    a.needs.health = 70
    second = project(previous, advance(world))
    assert first["tick"] == second["tick"]
    assert {f["id"] for f in first["facts"]}.isdisjoint(f["id"] for f in second["facts"])
    source_id = world.simulation.id
    world.simulation.id = "sim_branch"
    branch = project(
        previous, world, dict(parent_simulation_id=source_id, fork_revision=previous.simulation.revision)
    )
    assert branch["simulation_id"] == "sim_branch"
    assert branch["parent_simulation_id"] == source_id
    assert branch["fork_revision"] == previous.simulation.revision
    assert {f["id"] for f in branch["facts"]}.isdisjoint(f["id"] for f in second["facts"])


def test_deletion_tombstone_and_content_hash(world):
    previous = world.model_copy(deep=True)
    aid = next(iter(world.citizens))
    del world.citizens[aid]
    result = project(previous, advance(world))
    fact = next(f for f in result["facts"] if f["kind"] == "agent" and f["entity_id"] == aid)
    assert fact["payload"]["deleted"] is True
    assert fact["sha256"] == digest({k: fact[k] for k in ("kind", "entity_id", "payload")})


def test_metric_evidence_only_new_cause_is_used(world):
    a = next(iter(world.citizens.values()))
    metric_delta(a, "stress", 4, evidence("Old event", event_ids=["event_old"]))
    previous = world.model_copy(deep=True)
    a.summary.metrics.stress += 1
    changed = payloads(project(previous, advance(world)), "change")
    stress = next(c for c in changed if c["field"] == "stress")
    assert stress["event_ids"] == []
    previous = world.model_copy(deep=True)
    metric_delta(a, "stress", 3, evidence("New event", event_ids=["event_new"]))
    stress = next(c for c in payloads(project(previous, advance(world)), "change") if c["field"] == "stress")
    assert stress["event_ids"] == ["event_new"]


def test_capped_evidence_lists_preserve_new_explicit_causes(world):
    citizen = next(iter(world.citizens.values()))
    metric_delta(citizen, "stress", 1, evidence("First reason", event_ids=["event_old"]))
    citizen.condition.impacts = [
        Impact(
            tick=1,
            phase="passive",
            meter="health",
            reason="old",
            delta=-1,
            evidence=evidence("Old injury", event_ids=["event_old"]),
        )
    ]
    previous = world.model_copy(deep=True)
    metric_delta(citizen, "stress", 2, evidence("Second reason", event_ids=["event_new"]))
    citizen.metric_reasons = citizen.metric_reasons[-1:]
    citizen.needs.health -= 2
    citizen.condition.impacts = [
        Impact(
            tick=2,
            phase="event",
            meter="health",
            reason="new",
            delta=-2,
            evidence=evidence("New injury", event_ids=["event_new"]),
        )
    ]
    changes = payloads(project(previous, advance(world)), "change")
    assert next(c for c in changes if c["field"] == "stress")["event_ids"] == ["event_new"]
    assert next(c for c in changes if c["field"] == "health")["event_ids"] == ["event_new"]


def test_event_activation_baseline_persisted_before_effects(client):
    simulation = create_city(client)
    sid = simulation["id"]
    hold, compiled = preview(client, sid, "A flood for 2 ticks")
    response = commit_preview(client, sid, hold, compiled)
    assert response.status_code in {200, 201}
    state = client.app.state.service.repo.read(sid)
    queued = next(e for e in state.events.values() if e.summary.status == "queued")
    assert queued.observation_baseline is None
    expected = capture_baseline(state)
    activate(state)
    assert queued.observation_baseline == expected
    citizen = next(iter(state.citizens.values()))
    original_health = citizen.needs.health
    citizen.needs.health = 15
    baseline_health = next(
        a["health"] for a in queued.observation_baseline["agents"] if a["agent_id"] == citizen.summary.id
    )
    assert baseline_health == original_health
    restored = type(state).model_validate_json(state.model_dump_json())
    assert restored.events[queued.summary.id].observation_baseline == expected
    event = payloads(project(None, state), "event")[0]
    assert event["status"] == "active" and event["baseline_available"]
    queued.cancelled = True
    assert payloads(project(None, state), "event")[0]["status"] == "cancelled"


def test_legacy_event_has_explicit_unavailable_baseline(client):
    simulation = create_city(client)
    hold, compiled = preview(client, simulation["id"])
    assert commit_preview(client, simulation["id"], hold, compiled).status_code in {200, 201}
    state = client.app.state.service.repo.read(simulation["id"])
    event = payloads(project(None, state), "event")[0]
    assert event["baseline"] is None and event["baseline_available"] is False


def test_dense_baseline_split_is_lossless_bounded_and_emitted_once(client):
    simulation = create_city(client)
    hold, compiled = preview(client, simulation["id"])
    assert commit_preview(client, simulation["id"], hold, compiled).status_code in {200, 201}
    state = client.app.state.service.repo.read(simulation["id"])
    citizen = next(iter(state.citizens.values()))
    state.citizens = {}
    for i in range(100):
        clone = citizen.model_copy(deep=True)
        clone.summary.id = f"agent_dense_{i:03d}"
        clone.relationships = {}
        state.citizens[clone.summary.id] = clone
    for aid, clone in state.citizens.items():
        for bid in state.citizens:
            if bid != aid:
                clone.relationships[bid] = Relationship(
                    from_agent_id=aid,
                    to_agent_id=bid,
                    kind="acquaintance",
                    trust=50,
                    affection=50,
                    respect=50,
                    familiarity=20,
                    conflict=0,
                    desired_relationship="friend",
                    shared_history=[],
                    evidence=evidence("Known meeting"),
                )
    runtime = next(iter(state.events.values()))
    previous = state.model_copy(deep=True)
    runtime.observation_baseline = capture_baseline(state)
    assert len(json.dumps(runtime.observation_baseline).encode()) > 1_000_000
    envelope = project(previous, advance(state))
    assert max(len(json.dumps(f).encode()) for f in envelope["facts"]) < 1_000_000
    baseline_facts = payloads(envelope, "event_baseline")
    assert len(baseline_facts) == 9900
    assert {r["entity_id"] for r in baseline_facts} == {
        r["entity_id"] for r in runtime.observation_baseline["relationships"]
    }
    projected_event = payloads(envelope, "event")[0]
    assert projected_event["baseline"]["relationship_count"] == 9900
    assert "relationships" not in projected_event["baseline"]
    assert projected_event["baseline"]["agents"] == runtime.observation_baseline["agents"]
    previous = state.model_copy(deep=True)
    assert not payloads(project(previous, advance(state)), "event_baseline")
