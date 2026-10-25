import { doorway, insideBuilding } from "./buildingAccess";
import type { AgentSummary, MapData, Vec2 } from "../api/types";

/** Interpolate only the acknowledged prefix of the PREVIOUS legal path. The current path can contain future positions and must never be traversed speculatively. */
export function boundedPosition(
  previous: Vec2,
  current: AgentSummary,
  t: number,
  previousPath: Vec2[] = [],
): Vec2 {
  if (t >= 1 || previousPath.length === 0) return current.position;
  const route = [previous, ...previousPath];
  const prefix: Vec2[] = [previous];
  let found = false;
  for (let i = 1; i < route.length; i++) {
    const a = route[i - 1],
      b = route[i],
      p = current.position;
    const length = Math.hypot(b.x - a.x, b.y - a.y),
      along = Math.hypot(p.x - a.x, p.y - a.y),
      rest = Math.hypot(b.x - p.x, b.y - p.y);
    if (Math.abs(along + rest - length) < 0.001) {
      prefix.push(p);
      found = true;
      break;
    }
    prefix.push(b);
  }
  if (!found) return current.position;
  const lengths = prefix
    .slice(1)
    .map((p, i) => Math.hypot(p.x - prefix[i].x, p.y - prefix[i].y));
  let distance =
    lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(t, 1));
  for (let i = 0; i < lengths.length; i++) {
    if (distance <= lengths[i]) {
      const fraction = lengths[i] === 0 ? 1 : distance / lengths[i];
      return {
        x: prefix[i].x + (prefix[i + 1].x - prefix[i].x) * fraction,
        y: prefix[i].y + (prefix[i + 1].y - prefix[i].y) * fraction,
      };
    }
    distance -= lengths[i];
  }
  return current.position;
}

/** Keep interpolation between legal simulation ticks from merging two bodies. */
export function separatePositions(
  positions: Vec2[],
  canStand: (point: Vec2, index: number) => boolean,
  spacing = 1.6,
): Vec2[] {
  const result = positions.map((p) => ({ ...p }));
  for (let pass = 0; pass < 8; pass++) {
    let changed = false;
    for (let i = 0; i < result.length; i++) {
      for (let j = i + 1; j < result.length; j++) {
        const a = result[i],
          b = result[j];
        const length = Math.hypot(b.x - a.x, b.y - a.y);
        if (length >= spacing - 0.001) continue;
        const dx = length > 0.0001 ? (b.x - a.x) / length : 1;
        const dy = length > 0.0001 ? (b.y - a.y) / length : 0;
        const gap = spacing - length + 0.001;
        const moveA = (amount: number) => ({
          x: a.x - dx * amount,
          y: a.y - dy * amount,
        });
        const moveB = (amount: number) => ({
          x: b.x + dx * amount,
          y: b.y + dy * amount,
        });
        if (canStand(moveA(gap / 2), i) && canStand(moveB(gap / 2), j)) {
          result[i] = moveA(gap / 2);
          result[j] = moveB(gap / 2);
        } else if (canStand(moveA(gap), i)) result[i] = moveA(gap);
        else if (canStand(moveB(gap), j)) result[j] = moveB(gap);
        else continue;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return result;
}

/** Reconstruct only travel between two acknowledged positions, never a future path. */
export function acknowledgedRoute(
  previous: Vec2,
  destination: Vec2,
  map: MapData,
): Vec2[] {
  if (
    Math.hypot(previous.x - destination.x, previous.y - destination.y) < 0.001
  )
    return [previous, destination];
  const fromBuilding = map.buildings.find((b) => insideBuilding(previous, b));
  const toBuilding = map.buildings.find((b) => insideBuilding(destination, b));
  if (fromBuilding && fromBuilding.id === toBuilding?.id)
    return [previous, destination];
  const start = fromBuilding?.entrance ?? previous;
  const end = toBuilding?.entrance ?? destination;
  const index = (p: Vec2) =>
    Math.floor(p.y / map.cell_size_m) * map.columns +
    Math.floor(p.x / map.cell_size_m);
  const first = index(start),
    last = index(end);
  const costs = new Map<number, number>([[first, 0]]);
  const parents = new Map<number, number>();
  const pending = new Set([first]);
  while (pending.size) {
    let cell = -1,
      best = Infinity;
    for (const key of pending) {
      const score =
        costs.get(key)! +
        Math.abs((key % map.columns) - (last % map.columns)) +
        Math.abs(
          Math.floor(key / map.columns) - Math.floor(last / map.columns),
        );
      if (score < best) {
        best = score;
        cell = key;
      }
    }
    pending.delete(cell);
    if (cell === last) {
      const path = [last];
      while (path[0] !== first) path.unshift(parents.get(path[0])!);
      const points = path.slice(1).map((key) => ({
        x: ((key % map.columns) + 0.5) * map.cell_size_m,
        y: (Math.floor(key / map.columns) + 0.5) * map.cell_size_m,
      }));
      // The exact observed endpoint replaces the last cell center.
      if (points.length) points.pop();
      return [
        previous,
        ...(fromBuilding ? [doorway(fromBuilding), start] : []),
        ...points,
        end,
        ...(toBuilding ? [doorway(toBuilding), destination] : []),
      ];
    }
    const col = cell % map.columns,
      row = Math.floor(cell / map.columns);
    for (const [x, y] of [
      [col - 1, row],
      [col + 1, row],
      [col, row - 1],
      [col, row + 1],
    ]) {
      if (x < 0 || y < 0 || x >= map.columns || y >= map.rows) continue;
      const key = y * map.columns + x,
        next = map.cells[key];
      if (!next?.walkable) continue;
      const cost = costs.get(cell)! + (next.terrain === "road" ? 1 : 4);
      if (cost < (costs.get(key) ?? Infinity)) {
        costs.set(key, cost);
        parents.set(key, cell);
        pending.add(key);
      }
    }
  }
  // Keep the last displayed position if infrastructure removed the entire route.
  return [previous];
}

export function pointAlongRoute(route: Vec2[], progress: number): Vec2 {
  if (progress <= 0) return route[0];
  if (progress >= 1) return route.at(-1)!;
  const lengths = route
    .slice(1)
    .map((p, i) => Math.hypot(p.x - route[i].x, p.y - route[i].y));
  let remaining =
    lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(1, progress));
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] && lengths[i] > 0) {
      const fraction = remaining / lengths[i];
      return {
        x: route[i].x + (route[i + 1].x - route[i].x) * fraction,
        y: route[i].y + (route[i + 1].y - route[i].y) * fraction,
      };
    }
    remaining -= lengths[i];
  }
  return route.at(-1)!;
}

/** Match playback to delivered snapshots, which can batch several simulation ticks. */
export class WalkingCadence {
  private id = "";
  private tick = -1;
  private arrived = 0;
  duration = 600;

  observe(id: string, tick: number, now: number, running: boolean): number {
    if (id !== this.id || tick < this.tick) {
      this.duration = 600;
      this.arrived = now;
    } else if (tick > this.tick) {
      const elapsed = now - this.arrived;
      // Paused steps should remain visible; long stalls must not leave walkers lagging.
      this.duration = running ? Math.max(100, Math.min(2000, elapsed)) : 600;
      this.arrived = now;
    }
    this.id = id;
    this.tick = tick;
    return this.duration;
  }
}
