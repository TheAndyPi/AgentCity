import hashlib
import json
import zlib
from uuid import uuid4

import pytest
from conftest import command, commit_preview, create_city, preview, write
from fastapi.testclient import TestClient

from app.data.repository import Repository
from app.infrastructure.config import AppConfig
from app.main import create_app


def csrf(client):
    client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]


def test_restart_pauses_and_idempotency_survives(tmp_path):
    config = AppConfig(data_dir=tmp_path / "store", base_tps=2)
    key = str(uuid4())
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        csrf(client)
        sid = create_city(client)["id"]
        sim = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        body = dict(
            request_id=key,
            expected_control_version=sim["control_version"],
            command=dict(type="step", count=2),
        )
        original = write(client, f"/simulations/{sid}/commands", body, key=key)
        assert original.status_code == 200, original.text
        assert command(client, sid, "play").status_code == 200
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        csrf(client)
        loaded = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        assert loaded["status"] == "paused" and loaded["pause_reason"] == "loaded"
        retried = write(client, f"/simulations/{sid}/commands", body, key=key)
        assert retried.json() == original.json()
        assert client.get(f"/api/v1/simulations/{sid}").json()["data"]["tick"] == loaded["tick"]


def test_failed_navigation_save_retains_last_commit(client, monkeypatch):
    sid = create_city(client)["id"]
    service = client.app.state.service
    previous = service.heads[sid].model_dump()

    def fail(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(service.repo, "_manifest", fail)
    result = command(client, sid, "save", reason="navigation", label="Navigation")
    assert result.status_code == 503, result.text
    assert result.json()["error"]["code"] == "PERSISTENCE_UNAVAILABLE"
    assert service.heads[sid].model_dump() == previous
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200


def test_orphan_write_is_not_visible_on_recovery(client, tmp_path, monkeypatch):
    sid = create_city(client)["id"]
    head = client.app.state.service.heads[sid].model_copy(deep=True)
    directory = tmp_path / "journal"
    repo = Repository(directory)
    # Copy a real committed prefix into the isolated fault-injection store.
    source = client.app.state.service.repo
    for rev in range(head.simulation.revision + 1):
        repo.commit([source.read(sid, rev)])
    staged = head.model_copy(deep=True)
    staged.simulation.revision += 1
    staged.simulation.tick += 1
    with monkeypatch.context() as patch:
        patch.setattr(
            repo, "_manifest", lambda value: (_ for _ in ()).throw(OSError("crash before manifest rename"))
        )
        with pytest.raises(OSError):
            repo.commit([staged])
    repo.close()
    recovered = Repository(directory)
    assert recovered.read(sid).model_dump() == head.model_dump()
    assert not recovered.degraded
    recovered.close()


@pytest.mark.parametrize("damaged_offset", [-1, 3])
def test_recovery_stops_at_damaged_revision(client, tmp_path, damaged_offset):
    sid = create_city(client)["id"]
    command(client, sid, "step", count=2)
    source = client.app.state.service.repo
    directory = tmp_path / "damaged"
    repo = Repository(directory)
    entries = source.meta["simulations"][sid]
    for rev in range(len(entries)):
        repo.commit([source.read(sid, rev)])
    last = repo.meta["simulations"][sid][damaged_offset]
    (directory / "objects" / (last["sha256"] + ".json.z")).write_bytes(b"corrupt")
    repo.close()
    recovered = Repository(directory)
    assert recovered.degraded
    assert recovered.read(sid).simulation.revision == last["revision"] - 1
    with pytest.raises(OSError):
        recovered.commit([])
    recovered.close()


def test_recovery_fully_validates_the_restored_head_and_keeps_reads_independent(client, tmp_path):
    sid = create_city(client)["id"]
    source = client.app.state.service.repo
    repo = Repository(tmp_path / "malformed-head")
    for revision in range(len(source.meta["simulations"][sid])):
        repo.commit([source.read(sid, revision)])
    last = repo.meta["simulations"][sid][-1]
    # A matching checksum/reference does not make an incomplete head restorable.
    raw = zlib.compress(
        json.dumps({"simulation": {"revision": last["revision"], "tick": last["tick"]}}).encode()
    )
    digest = hashlib.sha256(raw).hexdigest()
    (repo.directory / "objects" / (digest + ".json.z")).write_bytes(raw)
    last["sha256"] = digest
    repo._manifest(repo.meta)
    repo.close()
    recovered = Repository(tmp_path / "malformed-head")
    try:
        assert recovered.degraded
        head = recovered.read(sid)
        assert head.simulation.revision == last["revision"] - 1
        original_name = head.simulation.name
        head.simulation.name = "Reader-local edit"
        assert recovered.read(sid).simulation.name == original_name
    finally:
        recovered.close()


def test_store_rejects_second_writer(tmp_path):
    repo = Repository(tmp_path / "single")
    with pytest.raises(RuntimeError, match="writer"):
        Repository(tmp_path / "single")
    repo.close()


def test_shutdown_retains_writer_lock_until_inflight_commit_finishes(tmp_path, monkeypatch):
    import threading

    repo = Repository(tmp_path / "shutdown")
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    manifest = repo._manifest

    def delayed(value):
        started.set()
        assert release.wait(5)
        manifest(value)

    monkeypatch.setattr(repo, "_manifest", delayed)
    writer = threading.Thread(target=lambda: repo.commit(metadata={"shutdown_probe": True}))
    writer.start()
    assert started.wait(5)

    def close():
        repo.close()
        closed.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05)
        assert not repo._process_file.closed
    finally:
        release.set()
        writer.join(5)
        closer.join(5)
    assert closed.is_set()
    recovered = Repository(tmp_path / "shutdown")
    assert recovered.meta["shutdown_probe"]
    recovered.close()


