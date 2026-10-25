"""Plan validation and compilation into the frozen core event contract.

A plan is rejected with explicit reasons rather than clamped or substituted:
targets must be registered, values in range after every repetition, entities
must exist, and simultaneous operations may not contradict each other.
"""

from pydantic import TypeAdapter, ValidationError

from app.contracts import EventSpec, InformationEffect, ScenarioPreview, Vec2
from app.scenario_engine.registry import OPERATIONS, POLICY_TARGETS, REGIONS, ScenarioPlan
from app.scenario_engine.systems import PolicyState
from app.simulation.navigation import polygon_contains
from app.simulation.scenario_scene import CATALOG, build_scene, matches
from app.simulation.scenarios import compose_recipe_effects, rectangle, validate_spec
from app.simulation.state import expiry
from app.simulation.timing import legacy_ticks

PLAN = TypeAdapter(ScenarioPlan)
MAX_APPLICATIONS = 200
CATALOG_BY_ID = {recipe["id"]: recipe for recipe in CATALOG}


def format_errors(error):
    return [
        f"{'.'.join(str(part) for part in item['loc']) or 'plan'}: {item['msg']}"[:300]
        for item in error.errors()[:20]
    ]


def current_policy(state):
    if state.systems.enabled:
        return state.systems.policy
    policy = PolicyState()
    policy.resource_distribution.ration_units_per_agent = state.policies.ration_units_per_agent
    policy.resource_distribution.aid_multiplier = state.policies.aid_multiplier
    policy.resource_distribution.evacuation_order = float(state.policies.evacuation_order)
    return policy


def window(op, plan):
    """Ticks (relative to activation) during which an operation is in force."""
    timing = op.timing
    every = timing.repeat_every or 0
    last = timing.start_tick + every * (timing.repeat_count or 0)
    duration = timing.duration_ticks or (None if plan.duration == "permanent" else plan.measurement_ticks)
    return timing.start_tick, None if duration is None else last + duration


def overlaps(a, b):
    return a[0] < (b[1] if b[1] is not None else 10**9) and b[0] < (a[1] if a[1] is not None else 10**9)


def physical_components(state, plan):
    """Compile exactly the selected operations; prompt matches only refine a selected recipe's styling."""
    effects, recipes = [], []
    styled = {recipe["id"]: recipe for recipe in matches(plan.prompt)}
    for op in plan.operations:
        if op.type == "physical_hazard":
            additions = [dict(type="hazard", hazard=op.hazard, severity=op.severity)]
            recipes.extend(matches(op.hazard))
        elif op.type == "community_gathering":
            additions = [dict(type="community", activity=op.activity, capacity=state.simulation.agent_count)]
            recipes.extend(matches(op.activity))
        elif op.type == "catalog_event":
            recipe = dict(styled.get(op.recipe, CATALOG_BY_ID[op.recipe]))
            if op.count is not None:
                recipe["count"] = op.count
            if op.color is not None:
                recipe["color"] = op.color
            recipes.append(recipe)
            additions = compose_recipe_effects([recipe], op.severity, state.simulation.agent_count)
        else:
            continue
        for effect in additions:
            if effect not in effects:
                effects.append(effect)
    return effects, recipes


