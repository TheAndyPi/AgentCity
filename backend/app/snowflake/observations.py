"""Resumable optional warehouse read model; the revision journal is its durable queue."""

import asyncio
import hashlib
import json
import logging
import math
import sqlite3
import time

from app.data.repository import encode
from app.infrastructure.errors import DomainError, require
from app.snowflake.observations_dto import METRICS, empty_coverage
from app.snowflake.observations_projection import project
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable

LOG = logging.getLogger("agentcity.observations")
MAX_BYTES = 900_000
MAX_FACTS = 2000


class ProjectionConflict(ValueError):
    """An immutable warehouse identity has different content; do not advance."""


def fact_digest(facts):
    text = "|".join(f"{f['id']}:{f['sha256']}" for f in sorted(facts, key=lambda f: f["id"]))
    return hashlib.sha256(text.encode()).hexdigest()


def chunks(envelope):
    """Bound the actual bound JSON and avoid losing an oversized record silently."""
    metadata = {k: v for k, v in envelope.items() if k != "facts"}
    current = []
    overhead = len(encode(dict(metadata, facts=[])))
    size = overhead
    for fact in envelope["facts"]:
        fact_size = len(encode(fact)) + 1
        if len(current) >= MAX_FACTS or size + fact_size > MAX_BYTES:
            if not current:
                raise ValueError("Observation fact exceeds ingestion budget")
            yield dict(metadata, facts=current)
            current = []
            size = overhead
        if overhead + fact_size > MAX_BYTES:
            raise ValueError("Observation fact exceeds ingestion budget")
        current.append(fact)
        size += fact_size
    if current:
        yield dict(metadata, facts=current)


