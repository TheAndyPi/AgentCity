import { beforeEach, describe, it, expect, vi, afterEach } from "vitest";
import { AgentCityClient, ApiError, LiveTransport } from "../src/api/client";
import { MockTransport } from "../src/api/mock";
import { defaultConfig, defaultProfile } from "../src/api/defaults";
import type { Simulation } from "../src/api/types";
let transport: MockTransport, client: AgentCityClient;
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  transport = new MockTransport();
  client = new AgentCityClient(transport);
});
afterEach(() => vi.useRealTimers());
const sim = () => client.simulation("preview-eden");
async function preview(running = false) {
  let s = await sim();
  if (running) s = (await client.command(s, { type: "play" })).simulation;
  const hold = await client.intervene(s);
  const p = await client.preview(s.id, {
    intervention_id: hold.id,
    source: "random",
    source_event_id: null,
    prompt: null,
    policy: null,
  });
  return { s, hold, p };
}
async function commit(running = false) {
  const { s, hold, p } = await preview(running);
  const result = await client.commit(s.id, hold, p, crypto.randomUUID());
  return { ...result, p, hold };
}
describe("safe event and outcome transitions", () => {
  it.each([true, false])(
    "cancellation restores only captured playback state: running=%s",
    async (running) => {
      const { s, hold } = await preview(running);
      expect((await sim()).status).toBe("paused");
      await client.cancel(s.id, hold);
      expect((await sim()).status).toBe(running ? "running" : "paused");
    },
  );
  it("preview never applies an event or advances the tick", async () => {
    const { p } = await preview(true);
    const f = await client.state("preview-eden");
    expect(p.can_commit).toBe(true);
    expect(f.events).toHaveLength(0);
    expect(f.ref.tick).toBe(0);
    expect(f.active_hazards).toHaveLength(0);
  });
  it.each([true, false])(
    "commit restores prior playback, with durable queued event: running=%s",
    async (running) => {
      const r = await commit(running);
      expect(r.simulation.status).toBe(running ? "running" : "paused");
      expect(r.event.status).toBe("queued");
      expect(r.snapshot.reason).toBe("pre_event");
    },
  );
  it("idempotent commit retry creates exactly one event and checkpoint", async () => {
    const { s, hold, p } = await preview();
    const key = crypto.randomUUID();
    const a = await client.commit(s.id, hold, p, key),
      b = await client.commit(s.id, hold, p, key);
    expect(a.event.id).toBe(b.event.id);
    expect(await client.events(s.id)).toHaveLength(1);
    expect(
      (await client.snapshots(s.id)).filter((p) => p.reason === "pre_event"),
    ).toHaveLength(1);
  });
  it("rejects expired, invalid and stale previews without resuming", async () => {
    const { s, hold, p } = await preview(true);
    transport.worlds.get(s.id)!.preview!.expires_at =
      "2000-01-01T00:00:00.000Z";
    await expect(
      client.commit(s.id, hold, p, crypto.randomUUID()),
    ).rejects.toMatchObject({ code: "PREVIEW_EXPIRED" });
    expect((await sim()).status).toBe("paused");
  });
  it("unsupported-only requests cannot commit and retain paused state", async () => {
    const { s, hold } = await preview();
    const p = await client.preview(s.id, {
      intervention_id: hold.id,
      source: "custom",
      source_event_id: null,
      prompt: "Teleport everyone with a dragon",
      policy: null,
    });
    expect(p.can_commit).toBe(false);
    await expect(
      client.commit(s.id, hold, p, crypto.randomUUID()),
    ).rejects.toMatchObject({ code: "INVALID_REQUEST" });
    expect((await sim()).status).toBe("paused");
  });
  it("explicit pause revokes cancellation auto-resume", async () => {
    const { s, hold } = await preview(true);
    await client.command(await sim(), { type: "pause" });
    const current = await sim();
    await client.cancel(s.id, {
      ...hold,
      control_version: current.control_version,
    });
    expect((await sim()).status).toBe("paused");
  });
  it("stepped event pauses with a pending report and acknowledgement stays paused", async () => {
    const r = await commit();
    let s = r.simulation;
    s = (await client.command(s, { type: "step", count: 9 })).simulation;
    expect(s.pause_reason).toBe("outcome");
    expect(s.pending_outcome_event_ids).toEqual([r.event.id]);
    const report = await client.report(s.id, r.event.id, s.revision);
    expect(report.event.status).toBe("resolved");
    expect(report.evacuated_count).toBe(10);
    s = (
      await client.command(s, {
        type: "acknowledge_outcome",
        event_id: r.event.id,
        resume: true,
      })
    ).simulation;
    expect(s.status).toBe("paused");
    expect(s.pending_outcome_event_ids).toEqual([]);
  });
  it("undo opens a new paused branch with original history preserved", async () => {
    const r = await commit();
    const s = (await client.command(r.simulation, { type: "step", count: 9 }))
      .simulation;
    const branch = await client.branch(s.id, "Restored city", {
      kind: "snapshot",
      snapshot_id: r.event.pre_event_snapshot_id,
    });
    expect(branch.simulation.id).not.toBe(s.id);
    expect(branch.simulation.status).toBe("paused");
    expect(branch.simulation.initial_preview).toBeNull();
    expect(branch.simulation.control_version).toBe(0);
    expect((await client.state(branch.simulation.id)).events).toHaveLength(0);
    expect(await client.events(s.id)).toHaveLength(1);
    expect((await client.state(branch.simulation.id)).ref.tick).toBe(0);
  });
});
describe("creation, history, persistence barriers, and request transport", () => {
  it("initializes through returned fixture stages, ends paused, and confirms the exact initial preview", async () => {
    const created = await client.create(
      { ...defaultConfig, scenario_description: "A flood" },
      crypto.randomUUID(),
    );
    expect(created.initialization.progress).toBe(0);
    let s: Simulation = created;
    for (let i = 0; i < 5; i++) s = await client.simulation(created.id);
    expect(s.status).toBe("paused");
    expect(s.initial_preview?.based_on.revision).toBe(s.revision);
    const confirmed = await client.initial(s, "confirm", crypto.randomUUID());
    expect(confirmed.event?.status).toBe("queued");
    expect(confirmed.simulation.status).toBe("paused");
  });
  it("setup double submission with one key returns the same initializing ID", async () => {
    const key = crypto.randomUUID();
    const a = await client.create(defaultConfig, key),
      b = await client.create(defaultConfig, key);
    expect(a.id).toBe(b.id);
  });
  it("historical reads exclude future dialogue and events", async () => {
    const initial = await client.state("preview-eden");
    const r = await commit();
    await client.command(r.simulation, { type: "step", count: 3 });
    expect(
      (await client.state("preview-eden", initial.ref.revision)).events,
    ).toEqual([]);
    expect(await client.dialogue("preview-eden", initial.ref.revision)).toEqual(
      [],
    );
    expect(await client.events("preview-eden", initial.ref.revision)).toEqual(
      [],
    );
  });
  it("navigation save pauses, acknowledges a snapshot and cancels an editor hold", async () => {
    const { s } = await preview(true);
    const result = await client.command(await sim(), {
      type: "save",
      reason: "navigation",
      label: "Before settings",
    });
    expect(result.simulation.status).toBe("paused");
    expect(result.snapshot?.reason).toBe("navigation");
    expect(transport.worlds.get(s.id)?.hold).toBeNull();
  });
  it("a failed save remains a failure with no fake saved result", async () => {
    const broken = new AgentCityClient({
      mode: "live",
      request: async () => {
        throw new ApiError("PERSISTENCE_UNAVAILABLE", "Disk unavailable", true);
      },
    });
    await expect(
      broken.command(await sim(), {
        type: "save",
        reason: "navigation",
        label: "Test",
      }),
    ).rejects.toMatchObject({ code: "PERSISTENCE_UNAVAILABLE" });
  });
  it("copies profiles into citizens; template edits do not rewrite them", async () => {
    const profile = await client.saveProfile({
      ...defaultProfile,
      name: "Test Citizen",
      role: "Gardener",
    });
    const created = await client.create(
      { ...defaultConfig, custom_agent_ids: [profile.id] },
      crypto.randomUUID(),
    );
    for (let i = 0; i < 5; i++) await client.simulation(created.id);
    await client.saveProfile(
      { ...profile.profile, name: "Changed template" },
      profile,
    );
    expect((await client.agent(created.id, "citizen-1")).profile.name).toBe(
      "Test Citizen",
    );
  });
  it("deletion requires archive and exact target name", async () => {
    await expect(client.delete(await sim())).rejects.toMatchObject({
      code: "INVALID_STATE",
    });
    const archived = (await client.command(await sim(), { type: "archive" }))
      .simulation;
    expect(archived.saved_at).not.toBeNull();
    const deleted = await client.delete(archived);
    expect(deleted.deleted_id).toBe(archived.id);
  });
  it("sends cookies, CSRF and matching request UUID/idempotency headers", async () => {
    const fetcher = vi.fn(
      async (_url: RequestInfo | URL, _options?: RequestInit) =>
        new Response(
          JSON.stringify({
            schema_version: "1.0.0",
            request_id: "server",
            data: { csrf_token: "csrf" },
          }),
          { status: 200 },
        ),
    );
    vi.stubGlobal("fetch", fetcher);
    const live = new LiveTransport();
    await live.request("POST", "/session", { passphrase: "test" });
    await live.request(
      "POST",
      "/simulations",
      { config: defaultConfig },
      "operation-key",
    );
    expect(fetcher.mock.calls[1][1]).toMatchObject({
      credentials: "include",
      headers: { "X-CSRF-Token": "csrf", "Idempotency-Key": "operation-key" },
    });
    vi.unstubAllGlobals();
  });
  it("waits for CSRF initialization when a write happens before app bootstrap", async () => {
    const calls: { method: string; headers: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: RequestInfo | URL, options?: RequestInit) => {
        calls.push({ method: options!.method!, headers: options!.headers });
        return new Response(
          JSON.stringify({
            schema_version: "1.0.0",
            request_id: "server",
            data: { authenticated: true, csrf_token: "bootstrapped-csrf" },
          }),
        );
      }),
    );
    try {
      const live = new LiveTransport();
      await live.request(
        "POST",
        "/simulations",
        { config: defaultConfig },
        "operation-key",
      );
      expect(calls.map((c) => c.method)).toEqual(["GET", "POST"]);
      expect(calls[1].headers).toMatchObject({
        "X-CSRF-Token": "bootstrapped-csrf",
        "Idempotency-Key": "operation-key",
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

it("recovers an ambiguous intervention response with the same key before cancellation", async () => {
  let lost = true;
  const reliable = client;
  const flaky = new AgentCityClient({
    mode: "mock",
    async request(method, path, body, key) {
      const result = await transport.request(method, path, body, key);
      if (path.endsWith("/interventions") && lost) {
        lost = false;
        throw new ApiError("CONNECTION_ERROR", "Response lost", true);
      }
      return result;
    },
  });
  const running = (await reliable.command(await sim(), { type: "play" }))
    .simulation;
  const key = crypto.randomUUID();
  await expect(flaky.intervene(running, key)).rejects.toMatchObject({
    code: "CONNECTION_ERROR",
  });
  const recovered = await flaky.intervene(running, key);
  await flaky.cancel(running.id, recovered);
  expect((await reliable.simulation(running.id)).status).toBe("running");
});
