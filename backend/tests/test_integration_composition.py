"""The merged default app exposes all three adapters without mount shadowing."""

import asyncio

from conftest import command, create_city, write
from fastapi.testclient import TestClient
from narration_fake import ElevenLabsFake, config, marked_audio
from snowflake_fake import SnowflakeFake

from app.infrastructure.config import AppConfig
from app.integrations import tiger
from app.main import create_app
from app.snowflake import router as snowflake_router
from app.snowflake.config import SnowflakeConfig


def test_default_app_runs_tiger_comparison_and_authorized_audio_together(tmp_path, monkeypatch):
    class Sink:
        def __init__(self):
            self.batches = []

        async def migrate(self):
            pass

        async def ingest(self, batch):
            self.batches.append(batch)

    sink = Sink()
    snowflake, speech = SnowflakeFake(), ElevenLabsFake()
    snow = SnowflakeConfig(
        enabled=True,
        account="test-account",
        user="TEST",
        database="TEST",
        schema="TEST",
        warehouse="TEST",
        role="TEST",
        private_key_file=__file__,
    )
    monkeypatch.setattr(SnowflakeConfig, "from_env", classmethod(lambda cls: snow))
    monkeypatch.setattr(snowflake_router, "SnowflakeTransport", snowflake.transport)
    monkeypatch.setattr(tiger, "PostgresSink", lambda config: sink)
    narration = config()
    app = create_app(
        AppConfig(
            data_dir=tmp_path / "store",
            tiger_enabled=True,
            tiger_database_url="controlled-fake-only",
            tiger_poll_seconds=0.01,
        ),
        narration,
        speech.transport(narration),
    )
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        capabilities = client.get("/api/v1/capabilities").json()["data"]
        assert capabilities["snowflake"] and capabilities["narration"]
        assert capabilities["persistence"] == "local"
        source = create_city(client)
        sid = source["id"]
        assert command(client, sid, "step", count=2).status_code == 200
        source = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        branched = write(
            client, f"/simulations/{sid}/branches", {"name": "Merged adapters", "source": {"kind": "whole"}}
        )
        assert branched.status_code == 201, branched.text
        branch = branched.json()["data"]["simulation"]
        response = write(
            client,
            "/integrations/snowflake/comparisons",
            {
                "a": {"simulation_id": sid, "revision": source["revision"]},
                "b": {"simulation_id": branch["id"], "revision": branch["revision"]},
                "question": "What recorded differences accompany cooperation in these histories?",
            },
        )
        assert response.status_code == 200, response.text
        comparison = response.json()["data"]
        assert comparison["data_source"] == "snowflake"
        assert comparison["explanation"]["source"] == "cortex_selection"
        assert comparison["lineage"] == "parent_branch"
        assert all(difference["delta_b_minus_a"] == 0 for difference in comparison["differences"])
        frame = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]
        decision = next(
            agent["latest_decision_id"] for agent in frame["agents"] if agent["latest_decision_id"]
        )
        response = write(
            client, f"/simulations/{sid}/narration", {"source_type": "decision", "source_id": decision}
        )
        assert response.status_code == 200, response.text
        media = client.get(response.json()["data"]["audio_url"])
        assert media.status_code == 200, media.text
        assert media.headers["content-type"] == "audio/mpeg"
        assert media.content == marked_audio(speech.texts[0])
        assert len(speech.requests) == 1 and len(snowflake.rows) == 2

        async def reconciled():
            async with asyncio.timeout(10):
                while any(
                    app.state.service.tiger._revision(key) < head.simulation.revision
                    for key, head in app.state.service.heads.items()
                ):
                    await asyncio.sleep(0.001)

        client.portal.call(reconciled)
        status = client.get("/api/v1/integrations/tiger/status")
        assert status.status_code == 200, status.text
        assert status.json()["data"]["enabled"]
        assert all(item["lag_revisions"] == 0 for item in status.json()["data"]["simulations"])
        assert {batch.simulation_id for batch in sink.batches} == {sid, branch["id"]}
        extension_paths = client.get("/api/v1/integrations/openapi.json").json()["paths"]
        assert "/tiger/status" in extension_paths and "/snowflake/comparisons" in extension_paths
