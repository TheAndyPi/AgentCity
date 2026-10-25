"""Convert simulated durations to ticks without changing legacy save timing."""

import math


def ticks_for(state_or_config, seconds):
    config = getattr(getattr(state_or_config, "simulation", None), "config", state_or_config)
    return max(1, math.ceil(seconds / config.tick_seconds))


def legacy_ticks(state_or_config, count):
    return ticks_for(state_or_config, count * 10)
