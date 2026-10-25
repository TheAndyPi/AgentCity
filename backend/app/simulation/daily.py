"""Persistent daily commitments shared by rules and model-driven citizens."""

import math

from app.simulation import calendar
from app.simulation.building_visits import interior_slot, trip_route
from app.simulation.navigation import distance, pathfind
from app.simulation.timing import legacy_ticks

RATES = {
    "awake_fullness": 4,
    "sleep_fullness": 2,
    "awake_energy": 4,
    "sleep_energy": 10,
    "rest_energy": 8,
    "awake_social": 3,
    "conversation_social": 12,
    "rest_mental": 1,
    "rest_stress": -2,
}


def home_building(state, citizen):
    agent = state.systems.agents.get(citizen.summary.id)
    home_id = agent.home_id if agent else citizen.home_building_id
    homes = [b for b in state.map.buildings if b.kind == "home"]
    return next((b for b in homes if b.id == home_id), None) or min(
        homes, key=lambda b: (distance(citizen.home, b.entrance), b.id), default=None
    )


def set_activity(citizen, activity, until=0, target=None):
    if citizen.summary.routine_state != activity or citizen.routine_target_id != target:
        citizen.task_generation += 1
    citizen.summary.routine_state = activity
    citizen.routine_target_id = target
    citizen.routine_until = until
    citizen.summary.activity_until_calendar_seconds = until or None


def travel_estimate(state, citizen):
    """Cache a conservative homeward trip estimate once per day and location target."""
    home = home_building(state, citizen)
    if not home or citizen.inside_building_id == home.id:
        return 0
    key = f"{int(calendar.now(state) // calendar.DAY)}:{home.id}:{citizen.last_building_id}"
    if key != citizen.homeward_estimate_key:
        from app.simulation.scenarios import blocked_cells

        current = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
        start = current.entrance if current else citizen.summary.position
        route = pathfind(state.map, start, home.entrance, blocked_cells(state))
        points = [start, *(route or [])]
        meters = sum(distance(a, b) for a, b in zip(points, points[1:])) + 8
        physical = meters / max(0.1, citizen.summary.movement_speed_mps)
        citizen.homeward_estimate_seconds = (
            physical
            / state.simulation.config.tick_seconds
            * state.simulation.config.calendar_seconds_per_tick
        )
        citizen.homeward_estimate_key = key
    return citizen.homeward_estimate_seconds


