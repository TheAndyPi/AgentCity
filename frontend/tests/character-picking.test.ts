import { expect, it } from "vitest";
import { prioritizeCharacterHighlights } from "../src/world/characterPicking";

it("lets visible character highlights receive clicks through buildings", () => {
  const building = { object: { userData: {} } };
  const nearHighlight = { object: { userData: { characterHighlight: true } } };
  const farHighlight = { object: { userData: { characterHighlight: true } } };
  const ground = { object: { userData: {} } };
  const hits = [building, nearHighlight, farHighlight, ground];
  expect(prioritizeCharacterHighlights(hits)).toEqual([
    nearHighlight, farHighlight, building, ground,
  ]);
  expect(hits[0]).toBe(building);
});

it("preserves normal picking order when no highlights are hit", () => {
  const hits = [{ object: { userData: {} } }, { object: { userData: {} } }];
  expect(prioritizeCharacterHighlights(hits)).toEqual(hits);
});
