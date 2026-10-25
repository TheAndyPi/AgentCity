"""Opt-in paid SQL verification using a disposable locally committed city.

Provision sql/003_observations.sql in a dedicated schema named
AGENTCITY_OBSERVATION_SMOKE_<suffix> first, then run from backend:
python -m scripts.snowflake_observations_smoke --live --schema AGENTCITY_OBSERVATION_SMOKE_TEST

No DDL or Cortex calls are made. Only this run's owner/simulation rows are cleaned.
Credentials come from the server environment and are never printed.
"""

import argparse
import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from app import contracts as c
from app.api.views import Cursors
from app.behavior.models import Impact
from app.infrastructure.config import AppConfig
from app.service import Service
from app.simulation.agents import connect, evidence
from app.simulation.state import EventRuntime
from app.snowflake.config import SnowflakeConfig
from app.snowflake.observations import ObservationService
from app.snowflake.observations_projection import capture_baseline, project
from app.snowflake.transport import SnowflakeTransport, VendorUnavailable


async def verify(schema):
    if not re.fullmatch(r"AGENTCITY_OBSERVATION_SMOKE_[A-Z0-9_]{1,48}", schema):
        raise ValueError("An explicitly provisioned dedicated observation smoke schema is required")
    config = replace(SnowflakeConfig.from_env(), enabled=True, schema=schema, deadline=30)
    config.validate()
    owner, sid = "observation_smoke_" + uuid4().hex, None
    transport = SnowflakeTransport(config)
    with TemporaryDirectory(prefix="agentcity-observation-smoke-") as directory:
        service = Service(AppConfig(data_dir=Path(directory)))
        parent = SimpleNamespace(
            state=SimpleNamespace(service=service, cursors=Cursors(service.repo.meta["cursor_secret"]))
        )
        observer = ObservationService(parent, config, transport)
        await service.start()
        try:
            tx = service.create(
                owner,
                c.CreateSimulation.model_validate(
                    {"config": {"name": "Observation SQL verification", "seed": 4242, "population": 10}}
                ),
            )
            await service.persist(tx.states)
            sid = tx.initialize
            await service.initialize(sid)
            state = service.repo.read(sid)
            assert state.simulation.initialization.stage == "ready"
            a, b = list(state.citizens.values())[:2]
            for citizen in state.citizens.values():
                citizen.relationships.clear()
            connect(state, a, b)
            connect(state, b, a)
            a.relationships[b.summary.id].trust = 20
            b.relationships[a.summary.id].trust = 80
            a.beliefs = [c.Belief(text="Recorded smoke belief", confidence=30, evidence=evidence("Smoke"))]
            spec = c.EventSpec(
                title="Observation smoke event",
                description="Controlled measurement fixture",
                kind="custom",
                origin=a.summary.position,
                affected_polygon=state.map.zones[0].polygon,
                severity=0,
                duration_ticks=1,
                effects=[
                    c.WellbeingEffect(
                        type="wellbeing",
                        happiness_delta=0,
                        stress_delta=0,
                        health_delta=0,
                    )
                ],
                success_condition="duration_elapsed",
            )
            eid = state.next_id("event")
            summary = c.EventSummary(
                id=eid,
                title=spec.title,
                kind="custom",
                status="queued",
                queued_tick=0,
                start_tick=None,
                end_tick=None,
                affected_agent_count=10,
                affected_polygon=spec.affected_polygon,
                pre_event_snapshot_id=state.snapshots[0].id,
                summary="Controlled observation verification",
            )
            values = state.metric_points[-1].values
            state.events[eid] = EventRuntime(summary=summary, spec=spec, before=values, after=values)
            service.bump(state)
            state.simulation.tick = 1
            await service.persist([state])
            baseline_revision = state.simulation.revision
            state = service.repo.read(sid)
            runtime = state.events[eid]
            runtime.observation_baseline = capture_baseline(state)
            runtime.cohort = list(state.citizens)
            runtime.summary.start_tick = 1
            runtime.summary.end_tick = 2
            runtime.summary.status = "resolved"
            a = state.citizens[a.summary.id]
            a.needs.health = 40
            a.relationships[b.summary.id].trust = 60
            a.beliefs[0].confidence = 90
            a.condition.impacts.append(
                Impact(
                    tick=2,
                    phase="smoke",
                    meter="health",
                    reason="Controlled observed event",
                    delta=-60,
                    evidence=evidence("Recorded smoke injury", event_ids=[eid]),
                )
            )
            service.bump(state)
            state.simulation.tick = 2
            await service.persist([state])
            revision = state.simulation.revision
            envelopes, previous = [], None
            for index, entry in enumerate(service.repo.meta["simulations"][sid]):
                current = service.repo.read(sid, index)
                envelope = project(previous, current)
                envelope["source_sha256"] = entry["sha256"]
                envelopes.append(envelope)
                await observer.ingest(envelope)
                previous = current
            # Repeat the complete history through a fresh service object, reproducing
            # loss/recovery of the local read-model checkpoint.
            recovered = ObservationService(parent, config, transport)
            for envelope in envelopes:
                await recovered.ingest(envelope)
            params = dict(
                owner_id=owner,
                simulation_id=sid,
                through_revision=revision,
                start_tick=0,
                end_tick=10,
                metric="health",
                agent_id=a.summary.id,
                limit=101,
                offset=0,
            )
            rows = await transport.execute("obs_trends", (json.dumps(params),))
            values = json.loads(rows[0][0])
            assert values["items"][-1]["mean"] == 40
            params["through_revision"] = baseline_revision
            rows = await transport.execute("obs_trends", (json.dumps(params),))
            assert json.loads(rows[0][0])["items"][-1]["mean"] == 100
            params.update(through_revision=revision, metric="relationship_trust")
            rows = await transport.execute("obs_trends", (json.dumps(params),))
            assert json.loads(rows[0][0])["items"][-1]["mean"] == 60
            params.update(agent_id=b.summary.id)
            rows = await transport.execute("obs_trends", (json.dumps(params),))
            assert json.loads(rows[0][0])["items"][-1]["mean"] == 80
            params.pop("agent_id")
            params["event_id"] = eid
            rows = await transport.execute("obs_changes", (json.dumps(params),))
            changes = [json.loads(row[0]) for row in rows]
            injury = next(change for change in changes if change["field"] == "health")
            assert (injury["before"], injury["after"], injury["link"]) == (100, 40, "explicit")
            assert injury["event_ids"] == [eid]
            rows = await transport.execute("obs_event_detail", (json.dumps(params),))
            detail = observer.event_observations(json.loads(rows[0][0]))
            assert detail["baseline"]["city"]["health"] == 100
            assert detail["resolution"]["city"]["health"] == 94
            assert detail["resolution"]["denominators"]["city"]["health"] == 10
            assert detail["observations"] and detail["citations"]
            assert not detail["followup_complete"]
            print(
                "Live observation SQL, retry/rebuild, pinned health/directed trust, event baseline and citations: passed"
            )
            return True
        except Exception as error:
            print(
                "Live observation verification failed:",
                type(error).__name__,
                error.reason if isinstance(error, VendorUnavailable) else "local_validation",
            )
            return False
        finally:
            try:
                if sid is not None:
                    await transport.execute("obs_delete_revisions", (owner, sid))
                    await transport.execute("obs_delete_facts", (owner, sid))
            finally:
                await service.close()
                await transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(verify(args.schema)) else 1)


if __name__ == "__main__":
    main()
