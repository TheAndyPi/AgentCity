import type { MapData, Vec2 } from "../api/types";

export const groundColors = {
  grass: "#527a45",
  asphalt: "#414950",
  water: "#467e90",
  sidewalk: "#b4b6a6",
  curb: "#d6d6c7",
  markings: "#e7dfbc",
};

export type GroundRect = {
  x: number;
  y: number;
  width: number;
  depth: number;
  angle?: number;
};

// Only geometry participates: resource stocks, occupancy and zone metrics change each tick.
export function groundSignature(map: MapData) {
  return JSON.stringify([
    map.id,
    map.seed,
    map.width_m,
    map.height_m,
    map.cell_size_m,
    map.cells.map((c) => [c.col, c.row, c.terrain]),
    map.buildings.map((b) => [b.id, b.footprint, b.entrance]),
  ]);
}

export function groundLayout(map: MapData) {
  const roads: GroundRect[] = [],
    water: GroundRect[] = [],
    sidewalks: GroundRect[] = [],
    curbs: GroundRect[] = [],
    markings: GroundRect[] = [],
    entrances: GroundRect[] = [];
  const size = map.cell_size_m,
    pavement = Math.min(0.6, size * 0.3);
  const cells = new Map(map.cells.map((c) => [`${c.col}:${c.row}`, c]));
  const at = (col: number, row: number) => cells.get(`${col}:${row}`);
  const road = (col: number, row: number) => at(col, row)?.terrain === "road";
  const directions = [
    [-1, 0],
    [1, 0],
    [0, -1],
    [0, 1],
  ] as const;
  const crossings = new Map<string, "horizontal" | "vertical">();

  for (const cell of map.cells) {
    const { col, row, terrain } = cell;
    const x = (col + 0.5) * size,
      y = (row + 0.5) * size;
    if (terrain === "water") water.push({ x, y, width: size, depth: size });
    if (terrain !== "road") continue;
    roads.push({ x, y, width: size, depth: size });
    const neighbors = directions.filter(([dx, dy]) => road(col + dx, row + dy));
    if (neighbors.length >= 3) {
      for (const [dx, dy] of neighbors) {
        const c = col + dx,
          r = row + dy;
        const horizontal = road(c - 1, r) || road(c + 1, r);
        const vertical = road(c, r - 1) || road(c, r + 1);
        if (horizontal !== vertical)
          crossings.set(`${c}:${r}`, horizontal ? "horizontal" : "vertical");
      }
    }
    for (const [dx, dy] of directions) {
      const neighbor = at(col + dx, row + dy);
      if (!neighbor || neighbor.terrain === "road") continue;
      if (neighbor.terrain === "land") {
        sidewalks.push({
          x: x + (dx * (size + pavement)) / 2,
          y: y + (dy * (size + pavement)) / 2,
          width: dx ? pavement : size,
          depth: dy ? pavement : size,
        });
      }
      curbs.push({
        x: x + dx * (size / 2 - 0.04),
        y: y + dy * (size / 2 - 0.04),
        width: dx ? 0.08 : size,
        depth: dy ? 0.08 : size,
      });
    }
  }
  for (const cell of map.cells) {
    if (cell.terrain !== "road") continue;
    const { col, row } = cell;
    const x = (col + 0.5) * size,
      y = (row + 0.5) * size;
    const crossing = crossings.get(`${col}:${row}`);
    if (crossing) {
      for (const offset of [-0.24, 0, 0.24])
        markings.push({
          x: x + (crossing === "horizontal" ? offset * size : 0),
          y: y + (crossing === "vertical" ? offset * size : 0),
          width: size * (crossing === "horizontal" ? 0.1 : 0.78),
          depth: size * (crossing === "vertical" ? 0.1 : 0.78),
        });
      continue;
    }
    const horizontal = road(col - 1, row) || road(col + 1, row);
    const vertical = road(col, row - 1) || road(col, row + 1);
    if (horizontal !== vertical)
      markings.push({
        x,
        y,
        width: horizontal ? size * 0.45 : 0.055,
        depth: vertical ? size * 0.45 : 0.055,
      });
  }
  for (const building of map.buildings) {
    const entrance = building.entrance;
    let closest: Vec2 | null = null,
      distance = Infinity;
    building.footprint.forEach((a, i, polygon) => {
      const b = polygon[(i + 1) % polygon.length];
      const dx = b.x - a.x,
        dy = b.y - a.y,
        length = dx * dx + dy * dy;
      const t = length
        ? Math.max(
            0,
            Math.min(
              1,
              ((entrance.x - a.x) * dx + (entrance.y - a.y) * dy) / length,
            ),
          )
        : 0;
      const point = { x: a.x + dx * t, y: a.y + dy * t };
      const d = Math.hypot(point.x - entrance.x, point.y - entrance.y);
      if (d < distance) {
        closest = point;
        distance = d;
      }
    });
    if (closest && distance > 0.01) {
      const target = closest as Vec2;
      entrances.push({
        x: (entrance.x + target.x) / 2,
        y: (entrance.y + target.y) / 2,
        width: distance,
        depth: Math.min(1, size * 0.5),
        angle: Math.atan2(target.y - entrance.y, target.x - entrance.x),
      });
    }
  }
  return { roads, water, sidewalks, curbs, markings, entrances };
}

export type GroundLayout = ReturnType<typeof groundLayout>;
