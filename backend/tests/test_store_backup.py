import pytest
from conftest import command, create_city, write

from app.data.repository import Repository
from scripts.store_backup import backup, restore


def test_r06_backup_refuses_live_writer_and_restores_exact_branch_history(client, tmp_path):
    sid = create_city(client)["id"]
    assert command(client, sid, "step", count=2).status_code == 200
    branch = write(
        client, f"/simulations/{sid}/branches", {"name": "Backup branch", "source": {"kind": "whole"}}
    )
    assert branch.status_code == 201
    bid = branch.json()["data"]["simulation"]["id"]
    assert command(client, bid, "step", count=1).status_code == 200
    service = client.app.state.service
    expected = {key: service.repo.read(key).model_dump(mode="json") for key in (sid, bid)}
    source = service.config.data_dir
    archive = tmp_path / "store.tar.gz"
    with pytest.raises(RuntimeError, match="already has a writer"):
        backup(source, archive)
    client.portal.call(service.close)
    backup(source, archive)
    restored = tmp_path / "restore-drill"
    restore(archive, restored)
    repo = Repository(restored)
    try:
        assert {key: repo.read(key).model_dump(mode="json") for key in (sid, bid)} == expected
    finally:
        repo.close()
    with pytest.raises(ValueError, match="must not exist"):
        restore(archive, restored)
    with pytest.raises(ValueError, match="new and outside"):
        backup(source, archive)
