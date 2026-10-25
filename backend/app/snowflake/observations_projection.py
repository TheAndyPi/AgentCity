"""Deterministic observation projection of committed history, with no vendor I/O.

Only public simulation measurements and structured evidence are projected. Private
memories, deliberation prompts and relationship desires never enter this model.
"""

import hashlib
import json
from statistics import mean

VERSION = "1.0.0"
AGENT_METRICS = (
    "happiness",
    "safety",
    "trust",
    "resources",
    "stress",
    "health",
    "hunger",
    "fatigue",
    "social_need",
    "mental",
    "institutional_trust",
)
RELATIONSHIP_METRICS = ("trust", "affection", "respect", "familiarity", "conflict")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _evidence(value):
    if value is None:
        return {}
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


def _agents(state):
    result = {}
    for aid, citizen in sorted(state.citizens.items()):
        systems = state.systems.agents.get(aid)
        result[aid] = dict(
            agent_id=aid,
            name=citizen.summary.name,
            active=citizen.summary.active,
            life=citizen.condition.life,
            **citizen.summary.metrics.model_dump(mode="json"),
            health=citizen.needs.health,
            hunger=citizen.needs.hunger,
            fatigue=citizen.needs.fatigue,
            social_need=citizen.needs.social,
            mental=citizen.condition.mental,
            institutional_trust=systems.institutional_trust if systems else None,
        )
    return result


def _relationships(state):
    result = {}
    for citizen in state.citizens.values():
        for relationship in citizen.relationships.values():
            source, target = relationship.from_agent_id, relationship.to_agent_id
            identity = f"{source}:{target}"
            result[identity] = dict(
                from_agent_id=source,
                to_agent_id=target,
                pair_id=":".join(sorted((source, target))),
                kind=relationship.kind,
                **{field: getattr(relationship, field) for field in RELATIONSHIP_METRICS},
                evidence=_evidence(relationship.evidence),
            )
    return result


def _opinions(state):
    result = {}

    def add(aid, category, key, value, confidence=None, evidence=None):
        identity = canonical([aid, category, key])
        result[identity] = dict(
            agent_id=aid,
            category=category,
            key=key,
            value=value,
            confidence=confidence,
            evidence=evidence or {},
        )

    for aid, citizen in sorted(state.citizens.items()):
        for belief in citizen.beliefs:
            proof = _evidence(belief.evidence)
            # Confidence is mutable; textual beliefs have no intrinsic source ID.
            key = digest(dict(text=belief.text, evidence=proof))
            add(aid, "belief", key, belief.text, belief.confidence, proof)
        for key, value in sorted(citizen.condition.class_beliefs.items()):
            add(aid, "class", key, value, evidence={"tick": citizen.condition.class_evidence_tick.get(key)})
        systems = state.systems.agents.get(aid)
        if systems:
            for key, belief in sorted(systems.beliefs.items()):
                add(
                    aid,
                    "information",
                    key,
                    belief.message,
                    belief.confidence,
                    dict(
                        source_op=belief.source_op,
                        topic=belief.topic,
                        channel=belief.channel,
                        tick=belief.tick,
                    ),
                )
            for key, value in sorted(systems.norms.items()):
                add(aid, "norm", key, value)
    return result


def _city(state, agents, relationships, opinions):
    living = {aid for aid, a in agents.items() if a["active"] and a["life"] != "dead"}
    values, denominators = {}, {}
    for field in AGENT_METRICS:
        recorded = [agents[aid][field] for aid in living if agents[aid][field] is not None]
        values[field] = mean(recorded) if recorded else None
        denominators[field] = len(recorded)
    ties = [r for r in relationships.values() if r["from_agent_id"] in living and r["to_agent_id"] in living]
    values.update(
        population=len(living),
        deaths=sum(a["life"] == "dead" for a in agents.values()),
        cooperation_count=state.counters.get("cooperation_count", 0),
        conflict_count=state.counters.get("conflict_count", 0),
        relationship_trust=mean(r["trust"] for r in ties) if ties else None,
        relationship_count=len(ties),
        opinion_count=sum(o["agent_id"] in living for o in opinions.values()),
        denominators={**denominators, "relationship_trust": len(ties)},
    )
    return values


