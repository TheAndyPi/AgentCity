import itertools
import random
from collections import Counter, deque
from types import SimpleNamespace

import pytest

from app import contracts as c
from app.simulation.navigation import cell_at
from app.simulation.scenarios import generate_map


def city_map(seed=42, settlement="urban", density=75):
    ids = itertools.count()
    state = SimpleNamespace(
        simulation=SimpleNamespace(
            config=c.ConfigRequest(
                name="Dense city",
                seed=seed,
                environment={"settlement": settlement, "population_density": density},
            ).normalized()
        ),
        next_id=lambda prefix: f"{prefix}_{next(ids)}",
    )
    return generate_map(state, random.Random(seed))


@pytest.mark.parametrize("settlement", ["urban", "suburb"])
@pytest.mark.parametrize("density", [0, 50, 100])
def test_multiple_buildings_per_block_have_clear_connected_road_entrances(settlement, density):
    town = city_map(settlement=settlement, density=density)
    blocks = Counter()
    occupied = set()
    roads = {(cell.col, cell.row) for cell in town.cells if cell.terrain == "road" and cell.walkable}
    reached, queue = {(0, 0)}, deque([(0, 0)])
    while queue:
        col, row = queue.popleft()
        for neighbor in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1)):
            if neighbor in roads and neighbor not in reached:
                reached.add(neighbor)
                queue.append(neighbor)
    for building in town.buildings:
        x, y = building.footprint[0].x, building.footprint[0].y
        col, row = int(x // 2), int(y // 2)
        blocks[(col // 8, row // 8)] += 1
        entrance = cell_at(town, building.entrance)
        assert entrance.terrain == "road" and entrance.walkable
        assert (entrance.col, entrance.row) in reached
        for dy in range(2):
            for dx in range(2):
                key = col + dx, row + dy
                assert key not in occupied
                occupied.add(key)
                cell = town.cells[key[1] * town.columns + key[0]]
                assert cell.terrain == "land" and not cell.walkable
        assert all(0 <= p.x <= town.width_m and 0 <= p.y <= town.height_m for p in building.footprint)
    assert len(blocks) == 64
    assert all(2 <= count <= 4 for count in blocks.values())
    assert all(not cell.walkable for cell in town.cells if cell.terrain == "water")
    assert {building.kind for building in town.buildings} == {
        "home",
        "work",
        "shop",
        "hospital",
        "shelter",
        "community",
    }


def test_dense_city_is_seeded_has_restaurants_and_responds_to_density():
    dense = city_map()
    assert len(dense.buildings) == 240
    assert city_map().model_dump() == dense.model_dump()
    assert city_map(seed=43).model_dump() != dense.model_dump()
    assert len(city_map(settlement="suburb", density=0).buildings) < len(dense.buildings)
    assert any("Restaurant" in building.name for building in dense.buildings)
    assert any("Market" in building.name for building in dense.buildings)
    assert len({b.height_m for b in dense.buildings if b.kind == "home"}) > 10


def test_addresses_capacity_skyline_and_river_vary_by_seed():
    town = city_map()
    names = [b.name for b in town.buildings]
    assert len(set(names)) == len(names)
    assert not any(ch.isdigit() for name in names for ch in name)
    assert all("Avenue" in name or "Street" in name for name in names)
    assert len({b.capacity for b in town.buildings if b.kind == "home"}) > 5
    assert max(b.height_m for b in town.buildings) >= 60
    for seed in range(6):
        refuges = city_map(seed=seed).buildings[:3]
        assert refuges[0].kind == "shelter" and refuges[2].kind == "community"
        assert refuges[0].entrance.x < 64 and refuges[0].entrance.y < 64
        assert refuges[2].entrance.x >= 64 and refuges[2].entrance.y >= 64
    towers = [b for b in town.buildings if b.height_m >= 25]
    assert 0 < len(towers) <= 0.15 * len(town.buildings)
    assert max(b.height_m for b in city_map(settlement="suburb").buildings) < 20
    rivers = set()
    for seed in range(12):
        water = [cell for cell in city_map(seed=seed).cells if cell.terrain == "water"]
        assert water and all(cell.col >= 60 or cell.row >= 60 for cell in water)
        rivers.add(tuple((cell.col, cell.row) for cell in water))
    assert len(rivers) == 12
    assert {
        all(cell.col >= 60 for cell in city_map(seed=s).cells if cell.terrain == "water") for s in range(12)
    } == {
        True,
        False,
    }
