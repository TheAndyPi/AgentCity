import { z } from "zod";
import type { AgentCityClient } from "../api/client";
import type { WorldFrame } from "../api/types";
import type { DisasterState } from "../disasters/client";
import {
  LiveVoices,
  silence,
  type ListeningScope,
  type VoiceView,
} from "./live";

const asset = z.object({
  audio_url: z.string(),
  expires_at: z.string(),
  manifest: z.record(z.string(), z.unknown()),
});
const capabilities = z.object({
  schema_version: z.literal("2.0.0"),
  categories: z.object({
    effects: z.string(),
    music: z.string(),
    reactions: z.string(),
  }),
  requires_user_gesture: z.boolean(),
});
type Bus = {
  player: HTMLAudioElement;
  key: string;
  desired: number;
  pending?: AbortController;
  generation: number;
  expiresAt?: number;
};
export type SoundView = {
  enabled: boolean;
  error: string;
  categories: Record<string, string>;
  effects: boolean;
  music: boolean;
  voices: boolean;
};
export function audibleDistance(
  point: { x: number; y: number },
  other: { x: number; y: number },
) {
  return Math.hypot(point.x - other.x, point.y - other.y);
}
/** Owned by LiveVoiceProvider. All backgrounds share this bounded mixer, and
 * reactions use LiveVoices' existing foreground player. No independent voice. */
