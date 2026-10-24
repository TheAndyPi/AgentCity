"""Immutable compressed revision journal, checksums, and one fsynced atomic manifest.

The manifest is the sole commit point. Orphan objects are never visible. A process
lock prevents competing workers. Branches own independent lists of immutable refs.
"""

import copy
import hashlib
import json
import os
import threading
import time
import zlib
from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import SHORTCUTS, Settings
from app.simulation.state import State


class _SimulationReference(BaseModel):
    model_config = ConfigDict(strict=True)
    revision: int = Field(ge=0)
    tick: int = Field(ge=0)


class _StoredReference(BaseModel):
    simulation: _SimulationReference


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class Repository:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "objects").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.degraded: list[str] = []
        self._process_file = (self.directory / "writer.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self._process_file.seek(0)
                if self._process_file.read(1) == b"":
                    self._process_file.write(b"0")
                    self._process_file.flush()
                self._process_file.seek(0)
                msvcrt.locking(self._process_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._process_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._process_file.close()
            raise RuntimeError("DATA_DIR already has a writer; run exactly one worker")
        manifest = self.directory / "manifest.json"
        if manifest.exists():
            wrapper = json.loads(manifest.read_bytes())
            if hashlib.sha256(encode(wrapper["data"])).hexdigest() != wrapper["sha256"]:
                self.close()
                raise RuntimeError("manifest checksum mismatch; restore a backup")
            self.meta = wrapper["data"]
        else:
            self.meta = {
                "version": "1.0.0",
                "simulations": {},
                "idempotency": {},
                "profiles": {},
                "sessions": {},
                "settings": {},
                "usage": {},
                "cursor_secret": os.urandom(32).hex(),
            }
            self._manifest(self.meta)
        self._recover()

    def _atomic(self, path, data):
        temp = path.with_name(path.name + ".tmp")
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows can temporarily deny an atomic rename while another process
        # holds a file handle. Retry only those errors on the same fsynced bytes;
        # the old manifest remains the commit point until replacement succeeds.
        for attempt in range(7):
            try:
                os.replace(temp, path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 6:
                    raise
                time.sleep(0.02 * 2**attempt)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _manifest(self, value):
        data = encode(value)
        self._atomic(
            self.directory / "manifest.json",
            encode({"sha256": hashlib.sha256(data).hexdigest(), "data": value}),
        )

    def _object(self, state):
        compressed = zlib.compress(state.model_dump_json().encode("utf-8"), level=3)
        digest = hashlib.sha256(compressed).hexdigest()
        path = self.directory / "objects" / (digest + ".json.z")
        if not path.exists():
            self._atomic(path, compressed)
        return {"revision": state.simulation.revision, "tick": state.simulation.tick, "sha256": digest}

    def _checked_data(self, entry):
        digest = entry["sha256"]
        raw = (self.directory / "objects" / (digest + ".json.z")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("revision checksum mismatch")
        return zlib.decompress(raw)

    def _read(self, entry, *, copy_state=True):
        digest = entry["sha256"]
        if digest in self.cache:
            self.cache.move_to_end(digest)
            cached = self.cache[digest]
            return cached.model_copy(deep=True) if copy_state else cached
        state = State.model_validate_json(self._checked_data(entry))
        if state.simulation.revision != entry["revision"] or state.simulation.tick != entry["tick"]:
            raise ValueError("revision reference mismatch")
        self.cache[digest] = state
        while len(self.cache) > 4:
            self.cache.popitem(last=False)
        return state.model_copy(deep=True) if copy_state else state

    def _recover(self):
        verified = {}
        for sid, entries in self.meta["simulations"].items():
            valid = 0
            for index, entry in enumerate(entries):
                try:
                    if entry["revision"] != index:
                        raise ValueError("non-contiguous revision journal")
                    digest = entry["sha256"]
                    if digest not in verified:
                        ref = _StoredReference.model_validate_json(self._checked_data(entry)).simulation
                        verified[digest] = (ref.revision, ref.tick)
                    if verified[digest] != (entry["revision"], entry["tick"]):
                        raise ValueError("revision reference mismatch")
                    valid += 1
                except (OSError, ValueError, zlib.error):
                    break
            # Every historical object is checksummed above. Only the restored head
            # needs a full object graph at startup; historical reads still validate
            # the complete State on demand. Malformed heads retain a valid prefix.
            while valid:
                try:
                    self._read(entries[valid - 1], copy_state=False)
                    break
                except (OSError, ValueError, zlib.error):
                    valid -= 1
            if valid < len(entries):
                self.degraded.append(
                    f"Recovered {sid} through revision {valid - 1}; damaged journal requires operator review"
                )
                self.meta["simulations"][sid] = entries[:valid]

    def read(self, sid, revision=None):
        with self.lock:
            entries = self.meta["simulations"].get(sid)
            if not entries:
                raise KeyError(sid)
            revision = entries[-1]["revision"] if revision is None else revision
            if revision < 0 or revision >= len(entries):
                raise KeyError(revision)
            state = self._read(entries[revision])
            # A branch's inherited bytes retain provenance, but projections belong to the branch.
            state.simulation.id = sid
            if state.simulation.initial_preview:
                state.simulation.initial_preview.simulation_id = sid
            if state.intervention:
                state.intervention.simulation_id = sid
            for snapshot in state.snapshots:
                snapshot.simulation_id = sid
            for preview in state.previews.values():
                preview.simulation_id = sid
            return state

    def commit(self, states=(), *, idempotency=None, metadata=None, branches=None, delete=None):
        with self.lock:
            if self.degraded:
                raise OSError("Persistence store is degraded")
            staged = copy.deepcopy(self.meta)
            if branches:
                for target, (source, revision) in branches.items():
                    staged["simulations"][target] = copy.deepcopy(
                        staged["simulations"][source][: revision + 1]
                    )
            for state in states:
                entries = staged["simulations"].setdefault(state.simulation.id, [])
                if state.simulation.revision != len(entries):
                    raise ValueError("revision must append exactly once")
                entries.append(self._object(state))
            if delete:
                staged["simulations"].pop(delete, None)
            if metadata:
                for key, value in metadata.items():
                    staged[key] = value
            if idempotency:
                key, value = idempotency
                staged["idempotency"][key] = value
            try:
                self._manifest(staged)
            except OSError:
                self.degraded.append("Commit manifest write failed; last committed state remains readable")
                raise
            self.meta = staged

    def settings(self, owner):
        return Settings.model_validate(
            self.meta["settings"].get(
                owner,
                dict(
                    version=0,
                    theme="dark",
                    view_mode="3d",
                    autosave=True,
                    reduce_motion=False,
                    shortcuts=SHORTCUTS,
                ),
            )
        )

    def close(self):
        # A cancelled asyncio.to_thread await does not stop an in-flight fsync.
        # Keep writer ownership until that storage transaction has finished.
        with self.lock:
            if not self._process_file.closed:
                self._process_file.close()
