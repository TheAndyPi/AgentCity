import type { Dialogue, WorldFrame } from "../api/types";
import type { AgentCityClient } from "../api/client";
import type { NarrationAudio } from "./results";

export type Subject = { kind: "agent" | "interaction"; id: string } | null;
export type ListeningScope = {
  simulation: string;
  revision: number | null;
  subject: Subject;
};
export function resolveSubject(
  interaction: string | null,
  inspected: string | null,
  focused: string[],
): Subject {
  if (interaction) return { kind: "interaction", id: interaction };
  const id = inspected ?? focused[0];
  return id ? { kind: "agent", id } : null;
}
export const LIMITS = {
  lines: 10,
  seconds: 45,
  prefetch: 2,
  pages: 3,
} as const;
export const order = (a: Dialogue, b: Dialogue) =>
  a.tick - b.tick || a.id.localeCompare(b.id, undefined, { numeric: true });
export const eligible = (line: Dialogue, subject: Subject) =>
  !!subject &&
  (subject.kind === "interaction"
    ? line.interaction_id === subject.id
    : line.speaker_id === subject.id ||
      line.recipient_ids.includes(subject.id));
const estimate = (line: Dialogue) =>
  Math.max(1, line.text.split(/\s+/).length / 2.6 + 0.5);
export function silence() {
  const bytes = new Uint8Array(124),
    view = new DataView(bytes.buffer);
  const text = (offset: number, value: string) =>
    [...value].forEach((c, n) => {
      bytes[offset + n] = c.charCodeAt(0);
    });
  text(0, "RIFF");
  view.setUint32(4, 116, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 8000, true);
  view.setUint32(28, 8000, true);
  view.setUint16(32, 1, true);
  view.setUint16(34, 8, true);
  text(36, "data");
  view.setUint32(40, 80, true);
  bytes.fill(128, 44);
  return "data:audio/wav;base64," + btoa(String.fromCharCode(...bytes));
}

type Entry = {
  line: Dialogue;
  revision: number;
  key: string;
  result?: NarrationAudio;
  loading?: boolean;
  error?: string;
  controller?: AbortController;
  preload?: HTMLAudioElement;
};
export type VoiceView = {
  enabled: boolean;
  paused: boolean;
  muted: boolean;
  volume: number;
  hidden: boolean;
  blocked: boolean;
  missed: boolean;
  queued: number;
  seconds: number;
  speaking: Dialogue | null;
  error: string;
  status: string;
  generation: number;
};

/** One page-owned playback channel. WorldStore notifications feed this directly,
 * independently of React batching. All asynchronous completions carry a generation. */
export class LiveVoices {
  private scope: ListeningScope | null = null;
  private scopeKey = "";
  private generation = 0;
  private queue: Entry[] = [];
  private cursor: Dialogue | null = null;
  private latest: WorldFrame | null = null;
  private reconciling = false;
  private reconciliation?: AbortController;
  private listeners = new Set<() => void>();
  private starting = false;
  private playback = 0;
  private unlocked = false;
  private unlocking = false;
  private blocked = false;
  private missed = false;
  private speaking: Dialogue | null = null;
  private error = "";
  private enabled = false;
  private categoryEnabled = true;
  private paused = false;
  private muted = false;
  private volume = 0.8;
  private hidden = false;
  private discardNextFrame = false;
  readonly player: HTMLAudioElement;
  private view!: VoiceView;

