"""Optional prose has one finite budget; deterministic lessons stay authoritative."""

import asyncio
import copy
import json
import threading

import httpx
import pytest
from conftest import command, commit_preview, create_city, preview

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway
from app.prompts.outputs import LessonDraft

MATERIAL = {"facts": [{"id": 0, "text": "A warning was heard"}], "draft_lessons": ["Keep warnings clear"]}
DRAFT = {"text": "A warning was heard. Keep warnings clear.", "fact_ids": [0]}


def response():
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": json.dumps({"lessons": [DRAFT]})}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10},
        },
    )


def config(**kwargs):
    return AppConfig(
        llm_mode="gemini", gemini_api_key="test", gemini_model="test", llm_concurrency=1, **kwargs
    )


@pytest.mark.parametrize("stage", ["queue", "auth", "http", "backoff", "usage"])
def test_lesson_deadline_covers_every_stage_and_allows_a_later_request(monkeypatch, stage):
    monkeypatch.setattr("app.infrastructure.gemini.LESSON_TIMEOUT_SECONDS", 0.05)

    async def run():
        release = asyncio.Event()
        recorded = []
        requests = []
        stalled = True

        async def record(sid, counts):
            if stalled and stage == "usage":
                await release.wait()
            recorded.append((sid, counts.copy()))

        async def handler(request):
            body = json.loads(request.content)
            assert body["generationConfig"]["responseJsonSchema"]["properties"]["lessons"]
            assert (
                json.loads(body["contents"][0]["parts"][0]["text"].split("instructions):\n")[1]) == MATERIAL
            )
            requests.append(request)
            if stalled and stage == "http":
                await release.wait()
            if stalled and stage == "backoff":
                return httpx.Response(429)
            return response()

        gateway = Gateway(config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        original_headers = gateway.headers

        async def headers():
            if stalled and stage == "auth":
                await release.wait()
            return await original_headers()

        gateway.headers = headers
        if stage == "queue":
            await gateway.semaphore.acquire()
        try:
            original_material = copy.deepcopy(MATERIAL)
            assert await asyncio.wait_for(gateway.lessons("city", MATERIAL), 1) is None
            assert MATERIAL == original_material
            assert gateway.reserved == 0
            assert gateway.diagnostics["timeouts"] == 1
            assert gateway.diagnostics["fallbacks"] == 1
            assert gateway.last_error == {"category": "timeout", "http_status": None}
            if stage == "queue":
                assert not recorded and not requests and gateway.tokens == 0
                gateway.semaphore.release()
            else:
                assert not gateway.semaphore.locked()
            if stage == "backoff":
                assert len(requests) == 1  # The overall budget interrupts the retry backoff.
            if stage == "usage":
                assert not recorded and gateway.usage_tasks
            stalled = False
            release.set()
            assert await asyncio.wait_for(gateway.lessons("city", MATERIAL), 1) == [
                LessonDraft.model_validate(DRAFT)
            ]
        finally:
            release.set()
            await gateway.close()
        assert len(recorded) == (1 if stage == "queue" else 2)
        first = recorded[0][1]
        if stage in {"auth", "http", "backoff"}:
            assert first["failed_calls"] == first["usage_unavailable"] == 1
            assert first["budget_charge"] > 0
            assert gateway.tokens == first["budget_charge"] + 30
        else:
            assert first["input_tokens"] == 20 and first["output_tokens"] == 10

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["auth", "http", "usage"])
def test_lesson_cancellation_releases_capacity_and_close_joins_durable_usage(monkeypatch, stage):
    monkeypatch.setattr("app.infrastructure.gemini.LESSON_TIMEOUT_SECONDS", 5)

    async def run():
        entered, recording, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        recorded = []

        async def record(sid, counts):
            recording.set()
            if stage == "usage":
                entered.set()
            await release.wait()
            recorded.append(counts.copy())

        async def handler(request):
            if stage == "http":
                entered.set()
                await asyncio.Event().wait()
            return response()

        gateway = Gateway(config(), record, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        original_headers = gateway.headers

        async def headers():
            if stage == "auth":
                entered.set()
                await asyncio.Event().wait()
            return await original_headers()

        gateway.headers = headers
        task = asyncio.create_task(gateway.lessons("city", MATERIAL))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(recording.wait(), 1)
            assert gateway.reserved == 0 and not gateway.semaphore.locked()
            closing = asyncio.create_task(gateway.close())
            await asyncio.sleep(0)
            assert not closing.done() and not gateway.client.is_closed
            assert recorded == []
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await (closing if closing is not None else gateway.close())
        assert len(recorded) == 1
        if stage == "usage":
            assert recorded[0]["input_tokens"] == 20
            assert recorded[0]["output_tokens"] == 10
            assert recorded[0]["failed_calls"] == 0
        else:
            assert recorded[0]["failed_calls"] == 1
            assert recorded[0]["budget_charge"] == gateway.tokens > 0

    asyncio.run(run())


def test_cancelled_vertex_waiter_does_not_start_overlapping_credential_workers(monkeypatch):
    monkeypatch.setattr("app.infrastructure.gemini.LESSON_TIMEOUT_SECONDS", 0.05)

    async def run():
        entered, release = threading.Event(), threading.Event()
        workers = []
        recorded = []

        def cloud_headers():
            workers.append(threading.get_ident())
            entered.set()
            assert release.wait(5), "Test must release the surviving credential worker"
            return {"authorization": "Bearer mock"}

        async def record(sid, counts):
            recorded.append(counts)

        async def handler(request):
            assert request.headers["authorization"] == "Bearer mock"
            return response()

        gateway = Gateway(
            config(gemini_backend="vertex", google_cloud_project="test"),
            record,
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(gateway, "_cloud_headers", cloud_headers)
        worker = None
        try:
            assert await asyncio.wait_for(gateway.lessons("city", MATERIAL), 1) is None
            assert entered.is_set()
            worker = gateway.auth_task
            assert worker and not worker.done()
            assert await asyncio.wait_for(gateway.lessons("city", MATERIAL), 1) is None
            assert gateway.auth_task is worker and len(workers) == 1
            assert gateway.reserved == 0 and not gateway.semaphore.locked()
            release.set()
            await asyncio.wait_for(asyncio.shield(worker), 1)
            assert await gateway.lessons("city", MATERIAL) == [LessonDraft.model_validate(DRAFT)]
            assert len(workers) == 2
        finally:
            release.set()
            if worker:
                await asyncio.shield(worker)
            await gateway.close()
        assert len(recorded) == 3
        assert all(c["failed_calls"] == c["usage_unavailable"] == 1 for c in recorded[:2])

    asyncio.run(run())


def test_lesson_timeout_keeps_deterministic_lessons_and_physical_ticks(client, monkeypatch):
    monkeypatch.setattr("app.infrastructure.gemini.LESSON_TIMEOUT_SECONDS", 0.1)
    sid = create_city(client)["id"]
    hold, proposed = preview(client, sid, "A flood across the whole city for 2 ticks")
    committed = commit_preview(client, sid, hold, proposed).json()["data"]
    assert command(client, sid, "step", count=3).status_code == 200
    service = client.app.state.service
    eid = committed["event"]["id"]
    runtime = service.heads[sid].events[eid]
    lessons, facts = copy.deepcopy(runtime.lessons), copy.deepcopy(runtime.lesson_facts)
    assert lessons and facts and runtime.lessons_source == "rules"
    entered = threading.Event()

    async def headers():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service.gateway, "config", config())
    monkeypatch.setattr(service.gateway, "headers", headers)
    task = client.portal.start_task_soon(service.rewrite_lessons, sid, eid, {"facts": facts})
    assert entered.wait(1)
    assert command(client, sid, "acknowledge_outcome", event_id=eid, resume=False).status_code == 200
    assert command(client, sid, "step", count=1).status_code == 200
    task.result(timeout=2)
    runtime = service.heads[sid].events[eid]
    assert runtime.lessons == lessons and runtime.lesson_facts == facts and runtime.lessons_source == "rules"
    assert service.heads[sid].simulation.tick == 4
    client.portal.call(service.gateway.close)
    usage = service.repo.meta["usage"][sid]
    assert usage["calls"] == usage["failed_calls"] == usage["usage_unavailable"] == 1
    assert usage["budget_charge"] > 0


def test_lesson_budget_is_explicit_and_rules_mode_never_calls_provider():
    async def run():
        async def forbidden(*args, **kwargs):
            raise AssertionError("Rules mode must not call provider or accounting")

        gateway = Gateway(AppConfig(), forbidden)
        try:
            assert 0 < gateway.lesson_timeout_seconds <= 10
            gateway.structured = forbidden
            assert await gateway.lessons("city", MATERIAL) is None
        finally:
            await gateway.close()

    asyncio.run(run())
