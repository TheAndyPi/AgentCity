import { expect, it } from "vitest";
import { slowForConversation, type Clock } from "../src/narration/speed";

it("slows playback and restores the previous speed", async () => {
  let clock: Clock = { id: "city", status: "running" as const, speed_multiplier: 5 };
  const changes: number[] = [];
  const restore = await slowForConversation(
    () => clock,
    async (value) => {
      changes.push(value);
      clock = { ...clock, speed_multiplier: value };
    },
  );
  expect(clock.speed_multiplier).toBe(0.25);
  await restore?.();
  expect(changes).toEqual([0.25, 5]);
});

it("preserves manual speed changes while listening", async () => {
  let clock: Clock = { id: "city", status: "running" as const, speed_multiplier: 2 };
  const restore = await slowForConversation(
    () => clock,
    async (value) => {
      clock = { ...clock, speed_multiplier: value };
    },
  );
  clock = { ...clock, speed_multiplier: 1 };
  await restore?.();
  expect(clock.speed_multiplier).toBe(1);
});

it("leaves paused simulations and other cities alone", async () => {
  const paused: Clock = { id: "city", status: "paused" as const, speed_multiplier: 2 };
  expect(
    await slowForConversation(
      () => paused,
      async () => {
        throw new Error("must stay paused");
      },
    ),
  ).toBeUndefined();
  let clock: Clock = { ...paused, status: "running" as const };
  const changes: number[] = [];
  const restore = await slowForConversation(
    () => clock,
    async (value) => {
      changes.push(value);
      clock = { ...clock, speed_multiplier: value };
    },
  );
  clock = { ...clock, id: "another-city" };
  await restore?.();
  expect(changes).toEqual([0.25]);
});
