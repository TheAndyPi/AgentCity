import { expect, it } from "vitest";
import { conversationCameraZoom } from "../src/world/conversationCamera";

it("fits a distant diagonal pair between the side panels", () => {
  const zoom = conversationCameraZoom(1200, 800, [{ x: 0, y: 0 }, { x: 40, y: 40 }]);
  expect(zoom).toBeLessThan(12);
  expect((Math.hypot(40, 40) + 9) * zoom).toBeLessThanOrEqual(500);
});

it("keeps nearby citizens close while leaving room for their full bodies", () => {
  const zoom = conversationCameraZoom(1440, 900, [{ x: 10, y: 10 }, { x: 12, y: 10 }]);
  expect(zoom).toBeGreaterThan(12);
  expect(zoom * 9).toBeLessThanOrEqual(900 * 0.64);
});
