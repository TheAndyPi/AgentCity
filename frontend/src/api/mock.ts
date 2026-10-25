import type * as T from "./types";
import type { Transport } from "./client";
import { ApiError } from "./client";
import * as S from "./schemas";
import {
  fixtureMapFor,
  fixtureWorld,
  fixtureSimulation,
  fixtureAgents,
  fixtureDetail,
  fixturePreview,
  fixtureDate,
  baseline,
  recordedOutcomes,
  emptyEvidence,
  recordedOffsets,
} from "./fixtures";
import { defaultConfig, defaultSettings } from "./defaults";
type RecordState = {
  frame: T.WorldFrame;
  frames: T.WorldFrame[];
  snapshots: T.Snapshot[];
  reports: Record<string, T.EventReport>;
  hold: T.Intervention | null;
  preview: T.ScenarioPreview | null;
  stage: number;
  eventStep: number;
  profiles: Record<string, T.Profile>;
  outcomeResume: boolean;
  eventBaseline?: T.MetricPoint;
};
const copy = <T>(a: T): T => structuredClone(a);
const page = <T>(items: T[]) => ({ items, next_cursor: null });
export class MockTransport implements Transport {
  readonly mode = "mock" as const;
  worlds = new Map<string, RecordState>();
  profiles: T.CustomAgent[] = [];
  settings = copy(defaultSettings);
  listeners = new Map<string, Set<(f: T.WorldFrame) => void>>();
  results = new Map<string, { request: string; result: unknown }>();
  constructor() {
    if (typeof sessionStorage !== "undefined") {
      try {
        const stored = JSON.parse(
          sessionStorage.getItem("agentcity-review-fixtures-v1") ?? "null",
        );
        if (stored) {
          this.profiles = stored.profiles.map((p: unknown) =>
            S.customAgent.parse(p),
          );
          this.settings = S.settings.parse(stored.settings);
          for (const [id, raw] of stored.worlds) {
            const r = raw as RecordState;
            const map = fixtureMapFor(r.frame.simulation.config);
            r.frame = S.world.parse({ ...r.frame, map });
            r.frames = r.frames.map((f) => S.world.parse({ ...f, map }));
            if (r.frame.simulation.status === "running" || r.hold) {
              r.frame.simulation.status = "paused";
              r.frame.simulation.pause_reason = "loaded";
              r.hold = null;
              r.preview = null;
              r.outcomeResume = false;
              this.publish(r, true);
            }
            this.worlds.set(id, r);
          }
          return;
        }
      } catch {
        sessionStorage.removeItem("agentcity-review-fixtures-v1");
      }
    }
    this.add(fixtureWorld());
    const archived = fixtureSimulation("preview-harbor", {
      ...defaultConfig,
      name: "Harbor, after the rain",
      mode: "crisis_lab",
    });
    archived.archived = true;
    this.add(fixtureWorld(archived));
  }
  private cache() {
    if (typeof sessionStorage === "undefined") return;
    try {
      sessionStorage.setItem(
        "agentcity-review-fixtures-v1",
        JSON.stringify(
          {
            profiles: this.profiles,
            settings: this.settings,
            worlds: [...this.worlds],
          },
          (key, value) => (key === "map" ? undefined : value),
        ),
      );
    } catch {
      console.warn(
        "Mock review cache is full; this fixture session will remain in memory.",
      );
    }
  }
  private add(frame: T.WorldFrame) {
    const snap: T.Snapshot = {
      id: "snapshot-initial",
      simulation_id: frame.simulation.id,
      ref: copy(frame.ref),
      created_at: fixtureDate,
      reason: "initial",
      label: "Initial city",
    };
    const r: RecordState = {
      frame,
      frames: [copy(frame)],
      snapshots: [snap],
      reports: {},
      hold: null,
      preview: null,
      stage: 0,
      eventStep: 0,
      profiles: {},
      outcomeResume: false,
    };
    this.worlds.set(frame.simulation.id, r);
    return r;
  }
  private publish(r: RecordState, control = false) {
    const s = r.frame.simulation;
    s.revision++;
    if (control) s.control_version++;
    s.updated_at = new Date().toISOString();
    r.frame.ref = { tick: s.tick, revision: s.revision };
    r.frame.metrics = {
      ...r.frame.metrics,
      tick: s.tick,
      revision: s.revision,
    };
    r.frames.push(copy(r.frame));
    this.listeners.get(s.id)?.forEach((cb) => cb(copy(r.frame)));
    this.cache();
    return s;
  }
  private save(r: RecordState, reason: T.Snapshot["reason"], label: string) {
    const s = r.frame.simulation;
    const snapshot: T.Snapshot = {
      id: crypto.randomUUID(),
      simulation_id: s.id,
      ref: copy(r.frame.ref),
      created_at: new Date().toISOString(),
      reason,
      label,
    };
    r.snapshots.push(snapshot);
    s.latest_snapshot_id = snapshot.id;
    s.saved_at = snapshot.created_at;
    return snapshot;
  }
  private tick(r: RecordState) {
    const s = r.frame.simulation;
    if (
      s.initial_preview ||
      r.hold ||
      s.pending_outcome_event_ids.length ||
      s.archived ||
      s.tick >= s.config.max_ticks
    )
      return;
    s.tick++;
    s.calendar_time_seconds =
      (s.calendar_time_seconds ?? s.sim_time_seconds) +
      (s.config.calendar_seconds_per_tick ?? s.config.tick_seconds * 12);
    s.sim_time_seconds = s.tick * s.config.tick_seconds;
    s.achieved_ticks_per_second =
      s.status === "running"
        ? (20 / s.config.tick_seconds) * s.speed_multiplier
        : 0;
    const sample =
      recordedOffsets[Math.min(s.tick, recordedOffsets.length - 1)];
    const base = fixtureAgents(s.agent_count);
    r.frame.agents = r.frame.agents.map((a, i) => ({
      ...a,
      position: { x: base[i].position.x + sample.x, y: base[i].position.y },
      path: [],
      action: s.tick % 3 === 0 ? "talk" : a.action,
    }));
    const e = r.frame.events.find(
      (e) => e.status === "queued" || e.status === "active",
    );
    if (e) {
      r.eventStep++;
      e.status = "active";
      e.start_tick ??= s.tick;
      r.frame.active_hazards = ["flood", "fire", "storm"].includes(e.kind)
        ? [
            {
              event_id: e.id,
              kind: e.kind as "flood" | "fire" | "storm",
              polygon: e.affected_polygon,
              severity: 60,
            },
          ]
        : [];
      const sample = recordedOutcomes[e.kind];
      if (
        s.tick >=
        (e.start_tick ?? s.tick) + r.reports[e.id].spec.duration_ticks
      ) {
        e.status = "resolved";
        e.end_tick = s.tick;
        s.status = "paused";
        s.pause_reason = "outcome";
        s.pending_outcome_event_ids = [e.id];
        s.control_version++;
        r.frame.active_hazards = [];
        r.frame.metrics = {
          ...r.frame.metrics,
          values: copy(sample.values),
          cooperation_count:
            (r.eventBaseline?.cooperation_count ?? 0) + sample.cooperation,
          conflict_count:
            (r.eventBaseline?.conflict_count ?? 0) + sample.conflicts,
          resources_consumed:
            (r.eventBaseline?.resources_consumed ?? 0) + sample.consumed,
          evacuated_count: sample.evacuated,
          exposed_count: sample.exposed,
        };
        r.frame.map.zones = r.frame.map.zones.map((z) => ({
          ...z,
          metrics: copy(sample.values),
        }));
        r.frame.agents = r.frame.agents.map((a) => ({
          ...a,
          metrics: copy(sample.values),
        }));
      }
      const p = r.reports[e.id];
      p.event = copy(e);
      p.ref = { tick: s.tick, revision: s.revision + 1 };
      p.after = copy(r.frame.metrics.values);
      p.delta = Object.fromEntries(
        Object.keys(baseline).map((k) => [
          k,
          p.after[k as T.Metric] - p.before[k as T.Metric],
        ]),
      ) as Record<T.Metric, number>;
      if (e.status === "resolved") {
        p.conflicts = sample.conflicts;
        p.resources_consumed = sample.consumed;
        p.evacuated_count = sample.evacuated;
        p.exposed_count = sample.exposed;
        p.consequences = [
          {
            text: sample.consequence,
            evidence: { ...emptyEvidence, event_ids: [e.id] },
          },
        ];
        p.community_lessons = [
          {
            text: sample.lesson,
            evidence: { ...emptyEvidence, event_ids: [e.id] },
          },
        ];
        p.suggested_preparations = [
          "Consider increasing shared supplies near the shelter.",
          "Explore how a broadcast evacuation order changes the response.",
        ];
      }
    }
    r.frame.recent_dialogue = [
      {
        id: "dialogue-1",
        interaction_id: "interaction-1",
        tick: 2,
        speaker_id: "citizen-1",
        recipient_ids: ["citizen-2"],
        audible_to_ids: ["citizen-1", "citizen-2"],
        text: "Let’s check on our neighbors. The shelter is open.",
        intent: "talk",
        emotion: "Concerned",
        end_conversation: false,
      },
      {
        id: "dialogue-2",
        interaction_id: "interaction-1",
        tick: 3,
        speaker_id: "citizen-2",
        recipient_ids: ["citizen-1"],
        audible_to_ids: ["citizen-1", "citizen-2"],
        text: "Good idea, Maya. I'll stop by the square and see who needs a hand.",
        intent: "talk",
        emotion: "Reassured",
        end_conversation: false,
      },
      {
        id: "dialogue-3",
        interaction_id: "interaction-1",
        tick: 4,
        speaker_id: "citizen-1",
        recipient_ids: ["citizen-2"],
        audible_to_ids: ["citizen-1", "citizen-2"],
        text: "Thank you, Oliver. It helps knowing we're looking out for each other.",
        intent: "talk",
        emotion: "Grateful",
        end_conversation: true,
      },
    ].filter((message) => message.tick <= s.tick);
    if (s.tick >= s.config.max_ticks && !s.pending_outcome_event_ids.length) {
      s.status = "completed";
      s.pause_reason = null;
    }
    this.publish(r);
  }
  subscribe(id: string, cb: (f: T.WorldFrame) => void) {
    let set = this.listeners.get(id);
    if (!set) {
      set = new Set();
      this.listeners.set(id, set);
    }
    set.add(cb);
    let lastTick = performance.now();
    const timer = setInterval(() => {
      const r = this.worlds.get(id);
      if (r?.frame.simulation.status === "running") {
        const now = performance.now();
        const interval =
          (1000 * r.frame.simulation.config.tick_seconds) /
          (20 * r.frame.simulation.speed_multiplier);
        if (now - lastTick >= interval) {
          this.tick(r);
          lastTick = now;
        }
      }
    }, 50);
    return () => {
      clearInterval(timer);
      set.delete(cb);
    };
  }
  async request(
    method: string,
    path: string,
    body?: unknown,
    key?: string,
  ): Promise<unknown> {
    await new Promise((resolve) => setTimeout(resolve, 100));
    const signature = JSON.stringify({ method, path, body });
    if (key && this.results.has(key)) {
      const hit = this.results.get(key)!;
      if (hit.request !== signature)
        throw new ApiError(
          "IDEMPOTENCY_CONFLICT",
          "This operation key belongs to a different request.",
        );
      return copy(hit.result);
    }
    let result: unknown;
    try {
      result = await this.route(method, path, body as any);
    } catch (e) {
      const error =
        e instanceof ApiError
          ? {
              code: e.code,
              message: e.message,
              retryable: e.retryable,
              details: e.details,
            }
          : {
              code: "VALIDATION_ERROR",
              message: e instanceof Error ? e.message : "Invalid request",
              retryable: false,
              details: [],
            };
      return {
        schema_version: "1.0.0",
        request_id: key ?? crypto.randomUUID(),
        error,
      };
    }
    this.cache();
    const envelope = {
      schema_version: "1.0.0",
      request_id: key ?? crypto.randomUUID(),
      data: copy(result),
    };
    if (key)
      this.results.set(key, { request: signature, result: copy(envelope) });
    return envelope;
  }
  private async route(method: string, path: string, b: any): Promise<unknown> {
    const url = new URL(path, "https://fixture.local");
    const parts = url.pathname.split("/").filter(Boolean);
    const [root, id, resource, item, collection] = parts;
    if (root === "capabilities")
      return {
        contract_version: "1.0.0",
        auth_mode: "local",
        max_agents: 100,
        max_concurrent_running_simulations: 1,
        gemini: false,
        narration: false,
        snowflake: false,
        persistence: "local",
        replay: true,
        branching: true,
      };
    if (root === "session")
      return method === "GET"
        ? { authenticated: true, csrf_token: null }
        : { csrf_token: "fixture-only" };
    if (root === "settings") {
      if (method === "PUT") {
        if (b.expected_version !== this.settings.version)
          throw new ApiError(
            "CONTROL_CONFLICT",
            "Settings changed. Reload and try again.",
          );
        this.settings = S.settings.parse({
          ...b.settings,
          version: this.settings.version + 1,
        });
      }
      return this.settings;
    }
    if (root === "usage")
      return {
        simulation_id: url.searchParams.get("simulation_id"),
        input_tokens: 0,
        output_tokens: 0,
        cached_tokens: 0,
        calls: 0,
        failed_calls: 0,
        estimated_cost_usd: null,
        pricing_as_of: null,
      };
    if (root === "templates")
      return {
        items: [
          [
            "flood",
            "The rising tide",
            "A flood tests the strength of neighborhood ties.",
          ],
          [
            "shortage",
            "Enough to go around?",
            "A supply shortage brings cooperation into focus.",
          ],
          [
            "misinformation",
            "Whispers in the city",
            "An unverified warning spreads between neighbors.",
          ],
          [
            "festival",
            "A reason to come together",
            "A festival creates space for new connections.",
          ],
          ["policy", "A helping hand", "Explore a community aid policy."],
        ].map(([id, title, description]) => ({
          id,
          title,
          description,
          config: {
            ...defaultConfig,
            name: title,
            mode: id === "policy" ? "policy_lab" : "sandbox",
            scenario_description: `Introduce a ${id} in the neighborhood.`,
          },
        })),
      };
    if (root === "custom-agents") {
      if (method === "GET") return page(this.profiles);
      if (method === "POST") {
        const p = {
          id: crypto.randomUUID(),
          version: 0,
          profile: S.profile.parse(b.profile),
          updated_at: new Date().toISOString(),
        };
        this.profiles.push(p);
        return p;
      }
      const p = this.profiles.find((p) => p.id === id);
      if (!p) throw new ApiError("NOT_FOUND", "Profile not found.");
      if (b.expected_version !== p.version)
        throw new ApiError(
          "CONTROL_CONFLICT",
          "Profile changed. Reload and try again.",
        );
      if (method === "DELETE") {
        this.profiles = this.profiles.filter((p) => p.id !== id);
        return { deleted_id: id };
      }
      p.profile = S.profile.parse(b.profile);
      p.version++;
      return p;
    }
    if (root !== "simulations")
      throw new ApiError("NOT_FOUND", "Unknown fixture endpoint.");
    if (!id) {
      if (method === "GET")
        return page(
          [...this.worlds.values()]
            .map((r) => r.frame.simulation)
            .filter(
              (s) =>
                s.archived === (url.searchParams.get("archived") === "true"),
            ),
        );
      const config = S.config.parse(b.config);
      const s = fixtureSimulation(crypto.randomUUID(), config);
      s.status = "initializing";
      s.initialization = {
        stage: "queued",
        progress: 0,
        message: "Getting your simulation ready",
        error: null,
      };
      const selected = this.profiles.filter((p) =>
        config.custom_agent_ids.includes(p.id),
      );
      const r = this.add(
        fixtureWorld(s, fixtureAgents(config.population, selected)),
      );
      selected.forEach((p, i) => {
        r.profiles[`citizen-${i + 1}`] = copy(p.profile);
      });
      return s;
    }
    const r = this.worlds.get(id);
    if (!r)
      throw new ApiError(
        "NOT_FOUND",
        "This review fixture is no longer available. Return to Previous simulations.",
      );
    const s = r.frame.simulation;
    const revision = url.searchParams.get("revision");
    const selected =
      revision === null
        ? r.frame
        : r.frames.find((f) => f.ref.revision === Number(revision));
    if (!selected)
      throw new ApiError(
        "HISTORY_UNAVAILABLE",
        "This committed revision is unavailable.",
      );
    if (!resource) {
      if (method === "DELETE") {
        if (!s.archived || b.confirmation_name !== s.name)
          throw new ApiError(
            "INVALID_STATE",
            "Archive the city and confirm its exact name first.",
          );
        this.worlds.delete(id);
        return { deleted_id: id };
      }
      if (s.status === "initializing") {
        const stages: T.Job[] = [
          {
            stage: "map",
            progress: 26,
            message: "Laying out streets and gathering places",
            error: null,
          },
          {
            stage: "population",
            progress: 51,
            message: "Welcoming your citizens",
            error: null,
          },
          {
            stage: "relationships",
            progress: 73,
            message: "Connecting neighbors and shared histories",
            error: null,
          },
          {
            stage: "persistence",
            progress: 94,
            message: "Almost there · validating the recorded city",
            error: null,
          },
          {
            stage: "ready",
            progress: 100,
            message: "Your city is ready",
            error: null,
          },
        ];
        s.initialization = stages[Math.min(r.stage++, 4)];
        if (s.initialization.stage === "ready") {
          s.status = "paused";
          s.pause_reason = "loaded";
          if (s.config.scenario_description) {
            s.initial_preview = fixturePreview(
              r.frame,
              "initial",
              s.config.scenario_description,
            );
            s.initial_preview.based_on = {
              tick: s.tick,
              revision: s.revision + 1,
            };
          }
          this.publish(r, true);
        }
      }
      return s;
    }
    if (resource === "state") return selected;
    if (resource === "agents") {
      if (!item)
        return page(
          selected.agents.filter((a) =>
            a.name
              .toLowerCase()
              .includes((url.searchParams.get("q") ?? "").toLowerCase()),
          ),
        );
      if (!selected.agents.some((a) => a.id === item))
        throw new ApiError(
          "NOT_FOUND",
          "This citizen does not exist at the selected revision.",
        );
      const detail = fixtureDetail(selected, item, r.profiles[item]);
      return collection
        ? detail[collection as "memories" | "relationships" | "decisions"]
        : detail;
    }
    if (resource === "decisions") {
      const a = selected.agents.find((a) => a.latest_decision_id === item);
      if (!a)
        throw new ApiError(
          "NOT_FOUND",
          "Decision not available at this revision.",
        );
      return fixtureDetail(selected, a.id).decisions.items[0];
    }
    if (resource === "events") {
      if (!item) return page(selected.events);
      const p = r.reports[item];
      if (!p || !selected.events.some((e) => e.id === item))
        throw new ApiError(
          "NOT_FOUND",
          "Event not available at this revision.",
        );
      return {
        ...p,
        ref: selected.ref,
        event: selected.events.find((e) => e.id === item),
        after: selected.metrics.values,
        delta: Object.fromEntries(
          Object.keys(baseline).map((k) => [
            k,
            selected.metrics.values[k as T.Metric] - p.before[k as T.Metric],
          ]),
        ),
        consequences:
          selected.events.find((e) => e.id === item)?.status === "resolved"
            ? p.consequences
            : [],
        community_lessons:
          selected.events.find((e) => e.id === item)?.status === "resolved"
            ? p.community_lessons
            : [],
      };
    }
    if (resource === "dialogue") {
      const agentId = url.searchParams.get("agent_id"),
        interactionId = url.searchParams.get("interaction_id");
      const lines = [...selected.recent_dialogue]
        .reverse()
        .filter(
          (line) =>
            (!agentId ||
              line.speaker_id === agentId ||
              line.recipient_ids.includes(agentId)) &&
            (!interactionId || line.interaction_id === interactionId),
        );
      const offset = Number(url.searchParams.get("cursor") ?? 0),
        limit = Math.min(100, Number(url.searchParams.get("limit") ?? 25));
      return {
        items: lines.slice(offset, offset + limit),
        next_cursor:
          offset + limit < lines.length ? String(offset + limit) : null,
      };
    }
    if (resource === "timeline")
      return page(
        r.frames.map((f) => ({
          ref: f.ref,
          sim_time_seconds: f.simulation.sim_time_seconds,
        })),
      );
    if (resource === "snapshots")
      return page(
        r.snapshots.filter((p) => p.ref.revision <= selected.ref.revision),
      );
    if (resource === "metrics")
      return {
        points: r.frames
          .filter((f) => f.ref.revision <= selected.ref.revision)
          .map((f) => f.metrics),
      };
    if (resource === "overview")
      return {
        ref: selected.ref,
        metrics: selected.metrics,
        top_events: selected.events
          .filter((e) => e.status === "resolved")
          .map((e) => ({
            event_id: e.id,
            title: e.title,
            impact_score: 55,
            evidence: { ...emptyEvidence, event_ids: [e.id] },
          }))
          .slice(0, 3),
        improvements: [],
        metric_reasons: Object.keys(baseline).map((metric) => ({
          metric,
          text: "Arithmetic mean of active citizens in this recorded fixture.",
          evidence: emptyEvidence,
        })),
      };
    if (resource === "commands") {
      const req = S.commandRequest.parse(b);
      if (req.expected_control_version !== s.control_version)
        throw new ApiError(
          "CONTROL_CONFLICT",
          "The city changed. Refresh and retry.",
        );
      const c = req.command;
      let snapshot: T.Snapshot | null = null;
      let affected_agent_ids: string[] = [];
      if (c.type === "play" || c.type === "step") {
        if (
          r.hold ||
          s.initial_preview ||
          s.pending_outcome_event_ids.length ||
          s.archived ||
          s.status === "completed" ||
          s.tick >= s.config.max_ticks
        )
          throw new ApiError(
            "INVALID_STATE",
            "Resolve the open event, preview, or report before continuing.",
          );
      }
      if (c.type === "play") {
        r.outcomeResume = true;
        s.status = "running";
        s.pause_reason = null;
      } else if (c.type === "pause") {
        s.status = "paused";
        s.pause_reason = "manual";
        r.outcomeResume = false;
        if (r.hold) r.hold.was_running = false;
      } else if (c.type === "step") {
        if (s.status !== "paused")
          throw new ApiError("INVALID_STATE", "Pause before stepping.");
        r.outcomeResume = false;
        for (let n = 0; n < c.count; n++) {
          this.tick(r);
          if (s.pending_outcome_event_ids.length) break;
        }
      } else if (c.type === "set_speed") s.speed_multiplier = c.value;
      else if (c.type === "save") {
        if (c.reason === "navigation") {
          s.status = "paused";
          s.pause_reason = "manual";
          r.hold = null;
          r.preview = null;
          r.outcomeResume = false;
        }
        snapshot = this.save(r, c.reason, c.label);
      } else if (c.type === "archive") {
        s.status = "paused";
        s.archived = true;
        r.hold = null;
        r.preview = null;
        snapshot = this.save(r, "navigation", "Archived city");
      } else if (c.type === "unarchive") {
        s.archived = false;
        s.status = "paused";
      } else if (c.type === "acknowledge_outcome") {
        if (!s.pending_outcome_event_ids.includes(c.event_id))
          throw new ApiError(
            "INVALID_STATE",
            "This report was already acknowledged.",
          );
        s.pending_outcome_event_ids = s.pending_outcome_event_ids.filter(
          (e) => e !== c.event_id,
        );
        if (c.resume && r.outcomeResume) {
          s.status = "running";
          s.pause_reason = null;
        }
      } else if (c.type === "add_agents") {
        if (r.hold)
          throw new ApiError(
            "INTERVENTION_OPEN",
            "Close the event editor first.",
          );
        if (s.agent_count + c.custom_agent_ids.length > 100)
          throw new ApiError(
            "VALIDATION_ERROR",
            "A city supports at most 100 citizens.",
          );
        const selected = this.profiles.filter((p) =>
          c.custom_agent_ids.includes(p.id),
        );
        const extra = fixtureAgents(s.agent_count + selected.length)
          .slice(s.agent_count)
          .map((a, i) => ({
            ...a,
            name: selected[i].profile.name,
            role: selected[i].profile.role,
          }));
        extra.forEach((a, i) => {
          r.profiles[a.id] = copy(selected[i].profile);
        });
        r.frame.agents.push(...extra);
        s.agent_count = r.frame.agents.length;
        affected_agent_ids = extra.map((a) => a.id);
      } else if (c.type === "override_agent" || c.type === "set_relationship") {
        if (r.hold)
          throw new ApiError(
            "INTERVENTION_OPEN",
            "Close the event editor first.",
          );
        throw new ApiError(
          "FEATURE_UNAVAILABLE",
          "Audited overrides require the real backend; the review adapter does not simulate them.",
        );
      }
      this.publish(r, true);
      return { simulation: s, snapshot, affected_agent_ids };
    }
    if (resource === "interventions" && !item) {
      if (b.expected_control_version !== s.control_version)
        throw new ApiError("CONTROL_CONFLICT", "The city changed. Try again.");
      if (r.hold)
        throw new ApiError("INTERVENTION_OPEN", "An editor is already open.");
      if (
        s.initial_preview ||
        s.pending_outcome_event_ids.length ||
        s.archived ||
        s.status === "initializing"
      )
        throw new ApiError(
          "INVALID_STATE",
          "Resolve the pending city workflow first.",
        );
      if (
        r.frame.events.some(
          (e) => e.status === "active" || e.status === "queued",
        )
      )
        throw new ApiError(
          "EVENT_ACTIVE",
          "Wait for the current event to resolve.",
        );
      const was_running = s.status === "running";
      s.status = "paused";
      s.pause_reason = "intervention";
      this.publish(r, true);
      r.hold = {
        id: crypto.randomUUID(),
        simulation_id: id,
        expires_at: new Date(Date.now() + 600000).toISOString(),
        based_on: copy(r.frame.ref),
        was_running,
        control_version: s.control_version,
      };
      return r.hold;
    }
    if (resource === "interventions" && item && parts[4] === "cancel") {
      if (!r.hold || r.hold.id !== item)
        throw new ApiError(
          "PREVIEW_EXPIRED",
          "The editor has already expired.",
        );
      if (b.expected_control_version !== s.control_version)
        throw new ApiError(
          "CONTROL_CONFLICT",
          "Playback changed while this editor was open.",
        );
      if (Date.parse(r.hold.expires_at) < Date.now()) {
        s.status = "paused";
        s.pause_reason = "manual";
        r.hold = null;
        r.preview = null;
        this.publish(r, true);
        return s;
      }
      s.status = r.hold.was_running ? "running" : "paused";
      s.pause_reason = r.hold.was_running ? null : "manual";
      r.hold = null;
      r.preview = null;
      this.publish(r, true);
      return s;
    }
    if (resource === "scenario-previews") {
      if (!r.hold || b.intervention_id !== r.hold.id)
        throw new ApiError("PREVIEW_EXPIRED", "Open a new event editor.");
      if (Date.parse(r.hold.expires_at) < Date.now())
        throw new ApiError("PREVIEW_EXPIRED", "The event editor expired.");
      r.preview = fixturePreview(r.frame, b.source, b.prompt ?? "");
      if (b.source === "policy")
        r.preview.spec.effects = [{ type: "policy", ...b.policy }];
      if (b.source === "repeat") {
        const previous = r.reports[b.source_event_id];
        if (!previous || previous.event.status !== "resolved")
          throw new ApiError("INVALID_REQUEST", "Select a resolved event.");
        r.preview.spec = copy(previous.spec);
        r.preview.source_event_id = b.source_event_id;
      }
      return r.preview;
    }
    if (resource === "scenario-commits" || resource === "initial-scenario") {
      const initial = resource === "initial-scenario";
      const p = initial ? s.initial_preview : r.preview;
      if (!p || p.id !== b.preview_id)
        throw new ApiError("PREVIEW_STALE", "Request a fresh preview.");
      if (!initial && (!r.hold || r.hold.id !== b.intervention_id))
        throw new ApiError("PREVIEW_EXPIRED", "The editor expired.");
      if (
        b.expected_control_version !== s.control_version ||
        p.based_on.revision !== r.frame.ref.revision
      )
        throw new ApiError(
          "PREVIEW_STALE",
          "The city changed. Request a new preview.",
        );
      if (Date.parse(p.expires_at) < Date.now())
        throw new ApiError("PREVIEW_EXPIRED", "The preview expired.");
      if (!p.can_commit)
        throw new ApiError(
          "INVALID_REQUEST",
          "This preview cannot be committed.",
        );
      if (initial && b.decision === "skip") {
        s.initial_preview = null;
        this.publish(r, true);
        return { simulation: s, event: null, snapshot: null };
      }
      const snapshot = this.save(r, "pre_event", `Before ${p.spec.title}`);
      const e: T.EventSummary = {
        id: crypto.randomUUID(),
        title: p.spec.title,
        kind: p.spec.kind,
        status: "queued",
        queued_tick: s.tick,
        start_tick: null,
        end_tick: null,
        affected_agent_count: p.affected_agent_ids.length,
        affected_polygon: p.spec.affected_polygon,
        pre_event_snapshot_id: snapshot.id,
        summary: p.interpretation,
        scene: copy(p.spec.scene ?? []),
      };
      r.frame.events.push(e);
      r.reports[e.id] = {
        ref: copy(r.frame.ref),
        event: copy(e),
        spec: copy(p.spec),
        before: copy(r.frame.metrics.values),
        after: copy(r.frame.metrics.values),
        delta: { happiness: 0, safety: 0, trust: 0, resources: 0, stress: 0 },
        affected_agent_ids: p.affected_agent_ids,
        conflicts: 0,
        resources_consumed: 0,
        evacuated_count: 0,
        exposed_count: 0,
        consequences: [],
        community_lessons: [],
        suggested_preparations: [],
      };
      r.eventStep = 0;
      r.eventBaseline = copy(r.frame.metrics);
      r.outcomeResume = r.hold?.was_running ?? false;
      s.status = r.outcomeResume ? "running" : "paused";
      s.initial_preview = null;
      r.hold = null;
      r.preview = null;
      this.publish(r, true);
      return { simulation: s, event: e, snapshot };
    }
    if (resource === "branches") {
      let f = r.frame;
      if (b.source.kind === "revision") {
        f = r.frames.find((f) => f.ref.revision === b.source.revision)!;
      } else if (b.source.kind === "snapshot") {
        const snap = r.snapshots.find((p) => p.id === b.source.snapshot_id);
        f = r.frames.find((f) => f.ref.revision === snap?.ref.revision)!;
      }
      if (!f)
        throw new ApiError(
          "HISTORY_UNAVAILABLE",
          "The selected source is unavailable.",
        );
      const newId = crypto.randomUUID();
      const frame = copy(f);
      frame.simulation = {
        ...frame.simulation,
        id: newId,
        name: b.name,
        parent_simulation_id: id,
        fork_ref: copy(f.ref),
        status: "paused",
        pause_reason: "loaded",
        control_version: 0,
        archived: false,
        initial_preview: null,
      };
      const branch = this.add(frame);
      branch.frames = r.frames
        .filter((x) => x.ref.revision <= f.ref.revision)
        .map((x) => {
          const y = copy(x);
          y.simulation.id = newId;
          return y;
        });
      branch.snapshots = copy(
        r.snapshots.filter((x) => x.ref.revision <= f.ref.revision),
      ).map((x) => ({ ...x, simulation_id: newId }));
      branch.reports = Object.fromEntries(
        Object.entries(copy(r.reports)).filter(([id]) =>
          frame.events.some((e) => e.id === id),
        ),
      );
      branch.profiles = copy(r.profiles);
      this.publish(branch);
      const snapshot = this.save(branch, "branch", "Restored branch");
      return { simulation: branch.frame.simulation, snapshot };
    }
    throw new ApiError(
      "FEATURE_UNAVAILABLE",
      "This operation is not available in the frontend review adapter.",
    );
  }
}
