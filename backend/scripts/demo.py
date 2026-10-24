"""Seed and rehearse a durable flood timeline via the real API, with no providers."""

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app
from scripts.client import Driver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo-trace.json"))
    args = parser.parse_args()
    with TestClient(
        create_app(AppConfig(data_dir=args.data_dir)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as client:
        driver = Driver(client)
        simulation = driver.city(scenario_description="A flood severity 65 for 6 ticks")
        sid = simulation["id"]
        queued = driver.write(
            f"/simulations/{sid}/initial-scenario",
            dict(
                preview_id=simulation["initial_preview"]["id"],
                decision="confirm",
                expected_control_version=simulation["control_version"],
            ),
        )["data"]
        driver.command(sid, "step", count=10)
        report = driver.get(f"/simulations/{sid}/events/{queued['event']['id']}")
        assert report["event"]["status"] == "resolved"
        branch = driver.write(
            f"/simulations/{sid}/branches",
            dict(
                name="Restored pre-flood copy",
                source=dict(kind="snapshot", snapshot_id=queued["snapshot"]["id"]),
            ),
        )["data"]
        assert branch["simulation"]["tick"] == 0
        trace = dict(
            contract_version="1.0.0",
            mode="rules",
            simulation_id=sid,
            restored_simulation_id=branch["simulation"]["id"],
            report=report,
            requests=driver.trace,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        (args.output.parent / "request-response-trace.json").write_text(
            json.dumps(driver.trace, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                dict(
                    simulation_id=sid,
                    restored_simulation_id=branch["simulation"]["id"],
                    event_status=report["event"]["status"],
                    trace=str(args.output.resolve()),
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
