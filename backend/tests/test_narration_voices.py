"""Citizen voice identity acceptance; no calls to the real ElevenLabs API."""

from dataclasses import replace

import pytest
from conftest import command, create_city, write
from narration_fake import ElevenLabsFake, config
from test_narration import city_with_records, narrate, narration_client


def assignments(client, sid):
    return dict(
        client.app.state.narration.store.db.execute(
            "SELECT agent_id,voice_id FROM character_voices WHERE simulation_id=?", (sid,)
        )
    )


def test_each_speaker_uses_own_voice_and_decisions_and_dialogue_agree(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        by_speaker = {d["agent_id"]: d for d in records["decisions"]}
        speakers = list(by_speaker)[:2]
        for aid in speakers:
            assert narrate(client, sid, "decision", by_speaker[aid]["id"]).status_code == 200
        assert fake.requests[0]["path"] != fake.requests[1]["path"]
        mapped = assignments(client, sid)
        assert len(mapped) == len(records["names"]) == len(set(mapped.values()))
        for line in records["dialogue"][:2]:
            response = narrate(client, sid, "dialogue", line["id"])
            assert response.status_code == 200, response.text
            assert fake.requests[-1]["path"].endswith("/" + mapped[line["speaker_id"]])
        assert narrate(client, sid, "event", records["event"]["id"]).status_code == 200
        assert fake.requests[-1]["path"] == "/v1/text-to-speech/TestVoice01"


def test_assignments_survive_restart_and_pool_reordering(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        decision = records["decisions"][0]
        assert narrate(client, sid, "decision", decision["id"]).status_code == 200
        before = assignments(client, sid)
    reversed_pool = tuple(reversed(config().character_voice_ids))
    with narration_client(tmp_path / "store", fake, character_voice_ids=reversed_pool) as client:
        # A different record bypasses the old audio receipt/cache.
        other = next(d for d in records["decisions"] if d["id"] != decision["id"])
        assert narrate(client, sid, "decision", other["id"]).status_code == 200
        assert assignments(client, sid) == before
        assert fake.requests[-1]["path"].endswith("/" + before[other["agent_id"]])


def test_branch_inherits_voice_ids_and_new_citizens_do_not_reassign_others(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        sid = records["sid"]
        decision = records["decisions"][0]
        assert narrate(client, sid, "decision", decision["id"]).status_code == 200
        before = assignments(client, sid)
        branch = write(
            client, f"/simulations/{sid}/branches", {"name": "Voice continuity", "source": {"kind": "whole"}}
        )
        assert branch.status_code == 201, branch.text
        bid = branch.json()["data"]["simulation"]["id"]
        assert narrate(client, bid, "decision", decision["id"]).status_code == 200
        assert assignments(client, bid) == before
        assert fake.requests[-1]["path"].endswith("/" + before[decision["agent_id"]])
        # Adding an existing citizen to a fresh resolver roster exercises allocation
        # without changing a frozen core DTO or physical simulation behavior.
        service = client.app.state.narration
        state = service.core.owned("demo_owner", bid).model_copy(deep=True)
        original = next(iter(state.citizens.values())).model_copy(deep=True)
        original.summary.id = "agent_99999999"
        state.citizens[original.summary.id] = original
        service.voices.resolve(state, "decision", decision["id"], service.config)
        grown = assignments(client, bid)
        assert all(grown[aid] == voice for aid, voice in before.items())
        assert len(grown) == len(set(grown.values())) == 11


def test_full_supported_population_has_100_distinct_voices(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        sid = create_city(client, population=100)["id"]
        assert command(client, sid, "step", count=1).status_code == 200
        service = client.app.state.narration
        state = service.core.owned("demo_owner", sid)
        decisions = {d.agent_id: d for d in state.decisions}
        # Assign the complete roster on first request, regardless of who speaks first.
        first = next(iter(decisions.values()))
        service.voices.resolve(state, "decision", first.id, service.config)
        mapped = assignments(client, sid)
        assert len(mapped) == 100 and len(set(mapped.values())) == 100
        assert fake.requests == []


@pytest.mark.parametrize("pool", [(), ("OnlyOneVoice",)])
def test_insufficient_pool_reuses_voices_and_calls_provider(tmp_path, pool):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake, character_voice_ids=pool) as client:
        records = city_with_records(client)
        decision = records["decisions"][0]
        response = narrate(client, records["sid"], "decision", decision["id"])
        assert response.status_code == 200
        assigned = assignments(client, records["sid"])
        assert len(assigned) == len(records["names"])
        assert set(assigned.values()) == set(pool or (config().voice_id,))
        assert len(fake.requests) == 1


def test_removing_assigned_voice_is_an_explicit_error(tmp_path):
    fake = ElevenLabsFake()
    with narration_client(tmp_path / "store", fake) as client:
        records = city_with_records(client)
        decision = records["decisions"][0]
        assert narrate(client, records["sid"], "decision", decision["id"]).status_code == 200
        service = client.app.state.narration
        mapped = assignments(client, records["sid"])
        removed = mapped[decision["agent_id"]]
        changed = replace(
            service.config,
            character_voice_ids=tuple(v for v in service.config.character_voice_ids if v != removed),
        )
        state = service.core.owned("demo_owner", records["sid"])
        with pytest.raises(Exception, match="assigned citizen voice is missing"):
            service.voices.resolve(state, "decision", decision["id"], changed)
        assert assignments(client, records["sid"]) == mapped


def test_duplicate_and_malformed_voice_ids_are_rejected_without_secret_output():
    for pool in [("Duplicate", "Duplicate"), ("../bad",), ("",)]:
        with pytest.raises(ValueError, match="ELEVENLABS_CHARACTER_VOICE_IDS"):
            config(character_voice_ids=pool).validate()


def test_legacy_unique_voice_table_is_migrated_without_losing_assignments(tmp_path):
    import sqlite3

    from app.narration.store import Store
    from app.narration.voices import VoiceAssignments

    store = Store(tmp_path, config())
    store.db.execute("""
        CREATE TABLE character_voices (
            owner TEXT NOT NULL, simulation_id TEXT NOT NULL,
            agent_id TEXT NOT NULL, voice_id TEXT NOT NULL,
            PRIMARY KEY(owner, simulation_id, agent_id),
            UNIQUE(owner, simulation_id, voice_id))
    """)
    store.db.execute("INSERT INTO character_voices VALUES ('owner', 'sim', 'agent1', 'voice')")
    store.db.commit()
    VoiceAssignments(store)
    store.db.execute("INSERT INTO character_voices VALUES ('owner', 'sim', 'agent2', 'voice')")
    store.db.commit()
    assert store.db.execute("SELECT COUNT(*) FROM character_voices").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("INSERT INTO character_voices VALUES ('owner', 'sim', 'agent1', 'other')")
    store.close()
