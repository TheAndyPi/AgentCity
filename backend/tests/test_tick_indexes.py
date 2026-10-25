"""Snapshot-safe incremental indexes and bounded live histories."""

import copy

from conftest import create_city

from app import contracts as c
from app.simulation.agents import remember, retrieve
from app.simulation.engine import tick, trim_hot_history
from app.simulation.indexes import DialogueIndex


def line(number, speaker="a", recipients=None, heard=None):
    return c.Dialogue(
        id=f"line_{number}",
        interaction_id=f"interaction_{number // 2}",
        tick=number,
        speaker_id=speaker,
        recipient_ids=recipients or ["b"],
        audible_to_ids=heard or ["c"],
        text=f"Message {number}",
        intent="talk",
        emotion="calm",
        end_conversation=False,
    )


def test_dialogue_index_snapshot_boundaries_and_branches():
    lines = [line(0), line(1)]
    index = DialogueIndex().update(lines)
    old = copy.deepcopy(index)
    lines.append(line(2, speaker="d"))
    index.update(lines)
    assert index.by_id["line_2"] == lines[2]
    assert "line_2" not in old.by_id
    assert list(old.by_participant.get("d", [])) == []
    assert list(old.by_audible["c"]) == lines[:2]
    assert index.by_audible["c"][-1] == lines[2]
    assert index.by_participant["b"][-2:] == lines[1:]
    branch = copy.deepcopy(old).update([*lines[:2], line(3)])
    assert list(branch.by_id) == ["line_0", "line_1", "line_3"]
    assert list(index.by_id) == ["line_0", "line_1", "line_2"]


def test_dialogue_index_appends_without_rescanning_history():
    class CountingList(list):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    lines = CountingList(line(n) for n in range(10000))
    index = DialogueIndex().update(lines)
    lines.reads = 0
    lines.append(line(10000))
    index.update(lines)
    assert lines.reads <= 2
    assert index.by_participant["b"][-1].id == "line_10000"


def test_tick_builds_spatial_index_once_before_movement(client, monkeypatch):
    from app.simulation import indexes

    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    count = 0
    original = indexes.SpatialIndex

    def counted(*args, **kwargs):
        nonlocal count
        count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(indexes, "SpatialIndex", counted)
    tick(state)
    assert 1 <= count <= 2
    assert state._tick_context is None


def test_hot_history_retirement_is_lossless_and_not_in_checkpoint(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    tick(state)
    decision = state.decisions[-1]
    point = state.metric_points[-1]
    state.decisions = [decision.model_copy(update={"id": f"decision_{i}"}) for i in range(1250)]
    state.metric_points = [point.model_copy(update={"tick": i, "revision": i}) for i in range(725)]
    trim_hot_history(state)
    assert len(state.decisions) == 1000 and len(state.pending_decisions) == 250
    assert len(state.metric_points) == 600 and len(state.pending_metric_points) == 125
    assert [d.id for d in state.pending_decisions + state.decisions] == [f"decision_{i}" for i in range(1250)]
    checkpoint = state.model_dump()
    assert "pending_decisions" not in checkpoint
    assert "pending_metric_points" not in checkpoint


def test_retrieve_bounds_scoring_window_and_returns_top_k(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid].model_copy(deep=True)
    citizen = next(iter(state.citizens.values()))
    citizen.memories = []
    for number in range(600):
        remember(state, citizen, f"Memory {number}", importance=100 if number == 0 else number % 100)
    result = retrieve(citizen, state.simulation.tick, limit=8)
    assert len(result) == 8
    assert all(memory in citizen.memories[-512:] for memory in result)
    assert [memory.importance for memory in result] == sorted(
        (memory.importance for memory in result), reverse=True
    )
