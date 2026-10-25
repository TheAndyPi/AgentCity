"""LV backend acceptance through owned revision-pinned routes and real HTTP transport."""

import concurrent.futures
import os
import threading
import time
from dataclasses import replace
from uuid import uuid4

from conftest import command, create_city, write
from narration_fake import ElevenLabsFake, marker
from test_narration import Clock, city_with_records, fetch, narration_client
from test_narration_voices import assignments


def live(client, sid, line, revision=None, key=None, **extra):
    if revision is None:
        revision = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]["ref"]["revision"]
    return write(
        client,
        f"/integrations/narration/v1/simulations/{sid}/dialogue",
        dict(source_id=line, revision=revision) | extra,
        key=key,
    )


def test_lv01_live_utterances_distinct_voices_no_name_prefix_manual_semantics_unchanged(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        for line in records["dialogue"][:4]:
            response = live(client, sid, line["id"])
            assert response.status_code == 200, response.text
            assert fake.texts[-1] == line["text"]
            assert fake.requests[-1]["path"].endswith("/" + assignments(client, sid)[line["speaker_id"]])
            media = fetch(client, response.json()["data"]["audio_url"])
            assert media.status_code == 200 and marker(line["text"]).encode() in media.content
        mapped = assignments(client, sid)
        assert len(mapped) == len(set(mapped.values()))
        from test_narration import narrate

        line = records["dialogue"][0]
        assert narrate(client, sid, "dialogue", line["id"]).status_code == 200
        assert fake.texts[-1] == records["names"][line["speaker_id"]] + ": " + line["text"]
        assert len(fake.voice_checks) == len(set(fake.voice_checks))


def test_lv08_concurrent_lost_response_retry_shares_receipt_and_synthesis(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid, line = records["sid"], records["dialogue"][0]
        revision = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]["ref"]["revision"]
        key = str(uuid4())
        fake.gate.clear()
        try:
            with concurrent.futures.ThreadPoolExecutor(3) as pool:
                first = pool.submit(live, client, sid, line["id"], revision, key)
                deadline = time.monotonic() + 3
                while not fake.requests and time.monotonic() < deadline:
                    time.sleep(0.01)
                second = pool.submit(live, client, sid, line["id"], revision, key)
                third = pool.submit(live, client, sid, line["id"], revision)
                fake.gate.set()
                a, b, c = first.result(), second.result(), third.result()
            assert a.status_code == b.status_code == c.status_code == 200
            assert a.json() == b.json()
            assert len(fake.requests) == 1
            assert live(client, sid, line["id"], revision, key).json() == a.json()
            assert live(client, sid, records["dialogue"][1]["id"], revision, key).status_code == 409
        finally:
            fake.gate.set()


def test_lv06_concurrent_different_records_respect_reserved_cache_bytes(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake, max_audio_bytes=8192, cache_max_bytes=8192) as client:
        records = city_with_records(client)
        sid = records["sid"]
        fake.gate.clear()
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                first = pool.submit(live, client, sid, records["dialogue"][0]["id"])
                deadline = time.monotonic() + 3
                while not fake.requests and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert fake.requests
                second = pool.submit(live, client, sid, records["dialogue"][1]["id"])
                denied = second.result(timeout=3)
                assert denied.status_code == 429
                assert len(fake.requests) == 1
                fake.gate.set()
                assert first.result().status_code == 200
            assert client.app.state.narration.reserved_bytes == 0
        finally:
            fake.gate.set()


def test_lv09_revision_pins_record_and_rejects_future_or_invented_text(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid, line = records["sid"], records["dialogue"][0]
        assert live(client, sid, line["id"], 0).status_code == 404
        assert live(client, sid, "invented").status_code == 404
        assert live(client, sid, line["id"], text="Injected speech").status_code == 400
        assert fake.requests == []


def test_lv07_shortage_preserves_existing_and_removed_voice_only_blocks_its_speaker(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        service = client.app.state.narration
        first = records["dialogue"][0]
        assert live(client, sid, first["id"]).status_code == 200
        before = assignments(client, sid)
        state = service.core.owned("demo_owner", sid).model_copy(deep=True)
        citizen = next(iter(state.citizens.values())).model_copy(deep=True)
        citizen.summary.id = "agent_99999999"
        state.citizens[citizen.summary.id] = citizen
        short = replace(service.config, character_voice_ids=tuple(before.values()))
        assert service.voices.resolve(state, "dialogue", first["id"], short) == before[first["speaker_id"]]
        grown = assignments(client, sid)
        assert all(grown[aid] == voice for aid, voice in before.items())
        new_line = state.dialogue[0].model_copy(
            update={"id": "dialogue_new", "speaker_id": citizen.summary.id}
        )
        state.dialogue.append(new_line)
        assert service.voices.resolve(state, "dialogue", new_line.id, short) in short.character_voice_ids
        removed = before[first["speaker_id"]]
        service.config = replace(
            short, character_voice_ids=tuple(v for v in short.character_voice_ids if v != removed)
        )
        another = next(d for d in records["dialogue"] if d["speaker_id"] != first["speaker_id"])
        assert live(client, sid, another["id"]).status_code == 200
        assert live(client, sid, first["id"]).status_code == 503
        assert assignments(client, sid) == grown


def test_lv07_historical_identity_is_reserved_after_roster_removal_and_inherited_by_branch(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        assert live(client, sid, records["dialogue"][0]["id"]).status_code == 200
        service = client.app.state.narration
        before = assignments(client, sid)
        state = service.core.owned("demo_owner", sid).model_copy(deep=True)
        removed = sorted(state.citizens)[0]
        del state.citizens[removed]
        state.simulation.id = "simulation_child"
        state.simulation.parent_simulation_id = sid
        line = next(d for d in state.dialogue if d.speaker_id in state.citizens)
        service.voices.resolve(state, "dialogue", line.id, service.config)
        assert assignments(client, "simulation_child") == before


def test_live_text_is_never_silently_truncated(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake, max_characters=1) as client:
        records = city_with_records(client)
        response = live(client, records["sid"], records["dialogue"][0]["id"])
        assert response.status_code == 503 and "NARRATION_MAX_CHARACTERS" in response.text
        assert fake.requests == []


def test_lv08_sweeping_during_an_active_write_keeps_both_recordings(tmp_path, monkeypatch):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        original = os.fsync
        writing, release = threading.Event(), threading.Event()

        def sync(handle):
            if not writing.is_set():
                writing.set()
                assert release.wait(5)
            return original(handle)

        monkeypatch.setattr(os, "fsync", sync)
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                first = pool.submit(live, client, records["sid"], records["dialogue"][0]["id"])
                assert writing.wait(3)
                second = pool.submit(live, client, records["sid"], records["dialogue"][1]["id"])
                result = second.result(timeout=3)
                assert result.status_code == 200, result.text
                release.set()
                result = first.result()
                assert result.status_code == 200, result.text
            assert len(fake.requests) == 2
            assert not client.app.state.narration.store.writing
        finally:
            release.set()


def test_lv07_authorization_is_verified_bounded_and_secret_safe(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid, line = records["sid"], records["dialogue"][0]
        service = client.app.state.narration
        state = service.core.owned("demo_owner", sid)
        voice = service.voices.resolve(state, "dialogue", line["id"], service.config)
        fake.denied_voices.add(voice)
        denied = live(client, sid, line["id"])
        assert denied.status_code == 503 and "unauthorized or unavailable" in denied.text
        assert "test-elevenlabs-key" not in denied.text
        assert fake.requests == []
        fake.denied_voices.clear()
        assert live(client, sid, line["id"]).status_code == 200
        assert live(client, sid, line["id"]).status_code == 200
        assert fake.voice_checks == [voice, voice]


def test_lv08_expired_receipt_needs_fresh_key_reuses_audio_and_denies_wrong_owner(tmp_path):
    fake, clock = ElevenLabsFake(), Clock()
    with narration_client(tmp_path / "store", fake, clock) as client:
        records = city_with_records(client)
        sid, line, key = records["sid"], records["dialogue"][0], str(uuid4())
        first = live(client, sid, line["id"], key=key)
        assert first.status_code == 200
        url = first.json()["data"]["audio_url"]
        clock.now += 901
        assert fetch(client, url).status_code == 404
        assert live(client, sid, line["id"], key=key).status_code == 409
        assert live(client, sid, line["id"]).status_code == 200
        assert len(fake.requests) == 1
        state = client.app.state.service.heads[sid]
        state.owner_id = "someone_else"
        assert live(client, sid, line["id"], state.simulation.revision).status_code == 404
        assert fetch(client, url).status_code == 404


def test_lv06_blocked_live_synthesis_keeps_physical_controls_independent(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        other = create_city(client, name="Independent live city")["id"]
        fake.gate.clear()
        finished = threading.Event()
        worker = threading.Thread(
            target=lambda: (live(client, records["sid"], records["dialogue"][0]["id"]), finished.set())
        )
        worker.start()
        try:
            deadline = time.monotonic() + 2
            while not fake.requests and time.monotonic() < deadline:
                time.sleep(0.01)
            assert fake.requests and not finished.is_set()
            assert not client.app.state.service.writer.locked()
            assert command(client, other, "step", count=1).status_code == 200
            assert not finished.is_set()
        finally:
            fake.gate.set()
            worker.join(5)
        assert finished.is_set()
