"""Calendar time is deliberately independent of physical simulation seconds."""

DAY = 86400
HOUR = 3600
VERSION = "3.0.0"


def now(state):
    return state.simulation.calendar_time_seconds


def hours_per_tick(state):
    return state.simulation.config.calendar_seconds_per_tick / HOUR


def in_window(minute, start, end):
    if start == end:
        return False
    return start <= minute < end if start < end else minute >= start or minute < end


def phase(seconds):
    hour = seconds % DAY / HOUR
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 19:
        return "day"
    if 19 <= hour < 21:
        return "dusk"
    return "night"


def clock_label(seconds):
    return f"{int(seconds // HOUR) % 24:02d}:{int(seconds // 60) % 60:02d}"


def advance(state):
    if state.calendar_rules_version != VERSION:
        from app.behavior.vitals import emit

        state.calendar_rules_version = VERSION
        state.calendar_activated_tick = state.simulation.tick
        state.rule_version = VERSION
        emit(
            state,
            "calendar_rules_activated",
            None,
            description="Daily calendar rules 3.0.0; physical timing retained",
        )
    state.simulation.calendar_time_seconds += state.simulation.config.calendar_seconds_per_tick


def effective_curfew(state):
    from app.contracts import CurfewPolicy

    policy = next(reversed(state.curfew_controls.values()), CurfewPolicy())
    return policy.model_copy(update={"revision": state.curfew_revision})
