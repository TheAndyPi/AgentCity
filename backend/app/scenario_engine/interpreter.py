"""Scenario interpreter: natural language to a validated, structured plan.

Gemini returns compact parameter maps instead of dozens of nullable fields per
operation. Every map is normalized into a registered typed operation and
validated. Corrections share one finite deadline with transport retries.
"""

import asyncio
import json
from typing import Any

from pydantic import model_validator

from app.contracts import Model
from app.scenario_engine.registry import (
    INCENTIVES,
    METRICS,
    NORMS,
    OPERATION_MODELS,
    OPERATIONS,
    ORGANIZATIONS,
    POLICY_TARGETS,
    Category,
    MetricId,
    OperationType,
    System,
)
from app.scenario_engine.validator import summary, validate_plan
from app.simulation.scenario_scene import CATALOG

OUTPUT_TOKENS = 8192
TIMEOUT_SECONDS = 40
TOTAL_TIMEOUT_SECONDS = 85  # Includes queue/auth/retries; the browser allows 95 seconds.
MAX_ATTEMPTS = 3

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
    parameters: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def accept_flat_draft(cls, value):
        """Accept earlier provider drafts; the generated schema uses parameter maps."""
        if isinstance(value, dict) and "parameters" not in value:
            identity = {key: value[key] for key in ("type", "id", "rationale") if key in value}
            return identity | dict(
                parameters={key: item for key, item in value.items() if key not in identity}
            )
        return value


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
    """Parameter maps and legacy timing/audience aliases to the typed, validated plan shape."""
    operations = []
    for item in draft.operations:
        fields = OPERATION_MODELS[item.type].model_fields
        data = {key: value for key, value in item.parameters.items() if value is not None}
        op = dict(type=item.type, id=item.id[:40] or "op", rationale=item.rationale[:300])
        timing = {
            k: data[k] for k in ("start_tick", "duration_ticks", "repeat_every", "repeat_count") if k in data
        }
        if timing:
            op["timing"] = timing
        if "audience" in fields:
            audience = {}
            for source, target in (
                ("audience_kind", "kind"),
                ("audience_share", "share"),
                ("audience_region", "region"),
                ("organization_id", "organization_id"),
            ):
                if source in data:
                    audience[target] = data[source]
            if audience:
                op["audience"] = audience
        aliases = {"start_tick", "duration_ticks", "repeat_every", "repeat_count"}
        if "audience" in fields:
            aliases |= {"audience_kind", "audience_share", "audience_region"}
            if "organization_id" not in fields:
                aliases.add("organization_id")
        for name in data:
            if name in {"type", "id", "rationale"} or name in aliases:
                continue
            op[name] = data[name]
        if "value" in fields and "value" not in op and data.get("operation") == "clear":
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
        operations={
            name: dict(description=d, systems=list(s), physical=p) for name, (d, s, p) in OPERATIONS.items()
        },
        operation_fields={
            name: [f for f in model.model_fields if f not in {"type", "id", "timing", "rationale"}]
            for name, model in OPERATION_MODELS.items()
        },
        required_parameters={
            name: [
                key
                for key, field in model.model_fields.items()
                if field.is_required() and key not in {"type", "id", "rationale"}
            ]
            for name, model in OPERATION_MODELS.items()
        },
        parameter_choices={
            name: {
                key: schema["enum"]
                for key, schema in model.model_json_schema()["properties"].items()
                if "enum" in schema and key not in {"target", "recipe"}
            }
            for name, model in OPERATION_MODELS.items()
        },
        policy_targets={
            t: dict(minimum=lo, maximum=hi, unit=u, clearable=n, description=d)
            for t, (lo, hi, u, n, d, _) in POLICY_TARGETS.items()
        },
        norms=NORMS,
        organizations=ORGANIZATIONS,
        incentives=INCENTIVES,
        metrics=METRICS,
        scene_catalog=[
            dict(
                id=recipe["id"],
                examples=recipe["terms"][:4],
                model=recipe["model"],
                effects=recipe["effects"],
            )
            for recipe in CATALOG
        ],
    )
    return (
        "You translate a user's scenario for a small simulated town into a structured plan of world "
        "changes. Citizens are autonomous: you decide only what changes in the world, never how citizens "
        "react. Their reactions are simulated from their own traits, money, knowledge and relationships.\n\n"
        "Rules:\n"
        "- Use only the registered operations, policy targets, building ids and organization ids below.\n"
        "- Represent every part of the request you can. Compose several operations for multi-part requests.\n"
        "- The scene_catalog is also supported through catalog_event. For example dinosaurs appearing "
        "is catalog_event with parameters.recipe=dinosaurs, not an unsupported hazard. Use catalog "
        "recipes for their illustrated subjects and listed effects, composing them with other requested "
        "changes. Do not claim a catalog subject is unsupported simply because it is not a physical_hazard.\n"
        "- Catalog props do not become autonomous creatures and cannot chase, attack, eat or destroy. "
        "If those extra behaviors are requested, explain them in unsupported while retaining the "
        "supported appearance and catalog effects. Never invent those behaviors or unrelated hazards.\n"
        "- unsupported contains only parts actually requested by this user. Do not list generic catalog "
        "limitations or actions the user did not request there; put general modeling assumptions in "
        "assumptions. For 'Dinosaurs appear in the town square for 20 ticks', return a ready catalog_event "
        "using recipe dinosaurs and unsupported=[]; autonomous behavior was not requested.\n"
        "- Make your best effort to build a runnable event. When a parameter is unspecified, choose a "
        "reasonable value and record it in assumptions. Default to a 36-tick measurement window and "
        "citywide scope when appropriate. Ask for clarification only when choosing would change the "
        "meaning of the request. Describe any supported approximation explicitly.\n"
        "- Short prompts are sufficient: 'illness' can use catalog_event recipe illness or an "
        "environmental_condition with condition illness; 'dinosaurs' uses catalog_event recipe dinosaurs. "
        "Use defaults for omitted duration, count and location, and describe those defaults consistently.\n"
        "- A '10 pm curfew' uses set_curfew with start_minute 1320 and end_minute 360. "
        "This operation announces the policy and creates clock-based homeward behavior; compliance "
        "depends on personality and institutional trust. Default to 22:00–06:00 when hours are omitted. "
        "Use enabled false to lift a curfew. Safety, rescue and urgent care take precedence. "
        "When no policy duration is given, use permanent duration so the curfew remains in force "
        "through the next night; use a 480-tick measurement window at the default calendar rate. "
        "Do not represent a curfew as announcement-only or invent police or penalties.\n"
        "- Never substitute a different event. Do not add floods, fires, storms, festivals, aid or shortages "
        "unless the user asked for them.\n"
        "- If part of the request cannot be represented, explain it in `unsupported` and represent the rest. "
        'If nothing can be represented, set status to "unsupported" with no operations.\n'
        '- If the request is too ambiguous to represent, set status to "needs_clarification" and ask in '
        "`clarification`.\n"
        '- Relative changes: "doubles" is multiply 2, "halves" is multiply 0.5, "raises by 20%" is multiply 1.2.\n'
        "- Spending money on a public service is modify_policy on that service's funding target; the "
        "treasury pays for it.\n"
        "- Announce official changes with broadcast_information (channel official) unless the request says "
        "they are secret or unannounced. Rumors use channel rumor with accurate false.\n"
        "- public_description is only what residents can directly observe; do not reveal secret changes.\n"
        "- agent_knowledge says which citizens know what at the start.\n"
        f"- Timing is in actual simulation ticks relative to the start of the scenario (one tick is {state.simulation.config.tick_seconds} seconds of town time). Preserve explicit tick counts from the request without rescaling. "
        "duration permanent keeps changes after the measurement window; temporary reverts them.\n"
        "- Choose metrics that measure the consequences the user cares about.\n"
        "- Each operation has type, id, rationale and a parameters object. Put all action arguments in "
        "parameters, using operation_fields, and include every required_parameters field. Omit irrelevant "
        "fields. Use parameter_choices for enumerated arguments. Timing goes in parameters.timing; "
        "audiences in parameters.audience.\n"
        '- Example operation: {"type":"modify_policy","id":"fare","rationale":"Double fares",'
        '"parameters":{"target":"transportation.transit_fare","operation":"multiply","value":2}}.\n'
        "- modify_policy.operation must be set, increase, decrease, multiply or clear. "
        "broadcast_information requires channel, topic and a nonempty message.\n"
        '- Use status "ready" when the plan has operations.\n\n'
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
    progress = []
    try:
        with gateway.event_budget():
            async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
                return await _interpret(gateway, state, sid, prompt, mode, progress)
    except TimeoutError:
        gateway.set_error("timeout")
        gateway.diagnostics["timeouts"] += 1
        gateway.diagnostics["fallbacks"] += 1
        return unavailable(gateway, progress[-1] if progress else 0)


def unavailable(gateway, attempts, previous=None):
    error = gateway.request_error or {}
    category, status = error.get("category"), error.get("http_status")
    messages = {
        "not_configured": "Gemini is not configured. Check its mode, model and project or API key.",
        "budget_exhausted": (
            "This event reached its Gemini planning allowance. "
            "Try a shorter description or increase LLM_EVENT_TOKEN_BUDGET in the backend environment "
            "and restart AgentCity. Background citizen usage does not consume this allowance."
        ),
        "rate_limited": "Gemini's local request limit was reached. Wait a minute, then retry this event.",
        "circuit_open": "Gemini is cooling down after repeated failures. Wait 30 seconds, then retry.",
        "authentication": (
            "Google Cloud authentication failed. Check that GOOGLE_APPLICATION_CREDENTIALS points "
            "to an existing valid file, or configure Application Default Credentials."
        ),
        "connection": "AgentCity could not connect to Gemini. Check the network connection, then retry.",
        "timeout": "Gemini took too long to plan this event. Retry the event or shorten its description.",
        "invalid_response": "Gemini returned an incomplete or invalid plan after correction attempts. Retry the event.",
    }
    message = messages.get(category, "Gemini could not produce a plan. Retry the event.")
    if category == "http":
        message = {
            400: "Gemini rejected the event-generation request (HTTP 400). Check model and structured-output support.",
            401: "Gemini rejected authentication (HTTP 401). Check the configured credentials or API key.",
            403: "Gemini denied access (HTTP 403). Check project permissions, API enablement and billing.",
            404: "The configured Gemini model or endpoint was not found (HTTP 404). Check model and location.",
            429: "Gemini's provider quota was reached (HTTP 429). Wait, check the project quota, then retry.",
        }.get(status, "Gemini is temporarily unavailable. Retry this event shortly.")
    return dict(
        status="unavailable",
        plan=previous,
        errors=[message],
        warnings=[],
        unsupported=[],
        clarification="",
        attempts=attempts,
    )


async def _interpret(gateway, state, sid, prompt, mode, progress):
    if not gateway.config.gemini_enabled:
        return dict(
            status="unavailable",
            plan=None,
            errors=["The AI interpreter is not configured."],
            warnings=[],
            unsupported=[],
            clarification="",
            attempts=0,
        )
    base = build_prompt(state, prompt, mode)
    request = base
    errors, previous = [], None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        progress.append(attempt)
        draft = await gateway.structured(
            sid, request, PlanDraft, max_output_tokens=OUTPUT_TOKENS, timeout=TIMEOUT_SECONDS
        )
        if draft is None:
            if (gateway.request_error or {}).get("category") == "invalid_response" and attempt < MAX_ATTEMPTS:
                request = (
                    base + "\nThe previous response was incomplete or invalid JSON. Return all required "
                    "PlanDraft fields and complete parameters for each operation. Keep the plan concise."
                )
                continue
            return unavailable(gateway, attempt, previous)
        if not draft.operations and (draft.status == "unsupported" or draft.unsupported):
            return dict(
                status="unsupported",
                plan=None,
                errors=[],
                warnings=[],
                unsupported=draft.unsupported or ["No registered operation can represent this scenario."],
                clarification=draft.clarification,
                attempts=attempt,
            )
        if draft.status == "needs_clarification" and not draft.operations:
            return dict(
                status="needs_clarification",
                plan=None,
                errors=[],
                warnings=[],
                unsupported=draft.unsupported,
                clarification=draft.clarification,
                attempts=attempt,
            )
        raw = normalize(draft, prompt)
        plan, errors, warnings = validate_plan(state, raw)
        if plan is not None:
            return dict(
                status="ready",
                plan=plan.model_dump(mode="json"),
                errors=[],
                warnings=warnings,
                unsupported=plan.unsupported,
                clarification="",
                attempts=attempt,
            )
        previous = raw
        request = correction_prompt(base, raw, errors)
    return dict(
        status="invalid",
        plan=previous,
        errors=errors,
        warnings=[],
        unsupported=previous.get("unsupported", []),
        clarification="",
        attempts=MAX_ATTEMPTS,
    )
