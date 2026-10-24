import heapq
import math
from collections import defaultdict

from app.contracts import Vec2


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def polygon_contains(point, polygon):
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (point.x - a.x) * (b.y - a.y) - (point.y - a.y) * (b.x - a.x)
        if (
            abs(cross) < 1e-8
            and min(a.x, b.x) <= point.x <= max(a.x, b.x)
            and min(a.y, b.y) <= point.y <= max(a.y, b.y)
        ):
            return True
        if (a.y > point.y) != (b.y > point.y) and point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x:
            inside = not inside
    return inside


def polygon_area(polygon):
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2


def simple_polygon(polygon):
    if len({(p.x, p.y) for p in polygon}) != len(polygon) or polygon_area(polygon) <= 1e-8:
        return False

    def orient(a, b, c):
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

    def on_segment(a, b, p):
        return (
            abs(orient(a, b, p)) < 1e-9
            and min(a.x, b.x) <= p.x <= max(a.x, b.x)
            and min(a.y, b.y) <= p.y <= max(a.y, b.y)
        )

    edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if (orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0) or any(
                (on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))
            ):
                return False
    return True


def cell_at(map_data, p):
    if not 0 <= p.x < map_data.width_m or not 0 <= p.y < map_data.height_m:
        return None
    return map_data.cells[
        int(p.y // map_data.cell_size_m) * map_data.columns + int(p.x // map_data.cell_size_m)
    ]


def pathfind(map_data, origin, destination, blocked=frozenset()):
    start_cell, end_cell = cell_at(map_data, origin), cell_at(map_data, destination)
    if start_cell is None or end_cell is None or not end_cell.walkable:
        return None
    start, end = (start_cell.col, start_cell.row), (end_cell.col, end_cell.row)
    if end in blocked:
        return None
    queue, costs, parents = [(0, start)], {start: 0}, {}
    while queue:
        _, current = heapq.heappop(queue)
        if current == end:
            route = [end]
            while route[-1] != start:
                route.append(parents[route[-1]])
            route.reverse()
            size = map_data.cell_size_m
            points = [Vec2(x=(col + 0.5) * size, y=(row + 0.5) * size) for col, row in route]
            if distance(origin, points[0]) < 1e-8:
                points = points[1:]
            if not points or distance(points[-1], destination) > 1e-8:
                points.append(destination.model_copy())
            return points
        col, row = current
        for nxt in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1)):
            x, y = nxt
            if not (0 <= x < map_data.columns and 0 <= y < map_data.rows) or nxt in blocked:
                continue
            next_cell = map_data.cells[y * map_data.columns + x]
            if not next_cell.walkable:
                continue
            # Prefer maintained public streets over cutting across lawns. Land
            # remains available for a destination approach or a blocked-road detour.
            cost = costs[current] + (1 if next_cell.terrain == "road" else 4)
            if cost < costs.get(nxt, math.inf):
                costs[nxt], parents[nxt] = cost, current
                heapq.heappush(queue, (cost + abs(x - end[0]) + abs(y - end[1]), nxt))
    return None


def line_of_sight(map_data, a, b):
    steps = max(1, math.ceil(distance(a, b) / (map_data.cell_size_m / 3)))
    for step in range(1, steps):
        t = step / steps
        cell = cell_at(map_data, Vec2(x=a.x + (b.x - a.x) * t, y=a.y + (b.y - a.y) * t))
        if cell is None or (not cell.walkable and cell.terrain != "water"):
            return False
    return True


class SpatialIndex:
    def __init__(self, citizens, size=8):
        self.size = size
        self.buckets = defaultdict(list)
        for citizen in citizens.values():
            if citizen.summary.active:
                p = citizen.summary.position
                self.buckets[(int(p.x // size), int(p.y // size))].append(citizen)

    def nearby(self, position, radius):
        n = math.ceil(radius / self.size)
        x, y = int(position.x // self.size), int(position.y // self.size)
        return [
            c
            for i in range(x - n, x + n + 1)
            for j in range(y - n, y + n + 1)
            for c in self.buckets.get((i, j), [])
            if distance(position, c.summary.position) <= radius
        ]
