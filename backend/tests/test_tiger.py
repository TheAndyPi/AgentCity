"""T-01..T-06: exact read-back, loss/restart, isolation and public child routes."""

import asyncio
import copy
import os
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from conftest import command, commit_preview, create_city, preview, write
from fastapi import Request
from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.infrastructure.errors import DomainError
from app.integrations import tiger
from app.main import create_app


class ControlledSink:
    def __init__(self):
        self.rows = {}
        self.provenance = {}
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.changed = asyncio.Event()
        self.block = False
        self.fail = False
        self.lose_ack = False

    async def migrate(self):
        pass

    async def ingest(self, batch):
        self.entered.set()
        if self.block:
            await self.release.wait()
        if self.fail:
            raise ConnectionError("postgresql://secret:password@private-host/private-db")
        self.calls.append((batch.simulation_id, batch.revision))
        self.provenance[batch.simulation_id] = batch.provenance
        for kind, key, tick, payload in batch.records:
            identity = (batch.simulation_id, kind, key)
            old = self.rows.get(identity)
            revision = payload["revision"] if kind == "metric" else batch.revision
            if old is None or (old[0] < revision and old[2] != payload):
                self.rows[identity] = (revision, tick, copy.deepcopy(payload))
        self.changed.set()
        if self.lose_ack:
            self.lose_ack = False
            raise ConnectionError("Lost acknowledgement")


def client_for(config):
    return TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def csrf(client):
    client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]


@pytest.fixture
def integrated(tmp_path, monkeypatch):
    sink = ControlledSink()
    monkeypatch.setattr(tiger, "PostgresSink", lambda config: sink)
    config = AppConfig(
        data_dir=tmp_path / "store",
        tiger_enabled=True,
        tiger_database_url="unused-by-fake",
        tiger_retry_min=0.01,
        tiger_retry_max=0.02,
        tiger_poll_seconds=0.01,
    )
    with client_for(config) as client:
        csrf(client)
        yield client, sink, config


def caught_up(client, sid):
    async def wait():
        worker = client.app.state.service.tiger
        async with asyncio.timeout(10):
            while worker._revision(sid) < client.app.state.service.heads[sid].simulation.revision:
                await asyncio.sleep(0.001)
        return worker._revision(sid)

    return client.portal.call(wait)


def values(sink, sid, kind):
    return {
        key: row[2]
        for (simulation, category, key), row in sink.rows.items()
        if simulation == sid and category == kind
    }


def assert_export_rows(sink, export):
    sid = export["simulation"]["id"]
    latest = {}
    for point in sorted(values(sink, sid, "metric").values(), key=lambda p: p["revision"]):
        if point["revision"] <= export["simulation"]["revision"]:
            latest[point["tick"]] = point
    assert latest == {p["tick"]: p for p in export["metrics"]}
    assert values(sink, sid, "decision") == {p["id"]: p for p in export["decisions"]}
    movement = {
        f"{f['ref']['revision']}:{a['id']}": a
        for f in export["frames"]
        if f["ref"]["tick"] % 2 == 0
        for a in f["agents"]
    }
    assert values(sink, sid, "movement") == movement
    revision = export["simulation"]["revision"]
    events = values(sink, sid, "event")
    assert {f"{revision}:{e['event']['id']}": e for e in export["events"]} == {
        key: value for key, value in events.items() if key.startswith(f"{revision}:")
    }
    assert sum(p["resources_consumed"] for p in latest.values()) == sum(
        p["resources_consumed"] for p in export["metrics"]
    )


