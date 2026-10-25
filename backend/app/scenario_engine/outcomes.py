"""Outcome analyzer: measurements and findings derived only from recorded state."""

from statistics import mean

from app.scenario_engine.registry import METRICS
from app.scenario_engine.systems import SERIES_LIMIT, STRAIN_WALLET
from app.scenario_engine.world import rent_for
from app.simulation.agents import evidence

COUNTERS = (
    "trips_walk", "trips_transit", "trips_car", "fare_revenue", "business_tax", "relocations",
    "assistance_requests", "information_shares", "information_accepted", "information_rejected",
    "norm_adoptions", "organization_joins", "hospital_care", "food_bought", "food_gathered",
    "service_attempts", "service_success", "compliance_yes", "compliance_no", "aid_transfers",
    "rally_conflicts", "habit_changes", "alternatives_sought", "beliefs_adopted", "beliefs_doubted",
    "wage_cuts", "shortfall_ticks", "sold_out",
)


def snapshot_counters(state):
    values = {name: state.systems.counters.get(name, 0) for name in COUNTERS}
    values.update(
        cooperation_count=state.counters["cooperation_count"],
        conflict_count=state.counters["conflict_count"],
        social_updates=len(state.applied_social_evidence),
    )
    return values


def measure(state, record=None):
    systems = state.systems
    active = [c for c in state.citizens.values() if c.summary.active]
    agents = [systems.agents[c.summary.id] for c in active if c.summary.id in systems.agents]
    metrics = state.metric_points[-1].values if state.metric_points else None
    counters = snapshot_counters(state)
    base = record.counters if record else {k: 0 for k in counters}
    delta = {k: counters[k] - base.get(k, 0) for k in counters}
    trips = delta["trips_walk"] + delta["trips_transit"] + delta["trips_car"]
    decided = delta["compliance_yes"] + delta["compliance_no"]
    attempts = delta["service_attempts"]
    scenario_beliefs = {
        op["id"] for op in (record.plan["operations"] if record else []) if op["type"] in
        {"broadcast_information", "adjust_institutional_credibility"}
    }
    norms = {op.get("norm") for op in (record.plan["operations"] if record else []) if op["type"] == "introduce_social_norm"}
    orgs = [o for o in systems.organizations.values() if record is None or o.event_id == record.event_id]
    value = dict(
        tick=state.simulation.tick,
        happiness=metrics.happiness if metrics else None,
        stress=metrics.stress if metrics else None,
        safety=metrics.safety if metrics else None,
        trust=metrics.trust if metrics else None,
        resources=metrics.resources if metrics else None,
        institutional_trust=mean(a.institutional_trust for a in agents) if agents else None,
        cooperation=delta["cooperation_count"] + delta["aid_transfers"],
        social_conflict=delta["conflict_count"] + delta["rally_conflicts"],
        policy_compliance=delta["compliance_yes"] / decided if decided else None,
        service_access=delta["service_success"] / attempts if attempts else None,
        transit_usage=delta["trips_transit"] / trips if trips else None,
        car_usage=delta["trips_car"] / trips if trips else None,
        walking_trips=delta["trips_walk"] / trips if trips else None,
        trips=trips,
        business_resources=sum(v for k, v in systems.businesses.items() if k != "landlords"),
        city_treasury=systems.treasury,
        household_wallets=mean(a.wallet for a in agents) if agents else None,
        financial_strain=sum(a.wallet < STRAIN_WALLET for a in agents),
        rent_burden=mean(rent_for(state, a) for a in agents) if agents else None,
        relocations=delta["relocations"],
        assistance_requests=delta["assistance_requests"],
        information_shares=delta["information_shares"],
        belief_adoption=sum(any(k in scenario_beliefs for k in a.beliefs) for a in agents),
        norm_adoption=sum(any(a.norms.get(n, 0) > 0 for n in norms) for a in agents),
        organization_membership=sum(len(o.members) for o in orgs if o.active),
        relationship_change=delta["social_updates"],
        hospital_care=delta["hospital_care"],
        food_access=delta["food_bought"] + delta["food_gathered"],
    )
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in value.items()}


