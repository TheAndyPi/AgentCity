"""Shared latest-wins frames preserve snapshot maps without per-client projection."""

import json
from unittest.mock import patch

from conftest import command, create_city

from app import contracts as c
from app.api.views import StreamFrames, frame


def test_frames_share_encoding_and_omit_unchanged_map(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    cache = StreamFrames()
    with patch("app.api.views.frame", wraps=frame) as project:
        snapshot = cache.encoded(state, snapshot=True)
        delta = cache.encoded(state)
        assert cache.encoded(state) is delta
        assert cache.encoded(state, snapshot=True) is snapshot
        assert project.call_count == 2
    full, hot = json.loads(snapshot), json.loads(delta)
    c.SnapshotMessage.model_validate(full)
    c.FrameMessage.model_validate(hot)
    assert "map" not in hot["data"]
    assert full["data"]["map_version"] == hot["data"]["map_version"]
    # Null fields are meaningful in nested contracts and must survive encoding.
    assert hot["data"]["simulation"]["parent_simulation_id"] is None
    assert len(delta) < len(snapshot) / 2
    assert (
        hot["data"]["map_updates"]["resources"][0]["available_units"]
        == state.map.resources[0].available_units
    )
    assert hot["data"]["map_updates"]["buildings"][0]["occupancy"] == state.map.buildings[0].occupancy
    assert hot["data"]["map_updates"]["buildings"][0]["capacity"] == state.map.buildings[0].capacity
    assert "footprint" not in hot["data"]["map_updates"]["buildings"][0]
    assert "polygon" not in hot["data"]["map_updates"]["zones"][0]


def test_stream_sends_snapshot_then_mapless_frame(client):
    sid = create_city(client)["id"]
    with client.websocket_connect(f"ws://127.0.0.1/api/v1/simulations/{sid}/stream") as socket:
        socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=None))
        initial = socket.receive_json()
        assert initial["type"] == "snapshot"
        command(client, sid, "save", reason="manual", label="Notify stream")
        updated = socket.receive_json()
        assert updated["type"] == "frame"
        assert updated["data"]["ref"]["revision"] > initial["data"]["ref"]["revision"]
        assert "map" not in updated["data"]


def test_blocked_map_changes_send_a_new_snapshot_without_mutating_world(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    state = service.heads[sid]
    cell = next(cell for cell in state.map.cells if cell.walkable)
    original_version = frame(state).map_version
    with patch("app.api.views.blocked_cells", return_value={(cell.col, cell.row)}):
        snapshot = frame(state)
        assert snapshot.map_version != original_version
        assert not snapshot.map.cells[cell.row * state.map.columns + cell.col].walkable
        assert state.map.cells[cell.row * state.map.columns + cell.col].walkable