def test_branch_prefix_survives_source_deletion(client):
    sim = create_city(client)
    sid = sim["id"]
    command(client, sid, "step", count=2)
    branched = write(
        client, f"/simulations/{sid}/branches", dict(name="Independent copy", source=dict(kind="whole"))
    )
    assert branched.status_code == 201, branched.text
    branch = branched.json()["data"]["simulation"]
    target = branch["id"]
    assert branch["revision"] == client.get(f"/api/v1/simulations/{sid}").json()["data"]["revision"] + 1
    assert command(client, sid, "archive").status_code == 200
    deleted = write(client, f"/simulations/{sid}", dict(confirmation_name=sim["name"]), method="DELETE")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/simulations/{sid}").status_code == 404
    inherited = client.get(f"/api/v1/simulations/{target}/state", params=dict(revision=sim["revision"]))
    assert inherited.status_code == 200, inherited.text
    assert inherited.json()["data"]["simulation"]["id"] == target
    assert command(client, target, "step", count=1).status_code == 200


@pytest.mark.parametrize("ticks", [0, 1])
def test_pending_and_active_event_restore_without_reapplying(client, ticks):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid, "A shortage for 4 ticks")
    event = commit_preview(client, sid, hold, p).json()["data"]["event"]
    if ticks:
        assert command(client, sid, "step", count=ticks).status_code == 200
    before = client.app.state.service.heads[sid].model_copy(deep=True)
    branch = write(
        client, f"/simulations/{sid}/branches", dict(name="Restore event", source=dict(kind="whole"))
    ).json()["data"]["simulation"]
    state = client.app.state.service.heads[branch["id"]]
    assert state.rng_state == before.rng_state
    assert state.map.model_dump() == before.map.model_dump()
    assert state.interactions == before.interactions
    assert state.external_resource_changes == before.external_resource_changes
    command(client, branch["id"], "step", count=1)
    after = client.app.state.service.heads[branch["id"]]
    applied = [item for item in after.external_resource_changes if item["event_id"] == event["id"]]
    resources = [
        resource
        for resource in before.map.resources
        if resource.kind == "food" and resource.position.x <= 64 and resource.position.y <= 72
    ]
    assert len(applied) == len(resources)
