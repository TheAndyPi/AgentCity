import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import * as S from "../src/api/schemas";
import { defaultSettings } from "../src/api/defaults";

const directory = fileURLToPath(
  new URL("../../contracts/v1/fixtures/", import.meta.url),
);
const validators: Record<string, z.ZodTypeAny> = {
  WorldFrame: S.world,
  Simulation: S.simulation,
  "Page[Memory]": S.page(S.memory),
  Decision: S.decision,
  Relationship: S.relationship,
  ScenarioPreview: S.preview,
  ScenarioResult: z
    .object({ simulation: S.simulation, event: S.event, snapshot: S.snapshot })
    .strict(),
  CommandResult: S.commandResult,
  EventReport: S.eventReport,
  BranchResult: z
    .object({ simulation: S.simulation, snapshot: S.snapshot })
    .strict(),
  AgentDetail: S.agentDetail,
  ServerMessage: S.serverMessage,
  Failure: S.failure,
  CreateSimulation: S.createSimulationRequest,
  Intent: S.intent,
  CommandRequest: S.commandRequest,
};

describe("frozen backend/Python/Zod contract 1.0.0 parity", () => {
  for (const name of readdirSync(directory).filter((n) =>
    n.endsWith(".json"),
  )) {
    it(name, () => {
      const fixture = JSON.parse(readFileSync(`${directory}/${name}`, "utf8"));
      expect(validators[fixture.model], fixture.model).toBeDefined();
      const parsed = validators[fixture.model].safeParse(fixture.data);
      expect(parsed.success, parsed.success ? name : parsed.error.message).toBe(
        fixture.valid,
      );
    });
  }
  it("does not impose request ID limits on growing recorded history", () => {
    expect(
      S.evidence.safeParse({
        event_ids: [],
        memory_ids: [],
        decision_ids: Array.from({ length: 150 }, (_, i) => `decision_${i}`),
        description: "Committed audit history",
      }).success,
    ).toBe(true);
  });
  it("rejects the same invalid shortcut codes as the server", () => {
    expect(
      S.settings.safeParse({
        ...defaultSettings,
        shortcuts: { ...defaultSettings.shortcuts, pause: "NotARealCode" },
      }).success,
    ).toBe(false);
  });
  it("rejects whitespace drift in response names instead of rewriting them", () => {
    expect(
      S.branchRequest.safeParse({ name: " bad ", source: { kind: "whole" } })
        .success,
    ).toBe(false);
  });
});
