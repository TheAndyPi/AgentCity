import asyncio
import copy
import json
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from conftest import command, create_city, write
from fastapi.testclient import TestClient
from snowflake_fake import SnowflakeFake

from app.infrastructure.config import AppConfig
from app.snowflake.application import create_app
from app.snowflake.comparison import METRICS, stage
from app.snowflake.config import SnowflakeConfig
from app.snowflake.dto import ComparisonResponse, Failure
from app.snowflake.ledger import Ledger
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable


@contextmanager
def connected(tmp_path, fake=None, config=None):
    fake = fake or SnowflakeFake()
    # The fake never authenticates externally. A readable source file satisfies
    # startup validation; token_factory replaces signing only in these tests.
    snow = SnowflakeConfig(
        enabled=True,
        account="test-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=__file__,
    )
    app = create_app(config or AppConfig(data_dir=tmp_path / "store"), snow, fake.transport(snow))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        yield client, fake, app


def pair(client):
    a = create_city(client)
    assert command(client, a["id"], "step", count=2).status_code == 200
    a = client.get(f"/api/v1/simulations/{a['id']}").json()["data"]
    response = write(
        client, f"/simulations/{a['id']}/branches", {"name": "Comparison B", "source": {"kind": "whole"}}
    )
    assert response.status_code == 201, response.text
    b = response.json()["data"]["simulation"]
    assert command(client, b["id"], "step", count=1).status_code == 200
    b = client.get(f"/api/v1/simulations/{b['id']}").json()["data"]
    return {
        "a": {"simulation_id": a["id"], "revision": a["revision"]},
        "b": {"simulation_id": b["id"], "revision": b["revision"]},
        "question": "What recorded differences accompany lower cooperation in B?",
    }


def compare(client, body, key=None):
    return write(client, "/integrations/snowflake/comparisons", body, key=key)


def export(client, pin):
    return client.get(
        f"/api/v1/simulations/{pin['simulation_id']}/export", params={"through_revision": pin["revision"]}
    ).json()["data"]


def test_s01_s02_exact_readback_branch_keys_and_pinned_citations(tmp_path):
    with connected(tmp_path) as (client, fake, _):
        body = pair(client)
        originals = [export(client, body[s]) for s in ("a", "b")]
        result = compare(client, body)
        assert result.status_code == 200, result.text
        ComparisonResponse.model_validate(result.json())
        data = result.json()["data"]
        assert data["data_source"] == "snowflake"
        assert data["horizon"] == "unequal_endpoint_ticks"
        assert data["lineage"] == "parent_branch"
        assert data["explanation"]["source"] == "cortex_selection"
        assert data["a"]["endpoint_tick"] == 2 and data["b"]["endpoint_tick"] == 3
        assert data["b"]["parent_simulation_id"] == body["a"]["simulation_id"]
        assert data["b"]["fork_ref"] is not None
        for i, metric in enumerate(METRICS):
            source_values = [
                (v["metrics"][-1]["values"] if i < 5 else v["metrics"][-1])[metric] for v in originals
            ]
            d = data["differences"][i]
            assert [d["a"], d["b"]] == source_values
            assert d["delta_b_minus_a"] == pytest.approx(source_values[1] - source_values[0], abs=1e-12)
        assert data["citations"]
        for c in data["citations"]:
            r = client.get(c["url"])
            assert r.status_code == 200
            record = r.json()["data"]
            assert (record["id"] if c["kind"] == "decision" else record["event"]["id"]) == c["record_id"]
        shared = set(d["id"] for d in originals[0]["decisions"]) & set(
            d["id"] for d in originals[1]["decisions"]
        )
        assert shared  # Same inherited IDs live under separate simulation keys.
        assert len(fake.rows) == 2
        before = copy.deepcopy(fake.rows)
        assert compare(client, body).status_code == 200
        assert fake.rows == before
        assert command(client, body["b"]["simulation_id"], "step", count=1).status_code == 200
        again = compare(client, body).json()["data"]
        assert again["differences"] == data["differences"]
        assert again["a"] == data["a"] and again["b"] == data["b"]


@pytest.mark.parametrize(
    "output",
    [
        '{"fact_ids":["invented:record"]}',
        '{"fact_ids":["cooperation_count"],"made_up_number":999}',
        '{"fact_ids":["happiness"]}',
        "not json",
        '{"fact_ids":[]}',
    ],
)
def test_s03_rejects_unresolved_citations_invented_numbers_and_malformed_output(tmp_path, output):
    fake = SnowflakeFake()
    fake.model_output = output
    with connected(tmp_path, fake) as (client, _, __):
        response = compare(client, pair(client))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["data_source"] == "snowflake"
        assert data["explanation"]["source"] == "deterministic"
        assert data["explanation"]["status"] == "unavailable"
        assert "invented" not in response.text and "999" not in json.dumps(data["explanation"])


