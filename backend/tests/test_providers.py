import asyncio
import json
import time

import httpx
import pytest
from conftest import command, create_city

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway, relevance
from app.simulation.game_master import make_intent


def provider_config(**kwargs):
    return AppConfig(
        llm_mode="gemini", gemini_api_key="test-key", gemini_model="configured-test-model", **kwargs
    )


def test_structured_output_and_measured_usage():
    async def run():
        usage = []

        async def record(sid, counts):
            usage.append(counts.copy())

        async def handler(request):
            body = json.loads(request.content)
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert (
                "You are Example, a human being living in a real, functioning world."
                in body["contents"][0]["parts"][0]["text"]
            )
            return httpx.Response(
                200,
                json={
                    "candidates": [{"content": {"parts": [{"text": make_intent("rest").model_dump_json()}]}}],
                    "usageMetadata": {
                        "promptTokenCount": 123,
                        "candidatesTokenCount": 25,
                        "cachedContentTokenCount": 12,
                    },
                },
            )

        gateway = Gateway(
            provider_config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        result = await gateway.decide("simulation", {"profile": {"name": "Example"}})
        assert result.action == "rest"
        assert usage == [dict(input_tokens=123, output_tokens=25, cached_tokens=12, calls=1, failed_calls=0)]
        await gateway.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "429", "malformed", "illegal_schema"])
def test_provider_failure_falls_back_with_bounded_retries(failure):
    async def run():
        usage = []

        async def record(sid, counts):
            usage.append(counts.copy())

        async def handler(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("forced timeout", request=request)
            if failure == "429":
                return httpx.Response(429, json={"error": "limited"})
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": "not JSON"
                                        if failure == "malformed"
                                        else '{"action":"teleport"}'
                                    }
                                ]
                            }
                        }
                    ]
                },
            )

        gateway = Gateway(
            provider_config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        result = await gateway.decide("simulation", {"profile": {"name": "Example"}})
        assert result is None
        assert len(usage) == (2 if failure in {"timeout", "429"} else 1)
        assert all(record["failed_calls"] == 1 for record in usage)
        assert gateway.diagnostics["fallbacks"] == 1
        await gateway.close()

    asyncio.run(run())


def test_budget_and_circuit_breaker_do_not_call_provider():
    async def run():
        async def record(*args):
            raise AssertionError("No billable request expected")

        async def handler(request):
            raise AssertionError("Provider must not be called")

        gateway = Gateway(
            provider_config(llm_token_budget=1),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        assert await gateway.decide("simulation", {"profile": {"name": "Example"}}) is None
        gateway.config = provider_config()
        gateway.open_until = time.monotonic() + 30
        assert await gateway.decide("simulation", {"profile": {"name": "Example"}}) is None
        await gateway.close()

    asyncio.run(run())


def test_stale_and_other_lineage_results_are_discarded(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    state = service.heads[sid].model_copy(deep=True)
    citizen = next(iter(state.citizens.values()))
    tag = relevance(state, citizen)
    service.provider_results[(sid, citizen.summary.id)] = (tag, state.simulation.tick, make_intent("rest"))
    citizen.task_generation += 1
    assert service.take_proposals(state) == {}
    assert service.gateway.diagnostics["discarded"] == 1
    service.provider_results[(sid, citizen.summary.id)] = (tag, state.simulation.tick, make_intent("rest"))
    state.simulation.id = "different_branch"
    assert service.take_proposals(state) == {}


def test_slow_provider_does_not_stop_physical_ticks(client):
    sid = create_city(client)["id"]
    service = client.app.state.service

    async def slow():
        await asyncio.sleep(2)
        return None

    async def attach():
        service.provider_tasks[(sid, "pending_test")] = asyncio.create_task(slow())

    client.portal.call(attach)
    assert command(client, sid, "play").status_code == 200
    # Assert progress while the provider is still pending, without assuming an
    # exact scheduler/FS latency on a machine also running an interactive city.
    deadline = time.monotonic() + 1.5
    while True:
        simulation = client.get(f"/api/v1/simulations/{sid}").json()["data"]
        if simulation["tick"] >= 2 or time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    assert simulation["tick"] >= 2
    assert not service.provider_tasks[(sid, "pending_test")].done()
    assert command(client, sid, "pause").status_code == 200


def test_missing_usage_metadata_is_explicitly_unavailable(client):
    sid = create_city(client)["id"]
    service = client.app.state.service
    client.portal.call(
        service.record_usage,
        sid,
        dict(
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            calls=1,
            failed_calls=1,
            usage_unavailable=1,
            budget_charge=123,
        ),
    )
    response = client.get("/api/v1/usage", params=dict(simulation_id=sid))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert service.repo.meta["usage"][sid]["calls"] == 1
    assert service.repo.meta["usage"][sid]["budget_charge"] == 123