  constructor(
    private client: Pick<AgentCityClient, "liveDialogue" | "dialoguePage">,
    player: HTMLAudioElement,
    preferences?: { muted: boolean; volume: number },
    private createPreloader?: () => HTMLAudioElement,
  ) {
    this.player = player;
    if (preferences) {
      this.muted = preferences.muted;
      this.volume = preferences.volume;
    }
    player.preload = "auto";
    player.setAttribute("aria-label", "Live conversation voice");
    player.onended = () => {
      if (player.ended) this.finish();
    };
    player.onplaying = () => {
      if (this.unlocking) return;
      const head = this.queue[0];
      if (
        head?.result &&
        player.currentSrc === head.result.audio_url &&
        this.canPlay()
      ) {
        this.speaking = head.line;
        this.emit();
      } else this.stopPlayer();
    };
    player.onerror = () => {
      if (this.queue[0]) {
        this.error =
          "Audio unavailable or expired. Retry this line or catch up live.";
        this.paused = true;
        this.speaking = null;
        this.emit();
      }
    };
    this.emit();
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.view;
  private emit() {
    this.view = {
      enabled: this.enabled,
      paused: this.paused,
      muted: this.muted,
      volume: this.volume,
      hidden: this.hidden,
      blocked: this.blocked,
      missed: this.missed,
      queued: this.queue.length,
      seconds: this.queue.reduce((n, e) => n + estimate(e.line), 0),
      speaking: this.speaking,
      error: this.error,
      generation: this.generation,
      status: this.hidden
        ? "Tab hidden — resume when visible"
        : !this.enabled
          ? "Enable live voices"
          : this.paused
            ? "Audio paused — resume listening"
            : this.muted
              ? "Voices muted"
              : this.blocked
                ? "Listening limit reached — catch up live or pause"
                : this.reconciling
                  ? "Checking missed dialogue…"
                  : this.scope?.revision !== null && !this.queue.length
                    ? "History: choose Replay this conversation"
                    : !this.scope?.subject
                      ? "Choose a citizen or watch a conversation"
                      : this.queue[0]?.loading
                        ? "Preparing committed dialogue…"
                        : this.queue.length
                          ? "Listening"
                          : "Listening for new dialogue",
    };
    this.listeners.forEach((l) => l());
  }
  private stopPlayer() {
    this.playback++;
    this.player.pause();
    this.player.removeAttribute("src");
    this.player.load();
    this.speaking = null;
    this.starting = false;
  }
  private clear() {
    this.generation++;
    this.queue.forEach((e) => {
      e.controller?.abort();
      this.releasePreload(e);
    });
    this.reconciliation?.abort();
    this.reconciling = false;
    this.queue = [];
    this.blocked = false;
    this.missed = false;
    this.error = "";
    this.unlocking = false;
    this.stopPlayer();
  }
  configure(scope: ListeningScope, frame: WorldFrame) {
    const key = JSON.stringify(scope);
    if (this.scopeKey === key) {
      this.historicalFrame(frame);
      return;
    }
    this.clear();
    this.scope = scope;
    this.scopeKey = key;
    this.latest =
      scope.revision === null || scope.revision === frame.ref.revision
        ? frame
        : null;
    this.baseline(frame);
    this.emit();
  }
  private baseline(frame: WorldFrame) {
    this.cursor = [...frame.recent_dialogue].sort(order).at(-1) ?? null;
  }
  historicalFrame(frame: WorldFrame) {
    if (
      this.scope?.revision === frame.ref.revision &&
      this.scope.simulation === frame.simulation.id
    )
      this.latest = frame;
  }
  ingest(frame: WorldFrame) {
    if (!this.scope || frame.simulation.id !== this.scope.simulation) return;
    if (this.scope.revision !== null) return;
    this.latest = frame;
    if (!this.categoryEnabled) {
      this.baseline(frame);
      return;
    }
    if (this.discardNextFrame) {
      this.discardNextFrame = false;
      this.baseline(frame);
      return;
    }
    if (
      !this.enabled ||
      this.muted ||
      this.hidden ||
      !this.scope.subject ||
      this.scope.revision !== null
    ) {
      this.baseline(frame);
      return;
    }
    if (this.blocked || this.reconciling) return;
    const lines = [...frame.recent_dialogue].sort(order);
    if (
      lines.length &&
      ((this.cursor && order(lines[0], this.cursor) > 0) ||
        (!this.cursor && lines.length >= 25))
    ) {
      void this.reconcile(frame);
      return;
    }
    this.admit(
      lines.filter((l) => !this.cursor || order(l, this.cursor) > 0),
      frame.ref.revision,
    );
    if (lines.length) this.cursor = lines.at(-1)!;
  }
  private admit(lines: Dialogue[], revision: number) {
    const selected = lines.filter((l) =>
      eligible(l, this.scope?.subject ?? null),
    );
    const seconds = this.queue.reduce((n, e) => n + estimate(e.line), 0);
    if (
      selected.length + this.queue.length > LIMITS.lines ||
      selected.reduce((n, l) => n + estimate(l), seconds) > LIMITS.seconds
    ) {
      // No partial/quiet sentence loss: keep the admitted queue, stop new paid
      // work and require an explicit catch-up choice for the unadmitted interval.
      this.blocked = true;
      this.missed = true;
      this.emit();
      return;
    }
    this.queue.push(
      ...selected.map((line) => ({ line, revision, key: crypto.randomUUID() })),
    );
    this.emit();
    this.pump();
  }
  private async reconcile(frame: WorldFrame, historical = false) {
    const scope = this.scope!;
    const generation = this.generation;
    this.reconciling = true;
    this.emit();
    const controller = (this.reconciliation = new AbortController());
    try {
      const lines: Dialogue[] = [];
      let cursor: string | null = null,
        reached = false;
      for (let page = 0; page < LIMITS.pages; page++) {
        const result = await this.client.dialoguePage(
          scope.simulation,
          frame.ref.revision,
          cursor,
          controller.signal,
        );
        if (generation !== this.generation) return;
        lines.push(...result.items);
        cursor = result.next_cursor;
        reached = historical
          ? !cursor
          : !cursor ||
            result.items.some((l) => this.cursor && order(l, this.cursor) <= 0);
        if (reached) break;
      }
      if (!reached) {
        this.blocked = true;
        this.missed = true;
      } else {
        const unique = [...new Map(lines.map((l) => [l.id, l])).values()].sort(
          order,
        );
        this.admit(
          unique.filter(
            (l) => historical || !this.cursor || order(l, this.cursor) > 0,
          ),
          frame.ref.revision,
        );
        this.cursor = unique.at(-1) ?? this.cursor;
      }
    } catch (e) {
      if (generation !== this.generation) return;
      this.blocked = true;
      this.missed = true;
      this.error =
        e instanceof Error ? e.message : "Could not reconcile dialogue";
    } finally {
      if (generation === this.generation) {
        this.reconciling = false;
        this.emit();
        if (
          !historical &&
          this.latest &&
          this.latest.ref.revision > frame.ref.revision
        )
          this.ingest(this.latest);
      }
    }
  }
  private canPlay() {
    return (
      this.enabled &&
      this.categoryEnabled &&
      !this.muted &&
      !this.paused &&
      !this.hidden
    );
  }
  private pump() {
    if (!this.canPlay() || this.unlocking) return;
    // One current item + at most two next utterances, with at most two requests
    // in flight. At overload no further prefetch is admitted.
    {
      let loading = this.queue.filter((e) => e.loading).length;
      // At overflow, finish already admitted lines one at a time without
      // prefetching. Never strand accepted replies behind the limit warning.
      for (const entry of this.queue.slice(
        0,
        this.blocked ? 1 : 1 + LIMITS.prefetch,
      )) {
        if (loading >= LIMITS.prefetch) break;
        if (!entry.result && !entry.loading && !entry.error) {
          loading++;
          void this.prepare(entry);
        }
      }
    }
    const head = this.queue[0];
    if (!head || !head.result || this.speaking || this.starting) return;
    if (Date.parse(head.result.expires_at) <= Date.now() + 1000) {
      this.releasePreload(head);
      head.result = undefined;
      head.key = crypto.randomUUID();
      this.pump();
      return;
    }
    this.starting = true;
    const generation = this.generation;
    const playback = this.playback;
    this.player.volume = this.volume;
    this.player.muted = this.muted;
    if (this.player.getAttribute("src") !== head.result.audio_url)
      this.player.src = head.result.audio_url;
    void this.player
      .play()
      .then(() => {
        if (generation !== this.generation || playback !== this.playback)
          return;
        this.unlocked = true;
        this.starting = false;
      })
      .catch(() => {
        if (generation !== this.generation || playback !== this.playback)
          return;
        this.starting = false;
        this.paused = true;
        this.speaking = null;
        this.error =
          "Browser playback was blocked. Resume listening to allow audio.";
        this.emit();
      });
  }
  private releasePreload(entry: Entry) {
    if (!entry.preload) return;
    entry.preload.removeAttribute("src");
    entry.preload.load();
    entry.preload = undefined;
  }
  private async prepare(entry: Entry) {
    const scope = this.scope!,
      generation = this.generation;
    // Queued text is immutable, but an old live revision may have fallen between
    // durable checkpoints. Pin the first request to the newest displayed frame.
    // Retries keep that exact revision and idempotency key.
    if (!entry.controller && scope.revision === null && this.latest)
      entry.revision = this.latest.ref.revision;
    entry.loading = true;
    entry.controller = new AbortController();
    this.emit();
    try {
      entry.result = await this.client.liveDialogue(
        scope.simulation,
        entry.line.id,
        entry.revision,
        entry.key,
        entry.controller.signal,
      );
      if (generation !== this.generation) return;
      // Fetch upcoming audio while the current line plays, rather than waiting
      // for its turn to start the media download. Never play this element.
      if (this.createPreloader && this.queue[0] !== entry) {
        entry.preload = this.createPreloader();
        entry.preload.preload = "auto";
        entry.preload.src = entry.result.audio_url;
        entry.preload.load();
      }
    } catch (e) {
      if (generation !== this.generation) return;
      entry.error = e instanceof Error ? e.message : "Voice unavailable";
    } finally {
      if (generation === this.generation) {
        entry.loading = false;
        if (this.queue[0]?.error) {
          this.error = this.queue[0].error!;
          this.paused = true;
        }
        this.emit();
        this.pump();
      }
    }
  }
  private finish() {
    if (!this.speaking) return;
    const finished = this.queue.shift();
    if (finished) this.releasePreload(finished);
    // Keep this media element's browser permission while idle. Source/focus
    // changes still remove its source immediately through clear().
    this.playback++;
    this.player.pause();
    this.speaking = null;
    this.starting = false;
    if (this.queue[0]?.error) {
      this.error = this.queue[0].error!;
      this.paused = true;
    }
    this.emit();
    this.pump();
  }
  offerReaction(
    reaction: {
      id: string;
      agent_id: string;
      event_id: string;
      tick: number;
      text: string;
      kind: string;
    },
    result: NarrationAudio,
  ) {
    if (!this.canPlay() || this.queue.length || this.scope?.revision !== null)
      return false;
    const line: Dialogue = {
      id: reaction.id,
      interaction_id: reaction.event_id,
      tick: reaction.tick,
      speaker_id: reaction.agent_id,
      recipient_ids: [],
      audible_to_ids: [],
      text: reaction.text,
      intent: reaction.kind,
      emotion: "afraid",
      end_conversation: true,
    };
    this.queue.push({
      line,
      revision: this.latest?.ref.revision ?? 0,
      key: crypto.randomUUID(),
      result,
    });
    this.emit();
    this.pump();
    return true;
  }
  enable() {
    if (this.hidden) return;
    this.enabled = true;
    this.paused = false;
    this.error = "";
    // Site activation comes from this button gesture. A remembered preference
    // never invokes this method; a rejected play still requires Resume.
    this.emit();
    if (!this.unlocked && !this.queue[0]?.result) {
      // A real media play call *inside* the gesture unlocks this one element;
      // merely setting enabled would lose transient activation during synthesis.
      this.unlocking = true;
      const generation = this.generation;
      this.player.src = silence();
      void this.player
        .play()
        .then(() => {
          if (generation !== this.generation) return;
          this.unlocked = true;
          this.unlocking = false;
          this.stopPlayer();
          this.pump();
        })
        .catch(() => {
          if (generation !== this.generation) return;
          this.unlocking = false;
          this.paused = true;
          this.error =
            "Browser playback was blocked. Resume listening to allow audio.";
          this.emit();
        });
      return;
    }
    this.pump();
  }
  pause() {
    this.playback++;
    this.starting = false;
    this.paused = true;
    this.player.pause();
    this.speaking = null;
    this.emit();
  }
  mute(value: boolean) {
    this.muted = value;
    if (value) {
      this.clear();
      if (this.latest) this.baseline(this.latest);
    }
    this.emit();
    this.pump();
  }
  setCategoryEnabled(value: boolean) {
    this.categoryEnabled = value;
    this.clear();
    if (this.latest) this.baseline(this.latest);
    this.emit();
  }
  setVolume(value: number) {
    this.volume = Math.max(0, Math.min(1, value));
    this.player.volume = this.volume;
    this.emit();
  }
  visibility(hidden: boolean) {
    this.hidden = hidden;
    if (hidden) {
      this.clear();
      this.paused = true;
    }
    if (!hidden) this.discardNextFrame = true;
    if (this.latest) this.baseline(this.latest);
    this.emit();
  }
  catchUp() {
    this.clear();
    if (this.latest) this.baseline(this.latest);
    this.emit();
  }
  skip() {
    this.stopPlayer();
    const finished = this.queue.shift();
    if (finished) this.releasePreload(finished);
    this.error = "";
    this.paused = false;
    this.emit();
    this.pump();
  }
  retry() {
    const head = this.queue[0];
    if (head) {
      head.error = undefined;
      // Expired response needs a new receipt. Response loss retains exact body/key.
      if (head.result) {
        this.releasePreload(head);
        head.result = undefined;
        head.key = crypto.randomUUID();
      }
    }
    this.enable();
  }
  replay() {
    if (!this.latest || this.scope?.subject?.kind !== "interaction") return;
    this.clear();
    this.enabled = true;
    this.paused = false;
    void this.reconcile(this.latest, true);
  }
  revoke() {
    this.enabled = false;
    this.paused = true;
    this.clear();
    this.emit();
  }
  dispose() {
    this.clear();
    this.scopeKey = "";
    this.scope = null;
    this.emit();
  }
}
