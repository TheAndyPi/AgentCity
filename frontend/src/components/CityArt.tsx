import { useMemo } from "react";
import type { MapData } from "../api/types";

const cos = Math.cos(Math.PI / 6),
  sin = Math.sin(Math.PI / 6);
const iso = (x: number, y: number, z = 0): [number, number] => [
  (x - y) * cos,
  (x + y) * sin - z,
];
const points = (pts: [number, number][]) =>
  pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");

/** Isometric miniature of a simulation's real map: footprints, heights and river. */
export function CityArt({ map }: { map: MapData }) {
  const art = useMemo(() => {
    const cell = map.cell_size_m;
    const ground = [
      iso(0, 0),
      iso(map.width_m, 0),
      iso(map.width_m, map.height_m),
      iso(0, map.height_m),
    ];
    const water: string[] = [];
    const runs = new Map<number, number[]>();
    for (const c of map.cells)
      if (c.terrain === "water") {
        const row = runs.get(c.row) ?? [];
        row.push(c.col);
        runs.set(c.row, row);
      }
    for (const [row, cols] of runs) {
      cols.sort((a, b) => a - b);
      let start = cols[0];
      for (let i = 1; i <= cols.length; i++) {
        if (i < cols.length && cols[i] === cols[i - 1] + 1) continue;
        const x0 = start * cell,
          x1 = (cols[i - 1] + 1) * cell,
          y0 = row * cell,
          y1 = (row + 1) * cell;
        water.push(`M${points([iso(x0, y0), iso(x1, y0), iso(x1, y1), iso(x0, y1)])}Z`);
        start = cols[i];
      }
    }
    const boxes = map.buildings
      .map((b) => {
        const xs = b.footprint.map((p) => p.x),
          ys = b.footprint.map((p) => p.y);
        return {
          id: b.id,
          kind: b.kind,
          x0: Math.min(...xs),
          x1: Math.max(...xs),
          y0: Math.min(...ys),
          y1: Math.max(...ys),
          h: b.height_m,
        };
      })
      .sort((a, b) => a.x1 + a.y1 - (b.x1 + b.y1));
    const all = [...ground];
    const shapes = boxes.map((b) => {
      const top = [
        iso(b.x0, b.y0, b.h),
        iso(b.x1, b.y0, b.h),
        iso(b.x1, b.y1, b.h),
        iso(b.x0, b.y1, b.h),
      ];
      all.push(...top);
      return {
        id: b.id,
        kind: b.kind,
        top: points(top),
        left: points([
          iso(b.x0, b.y1),
          iso(b.x1, b.y1),
          iso(b.x1, b.y1, b.h),
          iso(b.x0, b.y1, b.h),
        ]),
        right: points([
          iso(b.x1, b.y0),
          iso(b.x1, b.y1),
          iso(b.x1, b.y1, b.h),
          iso(b.x1, b.y0, b.h),
        ]),
      };
    });
    const xs = all.map((p) => p[0]),
      ys = all.map((p) => p[1]);
    const minX = Math.min(...xs),
      minY = Math.min(...ys);
    const pad = (Math.max(...xs) - minX) * 0.04;
    return {
      viewBox: [
        minX - pad,
        minY - pad,
        Math.max(...xs) - minX + pad * 2,
        Math.max(...ys) - minY + pad * 2,
      ]
        .map((n) => n.toFixed(1))
        .join(" "),
      ground: points(ground),
      water,
      shapes,
    };
  }, [map]);
  return (
    <svg
      className="city-art"
      viewBox={art.viewBox}
      preserveAspectRatio="xMidYMax meet"
      aria-hidden="true"
    >
      <polygon className="city-art-ground" points={art.ground} />
      {art.water.length > 0 && (
        <path className="city-art-water" d={art.water.join("")} />
      )}
      {art.shapes.map((s) => (
        <g key={s.id} className={`city-art-building ${s.kind}`}>
          <polygon className="side-left" points={s.left} />
          <polygon className="side-right" points={s.right} />
          <polygon className="top" points={s.top} />
        </g>
      ))}
    </svg>
  );
}
