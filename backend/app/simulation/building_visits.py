"""Doorway routes and persistent, capacity-limited indoor visits."""

import math

from app.contracts import Vec2
from app.simulation.navigation import PERSONAL_SPACE, distance, pathfind, polygon_contains


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
    if not building.functional or len(reserved) >= building.capacity:
        return None
    occupied = [
        c.summary.path[-1] if c.entering_building_id == building.id and c.summary.path else c.summary.position
        for c in reserved
    ]
    xs, ys = [p.x for p in building.footprint], [p.y for p in building.footprint]
    # Reserve physical seats as well as the facility's declared capacity.
    candidates = []
    x = min(xs) + 0.8
    while x <= max(xs) - 0.8 + 1e-6:
        y = min(ys) + 0.8
        while y <= max(ys) - 0.8 + 1e-6:
            point = Vec2(x=x, y=y)
            if polygon_contains(point, building.footprint):
                candidates.append(point)
            y += PERSONAL_SPACE + 0.05
        x += PERSONAL_SPACE + 0.05
    return next(
        (
            p
            for p in sorted(candidates, key=lambda p: distance(p, doorway(building)), reverse=True)
            if all(distance(p, other) >= PERSONAL_SPACE for other in occupied)
        ),
        None,
    )


def trip_route(state, citizen, destination, building=None, blocked=frozenset()):
    current = next((b for b in state.map.buildings if b.id == citizen.inside_building_id), None)
    start = current.entrance if current else citizen.summary.position
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


def sync_building_location(state, citizen):
    allowed = {citizen.inside_building_id, citizen.entering_building_id, citizen.leaving_building_id}
    inside = next(
        (
            b
            for b in state.map.buildings
            if b.id in allowed and polygon_contains(citizen.summary.position, b.footprint)
        ),
        None,
    )
    citizen.inside_building_id = inside.id if inside else None
    if not citizen.summary.path:
        if inside and citizen.entering_building_id == inside.id:
            citizen.visit_until_tick = state.simulation.tick + (6 if inside.kind == "home" else 4)
            citizen.last_building_id = inside.id
        citizen.entering_building_id = None
        citizen.leaving_building_id = None


def same_room(a, b):
    return a.inside_building_id == b.inside_building_id
