import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import capabilitiesFixture from "./fixtures/scenario-capabilities.json";
import { ApiError, type Transport } from "../src/api/client";
import { ScenarioEngineClient } from "../src/scenarios/client";
import { PlanPreview } from "../src/scenarios/PlanPreview";
import { blankOperation, manualPlan } from "../src/scenarios/PlanEditor";
import { engineCapabilities, type PlanResult } from "../src/scenarios/schema";

const caps = engineCapabilities.parse(capabilitiesFixture);

const ready: PlanResult = {
  status: "ready",
  plan: {
    title: "Transit fares fund hospitals",
    category: "policy",
    description: "Transit fares double and the revenue funds hospitals.",
    duration: "permanent",
    source: "gemini",
    agent_knowledge: "Everyone hears the announcement.",
  },
  errors: [],
  warnings: [],
  unsupported: ["Hospital staff hiring is not simulated."],
  clarification: "",
  attempts: 1,
  summary: {
    operations: [
      {
        id: "fare",
        type: "modify_policy",
        label: "multiply transportation transit fare 2",
        rationale: "Fares double",
        timing: {
          start_tick: 0,
          duration_ticks: null,
          repeat_every: null,
          repeat_count: null,
        },
        physical: false,
      },
    ],
    affected_systems: ["transportation", "healthcare"],
    metrics: [
      {
        id: "transit_usage",
        description: "Share of recorded trips taken by public transit",
      },
    ],
    event_kind: "policy",
    region_polygon: [],
    affected_agent_count: 30,
    affected_building_count: 12,
    measurement_ticks: 36,
    warnings: [],
  },
};

function transport(
  answer: unknown,
  calls: unknown[][],
  mode: "live" | "mock" = "live",
): Transport {
  return {
    mode,
    request: async (...args: unknown[]) => {
      calls.push(args);
      return answer;
    },
  };
}

describe("scenario engine client", () => {
  it("interprets through the integrations route with a long timeout", async () => {
    const calls: unknown[][] = [];
    const engine = new ScenarioEngineClient(
      transport(
        { schema_version: "1.0.0", request_id: "x", data: ready },
        calls,
      ),
    );
    const result = await engine.interpret(
      "simulation_1",
      { id: "intervention_1", control_version: 3 } as never,
      "Double fares",
    );
    expect(result.status).toBe("ready");
    const [method, path, body, key, timeout] = calls[0];
    expect(method).toBe("POST");
    expect(path).toBe("/integrations/scenarios/simulations/simulation_1/plans");
    expect(body).toEqual({
      intervention_id: "intervention_1",
      prompt: "Double fares",
    });
    expect(typeof key).toBe("string");
    expect(timeout).toBeGreaterThan(15000);
  });

  it("surfaces failure envelopes and is unavailable in mock mode", async () => {
    const failure = {
      schema_version: "1.0.0",
      request_id: "x",
      error: {
        code: "VALIDATION_ERROR",
        message: "Bad plan",
        retryable: false,
        details: [],
      },
    };
    const engine = new ScenarioEngineClient(transport(failure, []));
    await expect(engine.validate("s", {})).rejects.toBeInstanceOf(ApiError);
    expect(
      new ScenarioEngineClient(transport(null, [], "mock")).available,
    ).toBe(false);
  });

  it("commits the plan with the intervention's control version", async () => {
    const calls: unknown[][] = [];
    const engine = new ScenarioEngineClient(transport({ data: {} }, calls));
    await expect(
      engine.commit(
        "s",
        { id: "i", control_version: 7 } as never,
        { title: "t" },
        "key-1",
      ),
    ).rejects.toThrow(/malformed/);
    expect(calls[0][2]).toEqual({
      intervention_id: "i",
      expected_control_version: 7,
      plan: { title: "t" },
    });
    expect(calls[0][3]).toBe("key-1");
  });
});

describe("plan preview and editor", () => {
  it("shows scenario, interpreted changes, affected systems, measurements and unsupported parts", () => {
    const html = renderToStaticMarkup(
      createElement(PlanPreview, { result: ready, plan: ready.plan }),
    );
    for (const text of [
      "Scenario",
      "Interpreted changes",
      "Affected systems",
      "Measurements",
      "multiply transportation transit fare 2",
      "Healthcare",
      "Share of recorded trips taken by public transit",
      "Hospital staff hiring is not simulated.",
      "Each one decides from their own situation",
    ])
      expect(html).toContain(text);
  });

  it("builds operations only from the registry schemas", () => {
    expect(caps.operations.map((o) => o.type)).toContain("modify_policy");
    const policy = blankOperation("modify_policy", caps, 0);
    expect(policy).toMatchObject({
      type: "modify_policy",
      id: "op1",
      target: "taxation.business_tax_rate",
    });
    const hazard = blankOperation("physical_hazard", caps, 1);
    expect(hazard).toMatchObject({
      hazard: "flood",
      region: "citywide",
      severity: 1,
    });
    expect(Object.keys(policy)).not.toContain("path");
    const catalog = blankOperation("catalog_event", caps, 2);
    expect(catalog.type).toBe("catalog_event");
    const catalogSchema = caps.operations.find(
      (o) => o.type === "catalog_event",
    )!.parameters as { properties: { recipe: { enum: string[] } } };
    expect(catalogSchema.properties.recipe.enum).toContain("dinosaurs");
    expect(catalogSchema.properties.recipe.enum).toContain(catalog.recipe);
    const plan = manualPlan("Close the shops");
    expect(plan).toMatchObject({
      source: "manual",
      operations: [],
      title: "Close the shops",
    });
  });
});
