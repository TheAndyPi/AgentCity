import { describe, expect, it } from "vitest";
import fixture from "../../contracts/v2/fixtures/behavior.json";
import { behaviorResponse } from "../src/behavior/schema";
import { readBehavior } from "../src/behavior/client";
import type { Transport } from "../src/api/client";

describe("behavior v2 strict consumer", () => {
  it("keeps Mental, life, crisis and living denominators separate", () => {
    const data = behaviorResponse.parse(fixture).data;
    const values = Object.values(data.citizens);
    expect(values.filter((c) => c.life === "dead")).toHaveLength(1);
    expect(values.filter((c) => c.life === "unconscious")).toHaveLength(1);
    expect(data.analytics.living).toBe(9);
    expect(data.analytics.unconscious).toBe(1);
    expect(data.analytics.survival_fraction).toBe(0.9);
    expect(values.some((c) => c.mental === 10 && c.episode)).toBe(true);
    expect(data.analytics.tiger_behavior_supported).toBe(false);
  });
  it("rejects missing Mental, enum drift and extra fields", () => {
    const raw = structuredClone(fixture) as unknown as Record<string, any>;
    const id = Object.keys(raw.data.citizens)[0];
    delete raw.data.citizens[id].mental;
    expect(behaviorResponse.safeParse(raw).success).toBe(false);
    expect(
      behaviorResponse.safeParse({ ...fixture, schema_version: "1.0.0" })
        .success,
    ).toBe(false);
    expect(
      behaviorResponse.safeParse({ ...fixture, unexpected: 1 }).success,
    ).toBe(false);
  });
  it("pins simulation/revision and makes no mock request", async () => {
    const transport: Transport = { mode: "live", request: async () => fixture };
    const data = fixture.data;
    expect(
      (await readBehavior(transport, data.simulation_id, data.ref.revision))
        ?.ref,
    ).toEqual(data.ref);
    await expect(
      readBehavior(transport, "another-simulation", data.ref.revision),
    ).rejects.toThrow("revision");
    transport.mode = "mock";
    transport.request = async () => {
      throw Error("unexpected request");
    };
    expect(await readBehavior(transport, data.simulation_id, 0)).toBeNull();
  });
});
