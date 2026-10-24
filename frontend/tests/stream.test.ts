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
