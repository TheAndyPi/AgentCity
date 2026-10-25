import { describe, expect, it } from "vitest";
import { isValidElement, type ReactNode } from "react";
import catalog from "../../contracts/scenario-catalog.json";
import { fixturePreview, fixtureWorld } from "../src/api/fixtures";
import { preview } from "../src/api/schemas";
import { ScenarioModel } from "../src/world/ScenarioScene";
import type { SceneObject } from "../src/api/types";

function geometry(node: ReactNode): string[] {
  if (Array.isArray(node)) return node.flatMap(geometry);
  if (!isValidElement<{ children?: ReactNode }>(node)) return [];
  if (typeof node.type === "function")
    return geometry((node.type as (p: unknown) => ReactNode)(node.props));
  return [
    ...(typeof node.type === "string" && node.type.endsWith("Geometry")
      ? [node.type]
      : []),
    ...geometry(node.props.children),
  ];
}
describe("procedural scenario scenes", () => {
  it.each(catalog)("compiles and renders the $id recipe", (recipe) => {
    const result = fixturePreview(
      fixtureWorld(),
      "custom",
      `A ${recipe.terms[0]} for 3 ticks`,
    );
    expect(preview.safeParse(result).success).toBe(true);
    expect(result.spec.scene?.some((o) => o.model === recipe.model)).toBe(true);
    expect(
      geometry(
        ScenarioModel({
          model: recipe.model as SceneObject["model"],
          color: recipe.color,
        }),
      ).length,
    ).toBeGreaterThan(0);
  });
  it("composes visuals and effects and explains unknown premises", () => {
    const result = fixturePreview(
      fixtureWorld(),
      "custom",
      "A dinosaur and alien at a festival in the east for 3 ticks",
    );
    expect(new Set(result.spec.scene?.map((o) => o.model))).toEqual(
      new Set(["dinosaur", "spacecraft", "stage"]),
    );
    expect(result.spec.scene?.every((o) => o.position.x >= 64)).toBe(true);
    expect(result.spec.duration_ticks).toBe(3);
    const unknown = fixturePreview(
      fixtureWorld(),
      "custom",
      "Gravity reverses without any fire",
    );
    expect(unknown.spec.scene?.[0].model).toBe("monument");
    expect(unknown.can_commit).toBe(false);
    expect(unknown.unsupported_requests[0]).toContain(
      "failed to interpret this scenario input",
    );
    expect(unknown.spec.effects.some((e) => e.type === "hazard")).toBe(false);
  });
  it("honors count and color without confusing water and food shortages", () => {
    const result = fixturePreview(
      fixtureWorld(),
      "custom",
      "2 red robots deliver aid during a water shortage",
    );
    const robots = result.spec.scene!.filter((o) => o.model === "robot");
    expect(robots).toHaveLength(2);
    expect(robots.every((o) => o.color === "#db7567")).toBe(true);
    expect(
      result.spec.effects.filter((e) => e.type === "resource_multiplier"),
    ).toEqual([
      { type: "resource_multiplier", resource: "water", multiplier: 0.35 },
    ]);
  });
  it("validates and renders free-form primitive geometry", () => {
    const result = fixturePreview(fixtureWorld(), "custom", "A whale arrives");
    const object: SceneObject = {
      model: "generated",
      label: "Whale",
      position: { x: 33, y: 33 },
      scale: 1,
      rotation: 0,
      color: "#8bb9db",
      parts: [
        {
          shape: "sphere",
          offset: { x: 0, y: 1, z: 0 },
          size: { x: 4, y: 2, z: 2 },
          color: "#8bb9db",
        },
      ],
    };
    result.spec.scene = [object];
    expect(preview.safeParse(result).success).toBe(true);
    expect(geometry(ScenarioModel(object))).toContain("icosahedronGeometry");
    object.parts![0].size.x = 100;
    expect(preview.safeParse(result).success).toBe(false);
  });
});
