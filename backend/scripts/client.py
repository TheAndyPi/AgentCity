"""Small real-API driver shared by the demo, fixture bootstrap and benchmark."""

import time
from uuid import uuid4


class Driver:
    def __init__(self, client):
        self.client = client
        client.headers["X-CSRF-Token"] = client.get("/api/v1/session").json()["data"]["csrf_token"]
        self.trace = []

    def get(self, path, **params):
        response = self.client.get("/api/v1" + path, params=params)
        response.raise_for_status()
        return response.json()["data"]

    def write(self, path, body, method="POST", key=None, expected=None):
        key = key or str(uuid4())
        response = self.client.request(method, "/api/v1" + path, json=body, headers={"Idempotency-Key": key})
        result = response.json()
        traced_body = body
        if path == "/session":
            traced_body = {"passphrase": "[redacted]"} if "passphrase" in body else body
            result = {name: value for name, value in result.items() if name != "data"} | {
                "data": {"authentication_result": "[redacted]"}
            }
        self.trace.append(
            dict(
                method=method,
                path="/api/v1" + path,
                request_id=key,
                request=traced_body,
                status=response.status_code,
                result=result,
            )
        )
        if expected is None:
            response.raise_for_status()
        else:
            assert response.status_code == expected, response.text
        return response.json()

    def city(self, **config):
        response = self.write(
            "/simulations", dict(config=dict(name="AgentCity demo", seed=42, population=30) | config)
        )
        sid = response["data"]["id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            simulation = self.get(f"/simulations/{sid}")
            if simulation["status"] != "initializing":
                if simulation["status"] != "paused":
                    raise RuntimeError(simulation)
                return simulation
            time.sleep(0.01)
        raise TimeoutError("Initialization did not finish")

    def command(self, sid, kind, **values):
        simulation = self.get(f"/simulations/{sid}")
        key = str(uuid4())
        return self.write(
            f"/simulations/{sid}/commands",
            dict(
                request_id=key,
                expected_control_version=simulation["control_version"],
                command=dict(type=kind, **values),
            ),
            key=key,
        )

    def preview(self, sid, prompt, source="custom", event_id=None):
        simulation = self.get(f"/simulations/{sid}")
        hold = self.write(
            f"/simulations/{sid}/interventions", dict(expected_control_version=simulation["control_version"])
        )["data"]
        preview = self.write(
            f"/simulations/{sid}/scenario-previews",
            dict(
                intervention_id=hold["id"],
                source=source,
                source_event_id=event_id,
                prompt=prompt,
                policy=None,
            ),
        )["data"]
        return hold, preview

    def commit(self, sid, hold, preview, key=None):
        return self.write(
            f"/simulations/{sid}/scenario-commits",
            dict(
                intervention_id=hold["id"],
                preview_id=preview["id"],
                expected_control_version=hold["control_version"],
            ),
            key=key,
        )
