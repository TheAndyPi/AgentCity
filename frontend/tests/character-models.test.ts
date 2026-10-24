import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { characterAppearance } from "../src/world/characterAppearance";
import { CitizenPortrait } from "../src/components/LifePanels";
import { defaultConfig } from "../src/api/defaults";
import { lifeIntent } from "../src/components/LifeHUD";

it("gives ten people distinct designs that survive ordering and renders", () => {
  const names = [
    "Maya Reyes",
    "Elias Chen",
    "Nora Patel",
    "Jules Brooks",
    "Priya Okafor",
    "Theo Rivera",
    "Amara Kim",
    "Felix Bennett",
    "Lena Singh",
    "Omar Morales",
  ];
  const looks = names.map(characterAppearance);
  expect(new Set(looks.map((look) => JSON.stringify(look))).size).toBe(10);
  expect([...names].reverse().map(characterAppearance).reverse()).toEqual(
    looks,
  );
  expect(new Set(looks.map((look) => look.shirt)).size).toBeGreaterThan(4);
  expect(new Set(looks.map((look) => look.hairStyle)).size).toBeGreaterThan(2);
});
it("uses the same skin, clothing and hair for portraits and world models", () => {
  const look = characterAppearance("Maya Reyes");
  const portrait = renderToStaticMarkup(
    createElement(CitizenPortrait, { name: "Maya Reyes" }),
  );
  for (const color of [look.skin, look.hair, look.shirt])
    expect(portrait).toContain(color);
});
it("starts with ten neighbors and builds normal validated social intents", () => {
  expect(defaultConfig.population).toBe(10);
  expect(lifeIntent("talk", "neighbor")).toMatchObject({
    action: "talk",
    target_id: "neighbor",
    parameters: { message: null },
  });
  expect(lifeIntent("consume").parameters).toEqual({
    resource_kind: "food",
    amount: 1,
    message: null,
  });
});

it("keeps crossing animations apart and respects unwalkable ground", async () => {
  const { separatePositions } = await import("../src/world/motion");
  const crossing = [
    { x: 5, y: 5 },
    { x: 5, y: 5 },
  ];
  const [a, b] = separatePositions(crossing, () => true);
  expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(1.6);
  expect(crossing).toEqual([
    { x: 5, y: 5 },
    { x: 5, y: 5 },
  ]);
  const [c, d] = separatePositions(crossing, (p) => p.x >= 5);
  expect(c.x).toBeGreaterThanOrEqual(5);
  expect(d.x).toBeGreaterThanOrEqual(5);
  expect(Math.hypot(c.x - d.x, c.y - d.y)).toBeGreaterThanOrEqual(1.6);
});
