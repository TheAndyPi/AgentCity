import type { Dialogue, WorldFrame } from "../api/types";

/** One current bubble for every speaker, including unselected neighbors. */
export function speechBySpeaker(frame: WorldFrame, focus: string[] = []) {
  const speech = new Map<string, Dialogue>();
  const agents = new Set(frame.agents.map((agent) => agent.id));
  for (const line of frame.recent_dialogue) {
    const age = frame.ref.tick - line.tick;
    const session = frame.conversation_sessions?.find(
      (s) => s.id === line.interaction_id,
    );
    const live =
      session?.status === "invited" || session?.status === "accepted";
    if (
      age < 0 ||
      (!live && age > 3) ||
      !agents.has(line.speaker_id) ||
      (focus.length > 0 && !focus.includes(line.speaker_id)) ||
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
  depth?: number;
};

/** Keep speech anchored to its speaker; dim bubbles behind nearer speech. */
export function layoutSpeech(bubbles: Bubble[], _width: number, _height: number) {
  const overlaps = (a: Bubble, b: Bubble) =>
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y;
  // Match Html's camera-depth ordering, with a stable tie break.
  const ordered = [...bubbles].sort(
    (a, b) => (a.depth ?? 0) - (b.depth ?? 0) || a.id.localeCompare(b.id),
  );
  return new Map(ordered.map((bubble, index) => [bubble.id, {
    x: 0,
    y: 0,
    obscured: ordered.slice(0, index).some((front) => overlaps(bubble, front)),
  }]));
}

/** Orthographic zoom should shrink speech along with the neighborhood. */
export const speechScale = (zoom: number) =>
  Math.max(0.45, Math.min(1.15, zoom / 28));
