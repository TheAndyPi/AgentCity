"""Event planning must recover from malformed output and bound every blocking stage."""

import asyncio
import json

import httpx
import pytest
from conftest import create_city
from test_scenario_engine import ACCEPTANCE, transit_hospital_draft

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway
from app.scenario_engine import interpreter


def config():
    return AppConfig(llm_mode="gemini", gemini_api_key="test-key", gemini_model="test", llm_concurrency=1)


def response(text):
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
        },
    )


@pytest.mark.parametrize("stage", ["queue", "auth", "http", "backoff", "usage"])
def test_one_deadline_covers_the_entire_event_request(client, monkeypatch, stage):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]
    monkeypatch.setattr(interpreter, "TOTAL_TIMEOUT_SECONDS", 0.04)

    async def run():
        release = asyncio.Event()

        async def record(*args):
            if stage == "usage":
                await release.wait()

        async def handler(request):
            if stage == "http":
                await release.wait()
            if stage == "backoff":
                return httpx.Response(503)
            answer = interpreter.PlanDraft.model_validate(transit_hospital_draft())
            return response(answer.model_dump_json())

        gateway = Gateway(config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        if stage == "queue":
            await gateway.semaphore.acquire()
        if stage == "auth":

            async def headers():
                await release.wait()

            gateway.headers = headers
        try:
            result = await asyncio.wait_for(
                interpreter.interpret(gateway, state, sid, ACCEPTANCE, "sandbox"), 1
            )
            assert result["status"] == "unavailable" and result["attempts"] == 1
            assert "too long" in result["errors"][0]
            assert gateway.reserved == 0
        finally:
            release.set()
            if stage == "queue":
                gateway.semaphore.release()
            await gateway.close()

    asyncio.run(run())


def test_malformed_gemini_output_gets_repaired_without_committing_a_broken_plan(client):
    sid = create_city(client)["id"]
    state = client.app.state.service.heads[sid]

    async def run():
        calls = []

        async def record(*args):
            pass

        async def handler(request):
            calls.append(json.loads(request.content))
            if len(calls) < 3:
                return response('{"operations":')
            return response(interpreter.PlanDraft.model_validate(transit_hospital_draft()).model_dump_json())

        gateway = Gateway(config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await interpreter.interpret(gateway, state, sid, ACCEPTANCE, "sandbox")
            assert result["status"] == "ready" and result["attempts"] == 3
            assert (
                len(calls) == 3
                and "incomplete or invalid JSON" in calls[1]["contents"][0]["parts"][0]["text"]
            )
            assert not state.events and not state.systems.plans
        finally:
            await gateway.close()

    asyncio.run(run())
