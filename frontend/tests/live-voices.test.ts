import { describe, expect, it } from "vitest";
import type { Dialogue, WorldFrame } from "../src/api/types";
import {
  eligible,
  LIMITS,
  LiveVoices,
  resolveSubject,
  type ListeningScope,
} from "../src/narration/live";

const line = (
  n: number,
  speaker = n % 2 ? "a" : "b",
  recipient = speaker === "a" ? "b" : "a",
  interaction = "chat",
): Dialogue => ({
  id: `dialogue_${String(n).padStart(8, "0")}`,
  tick: Math.floor(n / 2),
  speaker_id: speaker,
  recipient_ids: [recipient],
  audible_to_ids: ["overhearer"],
  interaction_id: interaction,
  text: `Committed line ${n}`,
  intent: "talk",
  emotion: "calm",
  end_conversation: n === 4,
});
const frame = (revision: number, lines: Dialogue[], simulation = "s") =>
  ({
    simulation: { id: simulation },
    ref: { revision, tick: revision },
    recent_dialogue: lines,
  }) as WorldFrame;
const scope = (
  id = "a",
  kind: "agent" | "interaction" = "agent",
  revision: number | null = null,
  simulation = "s",
): ListeningScope => ({
  simulation,
  revision,
  subject: { id, kind },
});
const result = (id: string) => ({
  audio_url: `https://city.test/${id}`,
  expires_at: new Date(Date.now() + 60_000).toISOString(),
});
const flush = async () => {
  for (let i = 0; i < 15; i++) await Promise.resolve();
};
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
class Player {
  src = "";
  volume = 1;
  muted = false;
  paused = true;
  ended = false;
  get currentSrc() {
    return this.src;
  }
  currentTime = 0;
  onended?: () => void;
  onplaying?: () => void;
  onerror?: () => void;
  played: string[] = [];
  reject = false;
  setAttribute() {}
  getAttribute() {
    return this.src;
  }
  removeAttribute() {
    this.src = "";
    this.currentTime = 0;
  }
  load() {}
  pause() {
    this.paused = true;
  }
  async play() {
    if (this.reject) throw new Error("autoplay denied");
    this.paused = false;
    this.ended = false;
    if (!this.src.startsWith("data:")) this.played.push(this.src);
    this.onplaying?.();
  }
  end() {
    this.ended = true;
    this.paused = true;
    this.onended?.();
  }
}
function setup(createPreloader?: () => HTMLAudioElement) {
  const calls: {
    id: string;
    revision: number;
    key: string;
    signal?: AbortSignal;
  }[] = [];
  const player = new Player();
  let synth = async (id: string) => result(id);
  let page = async () => ({
    items: [] as Dialogue[],
    next_cursor: null as string | null,
    revision: 1,
  });
  const voices = new LiveVoices(
    {
      liveDialogue: async (_s, id, revision, key, signal) => {
        calls.push({ id, revision, key, signal });
        return synth(id);
      },
      dialoguePage: async () => page(),
    },
    player as unknown as HTMLAudioElement,
    undefined,
    createPreloader,
  );
  voices.configure(scope(), frame(0, []));
  return {
    voices,
    player,
    calls,
    synth: (fn: typeof synth) => {
      synth = fn;
    },
    page: (fn: typeof page) => {
      page = fn;
    },
  };
}

