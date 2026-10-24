"""Established streams must lose access along with their authenticated session."""

import copy
import time
from uuid import uuid4

import anyio
import pytest
from conftest import command, create_city, write
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.infrastructure.config import AppConfig
from app.main import create_app


def next_message(socket):
    # TestClient's public receive has no deadline; bound the underlying test queue.
    async def receive():
        with anyio.fail_after(1):
            return await socket._send_rx.receive()

    return socket.portal.call(receive)


@pytest.mark.parametrize("revocation", ["logout", "expiry"])
def test_idle_stream_closes_when_session_is_revoked_or_expired(tmp_path, revocation):
    config = AppConfig(
        data_dir=tmp_path / "sessions",
        auth_mode="session",
        session_secret="test-stream-session-secret-" * 2,
        demo_passphrase="test passphrase",
        allowed_origins=("https://city.example",),
    )
    with TestClient(create_app(config), base_url="https://city.example") as client:
        client.headers["Origin"] = "https://city.example"
        login = write(client, "/session", {"passphrase": "test passphrase"})
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        sid = create_city(client)["id"]
        raw = client.cookies.get("agentcity_session")
        headers = {"Origin": "https://city.example", "Cookie": "agentcity_session=" + raw}
        with client.websocket_connect(f"/api/v1/simulations/{sid}/stream", headers=headers) as socket:
            socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=None))
            assert socket.receive_json()["type"] == "snapshot"
            if revocation == "logout":
                assert write(client, "/session", {}, method="DELETE").status_code == 200
            else:
                service = client.app.state.service

                async def expire():
                    async with service.writer:
                        sessions = copy.deepcopy(service.repo.meta["sessions"])
                        sessions[client.app.state.security.session_key(raw)]["expires_at"] = time.time() - 1
                        await service.persist([], metadata={"sessions": sessions})

                client.portal.call(expire)
            assert client.get(f"/api/v1/simulations/{sid}").status_code == 401
            assert next_message(socket) == {"type": "websocket.close", "code": 1008, "reason": ""}
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(f"/api/v1/simulations/{sid}/stream", headers=headers):
                pass
        assert denied.value.code == 1008


def test_logging_out_one_session_does_not_revoke_another_sessions_stream(tmp_path):
    config = AppConfig(
        data_dir=tmp_path / "sessions",
        auth_mode="session",
        session_secret="test-stream-session-secret-" * 2,
        demo_passphrase="test passphrase",
        allowed_origins=("https://city.example",),
    )
    with TestClient(create_app(config), base_url="https://city.example") as client:
        client.headers["Origin"] = "https://city.example"
        first = write(client, "/session", {"passphrase": "test passphrase"}).json()["data"]
        raw_first = client.cookies.get("agentcity_session")
        client.headers["X-CSRF-Token"] = first["csrf_token"]
        sid = create_city(client)["id"]
        second = write(client, "/session", {"passphrase": "test passphrase"}).json()["data"]
        raw_second = client.cookies.get("agentcity_session")
        with client.websocket_connect(
            f"/api/v1/simulations/{sid}/stream",
            headers={"Origin": "https://city.example", "Cookie": "agentcity_session=" + raw_second},
        ) as socket:
            socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=None))
            initial = socket.receive_json()
            logout = client.delete(
                "/api/v1/session",
                headers={
                    "Cookie": "agentcity_session=" + raw_first,
                    "X-CSRF-Token": first["csrf_token"],
                    "Idempotency-Key": str(uuid4()),
                },
            )
            assert logout.status_code == 200
            client.headers["Cookie"] = "agentcity_session=" + raw_second
            client.headers["X-CSRF-Token"] = second["csrf_token"]
            assert (
                command(client, sid, "save", reason="manual", label="Second session update").status_code
                == 200
            )
            updated = next_message(socket)
            assert updated["type"] == "websocket.send"
            import json

            assert json.loads(updated["text"])["data"]["ref"]["revision"] > initial["data"]["ref"]["revision"]


def test_revocation_cancels_a_backpressured_send(tmp_path):
    import asyncio

    config = AppConfig(
        data_dir=tmp_path / "sessions",
        auth_mode="session",
        session_secret="test-stream-session-secret-" * 2,
        demo_passphrase="test passphrase",
        allowed_origins=("https://city.example",),
    )
    app = create_app(config)
    stalled, cancelled = asyncio.Event(), asyncio.Event()

    async def transport(scope, receive, send):
        sent = 0

        async def backpressure(message):
            nonlocal sent
            if message["type"] == "websocket.send":
                sent += 1
                if sent > 1:
                    stalled.set()
                    try:
                        await asyncio.Future()
                    finally:
                        cancelled.set()
            await send(message)

        await app(scope, receive, backpressure)

    with TestClient(transport, base_url="https://city.example") as client:
        client.headers["Origin"] = "https://city.example"
        login = write(client, "/session", {"passphrase": "test passphrase"})
        client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        sid = create_city(client)["id"]
        with client.websocket_connect(
            f"/api/v1/simulations/{sid}/stream",
            headers={
                "Origin": "https://city.example",
                "Cookie": "agentcity_session=" + client.cookies.get("agentcity_session"),
            },
        ) as socket:
            socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=None))
            assert socket.receive_json()["type"] == "snapshot"
            assert command(client, sid, "save", reason="manual", label="Stalled send").status_code == 200

            async def wait_stalled():
                async with asyncio.timeout(1):
                    await stalled.wait()

            client.portal.call(wait_stalled)
            assert write(client, "/session", {}, method="DELETE").status_code == 200
            assert next_message(socket)["code"] == 1008
            assert cancelled.is_set()
