import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path / "store", base_tps=5))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        yield client


def write(client, path, body, method="POST", key=None):
    key = key or str(uuid4())
    response = client.request(method, "/api/v1" + path, json=body, headers={"Idempotency-Key": key})
    return response


def create_city(client, **config):
    response = write(
        client, "/simulations", dict(config=dict(name="Test city", seed=42, population=10) | config)
    )
    assert response.status_code == 202, response.text
    sid = response.json()["data"]["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        if simulation["status"] != "initializing":
            assert simulation["status"] == "paused", simulation
            return simulation
        time.sleep(0.01)
    raise AssertionError("Initialization timed out")


def command(client, sid, type, **fields):
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    key = str(uuid4())
    return write(
        client,
        f"/simulations/{sid}/commands",
        dict(
            request_id=key,
            expected_control_version=simulation["control_version"],
            command=dict(type=type, **fields),
        ),
        key=key,
    )


def preview(client, sid, prompt="A flood for 2 ticks"):
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    hold = write(
        client,
        f"/simulations/{sid}/interventions",
        dict(expected_control_version=simulation["control_version"]),
    )
    assert hold.status_code == 201, hold.text
    hold = hold.json()["data"]
    response = write(
        client,
        f"/simulations/{sid}/scenario-previews",
        dict(intervention_id=hold["id"], source="custom", source_event_id=None, prompt=prompt, policy=None),
    )
    assert response.status_code == 201, response.text
    return hold, response.json()["data"]


def commit_preview(client, sid, hold, preview, key=None):
    return write(
        client,
        f"/simulations/{sid}/scenario-commits",
        dict(
            intervention_id=hold["id"],
            preview_id=preview["id"],
            expected_control_version=hold["control_version"],
        ),
        key=key,
    )
