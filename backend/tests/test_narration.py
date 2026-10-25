"""N-01..N-06 narration acceptance through the real core route and media extension.

Only the external ElevenLabs HTTP endpoint is controlled (see narration_fake.py).
"""

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from conftest import command, create_city, write
from fastapi import FastAPI
from fastapi.testclient import TestClient
from narration_fake import API_KEY, TONE, ElevenLabsFake, config, marked_audio, marker

from app.infrastructure.config import AppConfig
from app.main import create_app
from app.narration.router import MOUNT_PATH, create_narration_app, install_narration
from app.narration.transport import valid_mp3

LOCAL = dict(base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
SESSION = dict(
    auth_mode="session",
    session_secret="narration-session-secret-" * 2,
    demo_passphrase="narration passphrase",
    allowed_origins=("https://city.example",),
)
OPENAPI = Path(__file__).parents[2] / "docs" / "release" / "narration-openapi.json"


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@contextmanager
def narration_client(data_dir, fake=None, clock=None, app_config=None, **overrides):
    narration_config = config(**overrides) if fake else None
    app_config = app_config or AppConfig(data_dir=data_dir, base_tps=5)
    app = create_app(app_config, narration_config, fake.transport(narration_config) if fake else None)
    if clock:
        app.state.narration.clock = clock
    with TestClient(app, **LOCAL) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        yield client


def narrate(client, sid, source_type, source_id, key=None):
    body = dict(source_type=source_type, source_id=source_id)
    return write(client, f"/simulations/{sid}/narration", body, key=key)


def city_with_records(client):
    simulation = create_city(client, scenario_description="A flood for 2 ticks")
    sid = simulation["id"]
    confirmed = write(
        client,
        f"/simulations/{sid}/initial-scenario",
        dict(
            preview_id=simulation["initial_preview"]["id"],
            decision="confirm",
            expected_control_version=simulation["control_version"],
        ),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert command(client, sid, "step", count=4).status_code == 200
    state = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]
    names = {agent["id"]: agent["name"] for agent in state["agents"]}
    event = client.get(f"/api/v1/simulations/{sid}/events/{state['events'][0]['id']}").json()["data"]
    decisions = [
        item
        for aid in names
        for item in client.get(f"/api/v1/simulations/{sid}/agents/{aid}/decisions").json()["data"]["items"]
    ]
    dialogue = client.get(f"/api/v1/simulations/{sid}/dialogue").json()["data"]["items"]
    assert decisions and dialogue
    return dict(sid=sid, names=names, event=event["event"], decisions=decisions, dialogue=dialogue)


def sentence(text):
    return text if text[-1] in ".!?:;" else text + "."


def expected_event(event):
    return f"{sentence(event['title'])} {event['summary']}"


def expected_decision(records, decision):
    name = records["names"][decision["agent_id"]]
    return f"{sentence(name)} {sentence(decision['concise_rationale'])} {decision['outcome_description']}"


def expected_dialogue(records, line):
    return f"{records['names'][line['speaker_id']]}: {line['text']}"


def fetch(client, url, **headers):
    return client.get(url, headers=headers)


def media_files(data_dir):
    return sorted((data_dir / "store" / "narration" / "audio").iterdir())


def assert_safe(response, *forbidden):
    text = response.text
    for value in (API_KEY, "vendor secret detail", "elevenlabs.io", "Traceback", *forbidden):
        assert value not in text


# N-01 -------------------------------------------------------------------------------------------


def test_owned_event_decision_and_dialogue_reach_provider_and_return_playable_audio(tmp_path):
    fake = ElevenLabsFake()
    clock = Clock()
    with narration_client(tmp_path / "store", fake, clock) as client:
        assert client.get("/api/v1/capabilities").json()["data"]["narration"] is True
        records = city_with_records(client)
        decision, line = records["decisions"][0], records["dialogue"][0]
        cases = [
            ("event", records["event"]["id"], expected_event(records["event"])),
            ("decision", decision["id"], expected_decision(records, decision)),
            ("dialogue", line["id"], expected_dialogue(records, line)),
        ]
        for index, (source_type, source_id, text) in enumerate(cases, start=1):
            response = narrate(client, records["sid"], source_type, source_id)
            assert response.status_code == 200, response.text
            assert_safe(response)
            data = response.json()["data"]
            assert set(data) == {"audio_url", "expires_at"}
            url = urlsplit(data["audio_url"])
            assert (url.scheme, url.netloc) == ("http", "127.0.0.1")
            assert url.path.startswith("/api/v1/integrations/narration/audio/")
            expires = int(dict(p.split("=") for p in url.query.split("&"))["expires"])
            assert expires == int(clock.now + 900)
            assert data["expires_at"] == time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))
            sent = fake.requests[-1]
            assert len(fake.requests) == index
            assert sent["host"] == "api.elevenlabs.io"
            if source_type == "event":
                assert sent["path"] == "/v1/text-to-speech/TestVoice01"
            else:
                speaker = decision["agent_id"] if source_type == "decision" else line["speaker_id"]
                roster = sorted(records["names"])
                assert sent["path"] == f"/v1/text-to-speech/CitizenVoice{roster.index(speaker):03}"
            assert sent["query"] == {"output_format": "mp3_44100_128"}
            assert sent["api_key"] == API_KEY and sent["accept"] == "audio/mpeg"
            assert sent["body"] == {"text": text, "model_id": "eleven_test_model"}
            audio = fetch(client, data["audio_url"])
            assert audio.status_code == 200
            assert audio.headers["content-type"] == "audio/mpeg"
            assert audio.headers["accept-ranges"] == "bytes"
            assert audio.headers["cache-control"].startswith("private")
            assert audio.content == marked_audio(text)
            assert marker(text).encode() in audio.content and valid_mp3(audio.content)