def validate_plan(state, raw):
    """Return (plan, errors, warnings). `plan` is None when it cannot be committed."""
    try:
        plan = PLAN.validate_python(raw)
    except ValidationError as error:
        return None, format_errors(error), []
    errors, warnings = [], []
    seen = set()
    for index, op in enumerate(plan.operations):
        if op.id in seen or op.id == "op":
            op.id = f"op{index + 1}"
        seen.add(op.id)
    buildings = {b.id: b for b in state.map.buildings}
    organizations = state.systems.organizations
    policy = current_policy(state)
    applications = 0
    policy_windows = {}
    service_windows = {}
    physical = []
    for op in plan.operations:
        where = f"{op.id} ({op.type})"
        timing = op.timing
        if (timing.repeat_every is None) != (timing.repeat_count is None):
            errors.append(f"{where}: repeat_every and repeat_count must be given together")
        if timing.start_tick >= plan.measurement_ticks:
            errors.append(
                f"{where}: starts at tick {timing.start_tick}, after the {plan.measurement_ticks}-tick measurement window"
            )
        repetitions = 1 + (timing.repeat_count or 0)
        applications += repetitions
        audience = getattr(op, "audience", None)
        if audience is not None:
            if audience.kind == "region" and audience.region is None:
                errors.append(f"{where}: a region audience needs a region")
            if audience.kind == "organization_members":
                org = organizations.get(audience.organization_id or "")
                if org is None or not org.active:
                    errors.append(f"{where}: organization {audience.organization_id} does not exist")
        if op.type == "modify_policy":
            low, high, unit_name, nullable, _, _ = POLICY_TARGETS[op.target]
            if op.operation == "clear":
                if not nullable:
                    errors.append(f"{where}: {op.target} cannot be cleared")
            elif op.value is None:
                errors.append(f"{where}: {op.operation} needs a value")
            else:
                value = policy.get(op.target)
                base = value if value is not None else (high if op.target == "housing.rent_cap" else low)
                for _ in range(repetitions):
                    base = {
                        "set": op.value,
                        "increase": base + op.value,
                        "decrease": base - op.value,
                        "multiply": base * op.value,
                    }[op.operation]
                    if not low - 1e-9 <= base <= high + 1e-9:
                        errors.append(
                            f"{where}: {op.target} would become {base:g} {unit_name}; allowed range is {low:g} to {high:g}"
                        )
                        break
                if op.target == "resource_distribution.evacuation_order" and base not in (0, 1):
                    errors.append(f"{where}: the evacuation order must be 0 or 1")
            span = window(op, plan)
            for other in policy_windows.get(op.target, []):
                if (
                    overlaps(span, window(other, plan))
                    and "set" in {op.operation, other.operation}
                    and op.timing.start_tick == other.timing.start_tick
                ):
                    errors.append(
                        f"{where}: conflicts with {other.id}, which changes {op.target} at the same time"
                    )
            policy_windows.setdefault(op.target, []).append(op)
        elif op.type == "set_service_availability":
            if (op.building_id is None) == (op.building_kind is None):
                errors.append(f"{where}: give exactly one of building_id or building_kind")
                continue
            if op.building_id is not None:
                building = buildings.get(op.building_id)
                if building is None:
                    errors.append(f"{where}: building {op.building_id} does not exist")
                    continue
                targets = [building]
            else:
                targets = [
                    b
                    for b in state.map.buildings
                    if b.kind == op.building_kind
                    and (op.region == "citywide" or polygon_contains(b.entrance, region_polygon(op.region)))
                ]
                if not targets:
                    errors.append(f"{where}: there is no {op.building_kind} in the {op.region} region")
            if any(b.kind == "home" for b in targets) and not op.open:
                errors.append(f"{where}: homes cannot be closed; use modify_housing_supply to change housing")
            for building in targets:
                for other in service_windows.get(building.id, []):
                    if other.open != op.open and overlaps(window(op, plan), window(other, plan)):
                        errors.append(
                            f"{where}: opens and closes {building.name} at the same time as {other.id}"
                        )
                service_windows.setdefault(building.id, []).append(op)
            if not op.open and targets and all(b.kind == "hospital" for b in targets):
                if len(targets) == sum(b.kind == "hospital" for b in state.map.buildings):
                    warnings.append(f"{where}: this closes every hospital in the city")
        elif op.type == "remove_organization":
            org = organizations.get(op.organization_id)
            if org is None or not org.active:
                errors.append(f"{where}: organization {op.organization_id} does not exist")
        elif OPERATIONS[op.type][2]:
            physical.append(op)
            if op.type == "catalog_event":
                effect_types = ", ".join(
                    dict.fromkeys(e["type"] for e in CATALOG_BY_ID[op.recipe]["effects"])
                )
                warnings.append(
                    f"{where}: {op.recipe.replace('_', ' ')} uses illustrated scenery and these catalog effects: "
                    f"{effect_types}. Props are not autonomous entities and cannot chase, attack or destroy."
                )
        elif op.type == "adjust_population_traits":
            warnings.append(
                f"{where}: edits the {op.trait} trait directly. This changes who citizens are, "
                "not the conditions they live in."
            )
    if applications > MAX_APPLICATIONS:
        errors.append(f"plan: {applications} scheduled applications exceed the limit of {MAX_APPLICATIONS}")
    if len(physical_components(state, plan)[0]) > 19:
        errors.append(
            "plan: the selected operations exceed the 19-effect event limit; split the event into smaller plans"
        )
    if len({op.region for op in physical}) > 1:
        errors.append("plan: physical hazards and gatherings in one scenario must share a single region")
    for op in physical:
        if op.timing.start_tick or op.timing.repeat_every:
            errors.append(
                f"{op.id} ({op.type}): physical events start when the scenario starts and do not repeat"
            )
        if op.timing.duration_ticks and op.timing.duration_ticks != plan.measurement_ticks:
            warnings.append(
                f"{op.id} ({op.type}): physical events last the whole {plan.measurement_ticks}-tick scenario window"
            )
    changes = [op for op in plan.operations if op.type == "modify_policy"]
    if changes and not any(op.type == "broadcast_information" for op in plan.operations):
        warnings.append(
            "No announcement is included, so citizens learn about policy changes only by experiencing them "
            "(for example when they pay a new fare)."
        )
    if plan.unsupported:
        warnings.extend(f"Not simulated: {item}" for item in plan.unsupported)
    return (None if errors else plan), errors, warnings


