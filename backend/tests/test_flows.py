import time
from uuid import uuid4

from conftest import command, commit_preview, create_city, preview, write

from app import contracts as c


def test_initialization_state_and_ticks(client):
    simulation = create_city(client)
    sid = simulation["id"]
    state = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]
    c.WorldFrame.model_validate(state)
    assert len(state["map"]["cells"]) == 4096
    assert len(state["agents"]) == 10
    assert state["ref"]["tick"] == 0
    time.sleep(0.25)
    assert client.get(f"/api/v1/simulations/{sid}").json()["data"]["tick"] == 0
    stepped = command(client, sid, "step", count=2)
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["data"]["simulation"]["tick"] == 2
    assert stepped.json()["data"]["simulation"]["status"] == "paused"
    agent = client.get(f"/api/v1/simulations/{sid}/agents").json()["data"]["items"][0]
    inspector = client.get(f"/api/v1/simulations/{sid}/agents/{agent['id']}").json()["data"]
    c.AgentDetail.model_validate(inspector)
    assert inspector["decisions"]["items"]
    assert inspector["decisions"]["items"][0]["source"] == "rules"


def test_flood_queue_outcome_undo_and_history(client):
    simulation = create_city(client)
    sid = simulation["id"]
    hold, view = preview(client, sid)
    before = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]
    result = commit_preview(client, sid, hold, view)
    assert result.status_code == 201, result.text
    result = result.json()["data"]
    event = result["event"]
    assert event["status"] == "queued"
    assert result["simulation"]["status"] == "paused"
    assert result["simulation"]["tick"] == 0
    queued = client.get(f"/api/v1/simulations/{sid}/events/{event['id']}")
    assert queued.status_code == 200, queued.text
    step = command(client, sid, "step", count=10)
    assert step.status_code == 200, step.text
    sim = step.json()["data"]["simulation"]
    assert sim["tick"] == 3
    assert sim["pause_reason"] == "outcome"
    assert sim["pending_outcome_event_ids"] == [event["id"]]
    report = client.get(f"/api/v1/simulations/{sid}/events/{event['id']}").json()["data"]
    c.EventReport.model_validate(report)
    assert report["event"]["status"] == "resolved"
    assert report["delta"] == {key: report["after"][key] - report["before"][key] for key in report["before"]}
    acknowledged = command(client, sid, "acknowledge_outcome", event_id=event["id"], resume=True)
    assert acknowledged.json()["data"]["simulation"]["status"] == "paused"
    branch = write(
        client,
        f"/simulations/{sid}/branches",
        dict(name="Restored copy", source=dict(kind="snapshot", snapshot_id=event["pre_event_snapshot_id"])),
    )
    assert branch.status_code == 201, branch.text
    branch = branch.json()["data"]["simulation"]
    assert branch["id"] != sid and branch["tick"] == 0
    restored = client.get(f"/api/v1/simulations/{branch['id']}/state").json()["data"]
    assert restored["events"] == []
    assert restored["agents"] == before["agents"]
    assert restored["simulation"]["initial_preview"] is None
    assert restored["simulation"]["control_version"] == 0
    old = client.get(f"/api/v1/simulations/{sid}/state", params=dict(revision=simulation["revision"])).json()[
        "data"
    ]
    assert old["events"] == []
    aid = restored["agents"][0]["id"]
    historic = client.get(
        f"/api/v1/simulations/{sid}/agents/{aid}", params=dict(revision=simulation["revision"])
    ).json()["data"]
    assert historic["memories"]["items"] == []
    assert historic["decisions"]["items"] == []


def test_preview_no_mutation_stale_and_idempotency(client):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid)
    key = str(uuid4())
    first = commit_preview(client, sid, hold, p, key)
    assert first.status_code == 201, first.text
    duplicate = commit_preview(client, sid, hold, p, key)
    assert duplicate.json() == first.json()
    assert len(client.get(f"/api/v1/simulations/{sid}/events").json()["data"]["items"]) == 1
    conflict = write(client, f"/simulations/{sid}/interventions", dict(expected_control_version=0), key=key)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_cancel_running_and_explicit_pause_revokes_resume(client):
    sid = create_city(client)["id"]
    assert command(client, sid, "play").status_code == 200
    hold, p = preview(client, sid)
    assert hold["was_running"]
    tick = client.get(f"/api/v1/simulations/{sid}").json()["data"]["tick"]
    time.sleep(0.3)
    assert client.get(f"/api/v1/simulations/{sid}").json()["data"]["tick"] == tick
    cancel = write(
        client,
        f"/simulations/{sid}/interventions/{hold['id']}/cancel",
        dict(expected_control_version=hold["control_version"]),
    )
    assert cancel.json()["data"]["status"] == "running"
    hold, p = preview(client, sid)
    pause = command(client, sid, "pause").json()["data"]["simulation"]
    stale = write(
        client,
        f"/simulations/{sid}/interventions/{hold['id']}/cancel",
        dict(expected_control_version=hold["control_version"]),
    )
    assert stale.json()["error"]["code"] == "CONTROL_CONFLICT"
    cancel = write(
        client,
        f"/simulations/{sid}/interventions/{hold['id']}/cancel",
        dict(expected_control_version=pause["control_version"]),
    )
    assert cancel.json()["data"]["status"] == "paused"


