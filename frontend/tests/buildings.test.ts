import { describe, expect, it } from "vitest";
import {
  buildingBounds,
  buildingInfo,
  buildingLayout,
  buildingSignature,
  type Building,
} from "../src/world/buildingLayout";

const building = (
  kind: Building["kind"],
  name: string,
  entrance = { x: 1, y: 7 },
): Building => ({
  id: name,
  kind,
  name,
  entrance,
  footprint: [
    { x: 4, y: 4 },
    { x: 8, y: 4 },
    { x: 8, y: 10 },
    { x: 4, y: 10 },
  ],
  height_m: 12,
  capacity: 8,
  occupancy: 0,
  functional: true,
});

describe("building architecture and purpose tags", () => {
  const buildings = [
    building("home", "Maple Apartments"),
    building("home", "Cedar Townhouse"),
    building("work", "Willow Company Offices"),
    building("shop", "Aster Restaurant"),
    building("shop", "Harbor Market"),
    building("hospital", "Oak Hospital"),
    building("shelter", "Juniper Shelter"),
    building("community", "Birch Community Center"),
  ];
  it("labels every existing contract kind and distinguishes restaurants from other retail", () => {
    expect(buildings.map((b) => buildingInfo(b).purpose)).toEqual([
      "apartments",
      "townhouse",
      "company",
      "restaurant",
      "shop",
      "hospital",
      "shelter",
      "community",
    ]);
    for (const b of buildings) expect(buildingInfo(b).description).toBeTruthy();
    expect(buildingInfo(building("shop", "Corner Café")).purpose).toBe(
      "restaurant",
    );
  });
  it("gives homes, offices, food shops and civic buildings different silhouettes", () => {
    const layouts = buildings.map((b) => buildingLayout([b]));
    expect(layouts[0].boxes.length).toBeGreaterThan(layouts[3].boxes.length);
    expect(layouts[0].roofs).toHaveLength(0);
    expect(layouts[1].roofs).toHaveLength(1);
    expect(layouts[5].boxes.some((p) => p.color === "#c4625f")).toBe(true);
    expect(
      new Set(layouts.map((l) => JSON.stringify(l.boxes.map((p) => p.scale))))
        .size,
    ).toBeGreaterThanOrEqual(6);
  });
  it("keeps rotated architecture on its authoritative lot and maps every part to its building", () => {
    for (const b of buildings)
      for (const entrance of [
        { x: 1, y: 7 },
        { x: 11, y: 7 },
        { x: 6, y: 1 },
        { x: 6, y: 13 },
      ]) {
        const rotated = { ...b, entrance },
          bounds = buildingBounds(rotated),
          layout = buildingLayout([rotated]);
        for (const p of [...layout.boxes, ...layout.roofs]) {
          expect(p.buildingId).toBe(b.id);
          expect(p.position.every(Number.isFinite)).toBe(true);
          expect(p.scale.every((v) => v > 0)).toBe(true);
          const side = Math.abs(Math.sin(p.rotation)) > 0.5;
          const width = side ? p.scale[2] : p.scale[0],
            depth = side ? p.scale[0] : p.scale[2];
          expect(
            Math.abs(p.position[0] - bounds.x) + width / 2,
          ).toBeLessThanOrEqual(bounds.width / 2 + 0.07);
          expect(
            Math.abs(p.position[2] - bounds.y) + depth / 2,
          ).toBeLessThanOrEqual(bounds.depth / 2 + 0.07);
          expect(p.position[1] + p.scale[1] / 2).toBeLessThanOrEqual(
            b.height_m + 0.07,
          );
        }
      }
  });
  it("retains arbitrary polygon footprints and reports unavailable buildings", () => {
    const b = {
      ...buildings[0],
      footprint: [
        { x: 1, y: 1 },
        { x: 7, y: 1 },
        { x: 5, y: 6 },
      ],
      functional: false,
    };
    expect(buildingLayout([b]).polygons).toEqual([b]);
    expect(
      buildingLayout([{ ...buildings[0], functional: false }]).boxes[0].color,
    ).toBe("#65636a");
  });
  it("does not rebuild facade geometry for live occupancy changes", () => {
    expect(buildingSignature(buildings)).toBe(
      buildingSignature(buildings.map((b) => ({ ...b, occupancy: 3 }))),
    );
    expect(buildingSignature(buildings)).not.toBe(
      buildingSignature(buildings.map((b) => ({ ...b, functional: false }))),
    );
  });
});
