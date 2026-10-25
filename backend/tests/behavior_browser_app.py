"""Test-only deterministic setup; all ticking/UI/security use the real app."""

import random
from typing import Literal

from fastapi import Request
from pydantic import BaseModel

from app.behavior.classes import classify, encounter
from app.behavior.crisis import evaluate_crisis
from app.behavior.vitals import evaluate
from app.contracts import Vec2
from app.infrastructure.config import AppConfig
from app.main import create_app as core_app
from app.simulation.agents import connect, perception, update_metrics
from app.simulation.game_master import apply_intent, make_intent


class Setup(BaseModel):
    mode: Literal["faint", "fatal", "crisis", "classes", "attack"]


def create_app():
    app = core_app(AppConfig.from_env())

    @app.state.integrations.post("/behavior-test/{sid}")
    async def setup(request: Request, sid: str, body: Setup):
        service = app.state.service
        async with service.writer:
            state = service.owned(request.state.owner, sid).model_copy(deep=True)
            a, b, *others = list(state.citizens.values())
            for c in others:
                c.summary.active = False
                c.condition.life = "dead"
            for c in (a, b):
                c.inventory.food = c.inventory.water = c.inventory.supplies = 15
                c.profile.traits.empathy = c.profile.traits.cooperation = 100
                c.summary.path = []
                c.inside_building_id = c.entering_building_id = c.leaving_building_id = None
                for other in (a, b):
                    connect(state, c, other, "friend")
            hospital = next(x for x in state.map.buildings if x.kind == "hospital")
            a.summary.position = hospital.entrance.model_copy()
            b.summary.position = Vec2(x=a.summary.position.x + 1.1, y=a.summary.position.y)
            if body.mode == "faint":
                b.needs.fatigue = 100
                b.needs.health = 40
                evaluate(state, b, "Browser fixture actual energy threshold")
            elif body.mode == "fatal":
                b.needs.hunger = 100
                evaluate(state, b, "Browser fixture actual fullness threshold")
            elif body.mode == "attack":
                from app.behavior.game_master import act

                a.profile.traits.empathy = a.profile.traits.cooperation = 0
                a.profile.traits.sociability = a.profile.traits.risk_tolerance = 100
                a.relationships[b.summary.id].conflict = 90
                a.condition.mental = 10
                b.needs.health = 1
                evaluate_crisis(state, a, random.Random(5))
                assert a.condition.episode.mode == "aggression"
                assert act(state, a, "attack", b.summary.id).accepted
            elif body.mode == "crisis":
                a.profile.traits.sociability = a.profile.traits.risk_tolerance = 0
                b.profile.traits.sociability = b.profile.traits.risk_tolerance = 100
                for person, seed in ((a, 1), (b, 0)):
                    person.condition.mental = 10
                    evaluate_crisis(state, person, random.Random(seed))
            else:
                source = state.map.resources[0]
                a.summary.position = Vec2(x=source.position.x + 1.1, y=source.position.y)
                b.summary.position = source.position.model_copy()
                b.inventory.food = b.inventory.water = b.inventory.supplies = 1
                a.profile.traits.empathy = a.profile.traits.cooperation = 0
                a.condition.wealth_band = classify(a)
                apply_intent(state, b, make_intent("gather", target=source.id, kind=source.kind, amount=0.1))
                encounter(state, a, perception(state, a))
            service.bump(state, True)
            update_metrics(state)
            await service.persist([state])
        return {"helper": a.summary.id, "patient": b.summary.id}

    return app
