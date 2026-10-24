import type { MapData, Vec2 } from "../api/types";

type Building = MapData["buildings"][number];
export function insideBuilding(p: Vec2, building: Building) {
  const polygon = building.footprint;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i],
      b = polygon[j];
    if (
      a.y > p.y !== b.y > p.y &&
      p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x
    )
      inside = !inside;
  }
  return inside;
}
export function doorway(building: Building): Vec2 {
  let closest = building.footprint[0],
    best = Infinity;
  building.footprint.forEach((a, i) => {
    const b = building.footprint[(i + 1) % building.footprint.length];
    const dx = b.x - a.x,
      dy = b.y - a.y;
    const t = Math.max(
      0,
      Math.min(
        1,
        ((building.entrance.x - a.x) * dx + (building.entrance.y - a.y) * dy) /
          (dx * dx + dy * dy),
      ),
    );
    const p = { x: a.x + dx * t, y: a.y + dy * t };
    const d = Math.hypot(p.x - building.entrance.x, p.y - building.entrance.y);
    if (d < best) {
      best = d;
      closest = p;
    }
  });
  return closest;
}
