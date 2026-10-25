"""Historical diagnostic; no real provider calls, secrets, or store mutations.

At reviewed dev 5f87f9c, lessons_pending_after_budget and slot_occupied are true.
If the fix uses a different explicit lesson budget, adapt the wait to that budget.
This probe is not a permanent regression test.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from app.infrastructure.config import AppConfig
from app.infrastructure.gemini import Gateway


async def main():
    async def usage(*_args):
        pass

    def reject_network(_request):
        raise AssertionError("This diagnostic must never make a live provider call")

    gateway = Gateway(
        AppConfig(
            llm_mode="gemini",
            gemini_model="dummy",
            gemini_api_key="dummy",
            llm_timeout=0.05,
            llm_concurrency=1,
        ),
        usage,
        client=httpx.AsyncClient(transport=httpx.MockTransport(reject_network)),
    )
    blocker = asyncio.Event()

    async def stalled_headers():
        await blocker.wait()

    gateway.headers = stalled_headers
    task = asyncio.create_task(gateway.lessons("diagnostic", {"facts": []}))
    try:
        start = time.monotonic()
        await asyncio.sleep(gateway.decision_timeout_seconds + 0.2)
        result = {
            "decision_deadline_seconds": gateway.decision_timeout_seconds,
            "observed_seconds": time.monotonic() - start,
            "lessons_pending_after_budget": not task.done(),
            "slot_occupied": gateway.semaphore.locked(),
        }
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        start = time.monotonic()
        fallback = await gateway.decide("diagnostic", {"profile": {"name": "Test"}})
        result["decision_control"] = {
            "returned_fallback": fallback is None,
            "elapsed_seconds": time.monotonic() - start,
        }
        print(json.dumps(result, indent=2))
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(main())