class ObservationService:
    def __init__(self, parent, config, transport=None, gate=None):
        self.parent, self.config = parent, config
        self.transport = transport
        self.gate = gate or asyncio.Lock()
        self.db = None
        self.task = None
        self.errors = {}
        self.cache = {}
        self.last_after = ""
        self.closed = False
        self.start_error = None
        self.reads = asyncio.Semaphore(8)

    @property
    def enabled(self):
        return bool(getattr(self.config, "observations_enabled", False))

    @property
    def core(self):
        return self.parent.state.service

    async def start(self):
        if not self.enabled or self.db is not None:
            return
        path = self.core.config.data_dir / "snowflake-observations.sqlite3"
        schema = """
            CREATE TABLE IF NOT EXISTS progress(
              sid TEXT PRIMARY KEY,owner TEXT NOT NULL,revision INTEGER NOT NULL,
              source_sha256 TEXT NOT NULL,projection_version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS blocked(sid TEXT PRIMARY KEY,code TEXT NOT NULL);
        """
        try:
            try:
                self.db = sqlite3.connect(path)
                self.db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                if self.db:
                    self.db.close()
                # A lost read-model cursor is safely rebuilt from the journal.
                suffix = ".corrupt-" + str(time.time_ns())
                for source in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
                    if source.exists():
                        source.rename(source.with_name(source.name + suffix))
                self.db = sqlite3.connect(path)
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(schema)
            self.db.commit()
        except (sqlite3.DatabaseError, OSError):
            if self.db:
                self.db.close()
            self.db = None
            self.start_error = "LOCAL_PROGRESS_UNAVAILABLE"
            return
        self.transport = self.transport or SnowflakeTransport(self.config)
        self.task = asyncio.create_task(self.run(), name="snowflake-observations")

    async def close(self):
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.transport:
            await self.transport.close()
        if self.db:
            self.db.close()
            self.db = None
        self.cache.clear()

    def checkpoint(self, sid):
        if self.db is None:
            return -1
        row = self.db.execute(
            "SELECT revision,source_sha256,projection_version FROM progress WHERE sid=?", (sid,)
        ).fetchone()
        entries = self.core.repo.meta["simulations"].get(sid, [])
        if row and 0 <= row[0] < len(entries) and entries[row[0]]["sha256"] == row[1] and row[2] == "1.0.0":
            return row[0]
        return -1

    def blocked(self, sid):
        return self.db and self.db.execute("SELECT code FROM blocked WHERE sid=?", (sid,)).fetchone()

    async def ingest(self, envelope):
        expected = fact_digest(envelope["facts"])
        identity = (envelope["owner_id"], envelope["simulation_id"], envelope["revision"])
        async with self.gate:
            for batch in chunks(envelope):
                await self.transport.execute("obs_ingest", (encode(batch).decode(),))
            rows = await self.transport.execute("obs_verify", identity)
            if len(rows) != 1 or int(rows[0][0]) != len(envelope["facts"]) or rows[0][1] != expected:
                raise ProjectionConflict("Immutable observation facts failed integrity verification")
            provenance = {k: v for k, v in envelope.items() if k != "facts"}
            manifest = dict(
                owner_id=identity[0],
                simulation_id=identity[1],
                revision=identity[2],
                tick=envelope["tick"],
                source_sha256=envelope["source_sha256"],
                facts_sha256=expected,
                fact_count=len(envelope["facts"]),
                provenance=provenance,
            )
            await self.transport.execute("obs_publish", (encode(manifest).decode(),))
            rows = await self.transport.execute("obs_receipt", identity)
            if len(rows) != 1 or rows[0] != [
                manifest["source_sha256"],
                expected,
                str(manifest["fact_count"]),
            ]:
                raise ProjectionConflict("Immutable revision manifest failed integrity verification")

    async def cleanup(self):
        for sid, owner in self.db.execute("SELECT sid,owner FROM progress").fetchall():
            if sid in self.core.repo.meta["simulations"]:
                continue
            async with self.gate:
                # Delete the publication first; no partially deleted revision is queryable.
                await self.transport.execute("obs_delete_revisions", (owner, sid))
                await self.transport.execute("obs_delete_facts", (owner, sid))
            self.db.execute("DELETE FROM progress WHERE sid=?", (sid,))
            self.db.execute("DELETE FROM blocked WHERE sid=?", (sid,))
            self.db.commit()
            self.errors.pop(sid, None)

    async def reconcile(self, maximum=100):
        """Round-robin bounded work. Failed simulations never starve other cities."""
        await self.cleanup()
        keys = sorted(self.core.heads)
        keys = [s for s in keys if s > self.last_after] + [s for s in keys if s <= self.last_after]
        work = False
        remaining = maximum
        for sid in keys:
            self.last_after = sid
            if self.blocked(sid):
                continue
            try:
                entries = self.core.repo.meta["simulations"].get(sid, [])
                self.db.execute(
                    "INSERT OR IGNORE INTO progress VALUES(?,?,-1,'','1.0.0')",
                    (sid, self.core.heads[sid].owner_id),
                )
                self.db.commit()
                previous_revision = self.checkpoint(sid)
                # Backfill uses the historical branch bytes with branch-local projection IDs.
                previous = None
                if previous_revision >= 0:
                    previous = await asyncio.to_thread(self.core.repo.read, sid, previous_revision)
                for revision in range(
                    previous_revision + 1, min(len(entries), previous_revision + 1 + remaining)
                ):
                    entry = entries[revision]
                    state = await asyncio.to_thread(self.core.repo.read, sid, revision)
                    head = self.core.heads.get(sid)
                    if head is None:
                        break
                    lineage = {
                        "parent_simulation_id": head.simulation.parent_simulation_id,
                        "fork_revision": head.simulation.fork_ref.revision
                        if head.simulation.fork_ref
                        else None,
                    }
                    envelope = await asyncio.to_thread(project, previous, state, lineage)
                    envelope["source_sha256"] = entry["sha256"]
                    await self.ingest(envelope)
                    # A concurrent deletion cannot publish a usable route: ownership is checked anew.
                    self.db.execute(
                        "INSERT INTO progress VALUES(?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                        "owner=excluded.owner,revision=excluded.revision,source_sha256=excluded.source_sha256,"
                        "projection_version=excluded.projection_version",
                        (sid, state.owner_id, revision, entry["sha256"], "1.0.0"),
                    )
                    self.db.commit()
                    self.errors.pop(sid, None)
                    self.cache = {key: value for key, value in self.cache.items() if key[1] != sid}
                    previous = state
                    work = True
                    remaining -= 1
                    if remaining <= 0:
                        return work
                    await asyncio.sleep(0)
            except ProjectionConflict:
                self.errors[sid] = "HASH_CONFLICT"
                self.db.execute("INSERT OR REPLACE INTO blocked VALUES(?,?)", (sid, "HASH_CONFLICT"))
                self.db.commit()
            except KeyError:
                continue  # Concurrent authorized deletion.
            except Exception as error:
                self.errors[sid] = (
                    "PROJECTION_LIMIT" if isinstance(error, ValueError) else "INGESTION_UNAVAILABLE"
                )
                LOG.warning("Observation ingestion unavailable (%s)", self.errors[sid])
        return work

    async def run(self):
        delay = 1
        while not self.closed:
            try:
                work = await self.reconcile()
                delay = min(60, delay * 2) if self.errors else 1
                await asyncio.sleep(
                    delay
                    if self.errors
                    else 0
                    if work
                    else getattr(self.config, "observation_poll_seconds", 30)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.warning("Observation worker unavailable")
                delay = min(60, delay * 2)
                await asyncio.sleep(delay)

    def status(self, owner, sid, revision=None):
        head = self.core.owned(owner, sid)
        requested = head.simulation.revision if revision is None else revision
        self.core.owned(owner, sid, requested)
        ingested = self.checkpoint(sid)
        blocked = self.blocked(sid)
        error = self.start_error or (blocked[0] if blocked else self.errors.get(sid))
        effective = min(ingested, requested) if ingested >= 0 else None
        entries = self.core.repo.meta["simulations"].get(sid, [])
        coverage = (
            empty_coverage()
            if effective is None
            else {
                "state": "complete" if effective == requested else "partial",
                "from_tick": entries[0]["tick"],
                "through_tick": entries[effective]["tick"],
            }
        )
        return {
            "source": "snowflake",
            "simulation_id": sid,
            "requested_revision": requested,
            "effective_revision": effective,
            "coverage": coverage,
            "enabled": self.enabled,
            "state": "disabled"
            if not self.enabled
            else "failed"
            if error
            else "backfilling"
            if ingested < 0
            else "lagged"
            if ingested < requested
            else "healthy",
            "published_revision": head.simulation.revision,
            "ingested_revision": ingested,
            "lag_revisions": max(0, requested - ingested),
            "error_code": error,
        }

    async def context(self, owner, sid, requested):
        self.core.owned(owner, sid, requested)
        require(self.enabled, "FEATURE_UNAVAILABLE", "Snowflake observations are disabled", 501)
        require(not self.start_error, "SERVICE_UNAVAILABLE", "Observation progress is unavailable", 503)
        try:
            rows = await self.read("obs_head", (owner, sid, requested))
            data = json.loads(rows[0][0]) if len(rows) == 1 else {}
            effective = data.get("revision")
        except (VendorUnavailable, ValueError, IndexError, TypeError):
            raise DomainError("SERVICE_UNAVAILABLE", "Snowflake observations are unavailable", 503)
        require(effective is not None, "SERVICE_UNAVAILABLE", "Observations are backfilling", 503)
        return {
            "source": "snowflake",
            "simulation_id": sid,
            "requested_revision": requested,
            "effective_revision": effective,
            "coverage": {
                "state": "complete" if effective == requested else "partial",
                "from_tick": data.get("from_tick"),
                "through_tick": data.get("tick"),
            },
        }

    async def read(self, shape, values):
        require(not self.reads.locked(), "RATE_LIMITED", "Observation queries are busy; retry later", 429)
        async with self.reads:
            try:
                async with asyncio.timeout(self.config.deadline):
                    async with self.gate:
                        return await self.transport.execute(shape, values)
            except TimeoutError:
                raise VendorUnavailable("query_deadline") from None

    async def query(self, owner, sid, kind, revision, **filters):
        # Always authorize before a cached read or a warehouse request.
        self.core.owned(owner, sid, revision)
        require(self.enabled, "FEATURE_UNAVAILABLE", "Snowflake observations are disabled", 501)
        if kind == "trends":
            require(filters.get("metric") in METRICS, "INVALID_REQUEST", "Unknown observation metric", 400)
        start = filters.get("start_tick", 0)
        end = filters.get("end_tick", 9007199254740991)
        require(start <= end, "INVALID_REQUEST", "Start tick must not exceed end tick", 400)
        key = (owner, sid, kind, revision, encode(filters))
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        context = await self.context(owner, sid, revision)
        params = dict(
            owner_id=owner,
            simulation_id=sid,
            through_revision=context["effective_revision"],
            start_tick=start,
            end_tick=end,
            offset=0,
            limit=51,
        )
        params.update({k: v for k, v in filters.items() if k != "after" and v is not None})
        page_limit = filters.get("limit", 50)
        params["limit"] = page_limit + 1
        cursor_filters = {k: v for k, v in filters.items() if k != "after"}
        resource = f"observations:{sid}:{kind}"
        cursor = self.parent.state.cursors.context(
            owner, resource, cursor_filters, revision, filters.get("after")
        )
        if cursor:
            require(
                cursor.get("effective_revision") == context["effective_revision"],
                "INVALID_REQUEST",
                "Coverage changed; restart pagination",
                400,
            )
            params["offset"] = cursor["offset"]
        try:
            rows = await self.read("obs_" + kind, (encode(params).decode(),))
            if kind in {"events", "changes"}:
                items = [json.loads(row[0]) for row in rows]
                next_after = None
                if len(items) > page_limit:
                    next_after = self.parent.state.cursors.sign(
                        dict(
                            owner=owner,
                            resource=resource,
                            filters=cursor_filters,
                            revision=revision,
                            effective_revision=context["effective_revision"],
                            offset=params["offset"] + page_limit,
                        )
                    )
                result = dict(context, items=items[:page_limit], next_after=next_after)
            else:
                require(len(rows) == 1, "SERVICE_UNAVAILABLE", "Observation result is incomplete", 503)
                value = json.loads(rows[0][0])
                require(isinstance(value, dict), "SERVICE_UNAVAILABLE", "Invalid observation result", 503)
                if kind == "event_detail":
                    require(
                        value.get("event") is not None, "NOT_FOUND", "Event not found in observations", 404
                    )
                    value = self.event_observations(value)
                else:
                    value.update(metric=filters["metric"], unit=METRICS[filters["metric"]]["unit"])
                result = dict(context, **value)
            # Fail closed on invalid/nonfinite warehouse output.
            json.dumps(result, allow_nan=False)
        except (VendorUnavailable, ValueError, TypeError, KeyError, IndexError):
            raise DomainError("SERVICE_UNAVAILABLE", "Snowflake observation query failed", 503)
        if len(self.cache) >= 128:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = (time.monotonic(), result)
        return result

    @staticmethod
    def event_observations(value):
        # Arithmetic comes from SQL. Rendering and citations are server-owned.
        facts = value.pop("numeric_observations", [])
        observations = []
        citations = value.get("citations", [])
        for fact in facts:
            delta = fact.get("delta")
            if not isinstance(delta, (int, float)) or not math.isfinite(delta):
                continue
            metric = fact["metric"]
            cid = f"event:{value['event']['event_id']}:{metric}"
            citations.append(
                {
                    "id": cid,
                    "tick": value["resolution"]["tick"],
                    "revision": fact["revision"],
                    "description": f"Recorded event baseline and resolution: {metric}",
                }
            )
            observations.append(
                {
                    "id": f"event:{metric}",
                    "text": f"{metric.replace('_', ' ').capitalize()} changed by {delta:+.2f} during the event "
                    "(observed change; other activity may contribute).",
                    "citation_ids": [cid],
                }
            )
        value["observations"] = observations
        value["citations"] = citations
        return value
