"""One clipped convex envelope and one local exposure function for every consumer."""

import math

from app.contracts import Vec2
from app.infrastructure.errors import require
from app.simulation.navigation import distance, polygon_contains, simple_polygon


def clip(poly, width, height):
    for axis, edge, keep_low in (("x", 0, False), ("x", width, True), ("y", 0, False), ("y", height, True)):
        result = []
        for a, b in zip(poly, poly[1:] + poly[:1]):
            av, bv = getattr(a, axis), getattr(b, axis)
            ai, bi = (av <= edge, bv <= edge) if keep_low else (av >= edge, bv >= edge)
            if ai:
                result.append(a)
            if ai != bi:
                t = (edge - av) / (bv - av)
                result.append(Vec2(x=a.x + t * (b.x - a.x), y=a.y + t * (b.y - a.y)))
        poly = result
        if not poly:
            return []
    # Canonical map-meter coordinates avoid platform-specific trig noise and
    # tiny clipping overshoots being rejected by the strict core map boundary.
    poly = [Vec2(x=min(width, max(0, round(p.x, 9))), y=min(height, max(0, round(p.y, 9)))) for p in poly]
    unique = []
    for p in poly:
        if not unique or distance(p, unique[-1]) > 1e-7:
            unique.append(p)
    if len(unique) > 1 and distance(unique[0], unique[-1]) < 1e-7:
        unique.pop()
    return unique


def hull(points):
    points = sorted(set((p.x, p.y) for p in points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [Vec2(x=x, y=y) for x, y in lower[:-1] + upper[:-1]]


def circle(center, radius):
    return [
        Vec2(
            x=center.x + radius * math.cos(i * math.tau / 48),
            y=center.y + radius * math.sin(i * math.tau / 48),
        )
        for i in range(48)
    ]


def envelope(params, map_data, current=None):
    maximum = math.hypot(map_data.width_m, map_data.height_m)
    require(
        map_data.cell_size_m <= params.extent_m <= maximum,
        "INVALID_REQUEST",
        f"Extent must be {map_data.cell_size_m}..{maximum:.3f} map meters",
        400,
    )
    require(
        0 <= params.origin.x <= map_data.width_m and 0 <= params.origin.y <= map_data.height_m,
        "INVALID_REQUEST",
        "Origin must be inside the map",
        400,
    )
    radius = params.extent_m / (2 if params.kind == "tornado" else 1)
    points = circle(current or params.origin, radius)
    if params.track_end and current is None:
        require(
            -maximum <= params.track_end.x <= map_data.width_m + maximum
            and -maximum <= params.track_end.y <= map_data.height_m + maximum,
            "INVALID_REQUEST",
            "Track end exceeds map-diagonal margin",
            400,
        )
        require(
            distance(params.origin, params.track_end) <= maximum,
            "INVALID_REQUEST",
            "Track length exceeds map diagonal",
            400,
        )
        points = hull(points + circle(params.track_end, radius))
    result = clip(points, map_data.width_m, map_data.height_m)
    require(simple_polygon(result), "INVALID_REQUEST", "Empty or invalid clipped footprint", 400)
    return result


def center_at(params, elapsed_ticks):
    if not params.track_end:
        return params.origin
    progress = max(0, min(1, elapsed_ticks / max(1, params.duration_ticks - 1)))
    return Vec2(
        x=params.origin.x + (params.track_end.x - params.origin.x) * progress,
        y=params.origin.y + (params.track_end.y - params.origin.y) * progress,
    )


def exposure(params, point, elapsed_ticks, polygon):
    if not polygon_contains(point, polygon):
        return 0.0
    center = center_at(params, elapsed_ticks)
    d = distance(point, center)
    radius = params.extent_m / (2 if params.kind == "tornado" else 1)
    if params.kind == "tornado":
        profile = max(0, 1 - d / radius)
    elif params.kind == "earthquake":
        # Attenuation length is fixed at 24m: changing coverage cannot change
        # the damage of an object already covered at the same distance.
        profile = 1 / (1 + (d / 24) ** 2)
    else:
        profile = 1.0
    return params.normalized * profile


def intersects(a, b):
    # Envelopes and building footprints are convex. SAT also catches crossings
    # with no vertex/entrance contained in the other footprint.
    for poly in (a, b):
        for p, q in zip(poly, poly[1:] + poly[:1]):
            nx, ny = -(q.y - p.y), q.x - p.x
            ap = [v.x * nx + v.y * ny for v in a]
            bp = [v.x * nx + v.y * ny for v in b]
            if max(ap) < min(bp) - 1e-8 or max(bp) < min(ap) - 1e-8:
                return False
    return True


def footprint_exposure(params, footprint, elapsed, polygon):
    if not intersects(footprint, polygon):
        return 0.0
    # Include the nearest point on every edge and the source center so an
    # envelope wholly inside a large building still produces structural loss.
    center = center_at(params, elapsed)
    points = list(footprint)
    for a, b in zip(footprint, footprint[1:] + footprint[:1]):
        dx, dy = b.x - a.x, b.y - a.y
        t = max(0, min(1, ((center.x - a.x) * dx + (center.y - a.y) * dy) / (dx * dx + dy * dy)))
        points.append(Vec2(x=a.x + t * dx, y=a.y + t * dy))
    if polygon_contains(center, footprint):
        points.append(center)
    return max(exposure(params, p, elapsed, polygon) for p in points)