def baseline(state):
    """Measures at activation, plus habitual travel shares since no trips are recorded yet."""
    value = measure(state)
    agents = [state.systems.agents[a] for a, c in state.citizens.items() if c.summary.active and a in state.systems.agents]
    if agents:
        for mode, key in (("transit", "transit_usage"), ("car", "car_usage"), ("walk", "walking_trips")):
            value[key] = round(sum(a.habit == mode for a in agents) / len(agents), 4)
        value["habit_basis"] = True
    return value


def record_point(state, record):
    record.series.append(measure(state, record))
    if len(record.series) > SERIES_LIMIT:
        record.series = record.series[::2]


def pct(value):
    return f"{value * 100:.0f}%"


def number(value):
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def finalize(state, record, runtime):
    """Findings from recorded measurements only; every claim cites the run's own records."""
    after = measure(state, record)
    before = record.baseline
    traces = [t for t in state.systems.traces if t.event_id == record.event_id]
    decisions = [t for t in traces if t.kind == "decision"]
    memory_ids = [m for t in sorted(decisions, key=lambda t: -t.significance)[:12] for m in t.memory_ids[:1]]
    proof = evidence("Recorded scenario measurements and decisions", event_ids=[record.event_id], memory_ids=memory_ids[:12])
    findings = []

    def add(text):
        findings.append(dict(text=text[:2000], evidence=proof.model_dump()))

    requested = list(dict.fromkeys([*record.plan.get("metrics", []), "happiness", "stress"]))
    for key in requested:
        if key in {"transit_usage", "car_usage", "walking_trips"}:
            if after["trips"]:
                mode = {"transit_usage": "public transit", "car_usage": "car", "walking_trips": "foot"}[key]
                counted = {"transit_usage": "trips_transit", "car_usage": "trips_car", "walking_trips": "trips_walk"}[key]
                taken = state.systems.counters.get(counted, 0) - record.counters.get(counted, 0)
                add(
                    f"{taken:.0f} of {after['trips']} recorded trips ({pct(after[key])}) were made by {mode}, "
                    f"compared with {pct(before.get(key) or 0)} of citizens who habitually travelled that way at activation."
                )
            continue
        if key not in METRICS or after.get(key) is None:
            continue
        b, a = before.get(key), after[key]
        if key in {"cooperation", "social_conflict", "relocations", "assistance_requests", "information_shares",
                   "relationship_change", "hospital_care", "food_access"}:
            add(f"{METRICS[key]}: {number(a)}.")
        elif key in {"policy_compliance", "service_access"}:
            add(f"{METRICS[key]}: {pct(a)}.")
        elif b is None:
            add(f"{METRICS[key]}: {number(a)} at the end of the window.")
        else:
            add(f"{METRICS[key]} moved from {number(b)} to {number(a)} ({a - b:+.1f}).")
    kinds = {}
    for t in decisions:
        kinds[t.title.split(":")[0][:60]] = kinds.get(t.title.split(":")[0][:60], 0) + 1
    if kinds:
        top = sorted(kinds.items(), key=lambda item: -item[1])[:4]
        add("Recorded citizen decisions: " + "; ".join(f"{name} ({count})" for name, count in top) + ".")
    switched = {t.agent_id for t in decisions if t.title.startswith("Switched my regular travel")}
    if switched:
        add(f"{len(switched)} citizens changed their regular way of travelling during the window.")
    add(
        "These are associations measured within this run, not proof of cause. For a control, branch from the "
        "pre-event snapshot and run the same ticks without the scenario."
    )
    record.findings = findings
    record.policy_after = state.systems.policy.model_dump()
    record.status = "resolved"
    record.resolved_tick = state.simulation.tick
    runtime.consequences = [*runtime.consequences, *findings]


def significant_decisions(state, event_id, limit=20):
    decisions = [t for t in state.systems.traces if t.event_id == event_id and t.kind == "decision"]
    decisions.sort(key=lambda t: (-t.significance, -t.tick, t.id))
    return decisions[:limit]
