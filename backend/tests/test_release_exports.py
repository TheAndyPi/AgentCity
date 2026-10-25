"""Read-back acceptance for the revision-pinned inputs used by new integrations."""

import csv
import io

from conftest import command, create_city, write
from fastapi.testclient import TestClient

from app import contracts as c
from app.infrastructure.config import AppConfig
from app.main import create_app


def exported(client, sid, revision):
    response = client.get(f"/api/v1/simulations/{sid}/export", params={"through_revision": revision})
    assert response.status_code == 200, response.text
    value = response.json()["data"]
    c.Export.model_validate(value)
    return value


def test_pinned_export_matches_csv_metrics_and_survives_head_changes_and_restart(tmp_path):
    config = AppConfig(data_dir=tmp_path / "store")
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        sid = create_city(client)["id"]
        stepped = command(client, sid, "step", count=3)
        assert stepped.status_code == 200, stepped.text
        revision = stepped.json()["data"]["simulation"]["revision"]
        baseline = exported(client, sid, revision)
        metrics = client.get(f"/api/v1/simulations/{sid}/metrics", params={"revision": revision}).json()[
            "data"
        ]["points"]
        assert baseline["metrics"] == metrics
        state = client.get(f"/api/v1/simulations/{sid}/state", params={"revision": revision}).json()["data"]
        assert metrics[-1] == state["metrics"]
        response = client.get(
            f"/api/v1/simulations/{sid}/export",
            params={"format": "csv", "through_revision": revision},
        )
        assert response.status_code == 200, response.text
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == len(metrics) and rows
        for row, point in zip(rows, metrics, strict=True):
            assert row["simulation_id"] == sid
            assert int(row["tick"]) == point["tick"]
            assert int(row["revision"]) == point["revision"]
            for field, value in point["values"].items():
                assert float(row[field]) == value
            for field in (
                "cooperation_count",
                "conflict_count",
                "resources_consumed",
                "evacuated_count",
                "exposed_count",
            ):
                assert float(row[field]) == point[field]
        assert command(client, sid, "step", count=2).status_code == 200
        assert exported(client, sid, revision) == baseline
    with TestClient(create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert exported(client, sid, revision) == baseline


def test_branch_export_keeps_its_identity_and_survives_source_deletion(client):
    source = create_city(client)
    sid = source["id"]
    assert command(client, sid, "step", count=2).status_code == 200
    response = write(
        client, f"/simulations/{sid}/branches", {"name": "Release comparison", "source": {"kind": "whole"}}
    )
    assert response.status_code == 201, response.text
    branch = response.json()["data"]["simulation"]
    bid = branch["id"]
    assert bid != sid and branch["parent_simulation_id"] == sid
    assert command(client, bid, "step", count=1).status_code == 200
    revision = client.get(f"/api/v1/simulations/{bid}").json()["data"]["revision"]
    baseline = exported(client, bid, revision)
    assert baseline["simulation"]["id"] == bid
    assert baseline["simulation"]["tick"] == 3
    assert baseline["frames"]
    assert all(frame["simulation"]["id"] == bid for frame in baseline["frames"])
    assert all(
        snapshot["simulation_id"] == bid
        for snapshot in client.get(f"/api/v1/simulations/{bid}/snapshots").json()["data"]["items"]
    )
    assert command(client, sid, "archive").status_code == 200
    deleted = write(client, f"/simulations/{sid}", {"confirmation_name": source["name"]}, method="DELETE")
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/v1/simulations/{sid}").status_code == 404
    assert exported(client, bid, revision) == baseline