@pytest.mark.parametrize(
    "side,change,status",
    [
        ("a", {"simulation_id": "missing"}, 404),
        ("b", {"revision": 9999}, 404),
        ("a", {"revision": -1}, 422),
        ("b", {"revision": 1.5}, 422),
    ],
)
def test_s04_invalid_pairs_rejected_before_vendor_calls(tmp_path, side, change, status):
    with connected(tmp_path) as (client, fake, _):
        body = pair(client)
        body[side].update(change)
        response = compare(client, body)
        assert response.status_code == status, response.text
        Failure.model_validate(response.json())
        assert fake.calls == []


def test_s04_ownership_is_checked_even_for_cached_result(tmp_path):
    with connected(tmp_path) as (client, fake, app):
        body = pair(client)
        key = str(uuid4())
        assert compare(client, body, key).status_code == 200
        count = len(fake.calls)
        app.state.service.heads[body["b"]["simulation_id"]].owner_id = "other_owner"
        assert compare(client, body, key).status_code == 404
        assert len(fake.calls) == count


def test_s04_unrelated_equal_horizon_and_missing_endpoint_records(tmp_path):
    with connected(tmp_path) as (client, fake, _):
        a, b = create_city(client), create_city(client, seed=7)
        body = {
            s: {"simulation_id": sim["id"], "revision": sim["revision"]} for s, sim in (("a", a), ("b", b))
        }
        data = compare(client, body).json()["data"]
        assert data["lineage"] == "unrelated" and data["horizon"] == "equal_endpoint_ticks"
        assert data["citations"] == []
        raw = export(client, body["a"])
        raw["metrics"] = []
        with pytest.raises(Exception, match="Endpoint metrics are absent"):
            stage(raw)
        assert len(fake.rows) == 2


def test_s05_response_loss_retry_and_changed_body_conflict_survive_restart(tmp_path):
    fake = SnowflakeFake()
    with connected(tmp_path, fake) as (client, _, __):
        body, key = pair(client), str(uuid4())
        first = compare(client, body, key)
        calls = len(fake.calls)
        assert first.status_code == 200, first.text
        assert compare(client, body, key).json() == first.json()  # lost acknowledgement
        assert len(fake.calls) == calls
        changed = body | {"question": "A different question"}
        assert compare(client, changed, key).status_code == 409
        assert len(fake.calls) == calls
    with connected(tmp_path, fake) as (client, _, __):
        assert compare(client, body, key).json() == first.json()
        assert len(fake.calls) == calls


@pytest.mark.parametrize(
    "shape,source", [("ingest", "local_export"), ("query", "local_export"), ("explain", "snowflake")]
)
def test_s05_outages_have_truthful_provenance_and_no_secret_leak(tmp_path, shape, source):
    fake = SnowflakeFake()
    fake.fail_shape = shape
    with connected(tmp_path, fake) as (client, _, __):
        key, body = str(uuid4()), pair(client)
        response = compare(client, body, key)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["data_source"] == source and data["explanation"]["status"] == "unavailable"
        assert data["explanation"]["source"] == "deterministic"
        assert "secret vendor" not in response.text
        assert compare(client, body, key).json() == response.json()
        assert len([s for s, _ in fake.calls if s == shape]) == 1


def test_corrupt_readback_is_not_presented_as_snowflake_facts(tmp_path):
    fake = SnowflakeFake()
    fake.corrupt = True
    with connected(tmp_path, fake) as (client, _, __):
        data = compare(client, pair(client)).json()["data"]
        assert data["data_source"] == "local_export"
        assert not any(shape == "explain" for shape, _ in fake.calls)


def test_pending_receipt_never_repeats_and_daily_budget_is_durable(tmp_path):
    path = tmp_path / "receipt.sqlite3"
    ledger = Ledger(path)
    ledger.begin("owner", "key", "fingerprint")
    assert ledger.reserve_model(1) is True
    ledger.close()
    ledger = Ledger(path)
    with pytest.raises(Exception, match="will not repeat vendor charges"):
        ledger.lookup("owner", "key", "fingerprint")
    assert ledger.reserve_model(1) is False
    ledger.close()


