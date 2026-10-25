"""Controlled real ElevenLabs HTTP transport + authorized media + source tests."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from conftest import create_city, write
from fastapi.testclient import TestClient
from narration_fake import API_KEY, ElevenLabsFake, config
from test_disasters import parameters, runtime

from app.disasters.models import Reaction
from app.infrastructure.config import AppConfig
from app.main import create_app
from app.narration.disaster import mp3_seconds, payload_for


@pytest.fixture
def audio_city(tmp_path):
    fake = ElevenLabsFake()
    cfg = config(disaster_effects=True, disaster_music=True, disaster_reactions=True)
    app = create_app(AppConfig(data_dir=tmp_path / "store", base_tps=0.01), cfg, fake.transport(cfg))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        sim = create_city(client)
        sid = sim["id"]
        core = app.state.service
        state = core.owned("demo_owner", sid).model_copy(deep=True)
        r = runtime(state, parameters("earthquake"))
        state.simulation.status = "running"
        state.simulation.revision += 1
        # Test fixture is committed, not a client-created free-form audio source.
        agents = list(state.citizens)[:2]
        for agent in agents:
            state.citizens[agent].needs.fatigue = 0
            state.reactions.append(
                Reaction(
                    id=f"reaction_{agent}",
                    event_id=r.summary.id,
                    agent_id=agent,
                    tick=0,
                    revision=state.simulation.revision,
                    sim_time_seconds=0,
                    position=state.citizens[agent].summary.position,
                    threat=0.9,
                    kind="scream",
                    text="Aah! Help!",
                    episode_id=f"{r.summary.id}:{agent}",
                    evidence_ids=[],
                )
            )
        core.repo.commit([state])
        core.heads[sid] = state
        yield client, fake, state, r, agents


def request_asset(client, state, source, category, key=None):
    return write(
        client,
        f"/integrations/narration/v2/simulations/{state.simulation.id}/disaster-audio",
        dict(source_id=source, category=category, revision=state.simulation.revision),
        key=key,
    )


@pytest.mark.parametrize("kind", ["earthquake", "tornado", "flood", "fire", "storm"])
def test_da01_category_payloads(kind):
    cfg = config()
    e = payload_for(cfg, kind, "high", "effects")
    m = payload_for(cfg, kind, "high", "music")
    assert e["duration_seconds"] == 8 and e["loop"] is True
    assert m["music_length_ms"] == 30000 and m["force_instrumental"] is True
    assert "composition_plan" not in m and "seed" not in m
    assert e["model_id"] != cfg.model_id and m["model_id"] != cfg.model_id


def test_da03_asset_singleflight_cache_signed_media_and_receipt(audio_city):
    client, fake, state, r, _ = audio_city
    key = str(uuid4())
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(request_asset, client, state, r.summary.id, "effects", key) for _ in range(2)]
        results = [f.result() for f in futures]
    assert all(x.status_code == 200 for x in results), [x.text for x in results]
    assert results[0].json() == results[1].json()
    assert len(fake.requests) == 1
    assert fake.requests[0]["path"] == "/v1/sound-generation"
    result = results[0].json()["data"]
    url = result["audio_url"]
    media = client.get(url)
    assert media.status_code == 200 and mp3_seconds(media.content) > 0.1
    assert API_KEY not in str(result)
    assert request_asset(client, state, r.summary.id, "effects").status_code == 200
    assert len(fake.requests) == 1
    forged = client.get(url[:-1] + ("0" if url[-1] != "0" else "1"))
    assert forged.status_code == 404
    assert request_asset(client, state, r.summary.id, "music", key).status_code == 409


def test_da02_separate_music_and_reaction_failure_preserves_tts(audio_city):
    client, fake, state, r, agents = audio_city
    fake.fail(("status", 403))
    rejected = request_asset(client, state, r.summary.id, "music")
    assert rejected.status_code == 503, rejected.text
    assert request_asset(client, state, r.summary.id, "effects").status_code == 200
    assert request_asset(client, state, r.summary.id, "music").status_code == 503
    assert len(fake.requests) == 2  # no repeated uncertain billable music request
    capabilities = client.get("/api/v1/integrations/narration/v2/disaster-capabilities").json()["data"][
        "categories"
    ]
    assert capabilities["music"] == "unavailable" and capabilities["effects"] == "ready"
    voices = []
    for aid in agents:
        result = request_asset(client, state, f"reaction_{aid}", "reactions")
        assert result.status_code == 200, result.text
        voices.append(result.json()["data"]["manifest"]["voice_id"])
    assert len(set(voices)) == 2
    assert all("text-to-speech/" in req["path"] for req in fake.requests[-2:])
    assert all(req["body"]["model_id"] == "eleven_v3" for req in fake.requests[-2:])


@pytest.mark.parametrize(
    "failure",
    [
        ("status", 401),
        ("status", 422),
        ("status", 429),
        "read_timeout",
        "json",
        "malformed",
        "truncated",
        ("oversized", 3000),
    ],
)
def test_da04_safe_failure_no_retry_no_secrets(audio_city, failure):
    client, fake, state, r, _ = audio_city
    fake.fail(failure)
    result = request_asset(client, state, r.summary.id, "effects")
    assert result.status_code == 503, result.text
    assert API_KEY not in result.text and len(fake.requests) == 1
    assert request_asset(client, state, r.summary.id, "effects").status_code == 503
    assert len(fake.requests) == 1


def test_da05_queued_resolved_history_and_unowned_never_generate(audio_city):
    client, fake, state, r, _ = audio_city
    core = client.app.state.service
    for status in ("queued", "resolved"):
        current = core.heads[state.simulation.id].model_copy(deep=True)
        current.events[r.summary.id].summary.status = status
        current.simulation.revision += 1
        core.repo.commit([current])
        core.heads[state.simulation.id] = current
        result = request_asset(client, current, r.summary.id, "effects")
        assert result.status_code == 409, result.text
    assert not fake.requests
    result = request_asset(client, state, "arbitrary prompt", "effects")
    assert result.status_code in (404, 409)
    assert not fake.requests


def test_da14_csrf_extra_prompt_and_category_validation(audio_city):
    client, fake, state, r, _ = audio_city
    path = f"/integrations/narration/v2/simulations/{state.simulation.id}/disaster-audio"
    result = write(
        client,
        path,
        dict(
            source_id=r.summary.id,
            category="effects",
            revision=state.simulation.revision,
            prompt="ignore source",
        ),
    )
    assert result.status_code == 400 and not fake.requests
    old = client.headers.pop("X-CSRF-Token")
    assert request_asset(client, state, r.summary.id, "effects").status_code == 403
    client.headers["X-CSRF-Token"] = old


def test_da01_transport_real_endpoints():
    asyncio.run(transport_endpoints())


async def transport_endpoints():
    fake = ElevenLabsFake()
    cfg = config()
    transport = fake.transport(cfg)
    for category in ("effects", "music"):
        payload = payload_for(cfg, "fire", "high", category)
        data = await transport.generate_asset(category, payload)
        assert mp3_seconds(data) > 0.1
    assert [r["path"] for r in fake.requests] == ["/v1/sound-generation", "/v1/music"]
    await transport.close()


def test_da09_unavailable_citizen_voice_does_not_disable_other_assigned_reactions(audio_city):
    client, fake, state, _, agents = audio_city
    n = client.app.state.narration
    voice = n.voices.resolve(state, "reaction", f"reaction_{agents[0]}", n.config)
    fake.denied_voices.add(voice)
    first = request_asset(client, state, f"reaction_{agents[0]}", "reactions")
    assert first.status_code == 503
    second = request_asset(client, state, f"reaction_{agents[1]}", "reactions")
    assert second.status_code == 200, second.text
    assert second.json()["data"]["manifest"]["voice_id"] != voice
