"""Bounded, restartable committed-history ingestion. Never called under the writer.

Only public export projections are sent: metric points, decisions, event reports,
and sampled agent summaries. No profiles, dialogue, memories or relationship edges.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.api.views import frame
from app.data.repository import encode
from app.simulation.scenarios import event_report
from app.simulation.state import now

LOG = logging.getLogger("agentcity.tiger")
MIGRATIONS = Path(__file__).with_name("migrations")
MAX_ROWS = 2000
MAX_BYTES = 2 * 1024 * 1024
SQL_BATCH = 100


class ProjectionLimit(ValueError):
    pass


@dataclass(frozen=True)
class Batch:
    simulation_id: str
    revision: int
    tick: int
    sim_time_seconds: float
    provenance: dict
    records: list[tuple[str, str, int, dict]]


def project(state, lineage, sample_ticks):
    """One immutable revision, using the exact objects exposed by the JSON export.

    Reconciliation visits every revision. Decisions are immutable after publication;
    those at this tick are upserted by entity ID. Event reports are revision snapshots.
    Metric versions retain same-tick edits, allowing reads pinned before later edits.
    """
    sim = state.simulation
    provenance = dict(
        simulation_id=sim.id,
        parent_simulation_id=lineage.parent_simulation_id,
        fork_ref=lineage.fork_ref.model_dump(mode="json") if lineage.fork_ref else None,
        seed=sim.config.seed,
        engine_version=state.rule_version,
        contract_version=state.schema_version,
    )
    records = []
    size = len(encode(provenance))

    def add(kind, identity, tick, payload):
        nonlocal size
        size += len(encode(payload))
        if len(records) >= MAX_ROWS or size > MAX_BYTES:
            raise ProjectionLimit("Committed projection exceeds ingestion budget")
        records.append((kind, str(identity), tick, payload))

    if sim.initialization.stage == "ready":
        # These are the same projections used by GET .../export?through_revision=.
        for point in state.metric_points[-1:]:
            add("metric", f"{point.revision}:{point.tick}", point.tick, point.model_dump(mode="json"))
        for decision in reversed(state.decisions):
            if decision.tick < sim.tick:
                break
            add("decision", decision.id, decision.tick, decision.model_dump(mode="json"))
        for runtime in state.events.values():
            report = event_report(state, runtime)
            add("event", f"{sim.revision}:{report.event.id}", sim.tick, report.model_dump(mode="json"))
        if state.conditions:
            from app.disasters.physics import event_view

            for runtime in state.events.values():
                if runtime.physical:
                    add("disaster_event", runtime.summary.id, sim.tick, event_view(state, runtime))
            for bid, condition in state.conditions.items():
                add("condition", bid, sim.tick, dict(**condition.model_dump(), stage=condition.stage))
            for change in state.service_changes:
                if change["tick"] == sim.tick:
                    add("service", change["id"], sim.tick, change)
            for damage in state.damage_records:
                if damage.tick == sim.tick:
                    add("damage", damage.id, damage.tick, damage.model_dump())
            for reaction in state.reactions:
                if reaction.tick == sim.tick:
                    add("reaction", reaction.id, reaction.tick, reaction.model_dump())
            # Group bounded map cells into one canonical terrain revision, avoiding
            # per-cell row-budget gaps on a citywide hazard.
            add(
                "terrain",
                f"{sim.revision}:terrain",
                sim.tick,
                dict(schema_version="2.0.0", cells=[t.model_dump() for t in state.terrain_damage.values()]),
            )
            for repair in state.repairs:
                add("repair", repair.id, sim.tick, repair.model_dump())
        if sim.tick % sample_ticks == 0:
            for agent in frame(state).agents:
                add("movement", f"{sim.revision}:{agent.id}", sim.tick, agent.model_dump(mode="json"))
    return Batch(sim.id, sim.revision, sim.tick, sim.sim_time_seconds, provenance, records)


class PostgresSink:
    """One bounded connection/transaction at a time; no pool or owner-only DDL.

    A private selector loop supports psycopg on Windows as well as Linux. Awaiting
    cancellation drains that one bounded operation before releasing process ownership.
    """

    def __init__(self, config):
        from psycopg.conninfo import conninfo_to_dict

        self.config = config
        try:
            parameters = conninfo_to_dict(config.tiger_database_url)
            host = parameters.get("host", "")
            if not host or host.startswith("/") or "," in host:
                raise ValueError
        except Exception:
            raise ValueError("TIGER_DATABASE_URL must specify one TLS PostgreSQL host") from None

    async def _call(self, operation):
        def run():
            # Explicit loop factory avoids process-wide event-loop policy changes.
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                return runner.run(self._execute(operation))

        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _execute(self, operation):
        import certifi
        import psycopg
        from psycopg.conninfo import conninfo_to_dict

        connection = None
        try:
            async with asyncio.timeout(self.config.tiger_timeout):
                connection = await psycopg.AsyncConnection.connect(
                    self.config.tiger_database_url,
                    sslmode="verify-full",
                    sslrootcert=conninfo_to_dict(self.config.tiger_database_url).get(
                        "sslrootcert", certifi.where()
                    ),
                    gssencmode="disable",
                    connect_timeout=math.ceil(self.config.tiger_timeout),
                    application_name="agentcity_tiger",
                    options="-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000",
                )
                async with connection:
                    from psycopg import sql

                    await connection.execute(
                        sql.SQL("SET LOCAL search_path TO {}, pg_catalog").format(
                            sql.Identifier(self.config.tiger_schema)
                        )
                    )
                    return await operation(connection)
        finally:
            if connection is not None and not connection.closed:
                # Close the socket even when cancellation interrupted a transaction.
                connection.pgconn.finish()

    async def migrate(self):
        async def operation(connection):
            # The schema is pre-provisioned; CREATE/USAGE there is sufficient.
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS tiger_migrations (version text PRIMARY KEY, sha256 text NOT NULL)"
            )
            for path in sorted(MIGRATIONS.glob("*.sql")):
                source = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(source.encode()).hexdigest()
                cursor = await connection.execute(
                    "SELECT sha256 FROM tiger_migrations WHERE version = %s", (path.name,)
                )
                row = await cursor.fetchone()
                if row:
                    if row[0] != digest:
                        raise ValueError("Migration checksum mismatch")
                    continue
                await connection.execute(source, prepare=False)
                await connection.execute(
                    "INSERT INTO tiger_migrations (version, sha256) VALUES (%s, %s)", (path.name, digest)
                )

        return await self._call(operation)

    async def ingest(self, batch):
        async def operation(connection):
            from psycopg.types.json import Jsonb

            stamp = now()
            await connection.execute(
                "INSERT INTO tiger_simulations (simulation_id, provenance, ingested_at) VALUES (%s,%s,%s) "
                "ON CONFLICT (simulation_id) DO UPDATE SET provenance = EXCLUDED.provenance",
                (batch.simulation_id, Jsonb(batch.provenance), stamp),
            )
            query = (
                "INSERT INTO tiger_records (simulation_id,kind,entity_key,revision,tick,sim_time_seconds,"
                "payload,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (simulation_id,kind,entity_key) DO UPDATE SET revision=EXCLUDED.revision,"
                "tick=EXCLUDED.tick,sim_time_seconds=EXCLUDED.sim_time_seconds,payload=EXCLUDED.payload "
                "WHERE tiger_records.revision < EXCLUDED.revision "
                "AND tiger_records.payload IS DISTINCT FROM EXCLUDED.payload"
            )
            async with connection.cursor() as cursor:
                for start in range(0, len(batch.records), SQL_BATCH):
                    await cursor.executemany(
                        query,
                        [
                            (
                                batch.simulation_id,
                                kind,
                                key,
                                payload["revision"] if kind == "metric" else batch.revision,
                                tick,
                                batch.sim_time_seconds,
                                Jsonb(payload),
                                stamp,
                            )
                            for kind, key, tick, payload in batch.records[start : start + SQL_BATCH]
                        ],
                    )
            # A database cursor is committed atomically with rows; it is diagnostic,
            # never trusted to skip missing history after a local restore.
            await connection.execute(
                "INSERT INTO tiger_progress (simulation_id,revision,ingested_at) VALUES (%s,%s,%s) "
                "ON CONFLICT (simulation_id) DO UPDATE SET revision=EXCLUDED.revision,"
                "ingested_at=EXCLUDED.ingested_at WHERE tiger_progress.revision < EXCLUDED.revision",
                (batch.simulation_id, batch.revision, stamp),
            )

        return await self._call(operation)


class TigerIngestor:
    def __init__(self, service, sink=None):
        self.service = service
        self.config = service.config
        self.sink = sink
        self.task = None
        self.wakeup = asyncio.Event()  # Coalesced hint, never a queue of states.
        self.progress = {}
        self.error_code = None
        self.retry_at = 0.0
        self.available = False
        self.path = self.config.data_dir / "tiger-progress.json"
        self.after = ""

    def start(self):
        if self.config.tiger_enabled:
            self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def notify(self):
        if self.config.tiger_enabled:
            self.wakeup.set()

    def _load(self):
        if not self.path.exists():
            return {}
        wrapper = json.loads(self.path.read_bytes())
        if wrapper["sha256"] != hashlib.sha256(encode(wrapper["data"])).hexdigest():
            raise ValueError("Invalid Tiger progress checksum")
        if not isinstance(wrapper["data"], dict) or any(
            not isinstance(key, str)
            or not isinstance(value, dict)
            or type(value.get("revision")) is not int
            or value["revision"] < 0
            or not isinstance(value.get("sha256"), str)
            or len(value["sha256"]) != 64
            for key, value in wrapper["data"].items()
        ):
            raise ValueError("Invalid Tiger progress records")
        return wrapper["data"]

    def _save(self, progress):
        # Dedicated metadata file: failures cannot degrade authoritative persistence.
        data = encode(progress)
        temp = self.path.with_suffix(".tmp")
        with temp.open("wb") as handle:
            handle.write(encode(dict(data=progress, sha256=hashlib.sha256(data).hexdigest())))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        if os.name != "nt":
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _revision(self, sid):
        saved = self.progress.get(sid)
        entries = self.service.repo.meta["simulations"].get(sid, ())
        if saved:
            entry = next((entry for entry in entries if entry["revision"] == saved["revision"]), None)
            if entry and entry["sha256"] == saved["sha256"]:
                return saved["revision"]
        return -1

    async def reconcile(self):
        # Round-robin one simulation and bounded revisions per turn. Pending work
        # lives in the durable journal; memory contains only one projection.
        keys = sorted(self.service.heads)
        ordered = [sid for sid in keys if sid > self.after] + [sid for sid in keys if sid <= self.after]
        for sid in ordered:
            head = self.service.heads.get(sid)
            if head is None or self._revision(sid) >= head.simulation.revision:
                continue
            self.after = sid
            advanced = False
            for _ in range(self.config.tiger_revision_batch):
                head = self.service.heads.get(sid)
                previous = self._revision(sid)
                if head is None:
                    break
                entries = self.service.repo.meta["simulations"].get(sid, ())
                entry = next((item for item in entries if item["revision"] > previous), None)
                if entry is None:
                    break
                revision, digest = entry["revision"], entry["sha256"]
                try:
                    state = await asyncio.to_thread(self.service.repo.read, sid, revision)
                except KeyError:
                    break  # A concurrent committed deletion is not a vendor failure.
                state.decisions = self.service.history(state, "decisions")
                state.metric_points = self.service.history(state, "metric_points")
                batch = await asyncio.to_thread(
                    project, state, head.simulation, self.config.tiger_sample_ticks
                )
                # No local lock is held across this optional network boundary.
                async with asyncio.timeout(self.config.tiger_timeout):
                    await self.sink.ingest(batch)
                progress = {key: value for key, value in self.progress.items() if key in self.service.heads}
                progress[sid] = dict(revision=revision, sha256=digest)
                save = asyncio.create_task(asyncio.to_thread(self._save, progress))
                try:
                    await asyncio.shield(save)
                except asyncio.CancelledError:
                    await save
                    raise
                self.progress = progress
                advanced = True
                await asyncio.sleep(0)
            # The journal can publish a deletion before the service removes its
            # old head. No work means wait/yield, never a tight True/pending loop.
            return advanced
        return False

    async def run(self):
        delay = self.config.tiger_retry_min
        migrated = False
        try:
            self.progress = await asyncio.to_thread(self._load)
        except (OSError, ValueError, KeyError, TypeError):
            # A lost cursor means replay, never skipped records.
            self.error_code = "PROGRESS_INVALID"
        while True:
            try:
                if self.sink is None:
                    self.sink = PostgresSink(self.config)
                if not migrated:
                    async with asyncio.timeout(self.config.tiger_timeout):
                        await self.sink.migrate()
                    migrated = True
                pending = await self.reconcile()
                self.available, self.error_code, self.retry_at = True, None, 0.0
                delay = self.config.tiger_retry_min
                if pending:
                    continue
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), self.config.tiger_poll_seconds)
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.available = False
                self.error_code = (
                    "PROJECTION_LIMIT" if isinstance(error, ProjectionLimit) else "INGESTION_UNAVAILABLE"
                )
                LOG.warning("Tiger ingestion unavailable (%s)", self.error_code)
                self.retry_at = time.monotonic() + delay
                # New publications cannot bypass outage backoff.
                await asyncio.sleep(delay)
                delay = min(self.config.tiger_retry_max, delay * 2)

    def status(self, owner, sid=None, after=None, limit=25):
        keys = sorted(
            key
            for key, head in self.service.heads.items()
            if head.owner_id == owner and (sid is None or key == sid) and (after is None or key > after)
        )
        items = []
        for key in keys[:limit]:
            published = self.service.heads[key].simulation.revision
            ingested = self._revision(key)
            items.append(
                dict(
                    simulation_id=key,
                    published_revision=published,
                    ingested_revision=ingested,
                    lag_revisions=published - ingested,
                )
            )
        return dict(
            enabled=self.config.tiger_enabled,
            state="disabled"
            if not self.config.tiger_enabled
            else (
                "unavailable"
                if not self.available
                else ("catching_up" if any(item["lag_revisions"] for item in items) else "healthy")
            ),
            error_code=self.error_code,
            retry_in_seconds=round(max(0.0, self.retry_at - time.monotonic()), 3),
            simulations=items,
            next_after=keys[limit - 1] if len(keys) > limit else None,
        )
