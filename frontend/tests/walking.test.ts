import { expect, it } from "vitest";
import { acknowledgedRoute, pointAlongRoute } from "../src/world/motion";
import { insideBuilding, doorway } from "../src/world/buildingAccess";
import { fixtureWorld } from "../src/api/fixtures";
import { speechScale } from "../src/world/speech";

it("animates a newly completed route even when the prior tick had no path", () => {
  const map = fixtureWorld().map;
  const start = { x: 9, y: 1 },
    end = { x: 17, y: 17 };
  const route = acknowledgedRoute(start, end, map);
  expect(pointAlongRoute(route, 0)).toEqual(start);
  expect(pointAlongRoute(route, 1)).toEqual(end);
  expect(pointAlongRoute(route, 0.3)).not.toEqual(start);
  expect(pointAlongRoute(route, 0.3)).not.toEqual(end);
  for (let t = 0; t < 1; t += 0.01) {
    const p = pointAlongRoute(route, t);
    const cell =
      map.cells[
        Math.floor(p.y / map.cell_size_m) * map.columns +
          Math.floor(p.x / map.cell_size_m)
      ];
    expect(cell.walkable).toBe(true);
  }
});

it("walks around a blocked block instead of cutting through it", () => {
  const map = fixtureWorld().map;
  // A closed road segment forces a detour for the acknowledged trip.
  map.cells[1 * map.columns + 6].walkable = false;
  const route = acknowledgedRoute({ x: 9, y: 3 }, { x: 17, y: 3 }, map);
  for (let t = 0; t <= 1; t += 0.01) {
    const p = pointAlongRoute(route, t);
    expect(
      map.cells[
        Math.floor(p.y / map.cell_size_m) * map.columns +
          Math.floor(p.x / map.cell_size_m)
      ].walkable,
    ).toBe(true);
  }
});

it("enters and leaves buildings through the doorway", () => {
  const map = fixtureWorld().map;
  const building = map.buildings[0];
  const inside = {
    x:
      building.footprint.reduce((v, p) => v + p.x, 0) /
      building.footprint.length,
    y:
      building.footprint.reduce((v, p) => v + p.y, 0) /
      building.footprint.length,
  };
  expect(insideBuilding(inside, building)).toBe(true);
  const entering = acknowledgedRoute(building.entrance, inside, map);
  expect(entering).toContainEqual(doorway(building));
  expect(pointAlongRoute(entering, 1)).toEqual(inside);
  const exiting = acknowledgedRoute(inside, building.entrance, map);
  expect(exiting).toContainEqual(doorway(building));
  expect(pointAlongRoute(exiting, 1)).toEqual(building.entrance);
});

it("shrinks dialogue with orthographic zoom while retaining bubbles in wide view", () => {
  expect(speechScale(12)).toBeLessThan(speechScale(45));
  expect(speechScale(12)).toBeGreaterThan(0);
  expect(speechScale(2)).toBeLessThan(0.5);
});
