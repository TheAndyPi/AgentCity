"""Immutable compressed revision journal, checksums, and one fsynced atomic manifest.

The manifest is the sole commit point. Orphan objects are never visible. A process
lock prevents competing workers. Branches own independent lists of immutable refs.
"""

import hashlib
import json
import os
import threading
import time
import zlib
from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import SHORTCUTS, Decision, MetricPoint, Settings, Simulation
from app.simulation.state import State


class _SimulationReference(BaseModel):
    model_config = ConfigDict(strict=True)
    revision: int = Field(ge=0)
    tick: int = Field(ge=0)


class _StoredReference(BaseModel):
    simulation: _SimulationReference


class _StoredSummary(BaseModel):
    model_config = ConfigDict(cache_strings=False)
    owner_id: str
    simulation: Simulation
    intervention: dict | None = None
    auto_resume: bool = False


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class Repository:
    def __init__(self, directory: Path, *, recover=True):
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
        if recover:
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
            previous_revision = -1
            bad_segment_revision = None
            for segment in self.meta.get("history", {}).get(sid, ()):
                try:
                    json.loads(self._checked_data(segment))
                except (OSError, ValueError, zlib.error):
                    bad_segment_revision = segment["revision"]
                    break
            for entry in entries:
                try:
                    if bad_segment_revision is not None and entry["revision"] >= bad_segment_revision:
                        raise ValueError("damaged history segment")
                    if entry["revision"] <= previous_revision:
                        raise ValueError("unordered revision journal")
                    previous_revision = entry["revision"]
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
                    f"Recovered {sid} through revision {entries[valid - 1]['revision'] if valid else -1}; damaged journal requires operator review"
                )
                self.meta["simulations"][sid] = entries[:valid]
                through = entries[valid - 1]["revision"] if valid else -1
                if "history" in self.meta:
                    self.meta["history"][sid] = [
                        segment
                        for segment in self.meta["history"].get(sid, ())
                        if segment["revision"] <= through
                    ]

    def restore(self, sid):
        """Restore the selected head; historical objects validate when requested."""
        with self.lock:
            entries = self.meta["simulations"].get(sid)
            if not entries:
                raise KeyError(sid)
            segments = self.meta.get("history", {}).get(sid, [])
            # Immutable objects can be read without holding the writer lock.
            recovery = object.__new__(Repository)
            recovery.directory = self.directory
            recovery.lock = threading.RLock()
            recovery.cache = OrderedDict()
            recovery.degraded = []
            recovery.meta = {
                "simulations": {sid: entries},
                "history": {sid: segments},
            }
        valid = len(entries)
        while valid:
            try:
                recovery._read(entries[valid - 1], copy_state=False)
                break
            except (OSError, ValueError, zlib.error):
                valid -= 1
        if valid < len(entries):
            recovery.degraded.append(f"Recovered {sid} through its last valid head; operator review required")
            recovery.meta["simulations"][sid] = entries[:valid]
            through = entries[valid - 1]["revision"] if valid else -1
            recovery.meta["history"][sid] = [s for s in segments if s["revision"] <= through]
        with self.lock:
            if self.meta["simulations"].get(sid) != entries:
                raise OSError("Simulation changed during recovery; retry opening it")
            self.meta["simulations"][sid] = recovery.meta["simulations"][sid]
            self.meta.setdefault("history", {})[sid] = recovery.meta["history"].get(sid, [])
            self.degraded.extend(recovery.degraded)
        return recovery.read(sid)

    def summaries(self):
        """Read only current summary fields; never walk historical revisions."""
        with self.lock:
            result = {}
            for sid, entries in self.meta["simulations"].items():
                if not entries:
                    continue
                result[sid] = self.summary(sid)
            return result

    def summary(self, sid):
        with self.lock:
            entries = self.meta["simulations"].get(sid)
            if not entries:
                raise KeyError(sid)
            summary = _StoredSummary.model_validate_json(self._checked_data(entries[-1]))
            summary.simulation.id = sid
            if summary.simulation.initial_preview:
                summary.simulation.initial_preview.simulation_id = sid
            if summary.simulation.status != "initializing" and (
                summary.simulation.status == "running" or summary.intervention or summary.auto_resume
            ):
                # Describe the paused state that opening this saved world will restore.
                summary.simulation.status = "paused"
                summary.simulation.pause_reason = "loaded"
                summary.simulation.revision += 1
                summary.simulation.control_version += 1
            return summary

    def read(self, sid, revision=None):
        with self.lock:
            entries = self.meta["simulations"].get(sid)
            if not entries:
                raise KeyError(sid)
            revision = entries[-1]["revision"] if revision is None else revision
            if revision < 0 or revision > entries[-1]["revision"]:
                raise KeyError(revision)
            # Revisions between durable checkpoints replay from the preceding commit.
            from bisect import bisect_right

            index = bisect_right(entries, revision, key=lambda item: item["revision"]) - 1
            if index < 0:
                raise KeyError(revision)
            state = self._read(entries[index])
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
            staged = dict(self.meta)
            staged["simulations"] = dict(self.meta["simulations"])
            staged["history"] = dict(self.meta.get("history", {}))
            staged["history_watermarks"] = dict(self.meta.get("history_watermarks", {}))
            for state in states:
                sid = state.simulation.id
                if branches and sid in branches:
                    target = sid
                    source, revision = branches[sid]
                    staged["simulations"][target] = [
                        entry for entry in staged["simulations"][source] if entry["revision"] <= revision
                    ]
                    staged["history"][target] = [
                        entry for entry in staged["history"].get(source, ()) if entry["revision"] <= revision
                    ]
                    staged["history_watermarks"][target] = {
                        kind: max(
                            (
                                entry["through"]
                                for entry in staged["history"][target]
                                if entry["kind"] == kind
                            ),
                            default=-1,
                        )
                        for kind in ("decisions", "metric_points")
                    }
                entries = list(staged["simulations"].get(sid, ()))
                if entries and state.simulation.revision <= entries[-1]["revision"]:
                    raise ValueError("revision must append exactly once in increasing order")
                if not entries and state.simulation.revision != 0:
                    raise ValueError("revision journal must begin at zero")
                segments = list(staged["history"].get(sid, ()))
                for kind in ("decisions", "metric_points"):
                    pending = getattr(state, "pending_" + kind, ())
                    previous = max((item["through"] for item in segments if item["kind"] == kind), default=-1)
                    records = [item for item in pending if self.history_key(kind, item) > previous]
                    if records:
                        raw = zlib.compress(encode([item.model_dump(mode="json") for item in records]), 3)
                        digest = hashlib.sha256(raw).hexdigest()
                        path = self.directory / "objects" / (digest + ".json.z")
                        if not path.exists():
                            self._atomic(path, raw)
                        segments.append(
                            dict(
                                kind=kind,
                                revision=state.simulation.revision,
                                through=self.history_key(kind, records[-1]),
                                sha256=digest,
                            )
                        )
                staged["history"][sid] = segments
                staged["history_watermarks"][sid] = {
                    kind: max((entry["through"] for entry in segments if entry["kind"] == kind), default=-1)
                    for kind in ("decisions", "metric_points")
                }
                entries.append(self._object(state))
                staged["simulations"][sid] = entries
            if delete:
                staged["simulations"].pop(delete, None)
                staged["history"].pop(delete, None)
                staged["history_watermarks"].pop(delete, None)
            if metadata:
                for key, value in metadata.items():
                    staged[key] = value
            if idempotency:
                key, value = idempotency
                staged["idempotency"] = dict(staged["idempotency"])
                staged["idempotency"][key] = value
            try:
                self._manifest(staged)
            except OSError:
                self.degraded.append("Commit manifest write failed; last committed state remains readable")
                raise
            self.meta = staged

    @staticmethod
    def history_key(kind, record):
        return int(record.id.rsplit("_", 1)[-1]) if kind == "decisions" else record.revision

    def history(self, sid, kind, through_revision=None):
        """Read cold history only on demand; hot ticks never deserialize segments."""
        model = Decision if kind == "decisions" else MetricPoint
        result = []
        for entry in self.meta.get("history", {}).get(sid, ()):
            if entry["kind"] != kind or (
                through_revision is not None and entry["revision"] > through_revision
            ):
                continue
            result.extend(model.model_validate(item) for item in json.loads(self._checked_data(entry)))
        return result

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
