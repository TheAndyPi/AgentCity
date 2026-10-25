import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorldStore } from "../src/state/world";
import { AgentCityClient, type Transport } from "../src/api/client";
import { fixtureWorld } from "../src/api/fixtures";
import type { WorldFrame } from "../src/api/types";
class Socket {
  static all: Socket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    Socket.all.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  send(message: string) {
    this.sent.push(message);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}
const envelope = (frame: WorldFrame) => ({
  schema_version: "1.0.0",
  request_id: "request",
  data: frame,
});
const message = (frame: WorldFrame) => ({
  schema_version: "1.0.0",
  simulation_id: frame.simulation.id,
  sent_at: new Date().toISOString(),
  type: "frame",
  data: frame,
});
const at = (revision: number) => {
  const f = fixtureWorld();
  f.ref.revision = revision;
  f.simulation.revision = revision;
  f.metrics.revision = revision;
  return f;
};
beforeEach(() => {
  vi.useFakeTimers();
  Socket.all = [];
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("window", { location: { origin: "https://example.com" } });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("stream generations, fallback and REST races", () => {
  it("a replaced socket cannot publish late frames or close the new connection", async () => {
    const store = new WorldStore();
    const stop = store.start(
      "preview-eden",
      new AgentCityClient({
        mode: "live",
        request: async () => envelope(at(1)),
      }),
    );
    const previous = Socket.all[0];
    previous.open();
    previous.close();
    await vi.advanceTimersByTimeAsync(1400);
    const current = Socket.all.at(-1)!;
    current.open();
    current.emit(message(at(8)));
    previous.emit(message(at(99)));
    previous.onerror?.();
    expect(current.readyState).toBe(Socket.OPEN);
    expect(store.getSnapshot().frame?.ref.revision).toBe(8);
    expect(store.getSnapshot().connection).toBe("live");
    stop();
  });
  it("sends versioned hello and never replaces a newer frame with a late REST response", async () => {
    let resolve!: (value: unknown) => void;
    const transport: Transport = {
      mode: "live",
      request: () =>
        new Promise((r) => {
          resolve = r;
        }),
    };
    const store = new WorldStore();
    const stop = store.start("preview-eden", new AgentCityClient(transport));
    const socket = Socket.all[0];
    socket.open();
    expect(JSON.parse(socket.sent[0])).toMatchObject({
      type: "hello",
      schema_version: "1.0.0",
      last_revision: null,
    });
    socket.emit(message(at(8)));
    resolve(envelope(at(1)));
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getSnapshot().frame?.ref.revision).toBe(8);
    socket.emit(message(at(7)));
    expect(store.getSnapshot().frame?.ref.revision).toBe(8);
    stop();
    socket.emit(message(at(20)));
    expect(store.getSnapshot().frame?.ref.revision).toBe(8);
  });
  it("retries the socket then polls complete snapshots after three failures", async () => {
    let reads = 0;
    const transport: Transport = {
      mode: "live",
      request: async () => {
        reads++;
        return envelope(at(reads));
      },
    };
    const store = new WorldStore();
    const stop = store.start("preview-eden", new AgentCityClient(transport));
    await vi.advanceTimersByTimeAsync(0);
    Socket.all.at(-1)!.close();
    await vi.advanceTimersByTimeAsync(1400);
    Socket.all.at(-1)!.close();
    await vi.advanceTimersByTimeAsync(2400);
    Socket.all.at(-1)!.close();
    expect(store.getSnapshot().connection).toBe("polling");
    await vi.advanceTimersByTimeAsync(2100);
    expect(reads).toBeGreaterThan(1);
    expect(store.getSnapshot().frame?.ref.revision).toBe(reads);
    stop();
  });
  it("freezes the last valid view and reacquires state on an invalid stream message", async () => {
    const transport: Transport = {
      mode: "live",
      request: async () => envelope(at(2)),
    };
    const store = new WorldStore();
    const stop = store.start("preview-eden", new AgentCityClient(transport));
    await vi.advanceTimersByTimeAsync(0);
    Socket.all[0].emit({ ...message(at(3)), data: { bad: "shape" } });
    expect(store.getSnapshot().frame?.ref.revision).toBe(2);
    expect(store.getSnapshot().error).toContain("Invalid stream data");
    stop();
  });
});

it("merges a mapless delta and rejects an unknown map version", () => {
  const store = new WorldStore();
  const initial = at(1);
  initial.map_version = 10;
  store.accept(initial);
  const { map: _map, ...delta } = at(2);
  expect(store.acceptDelta({ ...delta, map_version: 10 })).toBe(true);
  expect(store.getSnapshot().frame?.map).toBe(initial.map);
  expect(() =>
    store.acceptDelta({
      ...delta,
      ref: { ...delta.ref, revision: 3 },
      map_version: 11,
    }),
  ).toThrow("snapshot");
  expect(store.getSnapshot().frame?.ref.revision).toBe(2);
});

it("notifies subscribers once per animation frame with the latest revision", () => {
  let flush!: FrameRequestCallback;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    flush = callback;
    return 1;
  });
  const store = new WorldStore();
  const changed = vi.fn();
  store.subscribe(changed);
  store.accept(at(1));
  store.accept(at(2));
  store.accept(at(3));
  expect(changed).not.toHaveBeenCalled();
  expect(store.getSnapshot().frame?.ref.revision).toBe(3);
  flush(0);
  expect(changed).toHaveBeenCalledTimes(1);
});

it("merges dynamic map stats while preserving cached geometry", () => {
  const store = new WorldStore();
  const initial = at(1);
  store.accept(initial);
  const { map: _map, ...delta } = at(2);
  const resource = initial.map.resources[0];
  const building = initial.map.buildings[0];
  const zone = initial.map.zones[0];
  store.acceptDelta({
    ...delta,
    map_updates: {
      resources: [{ id: resource.id, available_units: 7 }],
      buildings: [
        { id: building.id, capacity: 4, occupancy: 3, functional: false },
      ],
      zones: [
        {
          id: zone.id,
          metrics: { ...zone.metrics, safety: 5 },
          population: 4,
          population_density_per_km2: 100,
        },
      ],
    },
  });
  const current = store.getSnapshot().frame!;
  expect(current.map.cells).toBe(initial.map.cells);
  expect(current.map.resources[0].available_units).toBe(7);
  expect(current.map.buildings[0]).toMatchObject({
    capacity: 4,
    occupancy: 3,
    functional: false,
  });
  expect(current.map.zones[0].metrics.safety).toBe(5);
  expect(initial.map.resources[0].available_units).toBe(
    resource.available_units,
  );
  expect(initial.map.buildings[0].functional).toBe(true);
});
