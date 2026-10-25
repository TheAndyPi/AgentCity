"""Observation integration: real journal/API plus controlled warehouse boundary."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from conftest import command, commit_preview, create_city, preview, write
from fastapi.testclient import TestClient
from observations_fake import ObservationFake

from app.behavior.models import Impact
from app.contracts import Belief
from app.infrastructure.config import AppConfig
from app.main import create_app
from app.simulation.agents import connect, evidence
from app.snowflake.config import SnowflakeConfig
from app.snowflake.observations import ObservationService, chunks
from app.snowflake.observations_api import install_observations
from app.snowflake.observations_projection import project
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable

ROOT = "/api/v1/integrations/snowflake/observations/v1/simulations/"


def test_global_action_totals_cannot_be_mislabeled_as_one_citizen(tmp_path):
    with connected(tmp_path) as (client, _, observer):
        city = create_city(client)
        sid = city["id"]
        reconcile(client, observer)
        agent_id = next(iter(client.app.state.service.heads[sid].citizens))
        for metric in ("cooperation_count", "conflict_count"):
            response = client.get(
                ROOT + sid + "/trends",
                params={"through_revision": city["revision"], "metric": metric, "agent_id": agent_id},
            )
            assert response.status_code == 400
            assert "citywide" in response.json()["error"]["message"]


def snow_config(**fields):
    return SimpleNamespace(
        **(
            asdict(SnowflakeConfig())
            | dict(
                observations_enabled=True,
                observation_poll_seconds=3600,
                account="test-account",
                user="TEST",
                database="TEST",
                schema="TEST",
                warehouse="TEST",
                role="TEST",
                private_key_file=__file__,
            )
            | fields
        )
    )


@contextmanager
def connected(tmp_path, fake=None, enabled=True):
    fake = fake or ObservationFake()
    config = snow_config(observations_enabled=enabled)
    app = create_app(AppConfig(data_dir=tmp_path / "store"))
    observer = install_observations(app.state.integrations, app, config, fake)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current):
        async with original(current):
            await observer.start()
            # Tests explicitly reconcile; real worker scheduling is exercised separately.
            if observer.task:
                observer.task.cancel()
                await asyncio.gather(observer.task, return_exceptions=True)
                observer.task = None
            try:
                yield
            finally:
                await observer.close()

    app.router.lifespan_context = lifespan
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        yield client, fake, observer


def reconcile(client, observer):
    client.portal.call(observer.reconcile, 10000)


def mutate(client, sid, operation, tick=None):
    async def change():
        service = client.app.state.service
        async with service.writer:
            state = service.repo.read(sid)
            operation(state)
            service.bump(state)
            if tick is not None:
                state.simulation.tick = tick
            await service.persist([state])
            return state.simulation.revision

    return client.portal.call(change)


def get(client, sid, kind, revision, **params):
    return client.get(ROOT + sid + "/" + kind, params=dict(through_revision=revision, **params))


def test_exact_health_asymmetric_relationship_and_opinion_history(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        sid = sim["id"]
        a, b = list(client.app.state.service.heads[sid].citizens)[:2]

        def baseline(state):
            for citizen in state.citizens.values():
                citizen.relationships.clear()
            connect(state, state.citizens[a], state.citizens[b])
            connect(state, state.citizens[b], state.citizens[a])
            state.citizens[a].relationships[b].trust = 20
            state.citizens[b].relationships[a].trust = 80
            state.citizens[a].beliefs = [
                Belief(text="Clinic helpful", confidence=30, evidence=evidence("Visited"))
            ]

        first = mutate(client, sid, baseline, tick=1)

        def changed(state):
            state.citizens[a].needs.health = 40
            state.citizens[a].relationships[b].trust = 60
            state.citizens[a].beliefs[0].confidence = 90

        last = mutate(client, sid, changed, tick=2)
        reconcile(client, observer)
        assert client.portal.call(observer.checkpoint, sid) == last
        health = get(client, sid, "trends", last, metric="health", agent_id=a).json()["data"]
        assert [p["mean"] for p in health["items"]][-2:] == [100, 40]
        assert health["source"] == "snowflake"
        assert health["coverage"]["state"] == "complete"
        trust_a = get(client, sid, "trends", last, metric="relationship_trust", agent_id=a).json()["data"]
        trust_b = get(client, sid, "trends", last, metric="relationship_trust", agent_id=b).json()["data"]
        assert trust_a["items"][-1]["mean"] == 60
        assert trust_b["items"][-1]["mean"] == 80
        opinion = get(client, sid, "changes", last, entity_kind="opinion").json()["data"]["items"]
        confidence = next(c for c in opinion if c["field"] == "confidence")
        assert (confidence["before"], confidence["after"]) == (30, 90)
        old = get(client, sid, "trends", first, metric="health", agent_id=a).json()["data"]
        assert old["items"][-1]["mean"] == 100
        assert old["effective_revision"] == first
        assert fake.manifests and fake.facts


def test_backfill_repeat_lost_cursor_and_restart_are_idempotent(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        sid = sim["id"]
        reconcile(client, observer)
        first_counts = len(fake.facts), len(fake.manifests)
        reconcile(client, observer)
        assert (len(fake.facts), len(fake.manifests)) == first_counts

        async def reset_cursor():
            observer.db.execute("DELETE FROM progress")
            observer.db.commit()

        client.portal.call(reset_cursor)
        reconcile(client, observer)
        assert (len(fake.facts), len(fake.manifests)) == first_counts
        checkpoint = client.portal.call(observer.checkpoint, sid)
    # Persistent journal reopening appends recovery revisions; all earlier facts remain identical.
    with connected(tmp_path, fake) as (client, _, observer):
        assert client.portal.call(observer.checkpoint, sid) == checkpoint
        reconcile(client, observer)
        assert (
            client.portal.call(observer.checkpoint, sid)
            == client.app.state.service.heads[sid].simulation.revision
        )
        old = get(client, sid, "trends", checkpoint, metric="health")
        assert old.status_code == 200


def test_ambiguous_publish_timeout_recovers_without_duplicate_facts(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        sid = sim["id"]
        once = [False]

        def fail_after_commit():
            if not once[0]:
                once[0] = True
                raise VendorUnavailable("network_response_lost")

        fake.after_publish = fail_after_commit
        reconcile(client, observer)
        assert client.portal.call(observer.checkpoint, sid) == -1
        assert get(client, sid, "status", sim["revision"]).json()["data"]["state"] == "failed"
        fake.after_publish = None
        reconcile(client, observer)
        assert client.portal.call(observer.checkpoint, sid) == sim["revision"]
        assert len(fake.facts) == len(set(fake.facts))


def test_conflicting_hash_blocks_only_affected_city(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        a = create_city(client)
        b = create_city(client, name="Other")
        bad = client.app.state.service.repo.read(a["id"], 0)
        batch = project(None, bad)
        fact = copy.deepcopy(batch["facts"][0])
        fact["sha256"] = "a" * 64
        fake.facts[(bad.owner_id, a["id"], 0, fact["id"])] = dict(fact, revision=0, tick=bad.simulation.tick)
        reconcile(client, observer)
        assert client.portal.call(observer.checkpoint, a["id"]) == -1
        assert client.portal.call(observer.blocked, a["id"])[0] == "HASH_CONFLICT"
        assert client.portal.call(observer.checkpoint, b["id"]) == b["revision"]
        assert not client.app.state.service.repo.degraded


def test_incomplete_revision_is_not_queryable_and_outage_does_not_stop_ticks(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        fake.fail_shape = "obs_publish"
        reconcile(client, observer)
        assert fake.facts and not fake.manifests
        assert get(client, sim["id"], "trends", sim["revision"], metric="health").status_code == 503
        assert command(client, sim["id"], "step", count=1).status_code == 200
        fake.fail_shape = None
        reconcile(client, observer)
        last = client.app.state.service.heads[sim["id"]].simulation.revision
        assert get(client, sim["id"], "trends", last, metric="health").status_code == 200


def test_all_dead_denominators_and_missing_institutional_values(tmp_path):
    with connected(tmp_path) as (client, _, observer):
        sim = create_city(client)
        sid = sim["id"]

        def death(state):
            for a in state.citizens.values():
                a.condition.life = "dead"
                a.summary.active = False
                a.needs.health = 0

        last = mutate(client, sid, death, tick=1)
        reconcile(client, observer)
        health = get(client, sid, "trends", last, metric="health").json()["data"]["items"][-1]
        deaths = get(client, sid, "trends", last, metric="deaths").json()["data"]["items"][-1]
        assert health["mean"] is None and health["denominator"] == 0
        assert deaths["mean"] == 10
        for kind in ("relationship_trust", "opinion_confidence"):
            point = get(client, sid, "trends", last, metric=kind).json()["data"]["items"][-1]
            assert point["mean"] is None and point["denominator"] == 0


def test_branch_pinned_history_and_owner_check_before_cache(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        sid = sim["id"]
        branch = write(
            client, f"/simulations/{sid}/branches", {"name": "Branch", "source": {"kind": "whole"}}
        ).json()["data"]["simulation"]
        bid = branch["id"]
        a = next(iter(client.app.state.service.heads[bid].citizens))
        last = mutate(client, bid, lambda state: setattr(state.citizens[a].needs, "health", 10), tick=1)
        reconcile(client, observer)
        parent = get(client, sid, "trends", sim["revision"], metric="health", agent_id=a).json()["data"]
        child = get(client, bid, "trends", last, metric="health", agent_id=a).json()["data"]
        assert parent["items"][-1]["mean"] == 100
        assert child["items"][-1]["mean"] == 10
        assert {key[1] for key in fake.manifests} == {sid, bid}
        assert get(client, sid, "trends", last + 100, metric="health").status_code == 404
        count = len(fake.calls)
        # Even a populated cache must not bypass the current authorization check.
        client.app.state.service.heads[sid].owner_id = "other_owner"
        assert get(client, sid, "trends", sim["revision"], metric="health", agent_id=a).status_code == 404
        assert len(fake.calls) == count


def test_filter_bound_pagination_and_query_validation(tmp_path):
    with connected(tmp_path) as (client, _, observer):
        sim = create_city(client)
        sid = sim["id"]
        for tick in range(1, 4):
            mutate(
                client,
                sid,
                lambda s: setattr(
                    next(iter(s.citizens.values())).needs, "health", 100 - s.simulation.revision
                ),
                tick=tick,
            )
        reconcile(client, observer)
        revision = client.app.state.service.heads[sid].simulation.revision
        first = get(client, sid, "changes", revision, limit=1).json()["data"]
        assert len(first["items"]) == 1 and first["next_after"]
        second = get(client, sid, "changes", revision, limit=1, after=first["next_after"]).json()["data"]
        assert second["items"][0]["id"] != first["items"][0]["id"]
        assert (
            get(
                client, sid, "changes", revision, limit=1, after=first["next_after"], entity_kind="opinion"
            ).status_code
            == 400
        )
        assert get(client, sid, "trends", revision, metric="user_sql").status_code == 400
        assert (
            get(client, sid, "trends", revision, metric="health", start_tick=5, end_tick=1).status_code == 400
        )
        assert get(client, sid, "changes", revision, limit=101).status_code == 422
        assert client.get(ROOT + sid + "/trends").status_code == 422


def test_disabled_observation_routes_and_metric_catalog(tmp_path):
    with connected(tmp_path, enabled=False) as (client, fake, _):
        sim = create_city(client)
        status = get(client, sim["id"], "status", sim["revision"]).json()["data"]
        assert status["state"] == "disabled" and not status["enabled"]
        assert get(client, sim["id"], "trends", sim["revision"], metric="health").status_code == 501
        catalog = get(client, sim["id"], "metrics", sim["revision"]).json()["data"]
        assert {"health", "relationship_trust", "relationship_respect", "opinion_count"} <= {
            i["id"] for i in catalog["items"]
        }
        assert not fake.calls


def test_deletion_revokes_routes_and_cleans_pending_warehouse_records(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        sid = sim["id"]
        reconcile(client, observer)

        # Reproduce the authoritative result of an authorized deletion without coupling
        # this read-model test to the archive command's presentation.
        async def delete():
            await client.app.state.service.persist([], delete=sid)
            client.app.state.service.heads.pop(sid)

        client.portal.call(delete)
        assert get(client, sid, "trends", sim["revision"], metric="health").status_code == 404
        reconcile(client, observer)
        assert not fake.facts and not fake.manifests


def test_corrupt_progress_rebuilds_without_failing_simulation_start(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    (store / "snowflake-observations.sqlite3").write_bytes(b"not sqlite")
    with connected(tmp_path) as (client, _, observer):
        sim = create_city(client)
        reconcile(client, observer)
        assert client.portal.call(observer.checkpoint, sim["id"]) == sim["revision"]
        assert list(store.glob("snowflake-observations.sqlite3.corrupt-*"))
        assert client.get("/health/ready").status_code == 200


def test_chunk_size_is_bounded_and_oversized_fact_fails_explicitly():
    envelope = dict(
        owner_id="o",
        simulation_id="s",
        revision=0,
        facts=[
            dict(id=str(i), sha256="f" * 64, kind="agent", entity_id=str(i), payload={"value": "a" * 1000})
            for i in range(2400)
        ],
    )
    batches = list(chunks(envelope))
    assert len(batches) >= 3
    assert sum(len(b["facts"]) for b in batches) == 2400
    assert all(len(b["facts"]) <= 2000 and len(json.dumps(b).encode()) <= 1_000_000 for b in batches)
    for batch in batches:
        bound = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
        request = {"statement": "x" * 4000, "bindings": {"1": {"type": "TEXT", "value": bound}}}
        assert len(json.dumps(request, ensure_ascii=False).encode()) < 1_000_000
    envelope["facts"] = [dict(id="huge", kind="agent", entity_id="a", payload={"value": "a" * 1_000_000})]
    with pytest.raises(ValueError, match="budget"):
        list(chunks(envelope))


def test_sql_ingestion_hashes_actual_canonical_payload_not_supplied_hash(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        state = client.app.state.service.repo.read(sim["id"], 0)
        envelope = project(None, state)
        envelope["facts"][0]["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="integrity"):
            client.portal.call(observer.ingest, envelope)
        assert not fake.manifests


def test_opt_in_live_smoke_logic_with_controlled_transport(monkeypatch, capsys):
    from scripts import snowflake_observations_smoke as smoke

    fake = ObservationFake()
    config = SnowflakeConfig(
        enabled=True,
        account="test-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=__file__,
    )
    monkeypatch.setattr(smoke.SnowflakeConfig, "from_env", lambda: config)
    monkeypatch.setattr(smoke, "SnowflakeTransport", lambda _: fake)
    assert asyncio.run(smoke.verify("AGENTCITY_OBSERVATION_SMOKE_TEST"))
    assert not fake.facts and not fake.manifests
    assert "passed" in capsys.readouterr().out


def test_untrusted_cortex_fact_selection_cannot_change_deterministic_observations():
    # This feature deliberately performs no automatic model calls. Unsupported
    # model-supplied facts cannot enter a numerical report.
    value = dict(
        event={"event_id": "e"},
        resolution={"tick": 2},
        citations=[],
        numeric_observations=[
            {"metric": "health", "delta": 5, "revision": 3},
            {"metric": "trust", "delta": float("nan"), "revision": 3},
        ],
    )
    result = ObservationService.event_observations(value)
    assert len(result["observations"]) == 1
    assert result["observations"][0]["text"].startswith("Health changed by +5.00")
    assert result["observations"][0]["citation_ids"] == ["event:e:health"]


def test_transport_observation_partitions_stable_requests_and_old_limits():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "GET":
            assert request.url.params["partition"] == "1"
            return httpx.Response(200, json={"data": [["3"]]})
        body = json.loads(request.content)
        if body["statement"].startswith("MERGE"):
            return httpx.Response(200, json={"data": [["1"]]})
        return httpx.Response(
            200,
            json={
                "statementHandle": "abc-123",
                "data": [["1"], ["2"]],
                "resultSetMetaData": {"numRows": 3, "partitionInfo": [{}, {}]},
            },
        )

    async def run():
        config = snow_config()
        transport = SnowflakeTransport(
            config,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            token_factory=lambda _: "fake-jwt",
        )
        assert await transport.execute("obs_trends", ("{}",)) == [["1"], ["2"], ["3"]]
        await transport.execute("obs_ingest", ('{"facts":[]}',))
        await transport.execute("obs_ingest", ('{"facts":[]}',))
        assert seen[-1].url.params["requestId"] == seen[-2].url.params["requestId"]
        assert seen[-1].url.params["retry"] == "true"
        with pytest.raises(VendorUnavailable):
            await transport.execute("query")
        await transport.close()

    asyncio.run(run())


def test_transport_rejects_missing_single_partition_rows():
    async def run():
        transport = SnowflakeTransport(
            snow_config(),
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"data": [["1"]], "resultSetMetaData": {"numRows": 2}})
                )
            ),
            token_factory=lambda _: "fake",
        )
        with pytest.raises(VendorUnavailable):
            await transport.execute("obs_trends", ("{}",))
        await transport.close()

    asyncio.run(run())


def test_approved_sql_queries_use_complete_pinned_view_and_typed_aggregates():
    from app.snowflake.transport import SQL

    for shape in ("obs_trends", "obs_events", "obs_changes", "obs_event_detail"):
        sql = (SQL / (shape + ".sql")).read_text()
        assert "AGENTCITY_OBSERVATIONS_V1" in sql
        assert "f.REVISION<=p.v:through_revision::NUMBER" in sql
        assert "p.v:owner_id::VARCHAR" in sql
        assert "PARSE_JSON(?)" in sql
    trends = (SQL / "obs_trends.sql").read_text()
    assert "AVG(" in trends and "LEAD(" in trends and "/500" in trends
    assert "COUNT(DISTINCT r.PAYLOAD:pair_id" in trends
    assert "COUNT(IFF(" in trends


def test_event_baseline_resolution_survival_and_partial_then_complete_followup(tmp_path):
    with connected(tmp_path) as (client, _, observer):
        sim = create_city(client)
        sid = sim["id"]
        hold, scene = preview(client, sid, "A citywide flood for 2 ticks")
        assert commit_preview(client, sid, hold, scene).status_code == 201
        assert command(client, sid, "step", count=3).status_code == 200
        head = client.app.state.service.heads[sid]
        runtime = next(r for r in head.events.values() if r.summary.status == "resolved")
        eid, end = runtime.summary.id, runtime.summary.end_tick
        revision = head.simulation.revision
        reconcile(client, observer)
        response = get(client, sid, "events/" + eid, revision)
        assert response.status_code == 200, response.text
        detail = response.json()["data"]
        assert detail["baseline"]["city"]["health"] == 100
        assert detail["baseline"]["denominators"]["city"]["health"] == 10
        assert detail["baseline"]["cohort"]["initial_population"] == len(runtime.cohort)
        assert detail["resolution"]["tick"] == end
        assert not detail["followup_complete"]
        assert detail["change_counts"]["explicit"] > 0
        assert all(c["revision"] <= revision for c in detail["changes"])
        victim = runtime.cohort[0] if runtime.cohort else next(iter(head.citizens))

        def aftermath(state):
            state.citizens[victim].condition.life = "dead"
            state.citizens[victim].summary.active = False
            for citizen in state.citizens.values():
                if citizen.summary.id != victim:
                    citizen.needs.health = 80

        partial = mutate(client, sid, aftermath, tick=end + 10)
        reconcile(client, observer)
        later = get(client, sid, "events/" + eid, partial).json()["data"]
        assert later["followup"]["city"]["deaths"] == 1
        assert later["followup"]["city"]["health"] == 80
        assert later["followup"]["city"]["population"] == 9
        assert later["followup"]["denominators"]["city"]["health"] == 9
        assert not later["followup_complete"]
        # Postevent health changes have no event evidence: window membership is temporal.
        health_changes = get(client, sid, "changes", partial, event_id=eid, start_tick=end + 1).json()[
            "data"
        ]["items"]
        assert health_changes and all(c["link"] == "temporal" for c in health_changes)
        complete = mutate(client, sid, lambda _: None, tick=end + 30)
        reconcile(client, observer)
        assert get(client, sid, "events/" + eid, complete).json()["data"]["followup_complete"]
        pinned = get(client, sid, "events/" + eid, revision).json()["data"]
        assert pinned["followup"]["city"]["deaths"] == 0


def test_same_tick_revisions_and_direct_health_evidence(tmp_path):
    with connected(tmp_path) as (client, _, observer):
        sim = create_city(client)
        sid = sim["id"]
        aid = next(iter(client.app.state.service.heads[sid].citizens))
        first = mutate(client, sid, lambda s: setattr(s.citizens[aid].needs, "health", 70), tick=1)

        def change(state):
            citizen = state.citizens[aid]
            citizen.needs.health = 50
            citizen.condition.impacts.append(
                Impact(
                    tick=1,
                    phase="test",
                    meter="health",
                    reason="Flood",
                    delta=-20,
                    evidence=evidence("Flood injury", event_ids=["event_flood"]),
                )
            )

        last = mutate(client, sid, change, tick=1)
        reconcile(client, observer)
        assert (
            get(client, sid, "trends", first, metric="health", agent_id=aid).json()["data"]["items"][-1][
                "mean"
            ]
            == 70
        )
        assert (
            get(client, sid, "trends", last, metric="health", agent_id=aid).json()["data"]["items"][-1][
                "mean"
            ]
            == 50
        )
        change_rows = get(client, sid, "changes", last, event_id="event_flood").json()["data"]["items"]
        assert len(change_rows) == 1 and change_rows[0]["link"] == "explicit"
        assert change_rows[0]["evidence"]["records"][0]["event_ids"] == ["event_flood"]


def test_panel_concurrent_reads_succeed_with_bounded_warehouse_access(tmp_path):
    with connected(tmp_path) as (client, fake, observer):
        sim = create_city(client)
        reconcile(client, observer)
        original = fake.execute

        async def slow(shape, values=()):
            if shape in {"obs_head", "obs_trends"}:
                await asyncio.sleep(0.01)
            return await original(shape, values)

        fake.execute = slow

        async def queries():
            return await asyncio.gather(
                *(
                    observer.query("demo_owner", sim["id"], "trends", sim["revision"], metric=metric)
                    for metric in ("health", "trust", "relationship_trust", "opinion_count")
                )
            )

        results = client.portal.call(queries)
        assert all(r["items"] for r in results)
