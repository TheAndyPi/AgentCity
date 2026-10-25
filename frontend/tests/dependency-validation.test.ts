import { describe, expect, it } from "vitest";
import * as S from "../src/api/schemas";
import { defaultConfig, defaultSettings } from "../src/api/defaults";
import { fixtureSimulation } from "../src/api/fixtures";

describe("dependency upgrades preserve the frozen wire validation", () => {
  it.each([
    "11111111-2222-3333-4444-555555555555",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    "00000000-0000-0000-0000-000000000000",
  ])(
    "accepts the contract's canonical hexadecimal request ID %s",
    (request_id) => {
      expect(
        S.commandRequest.parse({
          request_id,
          expected_control_version: 0,
          command: { type: "pause" },
        }).request_id,
      ).toBe(request_id);
    },
  );

  it.each([
    "not-a-uuid",
    "11111111222233334444555555555555",
    "{11111111-2222-3333-4444-555555555555}",
  ])("rejects noncanonical request IDs %s", (request_id) => {
    expect(
      S.commandRequest.safeParse({
        request_id,
        expected_control_version: 0,
        command: { type: "pause" },
      }).success,
    ).toBe(false);
  });

  it.each([
    ["2026-10-24T12:00:00Z", true],
    ["2026-10-24T12:00:00.123456+00:00", true],
    ["2026-10-24T12:00Z", false],
    ["2026-10-24T12:00:00-04:00", false],
    ["2026-02-30T12:00:00Z", false],
  ])("keeps timestamp validation for %s", (created_at, valid) => {
    expect(
      S.simulation.safeParse({ ...fixtureSimulation(), created_at }).success,
    ).toBe(valid);
  });

  it("keeps setup defaults and rejects unknown fields at nested boundaries", () => {
    expect(S.configRequest.parse({ name: "Migration", seed: 42 })).toEqual({
      ...defaultConfig,
      name: "Migration",
      seed: 42,
    });
    expect(
      S.configRequest.safeParse({
        name: "Migration",
        seed: 42,
        environment: { extra: true },
      }).success,
    ).toBe(false);
    expect(
      S.settings.safeParse({
        ...defaultSettings,
        shortcuts: { ...defaultSettings.shortcuts, extra: "KeyQ" },
      }).success,
    ).toBe(false);
  });

  it("keeps required envelope data and strict response fields", () => {
    const envelope = { schema_version: "1.0.0", request_id: "test" };
    expect(S.success(S.settings).safeParse(envelope).success).toBe(false);
    expect(
      S.success(S.settings).safeParse({
        ...envelope,
        data: { ...defaultSettings, extra: true },
      }).success,
    ).toBe(false);
    expect(
      S.success(S.settings).safeParse({
        ...envelope,
        data: defaultSettings,
        extra: true,
      }).success,
    ).toBe(false);
  });
});