describe("live conversation voices", () => {
  it("downloads upcoming audio before its turn and releases it on a scope change", async () => {
    const preloaders: Player[] = [];
    const s = setup(() => {
      const audio = new Player();
      preloaders.push(audio);
      return audio as unknown as HTMLAudioElement;
    });
    s.voices.enable();
    await flush();
    s.voices.ingest(frame(1, [line(1), line(2), line(3)]));
    await flush();
    expect(s.player.played).toEqual([result(line(1).id).audio_url]);
    expect(preloaders.map((p) => p.src)).toEqual([
      result(line(2).id).audio_url,
      result(line(3).id).audio_url,
    ]);
    expect(preloaders.every((p) => p.played.length === 0)).toBe(true);
    s.voices.configure(scope("b"), frame(1, []));
    expect(preloaders.every((p) => p.src === "")).toBe(true);
  });
  it("LV-06 drains admitted replies without further prefetch when newer turns overflow", async () => {
    const s = setup();
    s.voices.enable();
    await flush();
    s.voices.pause();
    s.voices.ingest(frame(1, [line(1), line(2), line(3), line(4)]));
    s.voices.ingest(
      frame(
        2,
        Array.from({ length: 14 }, (_, i) => line(i + 1)),
      ),
    );
    expect(s.voices.getSnapshot().blocked).toBe(true);
    s.voices.enable();
    await flush();
    expect(s.calls).toHaveLength(1);
    for (let n = 1; n <= 4; n++) {
      expect(s.voices.getSnapshot().speaking?.id).toBe(line(n).id);
      s.player.end();
      await flush();
    }
    expect(s.calls.map((c) => c.id)).toEqual(
      [1, 2, 3, 4].map((n) => line(n).id),
    );
    expect(s.voices.getSnapshot()).toMatchObject({
      queued: 0,
      blocked: true,
      missed: true,
    });
  });
  it("pins delayed live synthesis to a recent displayed revision", async () => {
    const s = setup();
    s.voices.enable();
    await flush();
    s.voices.pause();
    s.voices.ingest(frame(1, [line(1), line(2)]));
    s.voices.ingest(frame(20, [line(1), line(2)]));
    s.voices.enable();
    await flush();
    expect(s.calls).toHaveLength(2);
    expect(s.calls.every((c) => c.revision === 20)).toBe(true);
  });
  it("LV-03 reconciles frames arriving during a slow gap reconciliation", async () => {
    const s = setup();
    s.voices.ingest(frame(1, [line(1)]));
    s.voices.enable();
    const gate = deferred<{
      items: Dialogue[];
      next_cursor: string | null;
      revision: number;
    }>();
    let pages = 0;
    s.page(async () => {
      pages++;
      return pages === 1
        ? gate.promise
        : {
            items: [line(6), line(5), line(4)],
            next_cursor: null,
            revision: 6,
          };
    });
    s.voices.ingest(frame(4, [line(4)]));
    s.voices.ingest(frame(6, [line(6)]));
    gate.resolve({
      items: [line(4), line(3), line(2), line(1)],
      next_cursor: null,
      revision: 4,
    });
    await flush();
    expect(pages).toBe(2);
    expect(s.voices.getSnapshot().queued).toBe(6);
    for (let n = 1; n <= 6; n++) {
      await flush();
      expect(s.voices.getSnapshot().speaking?.id).toBe(line(n).id);
      s.player.end();
    }
  });
  it("LV-05 drops the first fresh visible snapshot rather than reading a hidden-tab gap", async () => {
    const s = setup();
    s.voices.enable();
    s.voices.visibility(true);
    s.voices.visibility(false);
    s.voices.enable();
    s.voices.ingest(frame(4, [line(1), line(2), line(3), line(4)]));
    await flush();
    expect(s.calls).toHaveLength(0);
    s.voices.ingest(frame(5, [line(4), line(5)]));
    await flush();
    expect(s.calls.map((c) => c.id)).toEqual([line(5).id]);
  });
  it("LV-01 preserves a four-turn exchange, orders same-tick ties and has one active channel", async () => {
    const { voices, calls, player } = setup();
    voices.configure(scope("chat", "interaction"), frame(0, []));
    voices.enable();
    voices.ingest(frame(4, [line(4), line(2), line(1), line(3)]));
    await flush();
    expect(calls.length).toBe(3);
    expect(player.played).toEqual([result(line(1).id).audio_url]);
    for (let i = 1; i <= 4; i++) {
      expect(voices.getSnapshot().speaking?.id).toBe(line(i).id);
      player.end();
      await flush();
    }
    expect(player.played).toEqual(
      [1, 2, 3, 4].map((n) => result(line(n).id).audio_url),
    );
    expect(voices.getSnapshot().queued).toBe(0);
  });
  it("LV-02 filters direct replies, excludes audible background and resolves one scope", async () => {
    expect(resolveSubject("chat", "b", ["c"])).toEqual({
      kind: "interaction",
      id: "chat",
    });
    expect(resolveSubject(null, "b", ["c", "d"])).toEqual({
      kind: "agent",
      id: "b",
    });
    expect(resolveSubject(null, null, [])).toBeNull();
    expect(eligible(line(1), { kind: "agent", id: "overhearer" })).toBe(false);
    const { voices, calls } = setup();
    voices.enable();
    voices.ingest(frame(4, [line(1), line(2), line(3, "x", "y", "other")]));
    await flush();
    expect(calls.map((c) => c.id)).toEqual([line(1).id, line(2).id]);
  });
  it("LV-03 reads existing dialogue immediately and deduplicates subsequent snapshots", async () => {
    const { voices, calls, player } = setup();
    voices.configure(scope("b"), frame(1, [line(1)]));
    voices.enable();
    expect(calls.map((call) => call.id)).toEqual([line(1).id]);
    for (let rev = 2; rev < 5; rev++)
      voices.ingest(frame(rev, [line(1), line(2)]));
    await flush();
    expect(calls).toHaveLength(2);
    player.end();
    voices.dispose();
    voices.configure(scope("b"), frame(6, [line(1), line(2)]));
    voices.ingest(frame(7, [line(1), line(2)]));
    await flush();
    expect(calls.map((call) => call.id)).toEqual([line(1).id, line(2).id, line(1).id, line(2).id]);
  });
  it("LV-04 aborts pending old work and stops playing on subject/simulation changes", async () => {
    const s = setup(),
      gate = deferred<ReturnType<typeof result>>();
    s.synth(() => gate.promise);
    s.voices.enable();
    s.voices.ingest(frame(1, [line(1)]));
    await flush();
    s.voices.configure(scope("x"), frame(2, [line(1)]));
    expect(s.calls[0].signal?.aborted).toBe(true);
    gate.resolve(result("stale"));
    await flush();
    expect(s.player.played).toEqual([]);
    s.synth(async (id) => result(id));
    s.voices.configure(scope(), frame(2, [line(1)]));
    s.voices.ingest(frame(3, [line(1), line(2)]));
    await flush();
    expect(s.player.paused).toBe(false);
    s.voices.configure(
      scope("a", "agent", null, "branch"),
      frame(1, [line(2)], "branch"),
    );
    expect(s.player.paused).toBe(true);
    expect(s.player.src).toBe("");
    s.voices.ingest(frame(2, [line(2)], "branch"));
    await flush();
    expect(s.calls).toHaveLength(4);
  });
  it("LV-05 requires a gesture, preserves audio pause, hides without backlog and handles autoplay denial", async () => {
    const { voices, calls, player } = setup();
    voices.ingest(frame(1, [line(1)]));
    await flush();
    expect(calls).toHaveLength(0);
    voices.enable();
    player.reject = true;
    voices.ingest(frame(2, [line(1), line(2)]));
    await flush();
    expect(voices.getSnapshot().error).toContain("Browser playback");
    player.reject = false;
    voices.enable();
    await flush();
    expect(player.paused).toBe(false);
    voices.pause();
    expect(player.paused).toBe(true);
    voices.enable();
    await flush();
    expect(player.played).toHaveLength(2);
    voices.visibility(true);
    voices.ingest(frame(3, [line(3)]));
    voices.visibility(false);
    await flush();
    expect(voices.getSnapshot().paused).toBe(true);
    expect(player.paused).toBe(true);
    voices.enable();
    voices.ingest(frame(4, [line(3)]));
    await flush();
    expect(calls).toHaveLength(2);
    voices.mute(true);
    voices.ingest(frame(5, [line(4)]));
    voices.mute(false);
    await flush();
    expect(calls).toHaveLength(2);
  });
  it("LV-06 bounds paid prefetch to two pending calls and shows overload without dropping ordinary turns", async () => {
    const s = setup(),
      gate = deferred<ReturnType<typeof result>>();
    s.synth(() => gate.promise);
    s.voices.enable();
    s.voices.ingest(frame(1, [line(1), line(2), line(3), line(4)]));
    await flush();
    expect(s.calls).toHaveLength(2);
    s.voices.ingest(
      frame(
        2,
        Array.from({ length: 14 }, (_, i) => line(i + 1)),
      ),
    );
    await flush();
    expect(s.voices.getSnapshot()).toMatchObject({
      blocked: true,
      missed: true,
      queued: 4,
    });
    expect(s.calls).toHaveLength(2);
    expect(s.voices.getSnapshot().seconds).toBeLessThanOrEqual(LIMITS.seconds);
    s.voices.catchUp();
    expect(s.voices.getSnapshot().queued).toBe(0);
    gate.resolve(result("obsolete"));
    await flush();
    expect(s.player.played).toEqual([]);
  });
  it("LV-06/08 retries response loss with exact key/body and errors retain the line", async () => {
    const s = setup();
    let attempts = 0;
    s.synth(async (id) => {
      if (++attempts === 1) throw new Error("response lost");
      return result(id);
    });
    s.voices.enable();
    s.voices.ingest(frame(1, [line(1)]));
    await flush();
    expect(s.voices.getSnapshot().queued).toBe(1);
    s.voices.ingest(frame(2, [line(1)]));
    s.voices.retry();
    await flush();
    expect(s.calls).toHaveLength(2);
    expect(s.calls[1]).toMatchObject({
      key: s.calls[0].key,
      revision: s.calls[0].revision,
      id: s.calls[0].id,
    });
    s.voices.revoke();
    expect(s.player.paused).toBe(true);
    expect(s.voices.getSnapshot().enabled).toBe(false);
  });
  it("LV-03 reconciles a pinned reconnect gap and refuses unbounded history", async () => {
    const s = setup();
    s.voices.enable();
    s.voices.ingest(frame(1, [line(1)]));
    await flush();
    s.player.end();
    let pages = 0;
    s.page(async () => {
      pages++;
      return {
        items: [line(4), line(3), line(2), line(1)],
        next_cursor: null,
        revision: 8,
      };
    });
    s.voices.ingest(frame(8, [line(4)]));
    await flush();
    expect(s.calls.map((c) => c.id)).toEqual(
      [1, 2, 3, 4].map((n) => line(n).id),
    );
    expect(pages).toBe(1);
    s.page(async () => {
      pages++;
      return { items: [line(100)], next_cursor: "more", revision: 100 };
    });
    s.voices.ingest(frame(100, [line(100)]));
    await flush();
    expect(pages).toBe(4);
    expect(s.voices.getSnapshot().missed).toBe(true);
  });
  it("requests focused audio before history fetches or media unlock completes", async () => {
    const s = setup();
    s.page(async () => { throw new Error("History should not be requested"); });
    s.voices.configure(scope("chat", "interaction"), frame(1, [line(2), line(1)]));
    s.voices.listenToConversation();
    expect(s.calls.map((call) => call.id)).toEqual([line(1).id, line(2).id]);
    await flush();
    s.voices.ingest(frame(2, [line(1), line(2)]));
    expect(s.calls).toHaveLength(2);
    expect(s.player.played).toEqual([result(line(1).id).audio_url]);
  });
  it("replay starts a selected conversation without enabling the radio first", async () => {
    const s = setup();
    s.voices.configure(scope("chat", "interaction"), frame(1, [line(1)]));
    s.page(async () => ({
      items: [line(1), line(2, "a", "b", "other")],
      next_cursor: null,
      revision: 1,
    }));
    s.voices.replay();
    await flush();
    expect(s.voices.getSnapshot().enabled).toBe(true);
    expect(s.calls.map((call) => call.id)).toEqual([line(1).id]);
    expect(s.player.played).toEqual([result(line(1).id).audio_url]);
  });
  it("LV-09 scrubbing stops audio; historical replay is explicit and revision pinned", async () => {
    const s = setup();
    s.voices.enable();
    s.voices.ingest(frame(1, [line(1)]));
    await flush();
    s.voices.configure(scope("chat", "interaction", 1), frame(1, [line(1)]));
    expect(s.player.paused).toBe(true);
    s.voices.ingest(frame(10, [line(10)]));
    await flush();
    expect(s.calls).toHaveLength(1);
    s.page(async () => ({ items: [line(1)], next_cursor: null, revision: 1 }));
    s.voices.replay();
    await flush();
    expect(s.calls[1].revision).toBe(1);
    s.voices.configure(scope("chat", "interaction"), frame(10, [line(10)]));
    s.voices.ingest(frame(11, [line(10)]));
    await flush();
    expect(s.calls).toHaveLength(3);
    expect(s.calls[2].id).toBe(line(10).id);
  });
});
