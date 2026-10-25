import { describe, it, expect, vi } from "vitest";
import {
  defaults,
  fromPrompt,
  parameters,
  kinds,
  limits,
  disasterState,
} from "../src/disasters/client";
import { Soundscape } from "../src/narration/soundscape";
import type {
  VoiceView,
  ListeningScope,
  LiveVoices,
} from "../src/narration/live";
import type { AgentCityClient } from "../src/api/client";
import type { WorldFrame } from "../src/api/types";
import type { DisasterState } from "../src/disasters/client";
const flush = async () => {
  for (let n = 0; n < 12; n++) await Promise.resolve();
};
const scope: ListeningScope = {
  simulation: "s",
  revision: null,
  subject: { kind: "agent", id: "a" },
};
const voice: VoiceView = {
  enabled: true,
  paused: false,
  muted: false,
  volume: 0.8,
  hidden: false,
  blocked: false,
  missed: false,
  queued: 0,
  seconds: 0,
  speaking: null,
  error: "",
  status: "",
  generation: 0,
};
const frame = {
  simulation: { id: "s", status: "running" },
  ref: { tick: 1, revision: 1 },
  map: { width_m: 128, height_m: 128 },
  agents: [{ id: "a", active: true, position: { x: 64, y: 64 } }],
} as WorldFrame;
function data(): DisasterState {
  return {
    schema_version: "2.0.0",
    rule_version: "disasters-2.0.0",
    simulation_id: "s",
    ref: { tick: 1, revision: 1 },
    sim_time_seconds: 10,
    events: Array.from({ length: 5 }, (_, i) => ({
      legacy_projection: false,
      id: `event${i}`,
      phase: "active",
      phase_id: `event${i}:active`,
      parameters: defaults("fire", 128, 128, 42),
      normalized_intensity: 0.8,
      unit: "/100",
      start_tick: 1,
      end_tick: null,
      footprint: [],
      current_footprint: [],
      current_origin: { x: 64 + i, y: 64 },
      exposure_count: 0,
      damage_ids: [],
    })),
    vocal_states: { a: { alive: true, conscious: true } },
    service_changes: [],
    conditions: {},
    terrain: [],
    damage: [],
    reactions: [],
    repairs: [],
    rescue_needs: [],
  };
}
class Player {
  src = "";
  volume = 0;
  paused = true;
  loop = false;
  preload = "";
  dataset: Record<string, string> = {};
  played: string[] = [];
  deny = false;
  pause() {
    this.paused = true;
  }
  load() {}
  removeAttribute() {
    this.src = "";
  }
  async play() {
    if (this.deny) throw Error("denied");
    this.paused = false;
    if (!this.src.startsWith("data:")) this.played.push(this.src);
  }
}
function setup(held = false) {
  const players: Player[] = [];
  const calls: unknown[] = [];
  const waiting: Array<(x: unknown) => void> = [];
  const client = {
    call: vi.fn(
      async (
        method: string,
        _path: string,
        _schema: unknown,
        body: unknown,
      ) => {
        if (method === "GET")
          return {
            schema_version: "2.0.0",
            categories: {
              effects: "unverified",
              music: "unverified",
              reactions: "unverified",
            },
            requires_user_gesture: true,
          };
        calls.push(body);
        const result = {
          audio_url: `clip${calls.length}`,
          expires_at: new Date(Date.now() + 60000).toISOString(),
          manifest: {},
        };
        if (held)
          return await new Promise((resolve) =>
            waiting.push(() => resolve(result)),
          );
        return result;
      },
    ),
  };
  const foreground = {
    player: new Player(),
    offerReaction: vi.fn(),
    setCategoryEnabled: vi.fn(),
  } as unknown as LiveVoices;
  let clock = 0;
  const mixer = new Soundscape(
    client as unknown as AgentCityClient,
    foreground,
    () => {
      const p = new Player();
      players.push(p);
      return p as unknown as HTMLAudioElement;
    },
    () => clock,
  );
  return {
    mixer,
    players,
    calls,
    waiting,
    foreground,
    setClock: (n: number) => (clock = n),
  };
}
describe("disaster controls", () => {
  it("DS-01 typed parameters preserve independent extent and source units", () => {
    for (const kind of kinds) {
      const a = defaults(kind, 128, 128, 42);
      const b = parameters.parse({ ...a, extent_m: 60 });
      expect(b.intensity).toBe(limits[kind].default);
      expect(b.origin).toEqual(a.origin);
      expect(limits[kind].unit).toBeTruthy();
    }
  });
  it("DS-01 rejects nonfinite controls before transport", () => {
    expect(
      parameters.safeParse({
        ...defaults("flood", 128, 128, 42),
        intensity: NaN,
      }).success,
    ).toBe(false);
  });
  it("DS-02 compiles natural inputs into the same typed payload", () => {
    expect(
      fromPrompt("earthquake magnitude 6.2 for 20 ticks", 128, 128, 42),
    ).toMatchObject({ kind: "earthquake", intensity: 6.2, duration_ticks: 20 });
    expect(
      fromPrompt("tornado, 60 m/s, 20-meter width", 128, 128, 42),
    ).toMatchObject({ kind: "tornado", intensity: 60, extent_m: 20 });
    expect(fromPrompt("policy change", 128, 128, 42)).toBeNull();
  });
  it("versioned state validates separately from frozen v1", () => {
    expect(disasterState.parse(data()).schema_version).toBe("2.0.0");
  });
});
describe("bounded shared disaster mixer", () => {
  it("DA-03/06 admits two effects and one music only, repeated frames don't regenerate", async () => {
    const t = setup();
    await t.mixer.capabilities();
    t.mixer.enable();
    await flush();
    t.mixer.update(data(), frame, scope, voice);
    await flush();
    expect(t.calls).toHaveLength(3);
    expect(t.players.filter((p) => !p.paused)).toHaveLength(3);
    t.mixer.update(data(), frame, scope, voice);
    await flush();
    expect(t.calls).toHaveLength(3);
    t.mixer.dispose();
    expect(t.players.every((p) => p.paused)).toBe(true);
  });
  it("DA-11 master mute stops every background and late assets cannot play", async () => {
    const t = setup(true);
    await t.mixer.capabilities();
    t.mixer.enable();
    await flush();
    t.mixer.update(data(), frame, scope, voice);
    await flush();
    t.mixer.update(data(), frame, scope, { ...voice, muted: true });
    t.waiting.forEach((r) => r({}));
    await flush();
    expect(t.players.flatMap((p) => p.played)).toHaveLength(0);
    t.mixer.dispose();
  });
  it("DA-12 scope/replay/pause changes invalidate in-flight audio", async () => {
    for (const mode of ["focus", "history", "pause"]) {
      const t = setup(true);
      await t.mixer.capabilities();
      t.mixer.enable();
      await flush();
      t.mixer.update(data(), frame, scope, voice);
      await flush();
      t.mixer.update(
        data(),
        mode === "pause"
          ? { ...frame, simulation: { ...frame.simulation, status: "paused" } }
          : frame,
        mode === "history"
          ? { ...scope, revision: 1 }
          : mode === "focus"
            ? { ...scope, subject: { kind: "agent", id: "b" } }
            : scope,
        voice,
      );
      t.waiting.forEach((r) => r({}));
      await flush();
      expect(t.players.flatMap((p) => p.played)).toHaveLength(0);
      t.mixer.dispose();
    }
  });
  it("DA-10 no citywide reaction burst or historical reaction synthesis", async () => {
    const t = setup();
    await t.mixer.capabilities();
    t.mixer.enable();
    await flush();
    const d = data();
    d.reactions = Array.from({ length: 80 }, (_, i) => ({
      id: `reaction${i}`,
      agent_id: "a",
      event_id: "event0",
      tick: 1,
      revision: 1,
      sim_time_seconds: 10,
      position: { x: 64, y: 64 },
      threat: 0.9,
      kind: "scream" as const,
      text: "Help!",
      episode_id: `episode${i}`,
      evidence_ids: [],
      alive: true,
      conscious: true,
    }));
    t.mixer.update(d, frame, scope, voice);
    await flush();
    expect(t.calls).toHaveLength(3);
    d.reactions.push({ ...d.reactions[0], id: "new-reaction" });
    t.mixer.update(d, frame, scope, voice);
    await flush();
    expect(t.calls).toHaveLength(4);
    expect(t.foreground.offerReaction).toHaveBeenCalledTimes(1);
    t.mixer.dispose();
  });
  it("DA-11 category voice toggle does not mute environmental buses", async () => {
    const t = setup();
    await t.mixer.capabilities();
    t.mixer.enable();
    await flush();
    t.mixer.toggle("voices");
    t.mixer.update(data(), frame, scope, voice);
    await flush();
    expect(t.foreground.setCategoryEnabled).toHaveBeenCalledWith(false);
    expect(t.calls).toHaveLength(3);
    t.mixer.dispose();
  });
});
