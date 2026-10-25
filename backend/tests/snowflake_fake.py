"""Controlled external SQL API transport; never replaces AgentCity HTTP routes."""

import json

import httpx

from app.snowflake.transport import SnowflakeTransport


class SnowflakeFake:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.fail_shape = None
        self.model_output = None
        self.corrupt = False
        self.on_ingest = None

    def handle(self, request):
        assert request.url.host.endswith(".snowflakecomputing.com")
        assert request.headers["X-Snowflake-Authorization-Token-Type"] == "KEYPAIR_JWT"
        body = json.loads(request.content)
        sql = body["statement"]
        values = [v["value"] for _, v in sorted(body["bindings"].items(), key=lambda p: int(p[0]))]
        shape = (
            "ingest"
            if sql.startswith("MERGE")
            else "query"
            if sql.startswith("SELECT TO_JSON")
            else "explain"
        )
        self.calls.append((shape, values))
        if self.fail_shape == shape:
            return httpx.Response(429, json={"message": "secret vendor error must never leak"})
        if shape == "ingest":
            self.rows.setdefault(tuple(values[:3]), [values[4], values[3], "2026-10-24T23:00:00.000+00:00"])
            if self.on_ingest:
                self.on_ingest()
            return httpx.Response(200, json={"data": [["1"]]})
        if shape == "query":
            row = self.rows.get(tuple(values))
            if self.corrupt and row:
                row = ['{"wrong":true}', row[1], row[2]]
            return httpx.Response(200, json={"data": [row] if row else []})
        context = json.loads(values[1])
        record = next((key for key in context["facts"] if ":decision:" in key or ":event:" in key), None)
        selected = ["cooperation_count"] + ([record] if record else [])
        output = self.model_output or json.dumps({"fact_ids": selected})
        return httpx.Response(200, json={"data": [[output]]})

    def transport(self, config):
        return SnowflakeTransport(
            config,
            httpx.AsyncClient(transport=httpx.MockTransport(self.handle)),
            token_factory=lambda _: "controlled-fake-jwt",
        )
