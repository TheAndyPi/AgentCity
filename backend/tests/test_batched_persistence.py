"""Durable checkpoint batching and snapshot isolation under the real runner."""

import asyncio
import threading
import time

from conftest import command, create_city, write

from app.data.repository import Repository
from app.infrastructure.config import AppConfig
from app.service import Service, staging_copy
from app.simulation.engine import trim_hot_history


def test_staging_shares_immutable_history_but_isolates_mutable_world(client):
    sid = create_city(client)["id"]
    head = client.app.state.service.heads[sid]
    stage = staging_copy(head)
    aid = next(iter(head.citizens))
    original = head.model_dump()
    stage.simulation.tick += 1
    stage.citizens[aid].summary.position.x += 1
    stage.citizens[aid].needs.health -= 1
    stage.map.resources[0].available_units = 0
    stage.dialogue.clear()
    assert head.model_dump() == original
    assert stage.map.cells[0] is head.map.cells[0]  # Generated terrain is immutable.
    assert stage.map.resources[0] is not head.map.resources[0]


def test_sparse_journal_replays_committed_floor_and_recovers(client, tmp_path):
    sid = create_city(client)["id"]
    state = staging_copy(client.app.state.service.heads[sid])
    state.simulation.revision = 0
    directory = tmp_path / "sparse"
    repo = Repository(directory)
    repo.commit([state])
    state = staging_copy(state)
    state.simulation.revision = 5
    state.simulation.tick = 5
    repo.commit([state])
    state = staging_copy(state)
    state.simulation.revision = 12
    state.simulation.tick = 12
    repo.commit([state])
    assert repo.read(sid, 4).simulation.revision == 0
    assert repo.read(sid, 11).simulation.revision == 5
    repo.close()
    recovered = Repository(directory)
    try:
        assert not recovered.degraded
        assert recovered.read(sid).simulation.revision == 12
        assert [entry["revision"] for entry in recovered.meta["simulations"][sid]] == [0, 5, 12]
    finally:
        recovered.close()


def test_side_segments_preserve_retired_history_across_restart_and_branch(client, tmp_path):
    sid = create_city(client)["id"]
    command(client, sid, "step", count=1)
    source = client.app.state.service.heads[sid]
    state = staging_copy(source)
    decision, point = state.decisions[-1], state.metric_points[-1]
    state.decisions = [decision.model_copy(update={"id": f"decision_{i}"}) for i in range(1200)]
    state.metric_points = [point.model_copy(update={"tick": i, "revision": i}) for i in range(700)]
    trim_hot_history(state)
    state.simulation.revision = 0
    directory = tmp_path / "segments"
    repo = Repository(directory)
    repo.commit([state])
    assert len(repo.history(sid, "decisions")) == 200
    assert len(repo.history(sid, "metric_points")) == 100
    branch = staging_copy(state)
    branch.simulation.id = "independent"
    branch.simulation.revision = 1
    repo.commit([branch], branches={"independent": (sid, 0)}, delete=sid)
    repo.close()
    recovered = Repository(directory)
    try:
        head = recovered.read("independent")
        assert len(recovered.history("independent", "decisions") + head.decisions) == 1200
        assert len(recovered.history("independent", "metric_points") + head.metric_points) == 700
        assert not head.pending_decisions and not head.pending_metric_points
    finally:
        recovered.close()