def test_initial_preview_and_open_ended_request(client):
    sim = create_city(client, scenario_description="A flood for 1 tick")
    sid = sim["id"]
    assert command(client, sid, "play").status_code == 409
    committed = write(
        client,
        f"/simulations/{sid}/initial-scenario",
        dict(
            preview_id=sim["initial_preview"]["id"],
            decision="confirm",
            expected_control_version=sim["control_version"],
        ),
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["data"]["event"]["status"] == "queued"
    sid = create_city(client)["id"]
    hold, p = preview(client, sid, "Teleport dinosaurs into the city")
    assert p["can_commit"] is True
    assert p["unsupported_requests"] == []
    assert p["spec"]["description"] == "Teleport dinosaurs into the city"
    committed = commit_preview(client, sid, hold, p)
    assert committed.status_code == 201
    assert committed.json()["data"]["event"]["status"] == "queued"


def test_websocket_snapshot_reconnect(client):
    sid = create_city(client)["id"]
    for previous in (None, 0, 100000):
        with client.websocket_connect(f"ws://127.0.0.1/api/v1/simulations/{sid}/stream") as socket:
            socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=previous))
            message = socket.receive_json()
            assert message["type"] == "snapshot"
            c.SnapshotMessage.model_validate(message)
            socket.send_json(dict(type="ping"))


def test_validation_auth_and_csv(client):
    response = client.post("/api/v1/simulations", json={})
    assert response.status_code == 400
    assert (
        client.post(
            "/api/v1/simulations", json={}, headers={"Idempotency-Key": str(uuid4()), "X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    response = write(
        client, "/simulations", dict(config=dict(name="Wrong", seed=4, population=9, unknown=True))
    )
    assert response.status_code == 422
    c.Failure.model_validate(response.json())
    sid = create_city(client)["id"]
    response = client.get(f"/api/v1/simulations/{sid}/export", params=dict(format="csv"))
    assert response.status_code == 200
    assert response.text.startswith("simulation_id,tick,revision,happiness,safety,trust,resources,stress,")
    assert client.get(f"/api/v1/simulations/{sid}/state?revision=9999").status_code == 404


def test_pagination_is_pinned_to_revision(client):
    sid = create_city(client)["id"]
    first = client.get(f"/api/v1/simulations/{sid}/agents?limit=3").json()["data"]
    cursor = first["next_cursor"]
    assert cursor
    command(client, sid, "step", count=1)
    second = client.get(f"/api/v1/simulations/{sid}/agents", params=dict(cursor=cursor, limit=3))
    assert second.status_code == 200, second.text
    assert not ({a["id"] for a in first["items"]} & {a["id"] for a in second.json()["data"]["items"]})
    assert (
        client.get(f"/api/v1/simulations/{sid}/agents", params=dict(cursor=cursor, q="other")).status_code
        == 400
    )


def test_invalid_natural_language_controls_are_validation_errors_and_keep_hold(client):
    sid = create_city(client)["id"]
    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    hold = write(
        client,
        f"/simulations/{sid}/interventions",
        dict(expected_control_version=simulation["control_version"]),
    ).json()["data"]
    response = write(
        client,
        f"/simulations/{sid}/scenario-previews",
        dict(
            intervention_id=hold["id"],
            source="custom",
            source_event_id=None,
            prompt="A flood severity 200 for 0 ticks",
            policy=None,
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    current = client.get(f"/api/v1/simulations/{sid}").json()["data"]
    assert current["pause_reason"] == "intervention" and current["tick"] == 0


def test_every_advertised_template_compiles_to_a_supported_initial_preview(client):
    from app import contracts as c
    from app.simulation.scenarios import compile_preview

    templates = client.get("/api/v1/templates").json()["data"]["items"]
    assert len(templates) >= 6
    simulation = create_city(client)
    state = client.app.state.service.heads[simulation["id"]]
    for template in templates:
        c.Config.model_validate(template["config"])
        if template["config"]["scenario_description"]:
            result = compile_preview(
                state.model_copy(deep=True), "initial", template["config"]["scenario_description"]
            )
            assert result.can_commit


def test_slow_socket_does_not_block_ticks_and_is_disconnected(client):
    import asyncio
    from types import SimpleNamespace

    sid = create_city(client)["id"]
    command(client, sid, "play")
    endpoint = next(
        route.endpoint for route in client.app.routes if route.path == "/api/v1/simulations/{sid}/stream"
    )

    application = client.app

    class SlowSocket:
        app = application
        headers = {"origin": "http://localhost:5173"}
        scope = {"type": "websocket"}
        client = SimpleNamespace(host="127.0.0.1")
        url = SimpleNamespace(hostname="127.0.0.1")
        cookies = {}
        closed = False
        received = False

        async def accept(self):
            pass

        async def receive_json(self):
            if not self.received:
                self.received = True
                return dict(type="hello", schema_version="1.0.0", last_revision=None)
            await asyncio.Event().wait()

        async def send_text(self, text):
            await asyncio.sleep(5)

        async def close(self, code=1000):
            self.closed = True

    async def exercise():
        socket = SlowSocket()
        service = client.app.state.service
        before = service.heads[sid].simulation.tick
        await endpoint(socket, sid)
        return socket.closed, service.heads[sid].simulation.tick - before

    closed, advanced = client.portal.call(exercise)
    assert closed and advanced >= 3
    command(client, sid, "pause")