def region_polygon(region):
    return rectangle(*REGIONS[region])


def compile_preview(state, plan, warnings, source="custom"):
    """A core preview whose event carries the physical effects; the engine runs the rest."""
    physical = [op for op in plan.operations if OPERATIONS[op.type][2]]
    region = physical[0].region if physical else "citywide"
    polygon = region_polygon(region)
    effects, recipes = physical_components(state, plan)
    effects.append(
        InformationEffect(
            type="information",
            message=plan.public_description,
            reliability=25 if any(recipe["id"] == "misinformation" for recipe in recipes) else 100,
            delivery="local",
        )
    )
    gatherings = [op for op in physical if op.type == "community_gathering"]
    hazard_effects = [effect for effect in effects if isinstance(effect, dict) and effect["type"] == "hazard"]
    kind = (
        hazard_effects[0]["hazard"]
        if hazard_effects
        else "festival"
        if any(op.activity == "festival" for op in gatherings)
        else "policy"
        if any(op.type == "modify_policy" for op in plan.operations)
        else recipes[0]["kind"]
        if recipes
        else "custom"
    )
    spec = EventSpec(
        title=plan.title,
        description=plan.description,
        kind=kind,
        origin=Vec2(x=sum(p.x for p in polygon) / len(polygon), y=sum(p.y for p in polygon) / len(polygon)),
        affected_polygon=polygon,
        severity=max([effect["severity"] for effect in hazard_effects], default=50),
        duration_ticks=legacy_ticks(state, plan.measurement_ticks),
        effects=effects,
        success_condition="duration_elapsed",
    )
    if recipes:
        spec.scene = build_scene(state, spec, recipes)
    validate_spec(state, spec)
    return ScenarioPreview(
        id=state.next_id("preview"),
        simulation_id=state.simulation.id,
        source=source,
        source_event_id=None,
        based_on=state.ref(),
        expires_at=expiry(),
        interpretation=(
            f"{plan.description} Citizens respond in their own way over {legacy_ticks(state, plan.measurement_ticks)} ticks."
        )[:2000],
        spec=spec,
        affected_agent_ids=[
            a for a, c in state.citizens.items() if polygon_contains(c.summary.position, polygon)
        ],
        affected_building_ids=[b.id for b in state.map.buildings if polygon_contains(b.entrance, polygon)],
        warnings=[w[:2000] for w in warnings],
        unsupported_requests=[u[:2000] for u in plan.unsupported],
        can_commit=True,
    )


def summary(state):
    """Compact world state for the interpreter: ids it may target and current values."""
    policy = current_policy(state)
    kinds = {}
    for b in state.map.buildings:
        kinds.setdefault(b.kind, []).append(b)
    return dict(
        tick=state.simulation.tick,
        population=sum(c.summary.active for c in state.citizens.values()),
        policies={target: policy.get(target) for target in POLICY_TARGETS},
        treasury=round(state.systems.treasury, 2) if state.systems.enabled else 60,
        buildings={
            kind: [dict(id=b.id, name=b.name, functional=b.functional) for b in items][:12]
            for kind, items in kinds.items()
            if kind != "home"
        },
        home_count=len(kinds.get("home", [])),
        organizations=[
            dict(id=o.id, kind=o.kind, name=o.name, members=len(o.members))
            for o in state.systems.organizations.values()
            if o.active
        ],
        regions=list(REGIONS),
        active_events=[
            r.summary.title for r in state.events.values() if r.summary.status in {"queued", "active"}
        ],
    )
