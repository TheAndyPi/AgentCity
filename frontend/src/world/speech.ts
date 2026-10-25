import type { Dialogue, WorldFrame } from "../api/types";

/** One current bubble for every speaker, including unselected neighbors. */
export function speechBySpeaker(frame: WorldFrame, focus: string[] = []) {
  const speech = new Map<string, Dialogue>();
  const agents = new Set(frame.agents.map((agent) => agent.id));
  for (const line of frame.recent_dialogue) {
    const age = frame.ref.tick - line.tick;
    if (
      age < 0 ||
      age > 3 ||
      !agents.has(line.speaker_id) ||
      (focus.length > 1 &&
        (!focus.includes(line.speaker_id) ||
          !line.recipient_ids.some((id) => focus.includes(id))))
    )
      continue;
    const previous = speech.get(line.speaker_id);
    if (!previous || line.tick >= previous.tick)
      speech.set(line.speaker_id, line);
  }
  return speech;
}

type Bubble = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

/** Keep nearby speakers readable in screen space without moving their models. */
export function layoutSpeech(bubbles: Bubble[], width: number, height: number) {
  const placed: Bubble[] = [];
  const offsets = new Map<string, { x: number; y: number }>();
  const gap = 10;
  const overlaps = (a: Bubble, b: Bubble) =>
    a.x < b.x + b.width + gap &&
    a.x + a.width + gap > b.x &&
    a.y < b.y + b.height + gap &&
    a.y + a.height + gap > b.y;
  for (const bubble of bubbles) {
    const clamp = (p: Bubble) => ({
      ...p,
      x: Math.max(8, Math.min(width - p.width - 8, p.x)),
      y: Math.max(8, Math.min(height - p.height - 8, p.y)),
    });
    let next = clamp(bubble);
    if (placed.some((p) => overlaps(next, p))) {
      // Consider every free edge together; stepping around only the first
      // collision can oscillate between two neighbors in a crowded overview.
      const xs = [
        next.x,
        8,
        width - next.width - 8,
        ...placed.flatMap((p) => [p.x - next.width - gap, p.x + p.width + gap]),
      ];
      const ys = [
        next.y,
        8,
        height - next.height - 8,
        ...placed.flatMap((p) => [
          p.y - next.height - gap,
          p.y + p.height + gap,
        ]),
      ];
      const candidates = xs.flatMap((x) =>
        ys.map((y) => clamp({ ...bubble, x, y })),
      );
      const free = candidates.filter((p) =>
        placed.every((other) => !overlaps(p, other)),
      );
      const cost = (p: Bubble) => (p.x - bubble.x) ** 2 + (p.y - bubble.y) ** 2;
      if (free.length) next = free.sort((a, b) => cost(a) - cost(b))[0];
    }
    placed.push(next);
    offsets.set(bubble.id, { x: next.x - bubble.x, y: next.y - bubble.y });
  }
  return offsets;
}

/** Orthographic zoom should shrink speech along with the neighborhood. */
export const speechScale = (zoom: number) =>
  Math.max(0.45, Math.min(1.15, zoom / 28));
