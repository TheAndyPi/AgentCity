"""Opt-in, live Vertex test over HTTP using a disposable backend and simulation."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    if os.getenv("GEMINI_BACKEND") != "vertex":
        raise SystemExit("This smoke test requires GEMINI_BACKEND=vertex.")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="agentcity-vertex-") as data_dir:
        env = {
            **os.environ,
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "AUTH_MODE": "local",
            "DATA_DIR": data_dir,
            "FRONTEND_DIST": "",
            "LLM_MODE": "gemini",
            "SIM_BASE_TICKS_PER_SECOND": "0.5",
            "LLM_MAX_CONCURRENCY": "1",
            "LLM_REQUESTS_PER_MINUTE": "10",
            "LLM_SESSION_TOKEN_BUDGET": "30000",
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "app"],
            env=env,
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise SystemExit("Disposable backend failed to start.")
                    try:
                        if client.get("/health/ready").is_success:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:
                        raise SystemExit("Backend readiness timed out.")
                    time.sleep(0.2)
                session = client.get("/api/v1/session")
                session.raise_for_status()
                client.headers["X-CSRF-Token"] = session.json()["data"]["csrf_token"]

                def post(path, body, key=None):
                    response = client.post(
                        "/api/v1" + path,
                        json=body,
                        headers={"Idempotency-Key": key or str(uuid4())},
                    )
                    response.raise_for_status()
                    return response.json()["data"]

                simulation = post(
                    "/simulations",
                    {
                        "config": {
                            "name": "Vertex live integration test",
                            "seed": 42,
                            "population": 10,
                        }
                    },
                )
                sid = simulation["id"]

                def get_simulation():
                    response = client.get(f"/api/v1/simulations/{sid}")
                    response.raise_for_status()
                    return response.json()["data"]

                deadline = time.monotonic() + 30
                while get_simulation()["status"] == "initializing":
                    if time.monotonic() > deadline:
                        raise SystemExit("City initialization timed out.")
                    time.sleep(0.2)

                def command(kind):
                    key = str(uuid4())
                    return post(
                        f"/simulations/{sid}/commands",
                        {
                            "request_id": key,
                            "expected_control_version": get_simulation()["control_version"],
                            "command": {"type": kind},
                        },
                        key,
                    )

                agents = client.get(f"/api/v1/simulations/{sid}/agents").json()["data"]["items"]
                command("play")
                found = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline and found is None:
                    time.sleep(0.5)
                    for agent in agents:
                        response = client.get(f"/api/v1/simulations/{sid}/agents/{agent['id']}/decisions")
                        response.raise_for_status()
                        found = next(
                            (
                                d
                                for d in response.json()["data"]["items"]
                                if d["source"] == "gemini" and d["outcome"] == "accepted"
                            ),
                            None,
                        )
                        if found:
                            break
                command("pause")
                if found is None:
                    raise SystemExit("No accepted Gemini decision observed through the application API.")
                response = client.get(f"/api/v1/simulations/{sid}/decisions/{found['id']}")
                response.raise_for_status()
                assert response.json()["data"]["source"] == "gemini"
                print("Application HTTP integration: passed")
                print(f"Accepted Gemini decision: {found['intent']['action']}, tick {found['tick']}")
                print("Disposable city paused; test storage will be removed.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
