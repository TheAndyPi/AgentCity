"""Actual Uvicorn HTTP/WebSocket smoke test, beyond in-process ASGI tests."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from websockets.sync.client import connect

from app.contracts import SnapshotMessage


def test_real_single_worker_server(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    environment.update(DATA_DIR=str(tmp_path / "live"), AUTH_MODE="local", HOST="127.0.0.1", LLM_MODE="rules")
    log = tmp_path / "uvicorn.log"
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=3) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    raise AssertionError("Uvicorn did not become ready")
                csrf = client.get("/api/v1/session").json()["data"]["csrf_token"]
                response = client.post(
                    "/api/v1/simulations",
                    json={"config": {"name": "Network smoke", "seed": 101, "population": 10}},
                    headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
                )
                assert response.status_code == 202, response.text
                sid = response.json()["data"]["id"]
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
                    if simulation["status"] == "paused":
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("City did not initialize")
                with connect(
                    f"ws://127.0.0.1:{port}/api/v1/simulations/{sid}/stream",
                    origin="http://localhost:5173",
                    open_timeout=3,
                ) as ws:
                    ws.send(json.dumps(dict(type="hello", schema_version="1.0.0", last_revision=None)))
                    SnapshotMessage.model_validate_json(ws.recv(timeout=3))
                state = client.get(f"/api/v1/simulations/{sid}/state").json()["data"]
                assert len(state["agents"]) == 10 and len(state["map"]["cells"]) == 4096
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
