"""Doorway routes and persistent, capacity-limited indoor visits."""

import math
from functools import lru_cache

from app.contracts import Vec2
from app.simulation.indexes import buildings_by_id
from app.simulation.navigation import (
    PERSONAL_SPACE,
    cell_at,
    cell_at_xy,
    crowded_cells,
    distance,
    pathfind,
    polygon_contains,
    polygon_contains_xy,
)
from app.simulation.timing import legacy_ticks


def doorway(building):
    closest, best = building.footprint[0], math.inf
    for a, b in zip(building.footprint, building.footprint[1:] + building.footprint[:1]):
        dx, dy = b.x - a.x, b.y - a.y
        t = max(
            0,
            min(
                1, ((building.entrance.x - a.x) * dx + (building.entrance.y - a.y) * dy) / (dx * dx + dy * dy)
            ),
        )
        point = Vec2(x=a.x + dx * t, y=a.y + dy * t)
        if distance(point, building.entrance) < best:
            closest, best = point, distance(point, building.entrance)
    return closest.model_copy()


def interior_slot(state, citizen, building):
    reserved = [
        c
        for c in state.citizens.values()
        if c is not citizen
        and c.summary.active
        and building.id in {c.inside_building_id, c.entering_building_id}
    ]
    hospital = state.behavior.hospitals.get(building.id)
    represented_helpers = {c.summary.id for c in reserved} | {citizen.summary.id}
    bookings = (
        sum(helper_id not in represented_helpers for helper_id in hospital.reservations.values())
        if hospital
        else 0
    )
    if not building.functional or len(reserved) + bookings >= building.capacity:
        return None
    occupied = [
        c.summary.path[-1] if c.entering_building_id == building.id and c.summary.path else c.summary.position
        for c in reserved
    ]
    candidates = interior_candidates(
        tuple((p.x, p.y) for p in building.footprint),
        (building.entrance.x, building.entrance.y),
    )
    point = next(
        (p for p in candidates if all(distance(p, other) >= PERSONAL_SPACE for other in occupied)),
        None,
    )
    return point.model_copy() if point is not None else None


@lru_cache(maxsize=256)
def interior_candidates(footprint, entrance):
    """Facility geometry is static; reserve seats against current occupancy only."""
    polygon = [Vec2(x=x, y=y) for x, y in footprint]
    door = Vec2(x=entrance[0], y=entrance[1])
    closest, best = polygon[0], math.inf
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b.x - a.x, b.y - a.y
        t = max(0, min(1, ((door.x - a.x) * dx + (door.y - a.y) * dy) / (dx * dx + dy * dy)))
        point = Vec2(x=a.x + dx * t, y=a.y + dy * t)
        length = distance(point, door)
        if length < best:
            closest, best = point, length
    xs, ys = [p.x for p in polygon], [p.y for p in polygon]
    candidates = []
    x = min(xs) + 0.8
    while x <= max(xs) - 0.8 + 1e-6:
        y = min(ys) + 0.8
        while y <= max(ys) - 0.8 + 1e-6:
            point = Vec2(x=x, y=y)
            if polygon_contains(point, polygon):
                candidates.append(point)
            y += PERSONAL_SPACE + 0.05
        x += PERSONAL_SPACE + 0.05
    return tuple(sorted(candidates, key=lambda p: distance(p, closest), reverse=True))


def trip_route(state, citizen, destination, building=None, blocked=frozenset()):
    current = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
    start = current.entrance if current else citizen.summary.position
    crowd = crowded_cells(
        state.map,
        [c.summary.position for c in state.citizens.values() if c is not citizen and c.summary.active],
    )
    # A shared doorway/resource is approached from personal space. Its endpoint
    # cell must remain reachable, as must the cell the walker is already in.
    for point in (start, destination):
        cell = cell_at(state.map, point)
        if cell:
            crowd.discard((cell.col, cell.row))
    route = pathfind(state.map, start, destination, blocked | crowd)
    if route is None:
        # A crowded start/end can fill all four grid neighbors even when a
        # continuous sidestep exists. The local swept detour handles that case.
        route = pathfind(state.map, start, destination, blocked)
    if route is None:
        return None
    if current:
        route = [doorway(current), current.entrance.model_copy(), *route]
    if building:
        slot = interior_slot(state, citizen, building)
        if slot is None:
            return None
        route.extend([doorway(building), slot])
    return route


def walkable_segment(state, citizen, origin, destination, blocked=frozenset()):
    """Detours stay in a room or on outdoor ground; door legs remain explicit."""
    allowed = {citizen.inside_building_id, citizen.entering_building_id, citizen.leaving_building_id} - {None}
    buildings = buildings_by_id(state) if allowed else {}
    room = next(
        (
            b
            for b in (buildings[key] for key in allowed if key in buildings)
            if polygon_contains(origin, b.footprint) and polygon_contains(destination, b.footprint)
        ),
        None,
    )
    steps = max(1, math.ceil(distance(origin, destination) / (state.map.cell_size_m / 3)))
    for step in range(1, steps + 1):
        t = step / steps
        x = origin.x + (destination.x - origin.x) * t
        y = origin.y + (destination.y - origin.y) * t
        cell = cell_at_xy(state.map, x, y)
        if (
            cell is None
            or (cell.col, cell.row) in blocked
            or not (polygon_contains_xy(x, y, room.footprint) if room else cell.walkable)
        ):
            return False
    return True


def sync_building_location(state, citizen):
    allowed = {citizen.inside_building_id, citizen.entering_building_id, citizen.leaving_building_id} - {None}
    buildings = buildings_by_id(state) if allowed else {}
    inside = next(
        (
            b
            for b in (buildings[key] for key in allowed if key in buildings)
            if polygon_contains(citizen.summary.position, b.footprint)
        ),
        None,
    )
    citizen.inside_building_id = inside.id if inside else None
    if not citizen.summary.path:
        if inside and citizen.entering_building_id == inside.id:
            citizen.visit_until_tick = state.simulation.tick + legacy_ticks(
                state, 6 if inside.kind == "home" else 4
            )
            from app.simulation import calendar
            from app.simulation.daily import set_activity

            if citizen.summary.routine_state not in {"returning_home", "seeking_shelter"}:
                duration = 90 * 60 if inside.kind == "work" else 60 * 60
                set_activity(citizen, "visiting", calendar.now(state) + duration, inside.id)
            citizen.last_building_id = inside.id
        citizen.entering_building_id = None
        citizen.leaving_building_id = None


def same_room(a, b):
    return a.inside_building_id == b.inside_building_id


def interior_capacity(building):
    """Available floor positions, bounded by the declared capacity."""
    xs, ys = [p.x for p in building.footprint], [p.y for p in building.footprint]
    count = 0
    x = min(xs) + 0.8
    while x <= max(xs) - 0.8 + 1e-6:
        y = min(ys) + 0.8
        while y <= max(ys) - 0.8 + 1e-6:
            count += polygon_contains(Vec2(x=x, y=y), building.footprint)
            y += PERSONAL_SPACE + 0.05
        x += PERSONAL_SPACE + 0.05
    return min(building.capacity, count)
