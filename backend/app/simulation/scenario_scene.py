"""Shared scenario recipes and deterministic low-poly scene planning."""

import json
import math
import random
import re
from pathlib import Path

from app.contracts import SceneObject, Vec2
from app.simulation.navigation import polygon_contains

CATALOG = json.loads((Path(__file__).resolve().parents[3] / "contracts/scenario-catalog.json").read_text())
COLORS = json.loads((Path(__file__).resolve().parents[3] / "contracts/scenario-palette.json").read_text())


def matches(prompt):
    text = prompt.lower()
    recipes = [
        recipe
        for recipe in CATALOG
        if any(
            re.search(r"\b" + re.escape(term) + r"\b", text)
            and not re.search(r"\b(?:no|without|not)\s+(?:a\s+|any\s+)?" + re.escape(term) + r"\b", text)
            for term in recipe["terms"]
        )
    ][:8]
    result = []
    for recipe in recipes:
        recipe = dict(recipe)
        terms = "(?:" + "|".join(re.escape(t) for t in recipe["terms"]) + ")"
        count = re.search(r"\b(\d+)\s+(?:(?:" + "|".join(COLORS) + r")\s+)?" + terms + r"\b", text)
        if count:
            recipe["count"] = min(8, max(1, int(count[1])))
        color = re.search(r"\b(" + "|".join(COLORS) + r")\s+" + terms + r"\b", text)
        if color:
            recipe["color"] = COLORS[color[1]]
        # A qualified water shortage should not also remove the town's food.
        if recipe["id"] == "shortage" and re.search(r"\bwater shortage\b", text):
            continue
        result.append(recipe)
    return result


def build_scene(state, spec, recipes):
    """Place at most 24 props on open ground near the affected population."""
    rng = random.Random(f"{state.simulation.config.seed}:{spec.description}:scene")
    population = [
        c.summary.position
        for c in state.citizens.values()
        if polygon_contains(c.summary.position, spec.affected_polygon)
    ]
    anchor = (
        Vec2(
            x=sum(p.x for p in population) / len(population),
            y=sum(p.y for p in population) / len(population),
        )
        if population
        else spec.origin
    )
    buildings = [
        (
            min(p.x for p in b.footprint) - 1.5,
            max(p.x for p in b.footprint) + 1.5,
            min(p.y for p in b.footprint) - 1.5,
            max(p.y for p in b.footprint) + 1.5,
        )
        for b in state.map.buildings
    ]
    candidates = []
    for cell in state.map.cells:
        point = Vec2(
            x=(cell.col + 0.5) * state.map.cell_size_m,
            y=(cell.row + 0.5) * state.map.cell_size_m,
        )
        if not cell.walkable or cell.terrain == "water" or not polygon_contains(point, spec.affected_polygon):
            continue
        # A clearance around footprints prevents scenery emerging through houses.
        if any(x0 <= point.x <= x1 and y0 <= point.y <= y1 for x0, x1, y0, y1 in buildings):
            continue
        candidates.append(point)
    candidates.sort(key=lambda p: math.hypot(p.x - anchor.x, p.y - anchor.y))
    pool = candidates[:320]
    rng.shuffle(pool)
    if not recipes:
        recipes = [dict(model="monument", color="#b8cbd6", count=1, id="your scenario")]
    scene = []
    for instance in range(max(r["count"] for r in recipes)):
        for recipe in recipes:
            if instance >= recipe["count"]:
                continue
            point = next(
                (
                    p
                    for p in pool
                    if all(math.hypot(p.x - o.position.x, p.y - o.position.y) >= 6 for o in scene)
                ),
                None,
            )
            if point is None or len(scene) == 24:
                break
            scene.append(
                SceneObject(
                    model=recipe["model"],
                    label=recipe.get("label", spec.title if len(recipes) == 1 else recipe["id"].title()),
                    position=point,
                    scale=1.0 if recipe["model"] in {"stage", "spacecraft", "dinosaur"} else 0.85,
                    rotation=round(rng.uniform(0, math.tau), 3),
                    color=recipe["color"],
                    parts=recipe.get("parts", []),
                )
            )
    return scene