def capture_baseline(state):
    """Internal event baseline, captured before activation can mutate the world."""
    agents, relationships, opinions = _agents(state), _relationships(state), _opinions(state)
    return dict(
        tick=state.simulation.tick,
        revision=state.simulation.revision,
        agents=list(agents.values()),
        relationships=[dict(entity_id=k, **v) for k, v in sorted(relationships.items())],
        opinions=[dict(entity_id=k, **v) for k, v in sorted(opinions.items())],
        city=_city(state, agents, relationships, opinions),
    )


def _events(state):
    result = {}
    for eid, runtime in sorted(state.events.items()):
        event = runtime.summary
        plan = state.systems.plans.get(eid)
        result[eid] = dict(
            event_id=eid,
            title=event.title,
            status="cancelled" if runtime.cancelled else event.status,
            queued_tick=event.queued_tick,
            start_tick=event.start_tick,
            end_tick=event.end_tick,
            cohort=sorted(plan.cohort if plan and plan.activated_tick is not None else runtime.cohort),
            baseline=runtime.observation_baseline,
            baseline_available=runtime.observation_baseline is not None,
        )
    return result


def _records(state):
    if state is None:
        return {kind: {} for kind in ("agent", "relationship", "opinion", "event", "city")}
    agents, relationships, opinions = _agents(state), _relationships(state), _opinions(state)
    return dict(
        agent=agents,
        relationship=relationships,
        opinion=opinions,
        event=_events(state),
        city={"city": _city(state, agents, relationships, opinions)},
    )


def _new_proofs(previous, current):
    """Index only newly recorded evidence, never reuse an old cause by proximity."""
    result = {}

    def add(kind, identity, field, proof):
        if proof:
            result.setdefault((kind, identity, field), []).append(_evidence(proof))

    old_decisions = {d.id: d.model_dump(mode="json") for d in previous.decisions} if previous else {}
    for decision in current.decisions:
        if old_decisions.get(decision.id) == decision.model_dump(mode="json"):
            continue
        for effect in decision.effects:
            proof = dict(event_ids=decision.event_ids, decision_ids=[decision.id])
            field = effect.field.rsplit(".", 1)[-1]
            add("agent", effect.entity_id, field, proof)
    for aid, citizen in current.citizens.items():
        old = previous.citizens.get(aid) if previous else None
        old_reasons = len(old.metric_reasons) if old else 0
        for reason in citizen.metric_reasons[old_reasons:]:
            add("agent", aid, reason.metric, reason.evidence)
        old_impacts = len(old.condition.impacts) if old else 0
        for impact in citizen.condition.impacts[old_impacts:]:
            field = {"energy": "fatigue", "fullness": "hunger", "social": "social_need"}.get(
                impact.meter, impact.meter
            )
            add("agent", aid, field, impact.evidence)
        if old and old.condition.evidence != citizen.condition.evidence:
            add("agent", aid, "life", citizen.condition.evidence)
    old_traces = {t.id: t.model_dump(mode="json") for t in previous.systems.traces} if previous else {}
    for trace in current.systems.traces:
        if old_traces.get(trace.id) == trace.model_dump(mode="json"):
            continue
        for change in trace.changes:
            identity = change.get("entity_id", change.get("agent_id")) or trace.agent_id
            field = change.get("field", "").rsplit(".", 1)[-1]
            if identity and field:
                add(
                    "agent",
                    identity,
                    field,
                    dict(event_ids=[trace.event_id] if trace.event_id else [], trace_ids=[trace.id]),
                )
    return result