def curfew_window(state, citizen):
    """Return the current/upcoming known curfew window and a stable nightly choice."""
    policy = calendar.effective_curfew(state)
    if not policy.enabled or citizen.summary.id not in policy.informed_agent_ids:
        return None
    time = calendar.now(state)
    start = int(time // calendar.DAY) * calendar.DAY + policy.start_minute * 60
    duration = (policy.end_minute - policy.start_minute) % 1440 * 60
    if time >= start + duration:
        start += calendar.DAY
    elif start > time and start - calendar.DAY + duration > time:
        start -= calendar.DAY
    end = start + duration
    key = f"{policy.revision}:{int(start // calendar.DAY)}"
    if time < start - max(calendar.HOUR, travel_estimate(state, citizen) + 1800):
        return None
    if citizen.curfew_choice_key != key:
        from app.scenario_engine.systems import unit
        from app.scenario_engine.world import decide

        agent = state.systems.agents.get(citizen.summary.id)
        traits = citizen.profile.traits
        trust = agent.institutional_trust if agent else traits.trust
        probability = max(
            0.1,
            min(
                0.95,
                0.6
                + 0.002 * (traits.cooperation - 50)
                + 0.003 * (trust - 50)
                - 0.002 * (traits.risk_tolerance - 50),
            ),
        )
        comply = unit(state.simulation.config.seed, citizen.summary.id, key, "curfew") < probability
        action, _ = decide(
            state,
            citizen,
            "Considered the announced curfew",
            [
                dict(action="comply", label="Head indoors before curfew", score=float(comply)),
                dict(action="ignore", label="Keep my own evening plans", score=float(not comply)),
            ],
            observations=[
                f"Known curfew {calendar.clock_label(start)}–{calendar.clock_label(end)}",
                f"Cooperation {traits.cooperation:g}, institutional trust {trust:g}, risk tolerance {traits.risk_tolerance:g}",
            ],
            memory="I considered tonight's curfew and chose to {choice}.",
        )
        citizen.curfew_choice_key = key
        citizen.curfew_complies = action == "comply"
        citizen.task_generation += 1
    return (start, end) if citizen.curfew_complies else None


def can_start_conversation(state, citizen):
    window = curfew_window(state, citizen)
    return window is None or calendar.now(state) + calendar.HOUR < window[0]


def night_window(state, citizen):
    time = calendar.now(state)
    day = int(time // calendar.DAY) * calendar.DAY
    if time % calendar.DAY < 6 * calendar.HOUR:
        day -= calendar.DAY
    traits = citizen.profile.traits
    offset = (traits.sociability + traits.risk_tolerance - 100) * 18
    bedtime = day + 22 * calendar.HOUR + offset
    departure = min(day + 21 * calendar.HOUR + offset, bedtime - travel_estimate(state, citizen) - 1800)
    return departure, bedtime, day + 30 * calendar.HOUR


def emergency(state, citizen):
    from app.simulation.agents import hazard_severity

    return bool(
        hazard_severity(state, citizen.summary.position)
        or state.policies.evacuation_order
        or citizen.condition.care != "none"
        or citizen.condition.patient_id
    )


def commitment_intent(state, citizen, context=None):
    """(intent, handled): handled with None means continue an existing physical path."""
    from app.behavior.learning import rest_reason, threshold
    from app.behavior.vitals import conscious
    from app.simulation.game_master import make_intent
    from app.simulation.interactions import conversation_intent

    if not conscious(citizen) or emergency(state, citizen):
        return None, False
    conversation, busy = conversation_intent(state, citizen, context)
    if busy:
        return conversation, True
    time = calendar.now(state)
    hour = time % calendar.DAY / calendar.HOUR
    meal = next((i for i, at in enumerate((7, 13, 19)) if at <= hour < at + 2), None)
    slot = int(time // calendar.DAY) * 3 + meal if meal is not None else -1
    due_meal = meal is not None and citizen.last_meal_slot != slot
    if citizen.needs.hunger >= 70 or (due_meal and citizen.needs.hunger > 20):
        for kind in ("food", "water"):
            amount = min(
                3, math.ceil(max(0, citizen.needs.hunger - 20) / 12), getattr(citizen.inventory, kind)
            )
            if amount > 0:
                if due_meal:
                    citizen.last_meal_slot = slot
                return make_intent(
                    "consume", kind=kind, amount=amount, motivation="Eat a meal before continuing my day"
                ), True
    elif due_meal:
        citizen.last_meal_slot = slot
    if citizen.needs.hunger > 80 and citizen.inventory.food + citizen.inventory.water <= 0:
        set_activity(citizen, "free")
        return None, False
    if state.simulation.tick < citizen.routine_retry_tick:
        return make_intent("rest", motivation="My route is blocked; pause safely before trying again"), True
    departure, bedtime, wake = night_window(state, citizen)
    window = curfew_window(state, citizen)
    curfew_due = bool(window and time >= window[0] - travel_estimate(state, citizen) - 1800)
    nighttime = departure <= time < wake
    if citizen.nap and citizen.needs.fatigue <= 45:
        citizen.nap = False
    if 100 - citizen.needs.fatigue <= threshold(citizen):
        citizen.nap = True
    if not (nighttime or curfew_due or citizen.nap):
        if citizen.summary.routine_state in {
            "sleeping",
            "returning_home",
            "seeking_shelter",
            "resting",
            "talking",
        }:
            set_activity(citizen, "free")
        if (
            citizen.summary.routine_state == "visiting"
            and citizen.routine_until > time
            and citizen.inside_building_id == citizen.routine_target_id
        ):
            building = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
            if building and building.functional:
                action = (
                    "work"
                    if building.kind == "work" and citizen.inventory.supplies < citizen.target_inventory_units
                    else "rest"
                    if building.kind == "home"
                    else "idle"
                )
                return make_intent(
                    action,
                    target=building.id,
                    motivation=f"Spend time at {building.name} before my next activity",
                ), True
        return None, False
    until = max(wake if nighttime else 0, window[1] if curfew_due else 0)
    home = home_building(state, citizen)
    from app.simulation.agents import hazard_severity

    inside = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
    if (
        inside
        and inside.functional
        and not hazard_severity(state, inside.entrance)
        and (inside == home or inside.kind == "shelter")
    ):
        sleeping = nighttime and time >= bedtime or curfew_due and hour >= 22 or hour < 6
        set_activity(citizen, "sleeping" if sleeping else "resting", until, inside.id)
        citizen.summary.path = []
        citizen.plan = None
        return make_intent(
            "rest",
            target=inside.id,
            motivation="Sleep until morning"
            if sleeping
            else rest_reason(citizen, "Rest at home until my next activity"),
        ), True
    if citizen.summary.path and citizen.summary.routine_state in {"returning_home", "seeking_shelter"}:
        target = next((b for b in state.map.buildings if b.id == citizen.routine_target_id), None)
        if target and target.functional and not hazard_severity(state, target.entrance):
            return None, True
        citizen.summary.path = []
    if state.simulation.tick < citizen.routine_retry_tick:
        return make_intent(
            "rest", motivation="My safe homeward route is unavailable; rest here before trying again"
        ), True
    candidates = ([home] if home else []) + sorted(
        [b for b in state.map.buildings if b.kind == "shelter" and b.id in citizen.known_locations],
        key=lambda b: distance(citizen.summary.position, b.entrance),
    )
    from app.simulation.scenarios import blocked_cells

    for building in candidates:
        if (
            not building.functional
            or hazard_severity(state, building.entrance)
            or interior_slot(state, citizen, building) is None
        ):
            continue
        if trip_route(state, citizen, building.entrance, building, blocked_cells(state)) is None:
            continue
        citizen.plan = None
        set_activity(citizen, "returning_home" if building == home else "seeking_shelter", until, building.id)
        return make_intent(
            "move",
            target=building.id,
            destination=building.entrance,
            motivation=rest_reason(
                citizen,
                "Head home before curfew"
                if curfew_due
                else "Head home for the night"
                if nighttime
                else "Head home to recover my energy",
            )
            if building == home
            else "My home is unavailable; seek a known safe shelter",
        ), True
    citizen.summary.path = []
    citizen.plan = None
    set_activity(citizen, "seeking_shelter", until)
    citizen.routine_retry_tick = state.simulation.tick + legacy_ticks(state, 10)
    return make_intent(
        "rest", motivation="No reachable home or shelter has room; rest safely and retry soon"
    ), True


def decay(state, citizen):
    from app.behavior.vitals import impact

    hours = calendar.hours_per_tick(state)
    asleep = citizen.summary.routine_state == "sleeping" and citizen.summary.action == "rest"
    impact(
        state,
        citizen,
        "fullness",
        -RATES["sleep_fullness" if asleep else "awake_fullness"] * hours,
        "Daily nutrition",
        "base_decay",
    )
    if not asleep:
        impact(state, citizen, "energy", -RATES["awake_energy"] * hours, "Daily wakefulness", "base_decay")
        impact(state, citizen, "social", -RATES["awake_social"] * hours, "Daily isolation", "base_decay")


def model_available(state, citizen):
    from app.simulation.interactions import active_conversation

    session = active_conversation(state, citizen)
    if session:
        lines = state.dialogue_index().by_interaction.get(session.id, [])
        return bool(
            lines
            and lines[-1].speaker_id != citizen.summary.id
            and session.next_turn_calendar_seconds is not None
            and calendar.now(state) >= session.next_turn_calendar_seconds
        )
    return citizen.summary.routine_state not in {
        "sleeping",
        "resting",
        "returning_home",
        "seeking_shelter",
    } and not (citizen.summary.routine_state == "visiting" and citizen.routine_until > calendar.now(state))


def context(state, citizen):
    from app.simulation.interactions import active_conversation

    session = active_conversation(state, citizen)
    policy = calendar.effective_curfew(state)
    return dict(
        calendar_time_seconds=calendar.now(state),
        phase=calendar.phase(calendar.now(state)),
        activity=citizen.summary.routine_state,
        activity_until=citizen.routine_until,
        homeward_travel_seconds=round(travel_estimate(state, citizen)),
        known_curfew=policy.model_dump(exclude={"informed_agent_ids"})
        if citizen.summary.id in policy.informed_agent_ids
        else None,
        conversation=None
        if not session
        else dict(
            id=session.id,
            status=session.status,
            minimum_end=session.minimum_end_calendar_seconds,
            next_turn=session.next_turn_calendar_seconds,
            turns=session.turns,
        ),
    )