def test_runner_batches_bounds_crash_loss_and_flushes_shutdown(client, tmp_path, monkeypatch):
    import app.service as module

    sid = create_city(client)["id"]
    seed = staging_copy(client.app.state.service.heads[sid])
    seed.simulation.tick = seed.simulation.revision = 0
    seed.simulation.config.tick_seconds = 1
    seed.simulation.status = "running"

    def fast_tick(state, proposals=None):
        state.simulation.tick += 1
        state.simulation.sim_time_seconds = state.simulation.tick

    monkeypatch.setattr(module, "tick", fast_tick)

    async def exercise():
        service = Service(AppConfig(data_dir=tmp_path / "runner", base_tps=200, persist_interval_seconds=5))
        await service.persist([seed])
        original = service.repo.commit
        active, peak = 0, 0
        commit_ticks = []
        guard = threading.Lock()

        def slow_commit(states=(), **kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                # Deliberately slower than a tick: backpressure caps crash loss.
                time.sleep(0.018)
                original(states, **kwargs)
                commit_ticks.extend(state.simulation.tick for state in states)
            finally:
                with guard:
                    active -= 1

        monkeypatch.setattr(service.repo, "commit", slow_commit)
        deep_copies = []
        state_type = type(seed)
        original_copy = state_type.model_copy

        def tracked_copy(self, *args, **kwargs):
            if kwargs.get("deep"):
                deep_copies.append(self.simulation.revision)
            return original_copy(self, *args, **kwargs)

        monkeypatch.setattr(state_type, "model_copy", tracked_copy)
        service.ensure_runner(seed)
        old = service.heads[sid]
        deadline = time.monotonic() + 3
        max_gap = 0
        while service.heads[sid].simulation.tick < 14 and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
            head = service.heads[sid]
            durable = service.repo.meta["simulations"][sid][-1]["tick"]
            max_gap = max(max_gap, head.simulation.tick - durable)
        assert service.heads[sid].simulation.tick >= 14
        assert old.simulation.tick == 0
        assert deep_copies == []
        monkeypatch.setattr(state_type, "model_copy", original_copy)
        assert max_gap <= 5
        assert peak == 1
        assert len(commit_ticks) < service.heads[sid].simulation.tick / 2
        # Non-durable requested revisions resolve to the preceding durable checkpoint.
        head = service.heads[sid]
        assert service.owned(seed.owner_id, sid, head.simulation.revision) is head
        earlier = service.owned(seed.owner_id, sid, head.simulation.revision - 1)
        assert earlier.simulation.revision <= head.simulation.revision - 1
        await service.close()
        recovered = Repository(service.config.data_dir)
        try:
            assert recovered.read(sid).simulation.tick == head.simulation.tick
        finally:
            recovered.close()

    asyncio.run(exercise())


def test_command_flushes_exact_uncommitted_head_for_branch_replay(client, monkeypatch):
    sid = create_city(client)["id"]
    service = client.app.state.service
    dirty = staging_copy(service.heads[sid])
    dirty.simulation.revision += 3
    dirty.simulation.tick += 3
    service.publish_head(sid, dirty)
    calls = []
    original = service.persist

    async def outside_writer(*args, **kwargs):
        calls.append(service.writer.locked())
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "persist", outside_writer)
    response = write(
        client,
        f"/simulations/{sid}/branches",
        dict(name="Exact uncommitted branch", source=dict(kind="whole")),
    )
    assert response.status_code == 201, response.text
    target = response.json()["data"]["simulation"]["id"]
    assert calls == [False]
    assert service.repo.read(sid).simulation.revision == dirty.simulation.revision
    assert service.repo.read(target, dirty.simulation.revision).simulation.tick == dirty.simulation.tick
    assert command(client, sid, "save", reason="manual", label="Durable snapshot").status_code == 200
    assert all(not held for held in calls)
    snapshot = service.heads[sid].snapshots[-1]
    assert service.repo.read(sid, snapshot.ref.revision).simulation.tick == snapshot.ref.tick


def test_corrupt_cold_segment_recovers_only_complete_checkpoint(client, tmp_path):
    sid = create_city(client)["id"]
    command(client, sid, "step", count=1)
    state = staging_copy(client.app.state.service.heads[sid])
    state.simulation.revision = 0
    directory = tmp_path / "corrupt-segment"
    repo = Repository(directory)
    repo.commit([state])
    state = staging_copy(state)
    state.simulation.revision = 4
    state.pending_decisions = state.decisions[:1]
    repo.commit([state])
    segment = repo.meta["history"][sid][0]
    (directory / "objects" / (segment["sha256"] + ".json.z")).write_bytes(b"corrupt")
    repo.close()
    recovered = Repository(directory)
    try:
        assert recovered.degraded
        assert recovered.read(sid).simulation.revision == 0
        assert recovered.history(sid, "decisions") == []
    finally:
        recovered.close()


def test_recent_published_frames_are_bounded_and_owner_checked(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    for _ in range(20):
        frame = staging_copy(service.heads[sid])
        frame.simulation.revision += 1
        service.publish_head(sid, frame)
    assert len(service.recent_heads) == 16
    previous = service.heads[sid].simulation.revision - 1
    assert service.published_state("demo_owner", sid, previous).simulation.revision == previous
    from app.infrastructure.errors import DomainError
    import pytest

    with pytest.raises(DomainError):
        service.published_state("different_owner", sid, previous)
