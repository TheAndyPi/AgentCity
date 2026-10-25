"""Deterministic warehouse double. No paid calls or fake application HTTP routes.

This implements the approved SQL shapes' observable behavior, independently of
the worker. It verifies parameterized SQL inputs and manifest publication. It is
not evidence that a real Snowflake account executed the supplied SQL.
"""

import copy
import hashlib
import json
import math
from collections import Counter
from statistics import mean

from app.snowflake.observations import fact_digest
from app.snowflake.observations_dto import AGENT_METRICS, COUNT_METRICS, RELATIONSHIP_METRICS
from app.snowflake.transport import VendorUnavailable


def encoded(value):
    return [[json.dumps(value, allow_nan=False)]]


def marker(payload):
    return {k: payload.get(k) for k in ("event_id", "title", "status", "start_tick", "end_tick")}


def living(payload):
    return payload.get("active") and payload.get("life") != "dead" and not payload.get("deleted")


def change(fact, event_id=None):
    p = fact["payload"]
    result = dict(
        id=fact["id"],
        tick=fact["tick"],
        revision=fact["revision"],
        **{k: p.get(k) for k in ("entity_kind", "entity_id", "agent_id", "field", "before", "after", "link")},
        event_ids=p.get("event_ids", []),
        evidence=dict(
            records=p.get("evidence", []),
            decision_ids=p.get("decision_ids", []),
            active_event_ids=p.get("active_event_ids", []),
        ),
    )
    if event_id is not None:
        result["link"] = "explicit" if event_id in p.get("event_ids", []) else "temporal"
    return result