def test_media_supports_browser_range_and_head_requests(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        url = narrate(client, records["sid"], "event", records["event"]["id"]).json()["data"]["audio_url"]
        whole = fetch(client, url).content
        part = fetch(client, url, Range="bytes=0-99")
        assert part.status_code == 206
        assert part.headers["content-range"] == f"bytes 0-99/{len(whole)}"
        assert part.content == whole[:100]
        tail = fetch(client, url, Range="bytes=-10")
        assert tail.status_code == 206 and tail.content == whole[-10:]
        head = client.head(url)
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-length"] == str(len(whole))
        unsatisfiable = fetch(client, url, Range=f"bytes={len(whole)}-")
        assert unsatisfiable.status_code == 416
        assert unsatisfiable.headers["content-range"] == f"bytes */{len(whole)}"


# N-02 -------------------------------------------------------------------------------------------


def test_repeated_content_uses_one_synthesis_and_issues_fresh_urls(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        first = narrate(client, records["sid"], "event", records["event"]["id"]).json()["data"]
        second = narrate(client, records["sid"], "event", records["event"]["id"]).json()["data"]
        assert len(fake.requests) == 1
        assert urlsplit(first["audio_url"]).path == urlsplit(second["audio_url"]).path
        assert fetch(client, first["audio_url"]).content == fetch(client, second["audio_url"]).content
        counters = client.app.state.narration.store.counters()
        assert counters["cache_hits"] == 1 and counters["syntheses_started"] == 1
        assert len(media_files(tmp_path)) == 1


def test_concurrent_identical_requests_share_one_vendor_call(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        fake.gate.clear()
        results = []

        def request():
            results.append(narrate(client, records["sid"], "decision", records["decisions"][0]["id"]))

        threads = [threading.Thread(target=request) for _ in range(4)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 5
        while not fake.requests and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
        fake.gate.set()
        for thread in threads:
            thread.join(10)
        assert [r.status_code for r in results] == [200] * 4
        assert len(fake.requests) == 1
        paths = {urlsplit(r.json()["data"]["audio_url"]).path for r in results}
        assert len(paths) == 1
        assert client.app.state.narration.store.counters()["joined_in_flight"] == 3


def test_same_key_retry_after_response_loss_replays_exact_result_and_changed_body_conflicts(tmp_path):
    fake = ElevenLabsFake()
    store = tmp_path / "store"
    key = str(uuid4())
    with narration_client(store, fake) as client:
        records = city_with_records(client)
        sid, event_id = records["sid"], records["event"]["id"]
        fake.gate.clear()
        first = []
        lost = threading.Thread(target=lambda: first.append(narrate(client, sid, "event", event_id, key)))
        lost.start()
        while not fake.requests:
            time.sleep(0.01)
        # The same key arrives while the original is still synthesizing.
        joined = []
        retry = threading.Thread(target=lambda: joined.append(narrate(client, sid, "event", event_id, key)))
        retry.start()
        time.sleep(0.2)
        changed = narrate(client, sid, "dialogue", records["dialogue"][0]["id"], key)
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        fake.gate.set()
        lost.join(10)
        retry.join(10)
        original = first[0].json()
        assert first[0].status_code == 200 and joined[0].json() == original
        assert original["request_id"] == key
        # The original response was "lost"; a later exact retry replays the stored receipt.
        replay = narrate(client, sid, "event", event_id, key)
        assert replay.status_code == 200 and replay.json() == original
        changed = narrate(client, sid, "decision", records["decisions"][0]["id"], key)
        assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(fake.requests) == 1
    with narration_client(store, fake) as client:
        replay = narrate(client, sid, "event", event_id, key)
        assert replay.status_code == 200 and replay.json() == original
        assert fetch(client, original["data"]["audio_url"]).status_code == 200
        assert len(fake.requests) == 1


# N-03 -------------------------------------------------------------------------------------------


def test_missing_mismatched_and_invalid_sources_are_rejected_before_synthesis(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        other = create_city(client, name="Quiet city")["id"]
        cases = [
            (sid, "event", "event_does_not_exist", 404, "NOT_FOUND"),
            (sid, "decision", records["dialogue"][0]["id"], 404, "NOT_FOUND"),
            (sid, "dialogue", records["event"]["id"], 404, "NOT_FOUND"),
            (other, "event", records["event"]["id"], 404, "NOT_FOUND"),
            ("simulation_missing", "event", records["event"]["id"], 404, "NOT_FOUND"),
            (sid, "memory", records["event"]["id"], 422, "VALIDATION_ERROR"),
            (sid, "event", "", 422, "VALIDATION_ERROR"),
        ]
        for target, source_type, source_id, status, code in cases:
            response = narrate(client, target, source_type, source_id)
            assert response.status_code == status, (source_type, response.text)
            body = response.json()
            assert body["schema_version"] == "1.0.0" and body["error"]["code"] == code
            assert_safe(response, str(tmp_path))
        assert fake.requests == []
        assert not (tmp_path / "store" / "narration" / "audio").exists() or not media_files(tmp_path)


def test_cross_owner_guessed_and_traversal_media_requests_disclose_nothing(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        security = client.app.state.security
        original = security.identity

        def identity(connection, *args, **kwargs):
            # The product has one owner per deployment; simulate a second account.
            if connection.headers.get("x-test-owner") == "intruder":
                return "intruder_owner", original(connection, *args, **kwargs)[1]
            return original(connection, *args, **kwargs)

        security.identity = identity
        records = city_with_records(client)
        sid = records["sid"]
        url = narrate(client, sid, "event", records["event"]["id"]).json()["data"]["audio_url"]
        intruder = client.post(
            f"/api/v1/simulations/{sid}/narration",
            json=dict(source_type="event", source_id=records["event"]["id"]),
            headers={"Idempotency-Key": str(uuid4()), "x-test-owner": "intruder"},
        )
        assert intruder.status_code == 404 and intruder.json()["error"]["code"] == "NOT_FOUND"
        stolen = fetch(client, url, **{"x-test-owner": "intruder"})
        assert stolen.status_code == 404 and stolen.content != TONE
        parts = urlsplit(url)
        audio_id = parts.path.rsplit("/", 1)[1]
        query = dict(p.split("=") for p in parts.query.split("&"))
        guessed = "0" * 32 if audio_id != "0" * 32 else "1" * 32
        forged = f"{MOUNT_PATH}/audio/{audio_id}?expires={query['expires']}&signature={'a' * 64}"
        extended = f"{MOUNT_PATH}/audio/{audio_id}?expires={int(query['expires']) + 1}&signature={query['signature']}"
        attempts = [
            f"{MOUNT_PATH}/audio/{guessed}?{parts.query}",
            forged,
            extended,
            f"{MOUNT_PATH}/audio/{audio_id}",
            f"{MOUNT_PATH}/audio/{audio_id}?expires=abc&signature={query['signature']}",
            f"{MOUNT_PATH}/audio/..%2F..%2Fmanifest.json?{parts.query}",
            f"{MOUNT_PATH}/audio/%2e%2e%2fnarration.sqlite3?{parts.query}",
            f"{MOUNT_PATH}/audio/..%5C..%5Cmanifest.json?{parts.query}",
            f"{MOUNT_PATH}/audio/{audio_id}.mp3?{parts.query}",
            f"{MOUNT_PATH}/audio/{audio_id}/..%2F..%2F..%2Fmanifest.json?{parts.query}",
            f"{MOUNT_PATH}/narration.sqlite3",
        ]
        for path in attempts:
            response = client.get(path)
            assert response.status_code == 404, (path, response.status_code)
            assert response.headers["content-type"].startswith("application/json")
            body = response.json()
            assert body["error"]["code"] == "NOT_FOUND" and body["schema_version"] == "1.0.0"
            assert_safe(response, str(tmp_path), "sqlite", "cursor_secret", audio_id + ".mp3")
        assert fetch(client, url).status_code == 200
        assert len(fake.requests) == 1


# N-04 -------------------------------------------------------------------------------------------


def test_expiry_and_cache_ttl_define_retry_and_media_behavior(tmp_path):
    fake = ElevenLabsFake()
    clock = Clock()
    key = str(uuid4())
    with narration_client(tmp_path / "store", fake, clock, url_ttl=60, cache_ttl=600) as client:
        records = city_with_records(client)
        sid, event_id = records["sid"], records["event"]["id"]
        first = narrate(client, sid, "event", event_id, key).json()
        assert fetch(client, first["data"]["audio_url"]).status_code == 200
        clock.now += 61
        assert fetch(client, first["data"]["audio_url"]).status_code == 404
        retry = narrate(client, sid, "event", event_id, key)
        assert retry.status_code == 409 and retry.json()["error"]["code"] == "INVALID_STATE"
        fresh = narrate(client, sid, "event", event_id)
        assert fresh.status_code == 200 and len(fake.requests) == 1
        assert fetch(client, fresh.json()["data"]["audio_url"]).status_code == 200
        clock.now += 601
        again = narrate(client, sid, "event", event_id)
        assert again.status_code == 200 and len(fake.requests) == 2
        assert len(media_files(tmp_path)) == 1


def test_bounded_cache_never_evicts_live_urls_and_evicts_least_recent_afterwards(tmp_path):
    fake = ElevenLabsFake()
    clock = Clock()
    limits = dict(max_audio_bytes=8192, cache_max_bytes=16384, cache_max_entries=2, url_ttl=60, cache_ttl=600)
    with narration_client(tmp_path / "store", fake, clock, **limits) as client:
        records = city_with_records(client)
        sid = records["sid"]
        sources = [("event", records["event"]["id"])] + [
            ("dialogue", d["id"]) for d in records["dialogue"][:2]
        ]
        urls = [narrate(client, sid, *sources[i]).json()["data"]["audio_url"] for i in range(2)]
        full = narrate(client, sid, *sources[2])
        assert full.status_code == 429 and full.json()["error"]["code"] == "RATE_LIMITED"
        assert full.headers["retry-after"] == "60"
        assert len(fake.requests) == 2
        assert all(fetch(client, url).status_code == 200 for url in urls)
        clock.now += 61
        fetch_newest = narrate(client, sid, *sources[1])
        assert fetch_newest.status_code == 200
        third = narrate(client, sid, *sources[2])
        assert third.status_code == 200 and len(fake.requests) == 3
        count, total = client.app.state.narration.store.usage()
        assert count == 2 and total <= limits["cache_max_bytes"]
        assert len(media_files(tmp_path)) == 2
        assert fetch(client, fetch_newest.json()["data"]["audio_url"]).status_code == 200
        evicted = narrate(client, sid, *sources[0])
        assert evicted.status_code == 429


def test_restart_keeps_committed_audio_and_reconciles_damaged_or_orphaned_files(tmp_path):
    fake = ElevenLabsFake()
    store = tmp_path / "store"
    with narration_client(store, fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        event_url = narrate(client, sid, "event", records["event"]["id"]).json()["data"]["audio_url"]
        narrate(client, sid, "dialogue", records["dialogue"][0]["id"])
    damaged = media_files(tmp_path)
    audio_dir = store / "narration" / "audio"
    (audio_dir / ("f" * 32 + ".mp3")).write_bytes(TONE)
    (audio_dir / ("e" * 32 + ".tmp")).write_bytes(b"partial")
    event_id = urlsplit(event_url).path.rsplit("/", 1)[1]
    victim = next(path for path in damaged if path.stem != event_id)
    victim.write_bytes(b"truncated")
    with narration_client(store, fake) as client:
        assert {p.name for p in media_files(tmp_path)} == {event_id + ".mp3"}
        assert fetch(client, event_url).status_code == 200
        assert narrate(client, sid, "event", records["event"]["id"]).status_code == 200
        assert len(fake.requests) == 2
        assert narrate(client, sid, "dialogue", records["dialogue"][0]["id"]).status_code == 200
        assert len(fake.requests) == 3


def test_revoked_session_and_deleted_simulation_deny_media(tmp_path):
    fake = ElevenLabsFake()
    app_config = AppConfig(data_dir=tmp_path / "store", **SESSION)
    narration_config = config()
    app = create_app(app_config, narration_config, fake.transport(narration_config))
    with TestClient(app, base_url="https://city.example") as client:
        client.headers["Origin"] = "https://city.example"
        login = write(client, "/session", {"passphrase": "narration passphrase"})
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        raw = client.cookies.get("agentcity_session")
        records = city_with_records(client)
        url = narrate(client, records["sid"], "event", records["event"]["id"]).json()["data"]["audio_url"]
        assert url.startswith("https://city.example/api/v1/integrations/narration/audio/")
        assert fetch(client, url).status_code == 200
        assert write(client, "/session", {}, method="DELETE").status_code == 200
        client.cookies.clear()
        revoked = client.get(url, headers={"Cookie": "agentcity_session=" + raw})
        assert revoked.status_code == 401 and revoked.json()["error"]["code"] == "UNAUTHENTICATED"
        assert revoked.content != TONE
    with narration_client(tmp_path / "local", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        url = narrate(client, sid, "event", records["event"]["id"]).json()["data"]["audio_url"]
        acknowledge = command(
            client,
            sid,
            "acknowledge_outcome",
            event_id=records["event"]["id"],
            resume=False,
        )
        assert acknowledge.status_code == 200, acknowledge.text
        assert command(client, sid, "archive").status_code == 200
        deleted = write(client, f"/simulations/{sid}", {"confirmation_name": "Test city"}, method="DELETE")
        assert deleted.status_code == 200, deleted.text
        assert fetch(client, url).status_code == 404


# N-05 -------------------------------------------------------------------------------------------


def released(client):
    narration = client.app.state.narration
    transport = narration.transport
    return (
        transport.waiting == 0
        and transport.slots._value == narration.config.concurrency
        and narration.reserved_bytes == 0
        and narration.reserved_entries == 0
        and not narration.flights
        and not narration.pending
    )


@pytest.mark.parametrize(
    "actions, attempts, status, message",
    [
        ([("hang", 30)], 1, 503, "did not respond in time"),
        ([("status", 429, {"retry-after": "0"})] * 3, 3, 503, "rate limiting"),
        ([("status", 503)] * 3, 3, 503, "unavailable"),
        ([("status", 500)] * 3, 3, 503, "unavailable"),
        ([("status", 401)], 1, 503, "rejected"),
        ([("status", 422)], 1, 503, "rejected"),
        (["malformed"], 1, 503, "invalid audio"),
        (["json"], 1, 503, "invalid audio"),
        ([("oversized", 4)], 1, 503, "larger than"),
        ([("oversized_stream", 4)], 1, 503, "larger than"),
        (["read_timeout"], 1, 503, "did not respond in time"),
        (["connect"] * 3, 3, 503, "unavailable"),
    ],
)
def test_provider_failures_are_bounded_safe_and_recoverable(tmp_path, actions, attempts, status, message):
    fake = ElevenLabsFake()
    fake.fail(*actions)
    with narration_client(tmp_path / "store", fake, deadline=1, max_audio_bytes=8192) as client:
        records = city_with_records(client)
        sid, event_id = records["sid"], records["event"]["id"]
        started = time.monotonic()
        failed = narrate(client, sid, "event", event_id)
        assert time.monotonic() - started < 3
        assert failed.status_code == status, failed.text
        error = failed.json()["error"]
        assert error["code"] == "SERVICE_UNAVAILABLE" and error["retryable"] is True
        assert message in error["message"]
        assert_safe(failed, str(tmp_path))
        assert len(fake.requests) == attempts
        assert released(client)
        assert not (tmp_path / "store" / "narration" / "audio").exists() or not media_files(tmp_path)
        recovered = narrate(client, sid, "event", event_id)
        assert recovered.status_code == 200
        assert fetch(client, recovered.json()["data"]["audio_url"]).content == marked_audio(
            expected_event(records["event"])
        )
        assert len(fake.requests) == attempts + 1 and released(client)


@pytest.mark.parametrize("action", [("status", 429, {"retry-after": "0"}), ("status", 502), "connect"])
def test_transient_failure_is_retried_within_the_deadline(tmp_path, action):
    fake = ElevenLabsFake()
    fake.fail(action)
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        response = narrate(client, records["sid"], "event", records["event"]["id"])
        assert response.status_code == 200 and len(fake.requests) == 2
        assert fake.texts[0] == fake.texts[1] == expected_event(records["event"])


def test_local_rate_and_concurrency_limits_reject_without_vendor_calls(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake, requests_per_minute=1) as client:
        records = city_with_records(client)
        sid = records["sid"]
        assert narrate(client, sid, "event", records["event"]["id"]).status_code == 200
        limited = narrate(client, sid, "dialogue", records["dialogue"][0]["id"])
        assert limited.status_code == 429 and limited.json()["error"]["code"] == "RATE_LIMITED"
        assert limited.headers["retry-after"] == "60"
        assert len(fake.requests) == 1 and released(client)
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "busy", fake, concurrency=1, queue_limit=0) as client:
        records = city_with_records(client)
        sid = records["sid"]
        fake.gate.clear()
        first = []
        thread = threading.Thread(
            target=lambda: first.append(narrate(client, sid, "event", records["event"]["id"]))
        )
        thread.start()
        while not fake.requests:
            time.sleep(0.01)
        busy = narrate(client, sid, "dialogue", records["dialogue"][0]["id"])
        assert busy.status_code == 429 and "busy" in busy.json()["error"]["message"]
        fake.gate.set()
        thread.join(10)
        assert first[0].status_code == 200 and len(fake.requests) == 1 and released(client)


# N-06 -------------------------------------------------------------------------------------------


def test_blocked_synthesis_never_holds_simulation_locks_or_stops_ticks(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake, deadline=30, attempt_timeout=30) as client:
        records = city_with_records(client)
        sid = records["sid"]
        other = create_city(client, name="Running city")["id"]
        service = client.app.state.service
        fake.gate.clear()
        result = []
        thread = threading.Thread(
            target=lambda: result.append(narrate(client, sid, "event", records["event"]["id"]))
        )
        thread.start()
        while not fake.requests:
            time.sleep(0.01)
        assert not service.writer.locked()
        assert not any(lock.locked() for lock in service.locks.values())
        before = client.get(f"/api/v1/simulations/{other}").json()["data"]["tick"]
        assert command(client, other, "step", count=2).status_code == 200
        assert client.get(f"/api/v1/simulations/{other}").json()["data"]["tick"] == before + 2
        assert command(client, other, "play").status_code == 200
        deadline = time.monotonic() + 10
        while client.get(f"/api/v1/simulations/{other}").json()["data"]["tick"] < before + 5:
            assert time.monotonic() < deadline, "ticks stalled while narration was blocked"
            time.sleep(0.05)
        assert command(client, other, "pause").status_code == 200
        assert client.get(f"/api/v1/simulations/{other}").json()["data"]["status"] == "paused"
        assert thread.is_alive() and not result
        fake.gate.set()
        thread.join(10)
        assert result[0].status_code == 200 and len(fake.requests) == 1


def test_disabled_adapter_reports_unavailable_and_touches_nothing(tmp_path):
    with narration_client(tmp_path / "store") as client:
        assert client.get("/api/v1/capabilities").json()["data"]["narration"] is False
        sid = create_city(client)["id"]
        response = narrate(client, sid, "event", "event_1")
        assert response.status_code == 501
        error = response.json()["error"]
        assert (error["code"], error["message"]) == (
            "FEATURE_UNAVAILABLE",
            "Narration integration is unavailable",
        )
        assert narrate(client, "simulation_missing", "event", "event_1").status_code == 404
        media = client.get(f"{MOUNT_PATH}/audio/{'0' * 32}?expires=1&signature={'0' * 64}")
        assert media.status_code == 501 and media.json()["error"]["code"] == "FEATURE_UNAVAILABLE"
        assert not (tmp_path / "store" / "narration").exists()


def test_enabled_configuration_is_validated_without_echoing_values(tmp_path):
    for overrides, setting in [
        (dict(api_key=""), "ELEVENLABS_API_KEY"),
        (dict(voice_id="../voice"), "ELEVENLABS_VOICE_ID"),
        (dict(model_id=""), "ELEVENLABS_MODEL_ID"),
        (dict(output_format="pcm_16000"), "ELEVENLABS_OUTPUT_FORMAT"),
        (dict(public_origin="https://city.example/app"), "NARRATION_PUBLIC_ORIGIN"),
        (dict(deadline=0), "limits"),
    ]:
        with pytest.raises(ValueError) as raised:
            create_app(AppConfig(data_dir=tmp_path / "store"), config(**overrides))
        assert setting in str(raised.value) and API_KEY not in str(raised.value)
    assert API_KEY not in repr(config())


def test_unauthenticated_media_and_post_use_parent_security(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path / "store", **SESSION), config(), None)
    with TestClient(app, base_url="https://city.example") as client:
        media = client.get(f"{MOUNT_PATH}/audio/{'0' * 32}?expires=1&signature={'0' * 64}")
        assert media.status_code == 401 and media.json()["error"]["code"] == "UNAUTHENTICATED"
        post = client.post(
            "/api/v1/simulations/simulation_x/narration",
            json=dict(source_type="event", source_id="e"),
            headers={"Idempotency-Key": str(uuid4()), "Origin": "https://city.example"},
        )
        assert post.status_code == 401
        no_key = client.post("/api/v1/simulations/simulation_x/narration", json={})
        assert no_key.status_code == 400


# Extension seam ---------------------------------------------------------------------------------


def test_media_mount_precedes_generic_integrations_mount_and_spa():
    parent = FastAPI()
    parent.mount("/api/v1/integrations", FastAPI())
    parent.mount("/", FastAPI())
    install_narration(parent, config(enabled=False))
    paths = [getattr(route, "path", "") for route in parent.router.routes]
    assert paths.index(MOUNT_PATH) < paths.index("/api/v1/integrations") < paths.index("")


def test_media_mount_precedes_a_generic_mount_installed_later():
    parent = FastAPI()
    install_narration(parent, config(enabled=False))
    # Same placement as the Snowflake extension's installer: inserted first.
    parent.mount("/api/v1/integrations", FastAPI())
    parent.router.routes.insert(0, parent.router.routes.pop())
    with TestClient(parent):
        paths = [getattr(route, "path", "") for route in parent.router.routes]
        assert paths.index(MOUNT_PATH) < paths.index("/api/v1/integrations")


def test_extension_openapi_matches_documented_snapshot():
    parent = FastAPI()
    install_narration(parent, config(enabled=False))
    schema = create_narration_app(parent.state.narration).openapi()
    assert schema == json.loads(OPENAPI.read_text())
