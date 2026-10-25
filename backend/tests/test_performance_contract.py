"""Timing compatibility and bounded, append-stable conversation reads."""

from conftest import create_city

from app import contracts as c
from app.simulation.timing import legacy_ticks, ticks_for


def test_one_second_default_and_legacy_save(client):
    defaults = c.ConfigRequest(name="Defaults", seed=42)
    assert defaults.tick_seconds == 1 and defaults.max_ticks == 100000
    fresh = create_city(client, tick_seconds=1, max_ticks=100000)
    assert fresh["config"]["tick_seconds"] == 1
    legacy = create_city(client, tick_seconds=10, max_ticks=10000)
    service = client.app.state.service
    service.repo.cache.clear()
    restored = service.repo.read(legacy["id"])
    assert restored.simulation.config.tick_seconds == 10
    assert restored.simulation.config.max_ticks == 10000
    assert ticks_for(restored, 25) == 3
    assert legacy_ticks(restored, 3) == 3
    assert legacy_ticks(service.heads[fresh["id"]], 3) == 30


def seed_dialogue(client, count=120):
    sim = create_city(client, tick_seconds=1)
    state = client.app.state.service.heads[sim["id"]]
    aids = list(state.citizens)
    state.dialogue = [
        c.Dialogue(
            id=f"line_{i:08d}",
            interaction_id=f"chat_{i % 4}",
            tick=i // 4,
            speaker_id=aids[i % 2],
            recipient_ids=[aids[2]],
            audible_to_ids=[],
            text=f"Message {i}",
            intent="chat",
            emotion="calm",
            end_conversation=False,
        )
        for i in range(count)
    ]
    return sim["id"], state, aids


def test_dialogue_pages_are_append_stable_and_filter_bound(client):
    sid, state, aids = seed_dialogue(client)
    url = f"/api/v1/simulations/{sid}/dialogue"
    page = client.get(url, params={"limit": 17}).json()["data"]
    assert [line["id"] for line in page["items"]] == [f"line_{i:08d}" for i in range(119, 102, -1)]
    seen = [line["id"] for line in page["items"]]
    # New live data must never shift the next page's append-position cursor.
    state.dialogue.append(state.dialogue[-1].model_copy(update={"id": "new_line", "tick": 31}))
    cursor = page["next_cursor"]
    assert client.get(url, params={"cursor": cursor, "agent_id": aids[0]}).status_code == 400
    while cursor:
        page = client.get(url, params={"cursor": cursor, "limit": 17}).json()["data"]
        seen.extend(line["id"] for line in page["items"])
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 120
    assert "new_line" not in seen
    filtered = client.get(url, params={"agent_id": aids[0], "limit": 100}).json()["data"]
    assert filtered["items"] and all(line["speaker_id"] == aids[0] for line in filtered["items"])
    chat = client.get(url, params={"agent_id": aids[0], "interaction_id": "chat_0", "limit": 100}).json()[
        "data"
    ]
    assert len(chat["items"]) == 30
    assert all(line["interaction_id"] == "chat_0" for line in chat["items"])


def test_dialogue_cursor_allows_requested_revision_that_replays_to_commit(client):
    from app.service import staging_copy

    sid, state, _ = seed_dialogue(client)
    service = client.app.state.service
    service.bump(state)
    client.portal.call(service.persist, [state])
    committed_revision = state.simulation.revision
    dirty = staging_copy(state)
    dirty.simulation.revision += 5
    service.publish_head(sid, dirty)
    requested_revision = committed_revision + 3
    url = f"/api/v1/simulations/{sid}/dialogue"
    first = client.get(url, params={"revision": requested_revision, "limit": 10})
    assert first.status_code == 200
    cursor = first.json()["data"]["next_cursor"]
    assert cursor
    second = client.get(url, params={"revision": requested_revision, "cursor": cursor, "limit": 10})
    assert second.status_code == 200, second.text
    assert first.json()["data"]["items"][-1]["id"] != second.json()["data"]["items"][0]["id"]