def test_security_envelopes_disabled_and_extension_openapi(tmp_path):
    with connected(tmp_path) as (client, fake, app):
        body = pair(client)
        token = client.headers.pop("X-CSRF-Token")
        assert compare(client, body).status_code == 403
        client.headers["X-CSRF-Token"] = token
        assert compare(client, body, "bad-key").status_code == 400
        response = client.post(
            "/api/v1/integrations/snowflake/comparisons",
            json=body,
            headers={"Idempotency-Key": str(uuid4()), "Origin": "https://evil.invalid"},
        )
        assert response.status_code == 403
        assert fake.calls == []
        ext = client.get("/api/v1/integrations/openapi.json").json()
        assert "/snowflake/comparisons" in ext["paths"]
        assert "ComparisonResponse" in ext["components"]["schemas"]
        assert all("snowflake" not in p for p in app.openapi()["paths"])
    with TestClient(
        create_app(AppConfig(data_dir=tmp_path / "disabled"), SnowflakeConfig()),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        response = compare(client, body)
        assert response.status_code == 501
        Failure.model_validate(response.json())
        assert client.get("/api/v1/capabilities").json()["data"]["snowflake"] is False


def test_transport_bounds_async_polling_429_and_timeout():
    config = SnowflakeConfig(account="fake", deadline=0.05)

    async def run():
        for status in [429, 503, 200, 202]:
            calls = []

            def handle(request):
                calls.append(request)
                return httpx.Response(status, json={"data": [["ok"]], "statementHandle": "handle"})

            transport = SnowflakeTransport(
                config,
                httpx.AsyncClient(transport=httpx.MockTransport(handle)),
                token_factory=lambda _: "fake",
            )
            if status == 200:
                assert await transport.execute("query", ("a", "b", 1)) == [["ok"]]
            else:
                with pytest.raises(VendorUnavailable):
                    await transport.execute("query", ("a", "b", 1))
            assert len([r for r in calls if r.method == "POST"]) == 1
            await transport.close()

    asyncio.run(run())


def test_s01_literal_fixture_deltas_missing_counts_and_unequal_ticks():
    from app.snowflake.comparison import build, digest

    def fixture(sid, tick, values, counts):
        return {
            "simulation": {
                "id": sid,
                "revision": 8,
                "tick": tick,
                "sim_time_seconds": tick * 5,
                "parent_simulation_id": None,
                "fork_ref": None,
                "config": {"seed": 42},
            },
            "endpoint": {"tick": tick, "revision": 8, "values": values, **counts},
            "events": [],
            "decisions": [],
        }

    a = fixture(
        "a",
        2,
        dict(happiness=61.25, safety=70, trust=40, resources=52.5, stress=18.75),
        dict(cooperation_count=7, conflict_count=1, evacuated_count=3, resources_consumed=4.25),
    )
    b = fixture(
        "b",
        5,
        dict(happiness=59, safety=75, trust=41.5, resources=50, stress=20),
        dict(cooperation_count=4, conflict_count=2, evacuated_count=5, resources_consumed=6),
    )
    result = build(a, b, [digest(a), digest(b)], [None, None], "local_export")
    assert [d.delta_b_minus_a for d in result.differences] == [
        -2.25,
        5,
        1.5,
        -2.5,
        1.25,
        -3,
        1,
        1.75,
        2,
        None,
    ]
    assert result.differences[-1].a is None and result.differences[-1].b is None
    assert result.horizon == "unequal_endpoint_ticks"


def test_s05_blocked_vendor_allows_ticks_and_holds_single_comparison_gate(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started, release = threading.Event(), threading.Event()
    fake = SnowflakeFake()
    with connected(tmp_path, fake) as (client, _, app):
        body = pair(client)
        key = str(uuid4())
        snow = app.state.integrations.state.comparison

        async def blocked(request):
            value = json.loads(request.content)
            if value["statement"].startswith("MERGE") and not started.is_set():
                started.set()
                await asyncio.to_thread(release.wait, 10)
            return fake.handle(request)

        snow.transport.client = httpx.AsyncClient(transport=httpx.MockTransport(blocked))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(compare, client, body, key)
            try:
                assert started.wait(5)
                # Pending exact retries do not submit SQL/model requests.
                assert compare(client, body, key).status_code == 503
                assert compare(client, body | {"question": "changed"}, key).status_code == 409
                assert compare(client, body).status_code == 429
                stepped = command(client, body["a"]["simulation_id"], "step", count=1)
                assert stepped.status_code == 200
                assert stepped.json()["data"]["simulation"]["tick"] == 3
            finally:
                release.set()
            response = pending.result(timeout=10)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["a"]["endpoint_tick"] == 2  # Head advanced while SQL was blocked.
        assert data["a"]["revision"] == body["a"]["revision"]
        assert len([shape for shape, _ in fake.calls if shape == "explain"]) == 1


def test_s05_disconnected_caller_keeps_gate_and_receipt_until_completion(tmp_path):
    from starlette.requests import Request

    from app.snowflake.dto import ComparisonRequest

    with connected(tmp_path) as (client, fake, app):
        body = ComparisonRequest.model_validate(pair(client))
        snow = app.state.integrations.state.comparison
        key = str(uuid4())

        async def run():
            started, release = asyncio.Event(), asyncio.Event()

            async def blocked(request):
                if not started.is_set():
                    started.set()
                    await release.wait()
                return fake.handle(request)

            snow.transport.client = httpx.AsyncClient(transport=httpx.MockTransport(blocked))
            request = Request(
                {"type": "http", "app": app, "state": {"owner": "demo_owner", "request_id": key}}
            )
            caller = asyncio.create_task(snow.compare(request, body))
            await asyncio.wait_for(started.wait(), 5)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert snow.gate.locked()
            release.set()
            await asyncio.gather(*snow.inflight)
            assert not snow.gate.locked()
            count = len(fake.calls)
            replay = await snow.compare(request, body)
            assert replay["request_id"] == key
            assert len(fake.calls) == count

        client.portal.call(run)


def test_session_auth_origin_csrf_and_revocation(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "session",
        auth_mode="session",
        session_secret="x" * 32,
        demo_passphrase="test-pass",
        allowed_origins=("https://localhost",),
    )
    app = create_app(config, SnowflakeConfig())
    with TestClient(app, base_url="https://localhost", client=("127.0.0.1", 50000)) as client:
        body = {"a": {"simulation_id": "a", "revision": 2}, "b": {"simulation_id": "b", "revision": 2}}
        client.headers["Origin"] = "https://localhost"
        assert compare(client, body).status_code == 401
        login = write(client, "/session", {"passphrase": "test-pass"})
        assert login.status_code == 200
        assert compare(client, body).status_code == 403  # missing CSRF
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        assert compare(client, body).status_code == 501
        assert write(client, "/session", {}, method="DELETE").status_code == 200
        response = compare(client, body)
        assert response.status_code == 401
        Failure.model_validate(response.json())


def test_keypair_jwt_signature_subject_fingerprint_and_short_expiry(tmp_path):
    import base64
    import hashlib
    import time

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    from app.snowflake.transport import keypair_jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keyfile, passwordfile = tmp_path / "test.pem", tmp_path / "password"
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"offline-test"),
        )
    )
    passwordfile.write_bytes(b"offline-test\n")
    config = SnowflakeConfig(
        account="myorg-myaccount",
        user="test",
        private_key_file=str(keyfile),
        passphrase_file=str(passwordfile),
    )
    token = keypair_jwt(config)
    header, payload, signature = token.split(".")

    def decode(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    claims = json.loads(decode(payload))
    assert claims["sub"] == "MYORG-MYACCOUNT.TEST"
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    assert (
        claims["iss"]
        == claims["sub"] + ".SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
    )
    assert claims["exp"] - claims["iat"] == 300
    assert abs(claims["iat"] - time.time()) < 5
    key.public_key().verify(
        decode(signature), (header + "." + payload).encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_s01_event_citations_resolve_at_the_pinned_revision(tmp_path):
    from conftest import commit_preview, preview

    with connected(tmp_path) as (client, _, __):
        sid = create_city(client)["id"]
        hold, view = preview(client, sid)
        committed = commit_preview(client, sid, hold, view)
        assert committed.status_code == 201
        a = committed.json()["data"]["simulation"]
        assert command(client, sid, "step", count=2).status_code == 200
        b = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        body = {s: {"simulation_id": sid, "revision": sim["revision"]} for s, sim in (("a", a), ("b", b))}
        result = compare(client, body)
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        assert data["lineage"] == "same_history"
        events = [c for c in data["citations"] if c["kind"] == "event"]
        assert len(events) == 2
        for citation in events:
            record = client.get(citation["url"])
            assert record.status_code == 200
            assert record.json()["data"]["ref"]["revision"] == citation["revision"]
            assert record.json()["data"]["event"]["id"] == citation["record_id"]


def test_extension_openapi_snapshot_is_independent_of_core():
    from pathlib import Path

    from app.main import create_app as core
    from app.snowflake.router import create_snowflake_app

    actual = create_snowflake_app(core(), SnowflakeConfig()).openapi()
    saved = json.loads((Path(__file__).parents[2] / "docs/release/snowflake-openapi.json").read_text())
    assert actual == saved


def test_default_application_composes_tiger_and_snowflake_once(tmp_path, monkeypatch):
    from app.main import create_app as default_application

    snow = SnowflakeConfig(
        enabled=True,
        account="test-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=__file__,
    )
    fake = SnowflakeFake()
    monkeypatch.setattr(SnowflakeConfig, "from_env", classmethod(lambda cls: snow))
    monkeypatch.setattr("app.snowflake.router.SnowflakeTransport", lambda config: fake.transport(config))
    app = default_application(AppConfig(data_dir=tmp_path / "default-store"))
    assert sum(getattr(route, "path", "") == "/api/v1/integrations" for route in app.routes) == 1
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        assert client.get("/api/v1/capabilities").json()["data"]["snowflake"] is True
        assert client.get("/api/v1/integrations/tiger/status").json()["data"]["state"] == "disabled"
        schema = client.get("/api/v1/integrations/openapi.json").json()
        assert {"/tiger/status", "/snowflake/comparisons"} <= schema["paths"].keys()
        result = compare(client, pair(client))
        assert result.status_code == 200, result.text
        assert result.json()["data"]["data_source"] == "snowflake"
        assert result.json()["data"]["explanation"]["source"] == "cortex_selection"


def test_s02_ingestion_sql_request_identity_survives_ambiguous_submission():
    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ReadTimeout("acknowledgement lost")
            return httpx.Response(200, json={"data": [["1"]]})

        transport = SnowflakeTransport(
            SnowflakeConfig(account="fake", database="DB", schema="SCHEMA"),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)),
            token_factory=lambda _: "fake",
        )
        values = ("owner", "source", 3, "hash", "{}")
        with pytest.raises(VendorUnavailable):
            await transport.execute("ingest", values)
        await transport.execute("ingest", values)
        await transport.execute("ingest", ("owner", "branch", 3, "hash", "{}"))
        assert calls[0].url.params["requestId"] == calls[1].url.params["requestId"]
        assert calls[0].url.params["retry"] == calls[1].url.params["retry"] == "true"
        assert calls[2].url.params["requestId"] != calls[1].url.params["requestId"]
        assert json.loads(calls[1].content)["bindings"]["2"]["value"] == "source"
        await transport.close()

    asyncio.run(run())