export class Soundscape {
  private listeners = new Set<() => void>();
  private state: SoundView = {
    enabled: false,
    error: "",
    categories: {
      effects: "unconfigured",
      music: "unconfigured",
      reactions: "unconfigured",
    },
    effects: true,
    music: true,
    voices: true,
  };
  private buses: Bus[];
  private scope = "";
  private generation = 0;
  private seen = new Set<string>();
  private baseline = true;
  private latestData: DisasterState | null = null;
  private reactionPending: AbortController | null = null;
  private times: number[] = [];
  private context?: AudioContext;
  private timer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;
  constructor(
    private client: AgentCityClient,
    private foreground: LiveVoices,
    factory: () => HTMLAudioElement = () => new Audio(),
    private now = () => Date.now(),
  ) {
    this.buses = Array.from({ length: 3 }, () => {
      const player = factory();
      player.loop = true;
      player.preload = "auto";
      player.dataset.audioBus = "disaster";
      player.volume = 0;
      return { player, key: "", desired: 0, generation: 0 };
    });
  }
  subscribe = (cb: () => void) => {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  };
  getSnapshot = () => this.state;
  private emit(patch: Partial<SoundView> = {}) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((cb) => cb());
  }
  async capabilities() {
    this.disposed = false;
    try {
      const result = await this.client.call(
        "GET",
        "/integrations/narration/v2/disaster-capabilities",
        capabilities,
      );
      if (!this.disposed) this.emit({ categories: result.categories });
    } catch {
      /* older or mock backend: voices remain available */
    }
  }
  enable() {
    this.disposed = false;
    if (this.state.enabled) {
      if (this.context)
        void this.context.resume().catch(() => this.failAutoplay());
      return;
    }
    this.emit({ enabled: true, error: "" });
    // Called directly from the gesture for every continuous media element.
    try {
      const Context = globalThis.AudioContext;
      if (Context && !this.context) {
        this.context = new Context();
        const limiter = this.context.createDynamicsCompressor();
        limiter.threshold.value = -16;
        limiter.knee.value = 10;
        limiter.ratio.value = 12;
        limiter.attack.value = 0.003;
        limiter.release.value = 0.25;
        limiter.connect(this.context.destination);
        for (const b of this.buses)
          this.context.createMediaElementSource(b.player).connect(limiter);
        this.context
          .createMediaElementSource(this.foreground.player)
          .connect(limiter);
      }
      if (this.context)
        void this.context.resume().catch(() => this.failAutoplay());
    } catch {
      this.emit({
        error: "Audio mixer unavailable. Resume sound in a supported browser.",
      });
    }
    for (const b of this.buses) {
      const generation = b.generation;
      b.player.src = silence();
      void b.player
        .play()
        .then(() => {
          if (generation === b.generation) {
            b.player.pause();
            b.player.removeAttribute("src");
          }
        })
        .catch(() => {
          if (generation === b.generation) this.failAutoplay();
        });
    }
    if (!this.timer) this.timer = setInterval(() => this.fade(), 50);
    this.baseline = true;
  }
  private failAutoplay() {
    this.stop();
    this.emit({
      enabled: false,
      error: "Browser blocked sound. Enable sound to resume.",
    });
  }
  toggle(category: "effects" | "music" | "voices") {
    this.emit({ [category]: !this.state[category] });
    if (category === "effects") {
      this.stopBus(this.buses[0]);
      this.stopBus(this.buses[1]);
    }
    if (category === "music") this.stopBus(this.buses[2]);
    if (category === "voices")
      this.foreground.setCategoryEnabled(this.state.voices);
  }
  private stopBus(b: Bus, immediate = true) {
    b.pending?.abort();
    b.pending = undefined;
    b.key = "";
    b.expiresAt = undefined;
    b.generation++;
    b.desired = 0;
    if (immediate) {
      b.player.pause();
      b.player.removeAttribute("src");
      b.player.load();
    }
  }
  stop() {
    this.generation++;
    for (const b of this.buses) this.stopBus(b);
    this.reactionPending?.abort();
    this.reactionPending = null;
    this.baseline = true;
  }
  duck(view: VoiceView) {
    const gain = view.muted || view.paused || view.hidden ? 0 : view.volume;
    this.gain = gain;
    this.ducking =
      !!view.speaking || (!this.foreground.player.paused && !view.queued);
    if (gain === 0) this.stop();
  }
  private gain = 0.8;
  private ducking = false;
  private fade() {
    for (const b of this.buses) {
      const target = b.desired * this.gain * (this.ducking ? 0.22 : 1);
      b.player.volume = Math.max(
        0,
        Math.min(0.45, b.player.volume + (target - b.player.volume) * 0.15),
      );
      if (!b.key && b.player.volume < 0.003) {
        b.player.pause();
        b.player.removeAttribute("src");
      }
    }
  }
  private async prepare(
    bus: Bus,
    key: string,
    sid: string,
    revision: number,
    source: string,
    category: string,
    volume: number,
  ) {
    if (
      bus.key === key &&
      (!bus.expiresAt || bus.expiresAt > this.now() + 3000)
    ) {
      bus.desired = volume;
      return;
    }
    this.stopBus(bus);
    bus.key = key;
    bus.desired = volume;
    bus.pending = new AbortController();
    const generation = bus.generation;
    this.emit({
      categories: { ...this.state.categories, [category]: "pending" },
    });
    try {
      const result = await this.client.call(
        "POST",
        `/integrations/narration/v2/simulations/${encodeURIComponent(sid)}/disaster-audio`,
        asset,
        { source_id: source, category, revision },
        crypto.randomUUID(),
        bus.pending.signal,
      );
      if (
        bus.generation !== generation ||
        !this.state.enabled ||
        !bus.key ||
        this.gain === 0
      )
        return;
      bus.expiresAt = Date.parse(result.expires_at);
      bus.player.src = result.audio_url;
      bus.player.volume = 0;
      await bus.player.play();
      if (bus.generation !== generation) {
        bus.player.pause();
        return;
      }
      this.emit({
        categories: { ...this.state.categories, [category]: "ready" },
      });
    } catch (e) {
      if (bus.generation === generation) {
        this.emit({
          categories: { ...this.state.categories, [category]: "unavailable" },
          error: e instanceof Error ? e.message : "Sound unavailable",
        });
        bus.desired = 0;
      }
    } finally {
      if (bus.generation === generation) bus.pending = undefined;
    }
  }
  update(
    data: DisasterState | null,
    frame: WorldFrame,
    scope: ListeningScope,
    view: VoiceView,
    cameraPoint?: { x: number; y: number },
  ) {
    this.latestData = data ?? this.latestData;
    this.duck(view);
    const scopeKey = JSON.stringify(scope);
    if (scopeKey !== this.scope) {
      this.stop();
      this.scope = scopeKey;
      this.seen.clear();
    }
    if (
      !this.state.enabled ||
      view.hidden ||
      view.paused ||
      view.muted ||
      view.volume <= 0 ||
      scope.revision !== null ||
      frame.simulation.status !== "running"
    ) {
      this.stop();
      return;
    }
    if (!data) return;
    const listener =
      scope.subject?.kind === "agent"
        ? frame.agents.find((a) => a.id === scope.subject!.id)?.position
        : (cameraPoint ?? {
            x: frame.map.width_m / 2,
            y: frame.map.height_m / 2,
          });
    if (!listener) return;
    const relevant = data.events
      .filter(
        (e) =>
          e.phase === "active" &&
          e.normalized_intensity > 0 &&
          (!frame.events ||
            frame.events.some((f) => f.id === e.id && f.status === "active")),
      )
      .map((e) => ({
        event: e,
        distance: audibleDistance(listener, e.current_origin),
      }))
      .filter((e) => e.distance < e.event.parameters.extent_m + 40)
      .sort(
        (a, b) =>
          b.event.normalized_intensity / (1 + b.distance / 20) -
            a.event.normalized_intensity / (1 + a.distance / 20) ||
          a.event.id.localeCompare(b.event.id),
      );
    // Hold a still-relevant music choice within a 20% score margin.
    const musicCurrent = relevant.find((e) =>
      this.buses[2].key.startsWith(`${e.event.id}:`),
    );
    const best = relevant[0];
    const music =
      musicCurrent &&
      best &&
      musicCurrent.event.normalized_intensity /
        (1 + musicCurrent.distance / 20) >=
        (0.8 * best.event.normalized_intensity) / (1 + best.distance / 20)
        ? musicCurrent
        : best;
    for (let i = 0; i < 3; i++) {
      const selected = i === 2 ? music : relevant[i];
      const category = i === 2 ? "music" : "effects";
      if (
        !selected ||
        !this.state[category] ||
        ["unconfigured", "unavailable"].includes(
          this.state.categories[category],
        )
      ) {
        if (this.buses[i].key) this.stopBus(this.buses[i], false);
        continue;
      }
      const e = selected.event;
      const band =
        e.normalized_intensity < 0.35
          ? "low"
          : e.normalized_intensity < 0.7
            ? "medium"
            : "high";
      void this.prepare(
        this.buses[i],
        `${e.id}:${band}:${category}`,
        data.simulation_id,
        data.ref.revision,
        e.id,
        category,
        (i === 2 ? 0.2 : 0.32) / (1 + selected.distance / 30),
      );
    }
    const fresh = data.reactions.filter((r) => !this.seen.has(r.id));
    for (const r of data.reactions) this.seen.add(r.id);
    if (this.seen.size > 256)
      this.seen = new Set(data.reactions.map((r) => r.id));
    if (this.baseline) {
      this.baseline = false;
      return;
    }
    this.times = this.times.filter((t) => t > this.now() - 10000);
    if (
      !this.state.voices ||
      ["unconfigured", "unavailable"].includes(
        this.state.categories.reactions,
      ) ||
      this.reactionPending ||
      this.times.length >= 3 ||
      view.queued ||
      view.speaking
    )
      return;
    const candidate = fresh
      .filter(
        (r) =>
          r.alive &&
          r.conscious &&
          data.vocal_states[r.agent_id]?.alive &&
          data.vocal_states[r.agent_id]?.conscious &&
          data.events.some(
            (e) => e.id === r.event_id && e.phase === "active",
          ) &&
          audibleDistance(listener, r.position) <= 20 &&
          frame.agents.some((a) => a.id === r.agent_id && a.active),
      )
      .sort(
        (a, b) =>
          Number(b.agent_id === scope.subject?.id) -
            Number(a.agent_id === scope.subject?.id) || b.threat - a.threat,
      )[0];
    if (!candidate) return;
    const generation = this.generation;
    const started = this.now();
    const controller = new AbortController();
    this.reactionPending = controller;
    this.times.push(started);
    void this.client
      .call(
        "POST",
        `/integrations/narration/v2/simulations/${encodeURIComponent(data.simulation_id)}/disaster-audio`,
        asset,
        {
          source_id: candidate.id,
          category: "reactions",
          revision: data.ref.revision,
        },
        crypto.randomUUID(),
        controller.signal,
      )
      .then((result) => {
        if (
          generation !== this.generation ||
          this.now() - started > 3000 ||
          !this.state.voices
        )
          return;
        if (
          !this.latestData?.vocal_states[candidate.agent_id]?.alive ||
          !this.latestData.vocal_states[candidate.agent_id]?.conscious
        )
          return;
        this.foreground.offerReaction(candidate, result);
      })
      .catch((error) => {
        if (generation === this.generation)
          this.emit({
            error:
              error instanceof Error
                ? error.message
                : "This citizen’s reaction voice is unavailable; captions remain available.",
          });
      })
      .finally(() => {
        if (this.reactionPending === controller) this.reactionPending = null;
      });
  }
  dispose() {
    this.disposed = true;
    this.stop();
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.context) {
      void this.context.close();
      this.context = undefined;
    }
  }
}