class ObservationFake:
    def __init__(self):
        self.facts = {}
        self.manifests = {}
        self.calls = []
        self.fail_shape = None
        self.after_publish = None
        self.corrupt_verify = False
        self.closed = False

    def transport(self, _config=None):
        return self

    async def close(self):
        self.closed = True

    async def execute(self, shape, values=()):
        self.calls.append((shape, copy.deepcopy(values)))
        if shape == self.fail_shape:
            raise VendorUnavailable("controlled_outage")
        if shape == "obs_ingest":
            envelope = json.loads(values[0])
            assert len(values[0].encode()) <= 1_000_000
            assert len(envelope["facts"]) <= 2000
            for fact in envelope["facts"]:
                body = json.loads(fact["record_json"])
                record = dict(
                    body,
                    id=fact["id"],
                    sha256=hashlib.sha256(fact["record_json"].encode()).hexdigest(),
                    revision=envelope["revision"],
                    tick=envelope["tick"],
                )
                key = (envelope["owner_id"], envelope["simulation_id"], envelope["revision"], fact["id"])
                self.facts.setdefault(key, record)
            return [["1"]]
        if shape == "obs_verify":
            facts = [f for key, f in self.facts.items() if key[:3] == tuple(values)]
            digest = "corrupt" if self.corrupt_verify else fact_digest(facts)
            return [[str(len(facts)), digest]]
        if shape == "obs_publish":
            envelope = json.loads(values[0])
            key = (envelope["owner_id"], envelope["simulation_id"], envelope["revision"])
            self.manifests.setdefault(key, envelope)
            if self.after_publish:
                self.after_publish()
            return [["1"]]
        if shape == "obs_receipt":
            row = self.manifests.get(tuple(values))
            return [[row["source_sha256"], row["facts_sha256"], str(row["fact_count"])]] if row else []
        if shape in {"obs_delete_revisions", "obs_delete_facts"}:
            store = self.manifests if shape.endswith("revisions") else self.facts
            for key in list(store):
                if key[:2] == tuple(values):
                    del store[key]
            return [["1"]]
        if shape == "obs_head":
            rows = [
                (key, m)
                for key, m in self.manifests.items()
                if key[:2] == tuple(values[:2]) and key[2] <= int(values[2])
            ]
            return encoded(
                dict(
                    revision=max((k[2] for k, _ in rows), default=None),
                    tick=max((m["tick"] for _, m in rows), default=None),
                    from_tick=min((m["tick"] for _, m in rows), default=None),
                )
            )
        params = json.loads(values[0])
        facts = [
            f
            for key, f in self.facts.items()
            if key[:2] == (params["owner_id"], params["simulation_id"])
            and key[2] <= params["through_revision"]
            and key[:3] in self.manifests
        ]
        facts.sort(key=lambda f: (f["revision"], f["id"]))
        if shape == "obs_events":
            rows = self.events(facts)
            rows = [
                e
                for e in rows
                if (e["payload"].get("end_tick") if e["payload"].get("end_tick") is not None else math.inf)
                >= params["start_tick"]
                and (e["payload"].get("start_tick") or e["payload"].get("queued_tick", 0))
                <= params["end_tick"]
                and (not params.get("event_id") or params["event_id"] == e["entity_id"])
            ]
            rows.sort(
                key=lambda e: (
                    e["payload"].get("start_tick") or e["payload"].get("queued_tick", 0),
                    e["entity_id"],
                )
            )
            rows = rows[params["offset"] : params["offset"] + params["limit"]]
            return [[json.dumps(marker(e["payload"]))] for e in rows]
        if shape == "obs_changes":
            target = next(
                (e["payload"] for e in self.events(facts) if e["entity_id"] == params.get("event_id")), None
            )

            def matches_event(fact):
                if not params.get("event_id"):
                    return True
                p = fact["payload"]
                return params["event_id"] in p.get("event_ids", []) + p.get("active_event_ids", []) or (
                    target
                    and target.get("start_tick") is not None
                    and target["start_tick"]
                    <= fact["tick"]
                    <= (target["end_tick"] + 30 if target.get("end_tick") is not None else params["end_tick"])
                )

            rows = [
                f
                for f in facts
                if f["kind"] == "change"
                and params["start_tick"] <= f["tick"] <= params["end_tick"]
                and (not params.get("agent_id") or f["payload"]["agent_id"] == params["agent_id"])
                and (not params.get("entity_kind") or f["payload"]["entity_kind"] == params["entity_kind"])
                and matches_event(f)
            ]
            return [
                [json.dumps(change(f, params.get("event_id")))]
                for f in rows[params["offset"] : params["offset"] + params["limit"]]
            ]
        if shape == "obs_trends":
            return encoded(self.trends(facts, params))
        if shape == "obs_event_detail":
            return encoded(self.detail(facts, params))
        raise AssertionError(f"Unexpected SQL shape {shape}")

    @staticmethod
    def latest(facts, kind, revision):
        result = {}
        for f in facts:
            if f["revision"] <= revision and f["kind"] == kind:
                result[f["entity_id"]] = f["payload"]
        return {k: p for k, p in result.items() if not p.get("deleted")}

    def events(self, facts):
        entries = self.latest(facts, "event", math.inf)
        return [dict(entity_id=k, payload=p) for k, p in entries.items()]

    def trends(self, facts, params):
        metric = params["metric"]
        refs = {}
        for key, value in self.manifests.items():
            if (
                key[:2] == (params["owner_id"], params["simulation_id"])
                and key[2] <= params["through_revision"]
            ):
                if params["start_tick"] <= value["tick"] <= params["end_tick"]:
                    refs[value["tick"]] = max(refs.get(value["tick"], -1), key[2])
        target = next(
            (e["payload"] for e in self.events(facts) if e["entity_id"] == params.get("event_id")), None
        )
        if params.get("event_id"):
            refs = {
                t: r
                for t, r in refs.items()
                if target
                and (target.get("start_tick") or target.get("queued_tick", 0))
                <= t
                <= (target.get("end_tick") + 30 if target.get("end_tick") is not None else params["end_tick"])
            }
        points = []
        distribution = []
        for tick, revision in sorted(refs.items()):
            agents = self.latest(facts, "agent", revision)
            alive = {k: p for k, p in agents.items() if living(p)}
            selected = {
                k: p for k, p in alive.items() if not params.get("agent_id") or k == params["agent_id"]
            }
            rels = [
                r
                for r in self.latest(facts, "relationship", revision).values()
                if r["from_agent_id"] in alive
                and r["to_agent_id"] in alive
                and (not params.get("agent_id") or r["from_agent_id"] == params["agent_id"])
            ]
            opinions = [
                o for o in self.latest(facts, "opinion", revision).values() if o["agent_id"] in selected
            ]
            value, denominator = None, len(selected)
            if metric in AGENT_METRICS:
                vals = [p[metric] for p in selected.values() if p.get(metric) is not None]
                value, denominator = mean(vals) if vals else None, len(vals)
            elif metric in RELATIONSHIP_METRICS:
                vals = [r[RELATIONSHIP_METRICS[metric]] for r in rels]
                value, denominator = mean(vals) if vals else None, len(vals)
            elif metric == "relationship_pairs":
                value = denominator = len({r["pair_id"] for r in rels})
            elif metric == "opinion_count":
                value = denominator = len(opinions)
            elif metric == "opinion_confidence":
                vals = [o["confidence"] for o in opinions if o.get("confidence") is not None]
                value, denominator = mean(vals) if vals else None, len(vals)
            elif metric in {"opinion_adoptions", "opinion_removals"}:
                value = sum(
                    f["kind"] == "change"
                    and f["tick"] == tick
                    and f["revision"] <= revision
                    and f["payload"]["entity_kind"] == "opinion"
                    and f["payload"]["field"] == "__entity__"
                    and (not params.get("agent_id") or f["payload"]["agent_id"] == params["agent_id"])
                    and (
                        f["payload"]["before"] is None
                        if metric.endswith("adoptions")
                        else f["payload"]["after"] is None
                    )
                    for f in facts
                )
                denominator = len(opinions)
            elif metric == "population":
                value = len(selected)
            elif metric == "deaths":
                value = sum(
                    a["life"] == "dead"
                    for k, a in agents.items()
                    if not params.get("agent_id") or k == params["agent_id"]
                )
            elif metric in COUNT_METRICS:
                city = next(iter(self.latest(facts, "city", revision).values()), {})
                value = city.get(metric, 0)
            else:
                raise AssertionError(metric)
            points.append(
                dict(
                    tick=tick,
                    revision=revision,
                    mean=value,
                    min=value,
                    max=value,
                    sample_count=1,
                    denominator=denominator,
                )
            )
            if metric.startswith("relationship_"):
                pairs = {}
                for rel in rels:
                    pairs.setdefault(rel["pair_id"], set()).add(rel["kind"])
                labels = Counter(" / ".join(sorted(kinds)) for kinds in pairs.values())
                distribution = [dict(label=label, count=count) for label, count in sorted(labels.items())]
            elif metric.startswith("opinion_"):
                distribution = [
                    dict(label=label, count=count)
                    for label, count in sorted(Counter(o["category"] for o in opinions).items())
                ]
        if len(points) > 500:
            width = math.ceil((points[-1]["tick"] - points[0]["tick"] + 1) / 500)
            groups = {}
            for point in points:
                groups.setdefault((point["tick"] - points[0]["tick"]) // width, []).append(point)
            points = [
                dict(
                    tick=group[-1]["tick"],
                    revision=group[-1]["revision"],
                    mean=mean(vals)
                    if (vals := [p["mean"] for p in group if p["mean"] is not None])
                    else None,
                    min=min(vals) if vals else None,
                    max=max(vals) if vals else None,
                    sample_count=len(group),
                    denominator=max(p["denominator"] for p in group),
                )
                for group in groups.values()
            ]
        events = [
            marker(e["payload"])
            for e in self.events(facts)
            if (e["payload"].get("start_tick") or e["payload"].get("queued_tick", 0)) <= params["end_tick"]
            and (e["payload"].get("end_tick") if e["payload"].get("end_tick") is not None else math.inf)
            >= params["start_tick"]
        ]
        return dict(items=points, events=events, distribution=distribution)

    def detail(self, facts, params):
        payload = next(
            (e["payload"] for e in self.events(facts) if e["entity_id"] == params["event_id"]), None
        )
        if payload is None:
            return dict(event=None)
        eid = payload["event_id"]
        cohort = payload.get("cohort", [])
        end = payload.get("end_tick")
        latest_tick = max((f["tick"] for f in facts), default=0)
        resolution = min(
            (
                f["revision"]
                for f in facts
                if f["kind"] == "event" and f["entity_id"] == eid and f["payload"].get("end_tick") is not None
            ),
            default=None,
        )

        def aggregate(agents, subset=None, available=True):
            values = [a for a in agents if subset is None or a["agent_id"] in subset]
            good = [a for a in values if living(a)]
            result = {
                k: mean(vals) if (vals := [a[k] for a in good if a.get(k) is not None]) else None
                for k in AGENT_METRICS
            }
            result.update(
                population=len(good) if available else None,
                deaths=sum(a["life"] == "dead" for a in values) if available else None,
            )
            if subset is not None:
                result["initial_population"] = len(subset)
            return result

        baseline_agents = (payload.get("baseline") or {}).get("agents", [])

        def denominators(agents):
            result = {}
            for name, subset in (
                ("city", agents),
                ("cohort", [a for a in agents if a["agent_id"] in cohort]),
            ):
                valid = [a for a in subset if living(a)]
                result[name] = {k: sum(a.get(k) is not None for a in valid) for k in AGENT_METRICS}
                result[name].update(population=len(valid), deaths=len(subset))
            return result

        bas = dict(
            tick=payload.get("start_tick"),
            city=aggregate(baseline_agents, available=payload.get("baseline_available", False)),
            cohort=aggregate(baseline_agents, cohort, payload.get("baseline_available", False)),
            denominators=denominators(baseline_agents),
        )
        res_agents = list(self.latest(facts, "agent", resolution).values()) if resolution is not None else []
        res = dict(
            tick=end,
            city=aggregate(res_agents, available=end is not None),
            cohort=aggregate(res_agents, cohort, end is not None),
            denominators=denominators(res_agents),
        )
        follow_tick = min(end + 30, latest_tick) if end is not None else None
        follow_rev = max(
            (f["revision"] for f in facts if follow_tick is not None and f["tick"] <= follow_tick), default=-1
        )
        follow_agents = list(self.latest(facts, "agent", follow_rev).values())
        follow = dict(
            tick=follow_tick,
            city=aggregate(follow_agents, available=end is not None),
            cohort=aggregate(follow_agents, cohort, end is not None),
            denominators=denominators(follow_agents),
        )
        changes = [
            f
            for f in facts
            if f["kind"] == "change"
            and (
                eid in f["payload"].get("event_ids", []) + f["payload"].get("active_event_ids", [])
                or (
                    payload.get("start_tick") is not None
                    and payload["start_tick"] <= f["tick"] <= (end + 30 if end is not None else math.inf)
                )
            )
        ]
        numeric = [
            dict(metric=k, delta=res["city"][k] - bas["city"][k], revision=resolution)
            for k in ("health", "trust", "mental", "happiness", "stress", "population", "deaths")
            if res["city"][k] is not None and bas["city"][k] is not None
        ]
        overlaps = [
            marker(e["payload"])
            for e in self.events(facts)
            if e["entity_id"] != eid
            and (e["payload"].get("start_tick") or e["payload"].get("queued_tick", 0))
            <= (end if end is not None else math.inf)
            and (e["payload"].get("end_tick") if e["payload"].get("end_tick") is not None else math.inf)
            >= (payload.get("start_tick") or math.inf)
        ]
        return dict(
            event=marker(payload),
            baseline=bas,
            resolution=res,
            followup=follow,
            followup_complete=end is not None and latest_tick >= end + 30,
            overlaps=overlaps,
            changes=[change(f, eid) for f in changes[:100]],
            citations=[],
            numeric_observations=numeric,
            change_counts=dict(
                explicit=sum(eid in f["payload"].get("event_ids", []) for f in changes),
                temporal=sum(eid not in f["payload"].get("event_ids", []) for f in changes),
            ),
        )
