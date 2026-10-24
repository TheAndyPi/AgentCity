import { subscribeToContextLoss } from "../src/world/contextLoss";
import { describe, it, expect } from "vitest";
import * as S from "../src/api/schemas";
import {
  fixtureWorld,
  fixtureSimulation,
  fixtureDetail,
  fixturePreview,
  fixtureAgents,
} from "../src/api/fixtures";
import { defaultConfig, defaultSettings } from "../src/api/defaults";
import { WorldStore } from "../src/state/world";
import { boundedPosition, instanceAgentId } from "../src/world/World";
import {
  websocketUrl,
  AgentCityClient,
  type Transport,
} from "../src/api/client";
describe("contract 1.0.0 frontend consumers", () => {
  it("validates ready, initializing, initial preview, 30/100 citizen and empty frames", () => {
    for (const n of [0, 30, 100])
      expect(
        S.world.safeParse(fixtureWorld(fixtureSimulation(), fixtureAgents(n)))
          .success,
      ).toBe(true);
    const s = fixtureSimulation();
    s.status = "initializing";
    s.initialization = {
      stage: "map",
      progress: 25,
      message: "Map",
      error: null,
    };
    expect(S.simulation.parse(s).status).toBe("initializing");
    expect(
      S.preview.parse(fixturePreview(fixtureWorld(), "initial")).source,
    ).toBe("initial");
  });
  it("validates rejected actions and asymmetric relationships", () => {
    const f = fixtureWorld();
    const a = fixtureDetail(f, "citizen-1"),
      b = fixtureDetail(f, "citizen-2"),
      rejected = fixtureDetail(f, "citizen-3");
    b.relationships.items[0].trust = 32;
    expect(S.agentDetail.parse(a).relationships.items[0].trust).toBe(78);
    expect(S.agentDetail.parse(b).relationships.items[0].trust).toBe(32);
    expect(
      S.agentDetail.parse(rejected).decisions.items[0].rejection_code,
    ).toBe("OUT_OF_RANGE");
  });
  it.each([NaN, Infinity, -1, 101])("rejects invalid metric %s", (value) => {
    expect(
      S.metrics.safeParse({
        ...fixtureWorld().metrics.values,
        happiness: value,
      }).success,
    ).toBe(false);
  });
  it("forbids unknown request properties and invalid ranges", () => {
    expect(S.config.safeParse({ ...defaultConfig, secret: "no" }).success).toBe(
      false,
    );
    expect(
      S.config.safeParse({ ...defaultConfig, population: 101 }).success,
    ).toBe(false);
    expect(
      S.config.safeParse({ ...defaultConfig, tick_seconds: 20 }).success,
    ).toBe(false);
    expect(
      S.commandRequest.safeParse({
        request_id: crypto.randomUUID(),
        expected_control_version: 0,
        command: { type: "step", count: 11 },
      }).success,
    ).toBe(false);
    expect(
      S.config.safeParse({ ...defaultConfig, custom_agent_ids: ["a", "a"] })
        .success,
    ).toBe(false);
  });
  it("rejects duplicate or noncanonical shortcuts", () => {
    expect(
      S.settings.safeParse({
        ...defaultSettings,
        shortcuts: { ...defaultSettings.shortcuts, zoom_in: "Space" },
      }).success,
    ).toBe(false);
    expect(
      S.settings.safeParse({
        ...defaultSettings,
        shortcuts: { ...defaultSettings.shortcuts, zoom_in: "Ctrl+plus" },
      }).success,
    ).toBe(false);
  });
  it("rejects response drift and stream drift", async () => {
    const transport: Transport = {
      mode: "live",
      request: async () => ({
        schema_version: "2.0.0",
        request_id: "r",
        data: fixtureWorld(),
      }),
    };
    await expect(
      new AgentCityClient(transport).state("a"),
    ).rejects.toMatchObject({ code: "CONTRACT_ERROR" });
    expect(
      S.serverMessage.safeParse({
        schema_version: "1.0.0",
        simulation_id: "a",
        sent_at: new Date().toISOString(),
        type: "frame",
        data: { ...fixtureWorld(), extra: true },
      }).success,
    ).toBe(false);
  });
  it("converts HTTPS to WSS, preserves API path and excludes secrets", () => {
    expect(websocketUrl("world-1", "/api/v1", "https://example.com")).toBe(
      "wss://example.com/api/v1/simulations/world-1/stream",
    );
  });
});
describe("render and subscription invariants", () => {
  it("discards equal, stale, foreign and prior-generation frames", () => {
    const store = new WorldStore();
    const a = fixtureWorld();
    a.ref.revision = 4;
    expect(store.accept(a)).toBe(true);
    expect(store.accept(fixtureWorld())).toBe(false);
    expect(store.accept(a)).toBe(false);
    const other = fixtureWorld(fixtureSimulation("other"));
    other.ref.revision = 5;
    expect(store.accept(other)).toBe(false);
    const newer = structuredClone(a);
    newer.ref.revision = 8;
    expect(store.accept(newer, store.generation - 1)).toBe(false);
    expect(store.accept(newer)).toBe(true);
    expect(store.getSnapshot().frame?.ref.revision).toBe(8);
  });
  it("resolves instance IDs after insertion/removal without using array index as identity", () => {
    const agents = fixtureAgents();
    expect(instanceAgentId(agents, 2)).toBe("citizen-3");
    const removed = agents.filter((a) => a.id !== "citizen-2");
    expect(instanceAgentId(removed, 1)).toBe("citizen-3");
    expect(instanceAgentId(removed, undefined)).toBeNull();
  });
  it("maps unequal x/y consistently and bounds interpolation to the received path", () => {
    const a = fixtureAgents()[0];
    a.position = { x: 9, y: 7 };
    a.path = [{ x: 2, y: 7 }];
    expect(boundedPosition({ x: 2, y: 3 }, a, 1)).toEqual({ x: 9, y: 7 });
    expect(
      boundedPosition({ x: 2, y: 3 }, a, 0.2, [
        { x: 2, y: 7 },
        { x: 12, y: 7 },
      ]).x,
    ).toBe(2);
    expect(boundedPosition({ x: 2, y: 3 }, a, 2)).toEqual(a.position);
    a.path = [];
    expect(boundedPosition({ x: 100, y: 100 }, a, 0.2)).toEqual(a.position);
  });
});

it("cleans up the WebGL listener before normal renderer disposal", () => {
  const canvas = new EventTarget();
  let calls = 0;
  const off = subscribeToContextLoss(canvas, () => calls++);
  const first = new Event("webglcontextlost", { cancelable: true });
  canvas.dispatchEvent(first);
  expect(first.defaultPrevented).toBe(true);
  expect(calls).toBe(1);
  off();
  canvas.dispatchEvent(new Event("webglcontextlost"));
  expect(calls).toBe(1);
});
