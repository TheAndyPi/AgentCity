"""Explicit event requests cannot be starved by lifetime citizen usage."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from conftest import command, create_city
from test_scenario_engine import draft, engine, hold, op, transit_hospital_draft

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway
from app.scenario_engine.interpreter import PlanDraft


def config(**values):
    return AppConfig(
        llm_mode="gemini", gemini_api_key="test", gemini_model="test", llm_token_budget=1, **values
    )


def response(input_tokens=10, output_tokens=20):
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": json.dumps(transit_hospital_draft())}]}}],
            "usageMetadata": {"promptTokenCount": input_tokens, "candidatesTokenCount": output_tokens},
        },
    )


def test_recorded_background_exhaustion_does_not_block_an_explicit_event():
    async def run():
        calls, usage = [], []

        async def record(sid, counts):
            usage.append(counts)

        async def handler(request):
            calls.append(request)
            return response()

        gateway = Gateway(config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        gateway.tokens = 493098
        try:
            with gateway.event_budget() as budget:
                assert await gateway.structured("city", "Plan a custom event", PlanDraft)
                assert budget.tokens == 30 and budget.reserved == 0
            assert gateway.tokens == 493128
            assert usage[0]["input_tokens"] == 10 and usage[0]["output_tokens"] == 20
            assert await gateway.structured("city", "A background request", PlanDraft) is None
            assert gateway.request_error["category"] == "budget_exhausted" and len(calls) == 1
        finally:
            await gateway.close()

    asyncio.run(run())


def test_corrections_share_one_allowance_and_the_next_event_gets_a_fresh_allowance():
    async def run():
        calls = []

        async def record(*args):
            pass

        async def handler(request):
            calls.append(request)
            return response(800, 100)

        gateway = Gateway(
            config(llm_event_token_budget=1000),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            for _ in range(2):
                with gateway.event_budget() as budget:
                    assert await gateway.structured("city", "Plan", PlanDraft, max_output_tokens=100)
                    assert (
                        await gateway.structured("city", "Correction", PlanDraft, max_output_tokens=100)
                        is None
                    )
                    assert gateway.request_error["category"] == "budget_exhausted"
                    assert budget.tokens == 900 and budget.reserved == 0
            assert len(calls) == 2 and gateway.tokens == 1800 and gateway.reserved == 0
        finally:
            await gateway.close()

    asyncio.run(run())


def test_concurrent_events_have_independent_allowances_and_keep_shared_usage():
    async def run():
        async def record(*args):
            pass

        async def handler(request):
            await asyncio.sleep(0.01)
            return response(800, 100)

        gateway = Gateway(
            config(llm_event_token_budget=1000, llm_concurrency=2),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        async def event(sid):
            with gateway.event_budget() as budget:
                result = await gateway.structured(sid, "Plan", PlanDraft, max_output_tokens=100)
                assert result and budget.tokens == 900 and budget.reserved == 0

        try:
            await asyncio.gather(event("first"), event("second"))
            assert gateway.tokens == 1800 and gateway.reserved == 0
        finally:
            await gateway.close()

    asyncio.run(run())


def test_unknown_usage_retries_are_charged_to_the_same_event_allowance():
    async def run():
        usage = []

        async def record(sid, counts):
            usage.append(counts)

        async def handler(request):
            raise httpx.ConnectError("Disconnected", request=request)

        gateway = Gateway(
            config(llm_event_token_budget=24),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            with gateway.event_budget() as budget:
                assert await gateway.structured("city", "hello", PlanDraft, max_output_tokens=7) is None
                assert budget.tokens == 24 and budget.reserved == 0
                assert await gateway.structured("city", "hello", PlanDraft, max_output_tokens=7) is None
                assert gateway.request_error["category"] == "budget_exhausted"
            assert len(usage) == 2 and sum(item["budget_charge"] for item in usage) == 24
            assert gateway.tokens == 24 and gateway.reserved == 0
        finally:
            await gateway.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("prompt", "operations"),
    [
        (
            "10 pm curfew",
            [
                op(
                    "broadcast_information",
                    "curfew",
                    channel="official",
                    topic="government",
                    message="A curfew is announced for 10 pm.",
                )
            ],
        ),
        ("illness", [op("catalog_event", "illness", recipe="illness")]),
        ("dinosaurs", [op("catalog_event", "dinosaurs", recipe="dinosaurs")]),
    ],
)
def test_short_events_plan_commit_and_run_with_an_exhausted_background_allowance(client, prompt, operations):
    city = create_city(client)
    sid = city["id"]
    intervention = hold(client, sid)
    service = client.app.state.service
    service.config = service.gateway.config = replace(
        service.config, llm_mode="gemini", gemini_api_key="test", gemini_model="test", llm_token_budget=1
    )
    service.gateway.tokens = 493098
    calls = []

    async def handler(request):
        calls.append(request)
        answer = PlanDraft.model_validate(draft(operations))
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": answer.model_dump_json()}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
            },
        )

    async def install():
        await service.gateway.client.aclose()
        service.gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    client.portal.call(install)
    result = engine(
        client,
        f"/simulations/{sid}/plans",
        {
            "intervention_id": intervention["id"],
            "prompt": prompt,
        },
    ).json()["data"]
    assert result["status"] == "ready" and result["unsupported"] == []
    assert result["plan"]["source"] == "gemini" and len(calls) == 1
    assert service.gateway.tokens == 493128 and not service.heads[sid].events
    committed = engine(
        client,
        f"/simulations/{sid}/commits",
        {
            "intervention_id": intervention["id"],
            "expected_control_version": intervention["control_version"],
            "plan": result["plan"],
        },
    )
    assert committed.status_code == 201, committed.text
    service.config = service.gateway.config = replace(service.config, llm_mode="rules")
    assert command(client, sid, "step", count=2).status_code == 200
    assert service.heads[sid].simulation.tick == 2 and len(calls) == 1
