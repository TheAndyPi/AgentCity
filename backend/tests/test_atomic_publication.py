import errno
import json

import pytest

from app.data import repository
from app.data.repository import Repository


def windows_error(code):
    error = OSError(errno.EACCES, "Injected Windows rename failure")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_rename_retries_keep_the_previous_commit_until_success(tmp_path, monkeypatch, code):
    repo = Repository(tmp_path / "transient")
    manifest = repo.directory / "manifest.json"
    previous = manifest.read_bytes()
    original_replace = repository.os.replace
    attempts, delays = [], []

    def replace(source, destination):
        if destination == manifest:
            attempts.append(source)
            assert manifest.read_bytes() == previous
            assert repo.meta["usage"] == {}
            if len(attempts) < 3:
                raise windows_error(code)
        original_replace(source, destination)

    monkeypatch.setattr(repository.os, "replace", replace)
    monkeypatch.setattr(repository.time, "sleep", delays.append)
    try:
        repo.commit(metadata={"usage": {"committed": 1}})
        assert len(attempts) == 3 and len(set(attempts)) == 1
        assert delays == [0.02, 0.04]
        assert json.loads(manifest.read_bytes())["data"]["usage"] == {"committed": 1}
        assert repo.meta["usage"] == {"committed": 1} and not repo.degraded
    finally:
        repo.close()


def test_persistent_windows_rename_failure_is_bounded_and_never_publishes_staged_metadata(
    tmp_path, monkeypatch
):
    repo = Repository(tmp_path / "persistent")
    manifest = repo.directory / "manifest.json"
    previous = manifest.read_bytes()
    attempts, delays = [], []

    def replace(source, destination):
        attempts.append(source)
        raise windows_error(5)

    monkeypatch.setattr(repository.os, "replace", replace)
    monkeypatch.setattr(repository.time, "sleep", delays.append)
    try:
        with pytest.raises(OSError):
            repo.commit(metadata={"usage": {"uncommitted": 1}})
        assert len(attempts) == 7 and len(delays) == 6
        assert sum(delays) == pytest.approx(1.26)
        assert manifest.read_bytes() == previous and repo.meta["usage"] == {}
        assert repo.degraded
    finally:
        repo.close()


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENOSPC, "Disk full"),
        windows_error(112),
        PermissionError(errno.EACCES, "Permission denied"),
    ],
)
def test_other_save_failures_are_reported_immediately(tmp_path, monkeypatch, error):
    repo = Repository(tmp_path / "unrecoverable")
    manifest = repo.directory / "manifest.json"
    previous = manifest.read_bytes()
    attempts, delays = [], []

    def replace(source, destination):
        attempts.append(source)
        raise error

    monkeypatch.setattr(repository.os, "replace", replace)
    monkeypatch.setattr(repository.time, "sleep", delays.append)
    try:
        with pytest.raises(OSError):
            repo.commit(metadata={"usage": {"uncommitted": 1}})
        assert len(attempts) == 1 and delays == []
        assert manifest.read_bytes() == previous and repo.meta["usage"] == {}
        assert repo.degraded
    finally:
        repo.close()
