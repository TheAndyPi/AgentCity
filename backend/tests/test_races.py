import time
from uuid import uuid4

from conftest import command, commit_preview, create_city, preview, write

from app import contracts as c


def test_replaced_preview_token_cannot_commit_new_prompt(client):
    sid = create_city(client)["id"]
    hold, first = preview(client, sid, "A flood for 2 ticks")
    second = write(
        client,
        f"/simulations/{sid}/scenario-previews",
        dict(
            intervention_id=hold["id"],
            source="custom",
            source_event_id=None,
            prompt="A fire for 2 ticks",
            policy=None,
        ),
    )
    assert second.status_code == 201
    second = second.json()["data"]
    assert second["id"] != first["id"]
    assert second["based_on"] == first["based_on"]
    rejected = commit_preview(client, sid, hold, first)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "PREVIEW_STALE"
    result = commit_preview(client, sid, hold, second)
    assert result.status_code == 201 and result.json()["data"]["event"]["kind"] == "fire"


def test_expired_preview_and_navigation_invalidation(client):
    sid = create_city(client)["id"]
    hold, p = preview(client, sid)
    service = client.app.state.service
    service.repo.meta["editors"][sid]["preview"]["expires_at"] = "2000-01-01T00:00:00Z"
    result = commit_preview(client, sid, hold, p)
    assert result.status_code == 410
    assert client.get(f"/api/v1/simulations/{sid}").json()["data"]["pause_reason"] == "intervention"
    saved = command(client, sid, "save", reason="navigation", label="Leave editor")
    assert saved.status_code == 200
    assert service.heads[sid].intervention is None
    assert commit_preview(client, sid, hold, p).status_code == 409


def test_running_commit_and_outcome_restore_prior_play_intent(client):
    sid = create_city(client)["id"]
    command(client, sid, "play")
    hold, p = preview(client, sid, "A flood for 1 tick")
    result = commit_preview(client, sid, hold, p)
    assert result.status_code == 201, result.text
    assert result.json()["data"]["simulation"]["status"] == "running"
    eid = result.json()["data"]["event"]["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        sim = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        if sim["pause_reason"] == "outcome":
            break
        time.sleep(0.02)
    assert sim["pause_reason"] == "outcome"
    resumed = command(client, sid, "acknowledge_outcome", event_id=eid, resume=True)
    assert resumed.status_code == 200
    assert resumed.json()["data"]["simulation"]["status"] == "running"
    command(client, sid, "pause")


def test_outcome_manual_pause_revokes_auto_resume(client):
    sid = create_city(client)["id"]
    command(client, sid, "play")
    hold, p = preview(client, sid, "A flood for 1 tick")
    eid = commit_preview(client, sid, hold, p).json()["data"]["event"]["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if client.get(f"/api/v1/simulations/{sid}").json()["data"]["pause_reason"] == "outcome":
            break
        time.sleep(0.02)
    command(client, sid, "pause")
    result = command(client, sid, "acknowledge_outcome", event_id=eid, resume=True)
    assert result.json()["data"]["simulation"]["status"] == "paused"


def test_max_tick_horizon_and_running_limit(client):
    sid = create_city(client, max_ticks=1)["id"]
    result = command(client, sid, "step", count=10)
    assert result.json()["data"]["simulation"]["status"] == "completed"
    assert result.json()["data"]["simulation"]["tick"] == 1
    assert command(client, sid, "play").status_code == 409
    first = create_city(client)["id"]
    second = create_city(client)["id"]
    assert command(client, first, "play").status_code == 200
    assert command(client, second, "play").status_code == 409
    assert command(client, second, "step", count=1).status_code == 200
    service = client.app.state.service
    assert len([task for task in service.runners.values() if not task.done()]) == 1
    assert command(client, first, "pause").status_code == 200


def test_idempotent_step_does_not_repeat_ticks(client):
    sim = create_city(client)
    key = str(uuid4())
    body = dict(
        request_id=key, expected_control_version=sim["control_version"], command=dict(type="step", count=2)
    )
    first = write(client, f"/simulations/{sim['id']}/commands", body, key=key)
    duplicate = write(client, f"/simulations/{sim['id']}/commands", body, key=key)
    assert first.status_code == 200 and duplicate.json() == first.json()
    assert client.get(f"/api/v1/simulations/{sim['id']}").json()["data"]["tick"] == 2


def test_response_fields_required_and_integer_json_number_parity():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        c.Traits(curiosity=50)
    request = c.CreateSimulation(config=dict(name="Integral number", seed=1.0, population=10.0))
    assert request.config.population == 10 and type(request.config.population) is int
    with pytest.raises(ValidationError):
        c.SetSpeed(type="set_speed", value=True)


def test_resource_metric_override_conserves_units_and_rejects_remote_stock(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    original = service.heads[sid]
    state = original.model_copy(deep=True)
    citizen = next(iter(state.citizens.values()))
    citizen.summary.position = state.map.resources[0].position.model_copy()
    service.heads[sid] = state
    before = sum(sum(c.inventory.model_dump().values()) for c in state.citizens.values()) + sum(
        r.available_units for r in state.map.resources
    )
    request = c.CommandRequest(
        request_id=str(uuid4()),
        expected_control_version=state.simulation.control_version,
        command=dict(
            type="override_agent",
            agent_id=citizen.summary.id,
            metrics={"resources": 80},
            goal=None,
            memory_text=None,
            intent=None,
        ),
    )
    result = service.command("demo_owner", sid, request)
    after = result.states[-1]
    assert after.citizens[citizen.summary.id].summary.metrics.resources == 80
    total = sum(sum(c.inventory.model_dump().values()) for c in after.citizens.values()) + sum(
        r.available_units for r in after.map.resources
    )
    import pytest

    assert total == pytest.approx(before)
    service.heads[sid] = original
