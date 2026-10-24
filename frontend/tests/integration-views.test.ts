import { expect, it } from "vitest";
import { previewPoint } from "../src/world/previewGeometry";
import { metricDelta } from "../src/api/format";

it("fits the full backend map and north/east polygon vertices inside the preview", () => {
  for (const map of [
    { width_m: 128, height_m: 128 },
    { width_m: 200, height_m: 80 },
  ]) {
    const south = previewPoint({ x: 0, y: 0 }, map);
    const northEast = previewPoint({ x: map.width_m, y: map.height_m }, map);
    expect(south.x).toBeGreaterThanOrEqual(0);
    expect(south.y).toBeLessThanOrEqual(85);
    expect(northEast.x).toBeLessThanOrEqual(280);
    expect(northEast.y).toBeGreaterThanOrEqual(0);
    expect(northEast.y).toBeLessThan(south.y);
    expect(northEast.x).toBeGreaterThan(south.x);
  }
});

it("shows measured small deltas rather than rounding them to signed zero", () => {
  expect(metricDelta(0.024)).toBe("+0.02");
  expect(metricDelta(-0.024)).toBe("−0.02");
  expect(metricDelta(0.0002)).toBe("+<0.01");
  expect(metricDelta(-0)).toBe("0.00");
});
