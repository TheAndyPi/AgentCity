"""Test-only composition for browser acceptance.

All AgentCity routes are the real application; only the ElevenLabs HTTP endpoint
is the controlled fake. The `/__fake-elevenlabs` control routes exist only here.
"""

from fastapi import FastAPI
from narration_fake import API_KEY, ElevenLabsFake, config

from app.infrastructure.config import AppConfig
from app.main import create_app as create_core_app


def create_app():
    fake = ElevenLabsFake()
    narration_config = config(deadline=10, attempt_timeout=10)
    app = create_core_app(AppConfig.from_env(), narration_config, fake.transport(narration_config))
    control = FastAPI()

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
                text=r["body"]["text"],
                model_id=r["body"]["model_id"],
                path=r["path"],
                output_format=r["query"].get("output_format"),
                authenticated=r["api_key"] == API_KEY,
            )
            for r in fake.requests
        ]

    app.mount("/__fake-elevenlabs", control)
    app.router.routes.insert(0, app.router.routes.pop())
    return app