def test_t01_exact_committed_records_and_no_initialization_placeholders(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    hold, plan = preview(client, sid)
    assert commit_preview(client, sid, hold, plan).status_code == 201
    assert command(client, sid, "step", count=2).status_code == 200
    caught_up(client, sid)
    export = client.get(f"/api/v1/simulations/{sid}/export").json()["data"]
    assert export["decisions"] and export["events"] and len(export["metrics"]) == 3
    assert_export_rows(sink, export)
    ready_revision = export["frames"][0]["ref"]["revision"]
    assert all(row[0] >= ready_revision for key, row in sink.rows.items() if key[0] == sid)
    status = client.get("/api/v1/integrations/tiger/status", params={"simulation_id": sid}).json()["data"]
    assert status["simulations"] == [
        dict(
            simulation_id=sid,
            published_revision=export["simulation"]["revision"],
            ingested_revision=export["simulation"]["revision"],
            lag_revisions=0,
        )
    ]


def test_t02_duplicate_delivery_and_lost_ack_are_idempotent(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    sink.lose_ack = True
    assert command(client, sid, "step", count=2).status_code == 200
    caught_up(client, sid)
    baseline = copy.deepcopy(sink.rows)
    worker = client.app.state.service.tiger
    client.portal.call(worker.close)
    client.portal.call(lambda: worker.progress.clear())
    client.portal.call(worker.reconcile)
    while worker._revision(sid) < client.app.state.service.heads[sid].simulation.revision:
        client.portal.call(worker.reconcile)
    assert sink.rows == baseline
    assert len(sink.calls) > len(set(sink.calls))
    assert_export_rows(sink, client.get(f"/api/v1/simulations/{sid}/export").json()["data"])


def test_t01_metric_versions_preserve_an_earlier_same_tick_pin(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    before = client.get(f"/api/v1/simulations/{sid}/export").json()["data"]
    agent = before["frames"][-1]["agents"][0]["id"]
    response = command(
        client,
        sid,
        "override_agent",
        agent_id=agent,
        metrics={"stress": 99},
        goal=None,
        memory_text=None,
        intent=None,
    )
    assert response.status_code == 200, response.text
    caught_up(client, sid)
    after = client.get(f"/api/v1/simulations/{sid}/export").json()["data"]
    assert before["simulation"]["tick"] == after["simulation"]["tick"]
    assert before["metrics"][-1] != after["metrics"][-1]
    versions = values(sink, sid, "metric")
    assert before["metrics"][-1] in versions.values()
    assert after["metrics"][-1] in versions.values()


def test_t03_branch_identity_lineage_and_source_deletion(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    assert command(client, sid, "step", count=2).status_code == 200
    caught_up(client, sid)
    source = copy.deepcopy(values(sink, sid, "decision"))
    response = write(
        client, f"/simulations/{sid}/branches", {"name": "Tiger branch", "source": {"kind": "whole"}}
    )
    assert response.status_code == 201, response.text
    branch = response.json()["data"]["simulation"]
    bid = branch["id"]
    caught_up(client, bid)
    assert values(sink, bid, "decision") == source
    assert sink.provenance[bid]["parent_simulation_id"] == sid
    assert sink.provenance[bid]["fork_ref"] == branch["fork_ref"]
    assert command(client, bid, "step", count=1).status_code == 200
    caught_up(client, bid)
    assert values(sink, sid, "decision") == source
    assert_export_rows(sink, client.get(f"/api/v1/simulations/{bid}/export").json()["data"])


def test_t04_restart_replays_after_external_commit_before_local_cursor(integrated, monkeypatch):
    client, sink, config = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    worker = client.app.state.service.tiger
    original = worker._save
    failed = asyncio.Event()

    def no_progress(progress):
        failed.set()
        raise OSError("Progress write interrupted")

    monkeypatch.setattr(worker, "_save", no_progress)
    assert command(client, sid, "step", count=1).status_code == 200

    async def wait():
        async with asyncio.timeout(5):
            while not failed.is_set():
                await asyncio.sleep(0.001)

    client.portal.call(wait)
    client.portal.call(worker.close)
    before = worker._revision(sid)
    committed = client.app.state.service.heads[sid].simulation.revision
    assert before < committed
    monkeypatch.setattr(worker, "_save", original)
    # Simulate a new worker after a crash: discard all volatile progress.
    restarted = tiger.TigerIngestor(client.app.state.service, sink)
    client.app.state.service.tiger = restarted
    client.portal.call(restarted.start)
    assert caught_up(client, sid) == committed
    baseline = copy.deepcopy(sink.rows)
    client.portal.call(restarted.close)
    # Real service restart uses the same persistent DATA_DIR and fake database.
    client.portal.call(client.app.state.service.close)
    with client_for(config) as second:
        csrf(second)
        assert caught_up(second, sid) == committed
        assert sink.rows == baseline
        assert_export_rows(sink, second.get(f"/api/v1/simulations/{sid}/export").json()["data"])


def test_t05_failed_manifest_never_ingested(integrated, monkeypatch):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    baseline = copy.deepcopy(sink.rows)
    revision = client.app.state.service.heads[sid].simulation.revision

    def fail(value):
        raise OSError("Injected manifest failure")

    monkeypatch.setattr(client.app.state.service.repo, "_manifest", fail)
    response = command(client, sid, "step", count=1)
    assert response.status_code == 503
    assert client.app.state.service.heads[sid].simulation.revision == revision
    client.portal.call(client.app.state.service.tiger.reconcile)
    assert sink.rows == baseline
    assert (sid, revision + 1) not in sink.calls


def test_t05_blocked_database_does_not_hold_writer_or_http(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    sink.block = True
    client.portal.call(sink.entered.clear)
    assert command(client, sid, "step", count=1).status_code == 200

    async def entered():
        await asyncio.wait_for(sink.entered.wait(), 2)

    client.portal.call(entered)
    # The DB is demonstrably still blocked across both HTTP writes and reads.
    start = time.monotonic()
    assert command(client, sid, "step", count=1).status_code == 200
    assert command(client, sid, "set_speed", value=1).status_code == 200
    assert client.get(f"/api/v1/simulations/{sid}/state").json()["data"]["simulation"]["tick"] == 2
    assert time.monotonic() - start < 5
    assert not sink.release.is_set()
    status = client.get("/api/v1/integrations/tiger/status").json()["data"]
    assert status["simulations"][0]["lag_revisions"] > 0
    client.portal.call(sink.release.set)
    caught_up(client, sid)


def test_t05_outage_reports_safe_failure_and_recovers(integrated, caplog):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    sink.fail = True
    assert command(client, sid, "step", count=1).status_code == 200

    async def failed():
        worker = client.app.state.service.tiger
        async with asyncio.timeout(5):
            while worker.error_code is None:
                await asyncio.sleep(0.001)

    client.portal.call(failed)
    response = client.get("/api/v1/integrations/tiger/status")
    assert response.json()["data"]["state"] == "unavailable"
    assert response.json()["data"]["error_code"] == "INGESTION_UNAVAILABLE"
    assert "password" not in response.text + caplog.text
    assert "private-host" not in response.text + caplog.text
    assert client.get("/health/ready").status_code == 200
    sink.fail = False
    caught_up(client, sid)


def test_t06_child_auth_owner_validation_and_error_envelopes(tmp_path):
    config = AppConfig(
        data_dir=tmp_path,
        auth_mode="session",
        session_secret="s" * 40,
        demo_passphrase="test",
        allowed_origins=("https://city.example",),
    )
    with TestClient(create_app(config), base_url="https://city.example") as client:
        path = "/api/v1/integrations/tiger/status"
        denied = client.get(path)
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "UNAUTHENTICATED"
        client.headers["Origin"] = "https://city.example"
        login = write(client, "/session", {"passphrase": "test"})
        assert login.status_code == 200
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        sid = create_city(client)["id"]
        assert client.get(path).json()["data"]["state"] == "disabled"
        for url in (path + "?limit=0", path + "?limit=101"):
            response = client.get(url)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        response = client.get("/api/v1/integrations/missing")
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
        client.app.state.service.heads[sid].owner_id = "someone_else"
        assert client.get(path).json()["data"]["simulations"] == []
        assert client.get(path, params={"simulation_id": sid}).status_code == 404
        client.headers["Origin"] = "https://evil.example"
        assert client.get(path).status_code == 403


def test_extension_openapi_is_separate_and_documented(client):
    parent = client.get("/openapi.json").json()
    child = client.get("/api/v1/integrations/openapi.json").json()
    assert not any("integrations" in key for key in parent["paths"])
    assert "/tiger/status" in child["paths"]
    assert "TigerStatus" in child["components"]["schemas"]


def test_child_write_security_and_sanitized_handlers(client):
    child = next(
        route.app for route in client.app.routes if getattr(route, "path", "") == "/api/v1/integrations"
    )

    @child.post("/test-control")
    async def control(request: Request):
        assert request.app.state.service is client.app.state.service
        raise DomainError("INVALID_STATE", "Controlled domain failure", 409)

    path = "/api/v1/integrations/test-control"
    assert client.post(path).status_code == 400
    assert client.post(path, headers={"Idempotency-Key": uuid4().hex}).status_code == 400
    assert (
        client.post(path, headers={"Idempotency-Key": str(uuid4()), "X-CSRF-Token": "bad"}).status_code == 403
    )
    result = client.post(path, headers={"Idempotency-Key": str(uuid4())})
    assert result.status_code == 409
    assert result.json()["error"] == dict(
        code="INVALID_STATE", message="Controlled domain failure", retryable=False, details=[]
    )


def test_invalid_progress_replays_instead_of_skipping(integrated):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    worker = client.app.state.service.tiger
    client.portal.call(worker.close)
    worker.path.write_text('{"data": {}, "sha256": "bad"}', encoding="utf-8")
    baseline = copy.deepcopy(sink.rows)
    restarted = tiger.TigerIngestor(client.app.state.service, sink)
    client.app.state.service.tiger = restarted
    client.portal.call(restarted.start)
    caught_up(client, sid)
    assert sink.rows == baseline


def test_projection_size_is_bounded_without_skipping_progress(integrated, monkeypatch):
    client, sink, _ = integrated
    sid = create_city(client)["id"]
    caught_up(client, sid)
    revision = client.app.state.service.tiger._revision(sid)
    monkeypatch.setattr(tiger, "MAX_BYTES", 1)
    assert command(client, sid, "step", count=1).status_code == 200

    async def failed():
        async with asyncio.timeout(5):
            while client.app.state.service.tiger.error_code != "PROJECTION_LIMIT":
                await asyncio.sleep(0.001)

    client.portal.call(failed)
    assert client.app.state.service.tiger._revision(sid) == revision


@pytest.mark.parametrize(
    "field,value",
    [
        ("tiger_timeout", 0),
        ("tiger_timeout", 31),
        ("tiger_revision_batch", 17),
        ("tiger_schema", "bad; DROP TABLE users"),
        ("tiger_sample_ticks", 0),
    ],
)
def test_tiger_config_bounds(field, value):
    with pytest.raises(ValueError):
        replace(AppConfig(), **{field: value}).validate()


@pytest.mark.skipif(
    not os.getenv("TIGER_TEST_DATABASE_URL"), reason="opt-in disposable TLS PostgreSQL required"
)
def test_t06_real_postgres_migrations_upserts_and_totals(tmp_path):
    """Uses a new schema only; finally drops exactly that disposable schema."""
    import certifi
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    schema = "tiger_test_" + uuid4().hex
    config = AppConfig(
        data_dir=tmp_path / "store",
        tiger_database_url=make_conninfo(
            os.environ["TIGER_TEST_DATABASE_URL"],
            sslrootcert=conninfo_to_dict(os.environ["TIGER_TEST_DATABASE_URL"]).get(
                "sslrootcert", certifi.where()
            ),
        ),
        tiger_schema=schema,
    )
    with psycopg.connect(config.tiger_database_url, sslmode="verify-full", connect_timeout=5) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        sink = tiger.PostgresSink(config)
        with client_for(config) as client:
            csrf(client)
            sid = create_city(client)["id"]
            hold, plan = preview(client, sid)
            assert commit_preview(client, sid, hold, plan).status_code == 201
            assert command(client, sid, "step", count=2).status_code == 200
            export = client.get(f"/api/v1/simulations/{sid}/export").json()["data"]
            service = client.app.state.service

            async def ingest():
                await sink.migrate()
                await sink.migrate()
                for revision in range(service.heads[sid].simulation.revision + 1):
                    state = service.repo.read(sid, revision)
                    batch = tiger.project(state, service.heads[sid].simulation, 2)
                    await sink.ingest(batch)
                    await sink.ingest(batch)

            client.portal.call(ingest)
            expected = ControlledSink()
            for revision in range(service.heads[sid].simulation.revision + 1):
                batch = tiger.project(service.repo.read(sid, revision), service.heads[sid].simulation, 2)
                client.portal.call(expected.ingest, batch)
            with psycopg.connect(
                config.tiger_database_url, sslmode="verify-full", connect_timeout=5
            ) as connection:
                connection.execute(
                    sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema))
                )
                rows = connection.execute(
                    "SELECT simulation_id,kind,entity_key,revision,tick,payload FROM tiger_records"
                ).fetchall()
                assert {(a, b, c): (d, e, f) for a, b, c, d, e, f in rows} == expected.rows
                assert_export_rows(expected, export)
                progress = connection.execute("SELECT simulation_id,revision FROM tiger_progress").fetchall()
                assert progress == [(sid, export["simulation"]["revision"])]
                assert connection.execute("SELECT count(*) FROM tiger_migrations").fetchone() == (1,)
                assert connection.execute(
                    "SELECT count(*) FROM tiger_records WHERE ingested_at IS NULL OR sim_time_seconds < 0"
                ).fetchone() == (0,)

            async def blocked_query(connection):
                await connection.execute("SELECT pg_sleep(30)")

            bounded = tiger.PostgresSink(replace(config, tiger_timeout=0.2))
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                client.portal.call(bounded._call, blocked_query)
            assert time.monotonic() - started < 5
    finally:
        with psycopg.connect(
            config.tiger_database_url, sslmode="verify-full", connect_timeout=5
        ) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.skipif(
    not os.getenv("TIGER_TEST_DATABASE_URL"), reason="opt-in disposable TLS PostgreSQL required"
)
def test_t06_real_postgres_public_worker_branch_and_restart(tmp_path):
    import certifi
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    schema = "tiger_test_" + uuid4().hex
    url = make_conninfo(
        os.environ["TIGER_TEST_DATABASE_URL"],
        sslrootcert=conninfo_to_dict(os.environ["TIGER_TEST_DATABASE_URL"]).get(
            "sslrootcert", certifi.where()
        ),
    )
    config = AppConfig(
        data_dir=tmp_path / "store",
        tiger_enabled=True,
        tiger_database_url=url,
        tiger_schema=schema,
        tiger_timeout=20,
    )
    with psycopg.connect(url, sslmode="verify-full", connect_timeout=5) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def rows():
        with psycopg.connect(url, sslmode="verify-full", connect_timeout=5) as connection:
            connection.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema)))
            sink = ControlledSink()
            records = connection.execute(
                "SELECT simulation_id,kind,entity_key,revision,tick,payload FROM tiger_records"
            ).fetchall()
            sink.rows = {
                (sid, kind, key): (revision, tick, payload)
                for sid, kind, key, revision, tick, payload in records
            }
            sink.provenance = dict(
                connection.execute("SELECT simulation_id,provenance FROM tiger_simulations").fetchall()
            )
            return sink

    try:
        with client_for(config) as client:
            csrf(client)
            sid = create_city(client)["id"]
            assert command(client, sid, "step", count=2).status_code == 200
            caught_up(client, sid)
            branch = write(
                client, f"/simulations/{sid}/branches", {"name": "SQL branch", "source": {"kind": "whole"}}
            )
            assert branch.status_code == 201
            bid = branch.json()["data"]["simulation"]["id"]
            assert command(client, bid, "step", count=1).status_code == 200
            caught_up(client, bid)
            baseline = {
                key: client.get(f"/api/v1/simulations/{key}/export").json()["data"] for key in (sid, bid)
            }
            persisted = rows()
            for export in baseline.values():
                assert_export_rows(persisted, export)
            assert persisted.provenance[bid]["parent_simulation_id"] == sid
            status = client.get("/api/v1/integrations/tiger/status").json()["data"]
            assert all(item["lag_revisions"] == 0 for item in status["simulations"])
        with client_for(config) as client:
            caught_up(client, sid)
            caught_up(client, bid)
            assert rows().rows == persisted.rows
            for key, export in baseline.items():
                assert client.get(f"/api/v1/simulations/{key}/export").json()["data"] == export
    finally:
        with psycopg.connect(url, sslmode="verify-full", connect_timeout=5) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
