import math

import pytest
from test_social_life import city

from app.contracts import Vec2
from app.simulation.game_master import advance_movement
from app.simulation.navigation import (
    PERSONAL_SPACE,
    clear_travel,
    distance,
    meeting_point,
    restore_personal_space,
)


def test_swept_collision_stops_long_steps_and_allows_tangential_or_outward_motion():
    origin, destination, other = Vec2(x=0, y=0), Vec2(x=10, y=0), Vec2(x=5, y=0)
    fraction = clear_travel(origin, destination, [other])
    assert fraction == pytest.approx((5 - PERSONAL_SPACE) / 10, abs=1e-5)
    assert clear_travel(origin, destination, [Vec2(x=5, y=2)]) == 1
    assert clear_travel(origin, Vec2(x=-2, y=0), [Vec2(x=0.5, y=0)]) == 1
    assert clear_travel(origin, destination, [Vec2(x=0.5, y=0)]) == 0


def test_walkers_bypass_people_and_shared_destinations_do_not_overlap(client):
    state = city(client)
    a, b = list(state.citizens.values())[:2]
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
    a.summary.position, b.summary.position = Vec2(x=30, y=33), Vec2(x=35, y=33)
    a.summary.path = [Vec2(x=42, y=33)]
    for _ in range(15):
        advance_movement(state, a)
        assert distance(a.summary.position, b.summary.position) >= PERSONAL_SPACE - 1e-6
        if not a.summary.path:
            break
    assert not a.summary.path
    assert a.summary.position == Vec2(x=42, y=33)
    a.summary.path = [b.summary.position.model_copy()]
    for _ in range(15):
        advance_movement(state, a)
        if not a.summary.path:
            break
    assert not a.summary.path
    assert PERSONAL_SPACE - 1e-6 <= distance(a.summary.position, b.summary.position) <= 2.4


def test_meetings_leave_room_and_old_overlaps_recover(client):
    state = city(client)
    a, b = list(state.citizens.values())[:2]
    a.summary.position = Vec2(x=33, y=33)
    b.summary.position = a.summary.position.model_copy()
    for citizen in state.citizens.values():
        citizen.summary.active = citizen in (a, b)
    restore_personal_space(state)
    assert distance(a.summary.position, b.summary.position) >= PERSONAL_SPACE
    point = meeting_point(state.map, Vec2(x=30, y=33), Vec2(x=35, y=33))
    assert math.isclose(distance(point, Vec2(x=35, y=33)), 2.4)
