"""Scenario interpreter: natural language to a validated, structured plan.

Gemini returns a flat draft (one optional field per parameter, which keeps the
response schema simple for structured output). The draft is normalized into
typed operations and validated; on failure the model gets one correction
attempt with the exact validation errors.
"""

import json

from app.contracts import Model
from app.scenario_engine.registry import (
    INCENTIVES,
    METRICS,
    NORMS,
    OPERATION_MODELS,
    OPERATIONS,
    ORGANIZATIONS,
    POLICY_TARGETS,
    AudienceKind,
    BuildingKind,
    Category,
    Channel,
    Condition,
    Eligibility,
    Hazard,
    Incentive,
    MetricId,
    Norm,
    OperationType,
    OrganizationKind,
    PolicyTarget,
    Region,
    ResourceKind,
    System,
    Topic,
    Trait,
)
from app.scenario_engine.validator import summary, validate_plan

OUTPUT_TOKENS = 8192
TIMEOUT_SECONDS = 40

MODE_GUIDANCE = {
    "sandbox": "Open-ended sandbox. Represent whatever the user describes.",
    "behavior_lab": (
        "Behavior Lab: the user studies how people behave. Distinguish editing who citizens are "
        "(adjust_population_traits) from changing the conditions they live in (information, "
        "credibility, norms, incentives, organizations, social ties). Prefer conditions unless the "
        "request explicitly changes personality."
    ),
    "policy_lab": (
        "Policy Lab: the user studies public policy. Use modify_policy for laws, prices, taxes and "
        "budgets; announce policies with broadcast_information unless the request says they are secret."
    ),
    "crisis_lab": (
        "Crisis Lab: the user studies disruption. Use physical hazards, service closures, resource stock "
        "changes and environmental conditions only as the request describes them."
    ),
}


class OperationDraft(Model):
    type: OperationType
    id: str
    rationale: str
    start_tick: int | None = None
    duration_ticks: int | None = None
    repeat_every: int | None = None
    repeat_count: int | None = None
    target: PolicyTarget | None = None
    operation: str | None = None
    value: float | None = None
    building_id: str | None = None
    building_kind: BuildingKind | None = None
    region: Region | None = None
    open: bool | None = None
    capacity_multiplier: float | None = None
    resource: ResourceKind | None = None
    multiplier: float | None = None
    available_share: float | None = None
    audience_kind: AudienceKind | None = None
    audience_share: float | None = None
    audience_region: Region | None = None
    organization_id: str | None = None
    channel: Channel | None = None
    topic: Topic | None = None
    message: str | None = None
    credibility: float | None = None
    accurate: bool | None = None
    delta: float | None = None
    reason: str | None = None
    norm: Norm | None = None
    strength: float | None = None
    kind: OrganizationKind | None = None
    name: str | None = None
    mission: str | None = None
    eligibility: Eligibility | None = None
    budget_per_tick: float | None = None
    rally_every: int | None = None
    founding_share: float | None = None
    incentive: Incentive | None = None
    amount: float | None = None
    trait: Trait | None = None
    selection: str | None = None
    action: str | None = None
    ties_per_agent: int | None = None
    hazard: Hazard | None = None
    severity: float | None = None
    activity: str | None = None
    condition: Condition | None = None
    intensity: float | None = None


class PlanDraft(Model):
    status: str
    title: str
    category: Category
    description: str
    public_description: str
    duration: str
    measurement_ticks: int
    affected_systems: list[System]
    operations: list[OperationDraft]
    agent_knowledge: str
    metrics: list[MetricId]
    assumptions: list[str]
    unsupported: list[str]
    clarification: str


def normalize(draft, prompt):
    """Flat draft to the typed plan shape; fields that do not belong to an operation are dropped."""
    operations = []
    for item in draft.operations:
        fields = OPERATION_MODELS[item.type].model_fields
        data = item.model_dump(exclude_none=True)
        op = dict(type=item.type, id=item.id[:40] or "op", rationale=item.rationale[:300])
        timing = {k: data[k] for k in ("start_tick", "duration_ticks", "repeat_every", "repeat_count") if k in data}
        if timing:
            op["timing"] = timing
        if "audience" in fields:
            audience = {}
            for source, target in (("audience_kind", "kind"), ("audience_share", "share"),
                                   ("audience_region", "region"), ("organization_id", "organization_id")):
                if source in data:
                    audience[target] = data[source]
            if audience:
                op["audience"] = audience
        for name in fields:
            if name in {"type", "id", "rationale", "timing", "audience"} or name not in data:
                continue
            op[name] = data[name]
        if "value" in fields and "value" not in op and item.operation == "clear":
            op["value"] = None
        operations.append(op)
    return dict(
        title=draft.title[:80] or prompt[:80],
        category=draft.category,
        description=draft.description[:1000],
        public_description=draft.public_description[:500] or draft.title[:500],
        duration=draft.duration if draft.duration in {"temporary", "permanent"} else "temporary",
        measurement_ticks=draft.measurement_ticks,
        affected_systems=list(dict.fromkeys(draft.affected_systems)),
        operations=operations,
        agent_knowledge=draft.agent_knowledge[:500],
        metrics=list(dict.fromkeys(draft.metrics)),
        assumptions=[a[:300] for a in draft.assumptions][:8],
        unsupported=[u[:300] for u in draft.unsupported][:8],
        source="gemini",
        prompt=prompt[:2000],
    )


