"""Revision-bound read projections and signed, filter-bound pagination."""

import base64
import hashlib
import hmac
import json

from app import contracts as c
from app.data.repository import encode
from app.infrastructure.errors import DomainError, require
from app.simulation.agents import evidence
from app.simulation.scenarios import blocked_cells, event_report


class Cursors:
    def __init__(self, secret):
        self.secret = bytes.fromhex(secret)

    def sign(self, value):
        data = encode(value)
        signature = hmac.new(self.secret, data, hashlib.sha256).hexdigest().encode()
        return base64.urlsafe_b64encode(data + b"." + signature).decode().rstrip("=")

    def read(self, value):
        try:
            raw = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
            data, signature = raw.rsplit(b".", 1)
            require(
                hmac.compare_digest(
                    signature, hmac.new(self.secret, data, hashlib.sha256).hexdigest().encode()
                ),
                "INVALID_REQUEST",
                "Invalid cursor",
                400,
            )
            return json.loads(data)
        except (ValueError, KeyError, TypeError):
            raise DomainError("INVALID_REQUEST", "Invalid cursor", 400)

    def context(self, owner, resource, filters, revision, cursor):
        value = self.read(cursor) if cursor else None
        if value:
            require(
                value["owner"] == owner and value["resource"] == resource and value["filters"] == filters,
                "INVALID_REQUEST",
                "Cursor belongs to a different resource or filters",
                400,
            )
            require(
                revision is None or revision == value["revision"],
                "INVALID_REQUEST",
                "Cursor belongs to a different revision",
                400,
            )
        return value

    def page(self, items, owner, resource, filters, revision, cursor, limit=25):
        value = self.context(owner, resource, filters, revision, cursor)
        offset = value["offset"] if value else 0
        result = items[offset : offset + limit]
        next_cursor = (
            self.sign(
                dict(
                    owner=owner, resource=resource, filters=filters, revision=revision, offset=offset + limit
                )
            )
            if offset + limit < len(items)
            else None
        )
        return dict(items=result, next_cursor=next_cursor)


def frame(state):
    require(
        state.map is not None and state.simulation.initialization.stage == "ready",
        "INVALID_STATE",
        "World is not ready",
    )
    map_data = state.map.model_copy(deep=True)
    blocked = blocked_cells(state)
    for col, row in blocked:
        map_data.cells[row * map_data.columns + col].walkable = False
    return c.WorldFrame(
        ref=state.ref(),
        simulation=state.simulation,
        map=map_data,
        agents=sorted([citizen.summary for citizen in state.citizens.values()], key=lambda a: (a.name, a.id)),
        events=sorted(
            [runtime.summary for runtime in state.events.values()],
            key=lambda e: (e.queued_tick, e.id),
            reverse=True,
        ),
        policies=state.policies,
        metrics=state.metric_points[-1],
        recent_dialogue=state.dialogue[-25:],
        active_hazards=behavior_hazards(state)
        + [
            c.Hazard(
                event_id=runtime.summary.id,
                kind=effect.hazard,
                polygon=runtime.spec.affected_polygon,
                severity=effect.severity,
            )
            for runtime in state.events.values()
            if runtime.summary.status == "active"
            for effect in runtime.spec.effects
            if effect.type == "hazard"
        ],
    )


def agent_records(state, aid, collection):
    citizen = state.citizens.get(aid)
    require(citizen is not None, "NOT_FOUND", "Citizen not found at this revision", 404)
    if collection == "memories":
        return sorted(citizen.memories, key=lambda m: (m.tick, m.id), reverse=True)
    if collection == "relationships":
        return sorted(citizen.relationships.values(), key=lambda r: r.to_agent_id)
    return sorted(
        [d for d in state.decisions if d.agent_id == aid], key=lambda d: (d.tick, d.id), reverse=True
    )


def agent_detail(state, aid, cursors=None, all_records=False):
    citizen = state.citizens.get(aid)
    require(citizen is not None, "NOT_FOUND", "Citizen not found at this revision", 404)
    pages = {}
    for collection in ("memories", "relationships", "decisions"):
        records = agent_records(state, aid, collection)
        if all_records:
            pages[collection] = dict(items=records, next_cursor=None)
        else:
            pages[collection] = cursors.page(
                records,
                state.owner_id,
                f"{state.simulation.id}/agents/{aid}/{collection}",
                {},
                state.simulation.revision,
                None,
            )
    return c.AgentDetail(
        ref=state.ref(),
        agent=citizen.summary,
        profile=citizen.profile,
        home=citizen.home,
        needs=citizen.needs,
        inventory=citizen.inventory,
        reputation=citizen.reputation,
        beliefs=citizen.beliefs,
        goals=citizen.goals,
        **pages,
        major_event_ids=citizen.major_event_ids,
        metric_reasons=citizen.metric_reasons,
    )


def overview(state):
    reports = [event_report(state, runtime) for runtime in state.events.values()]
    ranked = sorted(
        reports,
        key=lambda r: (
            -sum(abs(v) for v in r.delta.model_dump().values()),
            r.event.start_tick if r.event.start_tick is not None else 9007199254740991,
            r.event.id,
        ),
    )
    top = [
        c.TopEvent(
            event_id=r.event.id,
            title=r.event.title,
            impact_score=sum(abs(v) for v in r.delta.model_dump().values()),
            evidence=evidence(
                "Measured five-metric interval change; association does not establish causation",
                event_ids=[r.event.id],
            ),
        )
        for r in ranked[:3]
    ]
    initial = state.initial_metrics or state.metric_points[0].values
    current = state.metric_points[-1].values
    improvements = []
    reasons = []
    for metric in c.Metrics.model_fields:
        delta = getattr(current, metric) - getattr(initial, metric)
        if metric == "stress":
            delta = -delta
        if delta > 0:
            improvements.append(
                c.MetricReason(
                    metric=metric,
                    delta=delta,
                    evidence=evidence("Committed endpoint versus initial population mean"),
                )
            )
        reasons.append(
            c.OverviewReason(
                metric=metric,
                text={
                    "resources": "Mean inventory fraction relative to each citizen's target",
                    "safety": "100 minus the larger of local hazard severity and health deficit",
                    "trust": "Mean of directed known-person trust scores",
                    "happiness": "Bounded sum of versioned action, need and scenario contributions",
                    "stress": "Bounded sum of versioned action, need and scenario contributions",
                }[metric],
                evidence=evidence(
                    "Derived from committed citizen records", event_ids=[r.event.id for r in reports]
                ),
            )
        )
    improvements.sort(key=lambda item: (-item.delta, item.metric))
    return c.Overview(
        ref=state.ref(),
        metrics=state.metric_points[-1],
        top_events=top,
        improvements=improvements,
        metric_reasons=reasons,
    )


def behavior_hazards(state):
    import math

    return [
        c.Hazard(
            event_id=f.id,
            kind="fire",
            severity=f.severity,
            polygon=[
                c.Vec2(
                    x=max(
                        0, min(state.map.width_m - 0.001, f.position.x + f.radius * math.cos(i * math.pi / 8))
                    ),
                    y=max(
                        0,
                        min(state.map.height_m - 0.001, f.position.y + f.radius * math.sin(i * math.pi / 8)),
                    ),
                )
                for i in range(16)
            ],
        )
        for f in state.behavior.fires.values()
        if not f.extinguished and f.end_tick > state.simulation.tick
    ]