def test_transport_async_handles_and_streamed_output_limit():
    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            if request.method == "POST":
                return httpx.Response(202, json={"statementHandle": "approved-handle"})
            return httpx.Response(200, json={"data": [["read-back"]]})

        config = SnowflakeConfig(account="fake", deadline=1)
        transport = SnowflakeTransport(
            config, httpx.AsyncClient(transport=httpx.MockTransport(handle)), token_factory=lambda _: "fake"
        )
        assert await transport.execute("query", ("owner", "city", 1)) == [["read-back"]]
        assert len(calls) == 2 and calls[1].method == "GET"
        assert calls[1].url.path == "/api/v2/statements/approved-handle"
        assert calls[1].url.host == calls[0].url.host
        await transport.close()
        for response in [
            httpx.Response(202, json={"statementHandle": "../../other-host"}),
            httpx.Response(200, content=b"x" * 2_000_001),
        ]:
            transport = SnowflakeTransport(
                config,
                httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)),
                token_factory=lambda _: "fake",
            )
            with pytest.raises(VendorUnavailable):
                await transport.execute("explain", ("model", "bounded context"))
            await transport.close()

    asyncio.run(run())


def test_model_daily_limit_returns_queried_numbers_without_another_paid_submission(tmp_path):
    with connected(tmp_path) as (client, fake, app):
        body = pair(client)
        service = app.state.integrations.state.comparison
        service.config = replace(service.config, daily_model_calls=1)
        assert compare(client, body).json()["data"]["explanation"]["source"] == "cortex_selection"
        data = compare(client, body).json()["data"]
        assert data["data_source"] == "snowflake"
        assert data["explanation"]["source"] == "deterministic"
        assert data["explanation"]["reason"] == "Cortex daily call budget exhausted"
        assert len([shape for shape, _ in fake.calls if shape == "explain"]) == 1