def build_prompt(state, prompt, mode):
    registry = dict(
        operations={name: dict(description=d, systems=list(s), physical=p) for name, (d, s, p) in OPERATIONS.items()},
        operation_fields={name: [f for f in model.model_fields if f not in {"type", "id", "timing", "rationale"}]
                          for name, model in OPERATION_MODELS.items()},
        policy_targets={t: dict(minimum=lo, maximum=hi, unit=u, clearable=n, description=d)
                        for t, (lo, hi, u, n, d, _) in POLICY_TARGETS.items()},
        norms=NORMS,
        organizations=ORGANIZATIONS,
        incentives=INCENTIVES,
        metrics=METRICS,
    )
    return (
        "You translate a user's scenario for a small simulated town into a structured plan of world "
        "changes. Citizens are autonomous: you decide only what changes in the world, never how citizens "
        "react. Their reactions are simulated from their own traits, money, knowledge and relationships.\n\n"
        "Rules:\n"
        "- Use only the registered operations, policy targets, building ids and organization ids below.\n"
        "- Represent every part of the request you can. Compose several operations for multi-part requests.\n"
        "- Never substitute a different event. Do not add floods, fires, storms, festivals, aid or shortages "
        "unless the user asked for them.\n"
        "- If part of the request cannot be represented, explain it in `unsupported` and represent the rest. "
        "If nothing can be represented, set status to \"unsupported\" with no operations.\n"
        "- If the request is too ambiguous to represent, set status to \"needs_clarification\" and ask in "
        "`clarification`.\n"
        "- Relative changes: \"doubles\" is multiply 2, \"halves\" is multiply 0.5, \"raises by 20%\" is multiply 1.2.\n"
        "- Spending money on a public service is modify_policy on that service's funding target; the "
        "treasury pays for it.\n"
        "- Announce official changes with broadcast_information (channel official) unless the request says "
        "they are secret or unannounced. Rumors use channel rumor with accurate false.\n"
        "- public_description is only what residents can directly observe; do not reveal secret changes.\n"
        "- agent_knowledge says which citizens know what at the start.\n"
        "- Timing is in ticks relative to the start of the scenario (one tick is 10 seconds of town time). "
        "duration permanent keeps changes after the measurement window; temporary reverts them.\n"
        "- Choose metrics that measure the consequences the user cares about.\n"
        "- For each operation, set only the fields listed for its type in operation_fields; audience fields "
        "are audience_kind, audience_share, audience_region and organization_id.\n"
        "- Use status \"ready\" when the plan has operations.\n\n"
        f"Mode: {MODE_GUIDANCE.get(mode, MODE_GUIDANCE['sandbox'])}\n\n"
        f"Current town:\n{json.dumps(summary(state), separators=(',', ':'))}\n\n"
        f"Registry:\n{json.dumps(registry, separators=(',', ':'))}\n\n"
        f"User scenario:\n{prompt}\n"
    )


def correction_prompt(base, previous, errors):
    return (
        f"{base}\nYour previous plan failed validation:\n"
        + "\n".join(f"- {e}" for e in errors)
        + f"\n\nPrevious plan:\n{json.dumps(previous, separators=(',', ':'))[:12000]}\n\n"
        "Return a corrected plan. Fix only what the errors describe; if a requirement cannot be represented, "
        "move it to `unsupported`."
    )


async def interpret(gateway, state, sid, prompt, mode):
    """Returns dict(status, plan, errors, warnings, unsupported, clarification, attempts)."""
    if not gateway.config.gemini_enabled:
        return dict(status="unavailable", plan=None, errors=["The AI interpreter is not configured."],
                    warnings=[], unsupported=[], clarification="", attempts=0)
    base = build_prompt(state, prompt, mode)
    request = base
    errors, previous = [], None
    for attempt in (1, 2):
        draft = await gateway.structured(sid, request, PlanDraft, max_output_tokens=OUTPUT_TOKENS, timeout=TIMEOUT_SECONDS)
        if draft is None:
            return dict(status="unavailable", plan=previous, errors=["The AI interpreter did not respond."],
                        warnings=[], unsupported=[], clarification="", attempts=attempt)
        if draft.status == "unsupported" or (not draft.operations and draft.unsupported):
            return dict(status="unsupported", plan=None, errors=[], warnings=[],
                        unsupported=draft.unsupported or ["No registered operation can represent this scenario."],
                        clarification=draft.clarification, attempts=attempt)
        if draft.status == "needs_clarification" and not draft.operations:
            return dict(status="needs_clarification", plan=None, errors=[], warnings=[],
                        unsupported=draft.unsupported, clarification=draft.clarification, attempts=attempt)
        raw = normalize(draft, prompt)
        plan, errors, warnings = validate_plan(state, raw)
        if plan is not None:
            return dict(status="ready", plan=plan.model_dump(mode="json"), errors=[], warnings=warnings,
                        unsupported=plan.unsupported, clarification="", attempts=attempt)
        previous = raw
        request = correction_prompt(base, raw, errors)
    return dict(status="invalid", plan=previous, errors=errors, warnings=[], unsupported=previous.get("unsupported", []),
                clarification="", attempts=2)
