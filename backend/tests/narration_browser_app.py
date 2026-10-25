"""Test-only composition for browser acceptance.

All AgentCity routes are the real application; only the ElevenLabs HTTP endpoint
is the controlled fake. The `/__fake-elevenlabs` control routes exist only here.
"""

import asyncio

from fastapi import FastAPI
from narration_fake import API_KEY, ElevenLabsFake, config

from app import contracts as c
from app.infrastructure.config import AppConfig
from app.main import create_app as create_core_app


def create_app():
    fake = ElevenLabsFake()
    narration_config = config(
        deadline=10, attempt_timeout=10, disaster_effects=True, disaster_music=True, disaster_reactions=True
    )
    app = create_core_app(AppConfig.from_env(), narration_config, fake.transport(narration_config))
    control = FastAPI()

    @control.post("/reset")
    async def reset():
        fake.gate.set()
        fake.requests.clear()
        fake.script.clear()
        fake.voice_checks.clear()
        return {"reset": True}

    @control.post("/hold")
    async def hold():
        fake.gate.clear()
        return {"held": True}

    @control.post("/release")
    async def release():
        fake.gate.set()
        return {"held": False}

    @control.post("/fail")
    async def fail(body: dict):
        fake.fail(*[tuple(action) if isinstance(action, list) else action for action in body["actions"]])
        return {"queued": len(fake.script)}

    @control.get("/requests")
    async def requests():
        return [
            dict(
                text=r["body"].get("text", r["body"].get("prompt", "")),
                model_id=r["body"]["model_id"],
                path=r["path"],
                output_format=r["query"].get("output_format"),
                authenticated=r["api_key"] == API_KEY,
            )
            for r in fake.requests
        ]

    @control.post("/dialogue/{sid}")
    async def committed_dialogue(sid: str, body: dict):
        # Test-only producer. Persist real records through the actual repository;
        # production has no such route and the client still consumes WorldStore.
        service = app.state.service
        async with service.writer, service.locks.setdefault(sid, asyncio.Lock()):
            state = service.owned("demo_owner", sid).model_copy(deep=True)
            state.simulation.tick += 1
            service.bump(state)
            speakers = body["participants"]
            records = []
            for index in range(body.get("count", 1)):
                line = c.Dialogue(
                    id=state.next_id("dialogue"),
                    interaction_id=body["interaction"],
                    tick=state.simulation.tick,
                    speaker_id=speakers[index % len(speakers)],
                    recipient_ids=[a for a in speakers if a != speakers[index % len(speakers)]],
                    audible_to_ids=body.get("audible_to_ids", []),
                    text=f"{body.get('prefix', 'Committed exchange')} turn {index + 1}.",
                    intent="talk",
                    emotion="calm",
                    end_conversation=index == body.get("count", 1) - 1,
                )
                state.dialogue.append(line)
                records.append(line.model_dump(mode="json"))
            await service.persist([state])
            return {"lines": records, "revision": state.simulation.revision}

    app.mount("/__fake-elevenlabs", control)
    app.router.routes.insert(0, app.router.routes.pop())
    return app
