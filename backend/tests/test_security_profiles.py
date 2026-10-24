from uuid import uuid4

from conftest import command, create_city, write
from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app


def test_profile_copy_edit_add_delete_and_settings(client):
    sim = create_city(client)
    aid = client.get(f"/api/v1/simulations/{sim['id']}/agents").json()["data"]["items"][0]["id"]
    profile = client.get(f"/api/v1/simulations/{sim['id']}/agents/{aid}").json()["data"]["profile"]
    profile["name"] = "Custom citizen"
    custom = write(client, "/custom-agents", dict(profile=profile))
    assert custom.status_code == 201, custom.text
    custom = custom.json()["data"]
    second = create_city(client, custom_agent_ids=[custom["id"]])
    people = client.get(f"/api/v1/simulations/{second['id']}/agents").json()["data"]["items"]
    assert len(people) == 10 and sum(person["name"] == "Custom citizen" for person in people) == 1
    profile["name"] = "Edited template"
    update = write(
        client,
        f"/custom-agents/{custom['id']}",
        dict(profile=profile, expected_version=custom["version"]),
        method="PUT",
    )
    assert update.status_code == 200
    people = client.get(f"/api/v1/simulations/{second['id']}/agents").json()["data"]["items"]
    assert any(person["name"] == "Custom citizen" for person in people)
    added = command(client, second["id"], "add_agents", custom_agent_ids=[custom["id"]])
    assert added.status_code == 200, added.text
    assert len(added.json()["data"]["affected_agent_ids"]) == 1
    assert added.json()["data"]["simulation"]["agent_count"] == 11
    assert (
        write(client, f"/custom-agents/{custom['id']}", dict(expected_version=2), method="DELETE").status_code
        == 200
    )
    assert client.get("/api/v1/custom-agents").json()["data"]["items"] == []
    current = client.get("/api/v1/settings").json()["data"]
    version = current.pop("version")
    current["autosave"] = False
    assert (
        write(client, "/settings", dict(expected_version=version, settings=current), method="PUT").status_code
        == 200
    )
    save = command(client, second["id"], "save", reason="navigation", label="Mandatory navigation")
    assert save.status_code == 200 and save.json()["data"]["snapshot"]
    current["shortcuts"]["pan_down"] = current["shortcuts"]["pan_up"]
    assert (
        write(client, "/settings", dict(expected_version=1, settings=current), method="PUT").status_code
        == 422
    )


def test_session_auth_origin_csrf_cookie_and_owner_scope(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "sessions",
        auth_mode="session",
        session_secret="x" * 40,
        demo_passphrase="test passphrase",
        allowed_origins=("https://city.example",),
    )
    app = create_app(config)
    with TestClient(app, base_url="https://city.example") as client:
        assert client.get("/api/v1/session").json()["data"] == dict(authenticated=False, csrf_token=None)
        assert client.get("/api/v1/simulations").status_code == 401
        key = str(uuid4())
        no_origin = client.post(
            "/api/v1/session", json=dict(passphrase="test passphrase"), headers={"Idempotency-Key": key}
        )
        assert no_origin.status_code == 403
        client.headers["Origin"] = "https://city.example"
        login = write(client, "/session", dict(passphrase="test passphrase"))
        assert login.status_code == 200, login.text
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
        assert write(client, "/simulations", dict(config=dict(name="Denied", seed=1))).status_code == 403
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        sim = create_city(client)
        # Private single-owner demo still scopes every resource before projection.
        app.state.service.heads[sim["id"]].owner_id = "different_owner"
        assert client.get(f"/api/v1/simulations/{sim['id']}").status_code == 404
        assert client.get(f"/api/v1/simulations/{sim['id']}/export").status_code == 404
        assert (
            write(
                client, f"/simulations/{sim['id']}/branches", dict(name="Stolen", source=dict(kind="whole"))
            ).status_code
            == 404
        )
        client.headers["Origin"] = "https://evil.example"
        assert write(client, "/custom-agents", {}).status_code == 403
        client.headers["Origin"] = "https://city.example"
        logout = write(client, "/session", {}, method="DELETE")
        assert logout.status_code == 200
        assert client.get("/api/v1/simulations").status_code == 401


def test_local_mode_rejects_rebinding_and_remote_config(client, tmp_path):
    assert client.get("/api/v1/session", headers={"Host": "evil.example"}).status_code == 403
    assert write(client, "/simulations", dict(config=dict(name="No origin", seed=1))).status_code == 202
    assert (
        client.post(
            "/api/v1/simulations",
            json={},
            headers={"Origin": "https://evil.example", "Idempotency-Key": str(uuid4())},
        ).status_code
        == 403
    )
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        AppConfig(data_dir=tmp_path / "bad", host="0.0.0.0").validate()