def _change(kind, identity, field, before, after, previous, current, active, proofs):
    payload = after if after is not None else before
    proof = list(proofs.get((kind, identity, field), ()))
    if kind in {"relationship", "opinion"}:
        new_evidence = (after or {}).get("evidence", {})
        old_evidence = (before or {}).get("evidence", {})
        if new_evidence and new_evidence != old_evidence:
            proof.append(new_evidence)
    if kind == "event":
        proof.append(dict(event_ids=[identity]))
    event_ids = {eid for p in proof for eid in p.get("event_ids", [])}
    decision_ids = {did for p in proof for did in p.get("decision_ids", [])}
    # Information source operations explicitly identify their parent plan.
    for item in proof:
        source = item.get("source_op")
        if source:
            for eid, plan in current.systems.plans.items():
                if any(op.get("id") == source for op in plan.plan.get("operations", [])):
                    event_ids.add(eid)
    return dict(
        entity_kind=kind,
        entity_id=identity,
        agent_id=payload.get("agent_id", payload.get("from_agent_id")) if payload else None,
        field=field,
        before=(before or {}).get(field) if field != "__entity__" else before,
        after=(after or {}).get(field) if field != "__entity__" else after,
        event_ids=sorted(event_ids),
        decision_ids=sorted(decision_ids),
        evidence=proof,
        link="explicit" if event_ids or decision_ids else "temporal",
        active_event_ids=active,
    )


def project(previous, current, lineage=None):
    """Return full changed entity versions and exact field diffs for one revision.

    Calling this function never changes the state, advances RNG or contacts a
    provider. Same-tick commits remain independent observation revisions.
    """
    sim = current.simulation
    lineage = lineage or {}
    old, new = _records(previous), _records(current)
    active = sorted(eid for eid, e in new["event"].items() if e["status"] == "active")
    proofs = _new_proofs(previous, current)
    facts = []

    def add(kind, identity, payload):
        fact = dict(kind=kind, entity_id=identity, payload=payload)
        fact["sha256"] = digest(fact)
        fact["id"] = digest([VERSION, current.owner_id, sim.id, sim.revision, kind, identity])
        facts.append(fact)

    changes = []
    fields = dict(
        agent=(*AGENT_METRICS, "active", "life"),
        relationship=("kind", *RELATIONSHIP_METRICS),
        opinion=("value", "confidence"),
        event=("status",),
    )
    for kind in ("agent", "relationship", "opinion", "event", "city"):
        for identity in sorted(set(old[kind]) | set(new[kind])):
            before, after = old[kind].get(identity), new[kind].get(identity)
            if kind != "city" and before == after:
                continue
            add(kind, identity, after if after is not None else dict(**before, deleted=True))
            # Initial projection declares baselines, not invented historical changes.
            if previous is None or kind == "city":
                continue
            if before is None or after is None:
                changes.append(
                    _change(kind, identity, "__entity__", before, after, previous, current, active, proofs)
                )
            else:
                for field in fields[kind]:
                    if before.get(field) != after.get(field):
                        changes.append(
                            _change(kind, identity, field, before, after, previous, current, active, proofs)
                        )
    for change in changes:
        add("change", digest([change["entity_kind"], change["entity_id"], change["field"]]), change)
    fork = lineage.get("fork_ref", sim.fork_ref.model_dump(mode="json") if sim.fork_ref else None)
    return dict(
        projection_version=VERSION,
        owner_id=current.owner_id,
        simulation_id=sim.id,
        revision=sim.revision,
        tick=sim.tick,
        sim_time_seconds=sim.sim_time_seconds,
        rule_version=current.rule_version,
        seed=sim.config.seed,
        parent_simulation_id=lineage.get("parent_simulation_id", sim.parent_simulation_id),
        fork_revision=lineage.get("fork_revision", fork.get("revision") if fork else None),
        source_sha256=digest(current.model_dump(mode="json")),
        facts=facts,
    )
