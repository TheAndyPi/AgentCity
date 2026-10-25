import { expect, it } from "vitest";
import { fixtureWorld } from "../src/api/fixtures";
import type { Dialogue } from "../src/api/types";
import { layoutSpeech, speechBySpeaker } from "../src/world/speech";

it("shows the latest recent bubble for every speaker in the wide view", () => {
  const frame = fixtureWorld();
  frame.ref.tick = 10;
  const [a, b, c] = frame.agents;
  const line = (speaker: string, tick: number, text: string): Dialogue => ({
    id: text,
    interaction_id: "chat",
    tick,
    speaker_id: speaker,
    recipient_ids: [b.id],
    audible_to_ids: [],
    text,
    intent: "talk",
    emotion: "calm",
    end_conversation: false,
  });
  frame.recent_dialogue = [
    line(a.id, 8, "old"),
    line(b.id, 9, "reply"),
    line(a.id, 10, "latest"),
    line(c.id, 6, "expired"),
    line(c.id, 11, "future"),
    line("missing", 10, "gone"),
  ];
  expect([...speechBySpeaker(frame).values()].map((d) => d.text)).toEqual([
    "latest",
    "reply",
  ]);
  expect(speechBySpeaker(frame, [c.id]).size).toBe(0);
  expect([...speechBySpeaker(frame, [a.id]).keys()]).toEqual([a.id]);
  expect([...speechBySpeaker(frame, [b.id, c.id]).keys()]).toEqual([b.id]);
});

it("keeps overlapping speech anchored and dims only bubbles behind nearer speech", () => {
  const bubbles = [
    { id: "back", x: 500, y: 300, width: 170, height: 100, depth: 0.5 },
    { id: "front", x: 590, y: 310, width: 170, height: 85, depth: 0.1 },
    { id: "separate", x: 50, y: 50, width: 170, height: 110, depth: 0.8 },
  ];
  const offsets = layoutSpeech(bubbles, 1440, 900);
  expect(offsets.get("back")).toEqual({ x: 0, y: 0, obscured: true });
  expect(offsets.get("front")).toEqual({ x: 0, y: 0, obscured: false });
  expect(offsets.get("separate")).toEqual({ x: 0, y: 0, obscured: false });
  expect(layoutSpeech([bubbles[0]], 1440, 900).get("back")?.obscured).toBe(false);
});
