import type { MapData, Vec2 } from "../api/types";

export type MapBounds = Pick<MapData, "width_m" | "height_m">;

export function previewLayout(map: MapBounds) {
  const scale = Math.min(268 / map.width_m, 73 / map.height_m);
  return {
    scale,
    x: (280 - map.width_m * scale) / 2,
    y: (85 - map.height_m * scale) / 2,
  };
}

export function previewPoint(point: Vec2, map: MapBounds): Vec2 {
  const layout = previewLayout(map);
  return {
    x: layout.x + point.x * layout.scale,
    y: 85 - layout.y - point.y * layout.scale,
  };
}
