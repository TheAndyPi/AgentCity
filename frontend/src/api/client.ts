import { z } from "zod";
import * as S from "./schemas";
import type * as T from "./types";
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public retryable = false,
    public details: { field: string | null; reason: string }[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export interface Transport {
  mode: "live" | "mock";
  request(
    method: string,
    path: string,
    body?: unknown,
    key?: string,
    signalOrTimeout?: AbortSignal | number,
  ): Promise<unknown>;
  subscribe?(id: string, cb: (frame: T.WorldFrame) => void): () => void;
}
export class AgentCityClient {
  constructor(public transport: Transport) {}
  get mode() {
    return this.transport.mode;
  }
  async call<T>(
    method: string,
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    key?: string,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await this.transport.request(
      method,
      path,
      body,
      method === "GET" ? undefined : (key ?? crypto.randomUUID()),
      signal,
    );
    const failed = S.failure.safeParse(response);
    if (failed.success) {
      const e = failed.data.error;
      if (e.code === "UNAUTHENTICATED" && typeof window !== "undefined")
        window.dispatchEvent(new Event("agentcity:session-expired"));
      throw new ApiError(e.code, e.message, e.retryable, e.details);
    }
    const result = S.success(schema).safeParse(response);
    if (!result.success)
      throw new ApiError(
        "CONTRACT_ERROR",
        `Response does not match contract 1.0.0: ${result.error.issues[0]?.path.join(".")} ${result.error.issues[0]?.message}`,
      );
    return result.data.data;
  }
  capabilities = () => this.call("GET", "/capabilities", S.capabilities);
  session = () =>
    this.call(
      "GET",
      "/session",
      z
        .object({
          authenticated: z.boolean(),
          csrf_token: z.string().nullable(),
        })
        .strict(),
    );
  login = (passphrase: string) =>
    this.call(
      "POST",
      "/session",
      z.object({ csrf_token: z.string() }).strict(),
      { passphrase },
    );
  simulations = (archived = false) =>
    this.all(`/simulations?archived=${archived}`, S.simulation);
  simulation = (id: string) =>
    this.call("GET", `/simulations/${encodeURIComponent(id)}`, S.simulation);
  create = (config: T.Config, key: string) =>
    this.call(
      "POST",
      "/simulations",
      S.simulation,
      { config: S.config.parse(config) },
      key,
    );
  state = (id: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/state${query({ revision })}`,
      S.world,
    );
  command = (
    s: T.Simulation,
    command: T.CommandBody,
    key: string = crypto.randomUUID(),
  ) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(s.id)}/commands`,
      S.commandResult,
      S.commandRequest.parse({
        request_id: key,
        expected_control_version: s.control_version,
        command,
      }),
      key,
    );
  agents = (id: string, revision?: number, q?: string) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/agents${query({ revision, q })}`,
      S.agent,
    );
  agent = (id: string, a: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/agents/${encodeURIComponent(a)}${query({ revision })}`,
      S.agentDetail,
    );
  collection = (
    id: string,
    a: string,
    collection: "memories" | "relationships" | "decisions",
    revision: number,
  ) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/agents/${encodeURIComponent(a)}/${collection}${query({ revision })}`,
      collection === "memories"
        ? S.memory
        : collection === "relationships"
          ? S.relationship
          : (S.decision as z.ZodTypeAny),
    );
  decision = (id: string, d: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/decisions/${encodeURIComponent(d)}${query({ revision })}`,
      S.decision,
    );
  events = (id: string, revision?: number) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/events${query({ revision })}`,
      S.event,
    );
  report = (id: string, e: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/events/${encodeURIComponent(e)}${query({ revision })}`,
      S.eventReport,
    );
  overview = (id: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/overview${query({ revision })}`,
      S.overview,
    );
  dialogue = (id: string, revision?: number) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/dialogue${query({ revision })}`,
      S.dialogue,
    );
  metrics = (id: string, revision?: number) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/metrics${query({ revision })}`,
      z.object({ points: z.array(S.metricPoint) }).strict(),
    );
  timeline = (id: string) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/timeline`,
      z
        .object({
          ref: S.ref,
          sim_time_seconds: z.number().finite().nonnegative(),
        })
        .strict(),
    );
  snapshots = (id: string, revision?: number) =>
    this.all(
      `/simulations/${encodeURIComponent(id)}/snapshots${query({ revision })}`,
      S.snapshot,
    );
  intervene = (s: T.Simulation, key: string = crypto.randomUUID()) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(s.id)}/interventions`,
      S.intervention,
      S.interventionRequest.parse({
        expected_control_version: s.control_version,
      }),
      key,
    );
  preview = (
    id: string,
    body: {
      intervention_id: string;
      source: "random" | "repeat" | "custom" | "policy";
      source_event_id: string | null;
      prompt: string | null;
      policy: T.Policies | null;
    },
    key: string = crypto.randomUUID(),
  ) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(id)}/scenario-previews`,
      S.preview,
      S.previewRequest.parse(body),
      key,
    );
  cancel = (id: string, i: T.Intervention, key: string = crypto.randomUUID()) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(id)}/interventions/${encodeURIComponent(i.id)}/cancel`,
      S.simulation,
      S.interventionRequest.parse({
        expected_control_version: i.control_version,
      }),
      key,
    );
  commit = (id: string, i: T.Intervention, p: T.ScenarioPreview, key: string) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(id)}/scenario-commits`,
      z
        .object({
          simulation: S.simulation,
          event: S.event,
          snapshot: S.snapshot,
        })
        .strict(),
      S.commitRequest.parse({
        intervention_id: i.id,
        preview_id: p.id,
        expected_control_version: i.control_version,
      }),
      key,
    );
  initial = (s: T.Simulation, decision: "confirm" | "skip", key: string) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(s.id)}/initial-scenario`,
      z
        .object({
          simulation: S.simulation,
          event: S.event.nullable(),
          snapshot: S.snapshot.nullable(),
        })
        .strict(),
      S.initialRequest.parse({
        preview_id: s.initial_preview!.id,
        decision,
        expected_control_version: s.control_version,
      }),
      key,
    );
  branch = (
    id: string,
    name: string,
    source:
      | { kind: "whole" }
      | { kind: "revision"; revision: number }
      | { kind: "snapshot"; snapshot_id: string },
    key: string = crypto.randomUUID(),
  ) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(id)}/branches`,
      z.object({ simulation: S.simulation, snapshot: S.snapshot }).strict(),
      S.branchRequest.parse({ name, source }),
      key,
    );
  delete = (s: T.Simulation) =>
    this.call(
      "DELETE",
      `/simulations/${encodeURIComponent(s.id)}`,
      z.object({ deleted_id: z.string() }).strict(),
      { confirmation_name: s.name },
    );
  profiles = () => this.all("/custom-agents", S.customAgent);
  saveProfile = (
    profile: T.Profile,
    existing?: T.CustomAgent,
    key: string = crypto.randomUUID(),
  ) =>
    this.call(
      existing ? "PUT" : "POST",
      `/custom-agents${existing ? `/${encodeURIComponent(existing.id)}` : ""}`,
      S.customAgent,
      existing
        ? {
            expected_version: existing.version,
            profile: S.profile.parse(profile),
          }
        : { profile: S.profile.parse(profile) },
      key,
    );
  deleteProfile = (p: T.CustomAgent) =>
    this.call(
      "DELETE",
      `/custom-agents/${encodeURIComponent(p.id)}`,
      z.object({ deleted_id: z.string() }).strict(),
      { expected_version: p.version },
    );
  settings = () => this.call("GET", "/settings", S.settings);
  saveSettings = (s: T.Settings, key: string = crypto.randomUUID()) => {
    const { version, ...settings } = S.settings.parse(s);
    return this.call(
      "PUT",
      "/settings",
      S.settings,
      {
        expected_version: version,
        settings,
      },
      key,
    );
  };
  usage = (id?: string) =>
    this.call("GET", `/usage${query({ simulation_id: id })}`, S.usage);
  templates = () =>
    this.call(
      "GET",
      "/templates",
      z
        .object({
          items: z.array(
            z
              .object({
                id: z.string(),
                title: z.string(),
                description: z.string(),
                config: S.config,
              })
              .strict(),
          ),
        })
        .strict(),
    );
  narration = (
    id: string,
    source_type: "event" | "decision" | "dialogue",
    source_id: string,
    key?: string,
  ) =>
    this.call(
      "POST",
      `/simulations/${encodeURIComponent(id)}/narration`,
      z
        .object({
          audio_url: z.string().url(),
          expires_at: z.string().datetime(),
        })
        .strict(),
      { source_type, source_id },
      key,
    );
  liveDialogue = (
    id: string,
    source_id: string,
    revision: number,
    key: string,
    signal?: AbortSignal,
  ) =>
    this.call(
      "POST",
      `/integrations/narration/v1/simulations/${encodeURIComponent(id)}/dialogue`,
      z
        .object({
          audio_url: z.string().url(),
          expires_at: z.string().datetime(),
        })
        .strict(),
      { source_id, revision },
      key,
      signal,
    );
  dialoguePage = (
    id: string,
    revision: number,
    cursor?: string | null,
    signal?: AbortSignal,
  ) =>
    this.call(
      "GET",
      `/simulations/${encodeURIComponent(id)}/dialogue${query({ revision, limit: 100, cursor: cursor ?? undefined })}`,
      S.page(S.dialogue),
      undefined,
      undefined,
      signal,
    );
  exportUrl = (id: string, revision: number) =>
    `${apiBase}/simulations/${encodeURIComponent(id)}/export?format=csv&through_revision=${revision}`;
  async all<Item>(path: string, schema: z.ZodType<Item>): Promise<Item[]> {
    const items: Item[] = [];
    let cursor: string | null = null;
    do {
      const next: T.Page<Item> = await this.call(
        "GET",
        `${path}${path.includes("?") ? "&" : "?"}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        S.page(schema),
      );
      items.push(...next.items);
      cursor = next.next_cursor;
    } while (cursor);
    return items;
  }
}
export function query(values: Record<string, string | number | undefined>) {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== undefined) p.set(k, String(v));
  });
  return p.size ? `?${p}` : "";
}
export const apiBase = import.meta.env.VITE_API_BASE_URL || "/api/v1";
export function websocketUrl(
  id: string,
  base = apiBase,
  origin = window.location.origin,
) {
  const url = new URL(
    `${base}/simulations/${encodeURIComponent(id)}/stream`,
    origin,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
export class LiveTransport implements Transport {
  readonly mode = "live" as const;
  csrf: string | null = null;
  private sessionReady: Promise<void> | null = null;
  async request(
    method: string,
    path: string,
    body?: unknown,
    key?: string,
    signalOrTimeout?: AbortSignal | number,
  ): Promise<unknown> {
    const signal =
      typeof signalOrTimeout === "number" ? undefined : signalOrTimeout;
    const timeoutMs =
      typeof signalOrTimeout === "number"
        ? signalOrTimeout
        : signal
          ? 30000
          : 15000;
    if (
      method !== "GET" &&
      !(method === "POST" && path === "/session") &&
      !this.csrf
    ) {
      this.sessionReady ??= this.request("GET", "/session")
        .then((result) => {
          const failed = S.failure.safeParse(result);
          if (failed.success)
            throw new ApiError(
              failed.data.error.code,
              failed.data.error.message,
            );
          if (!this.csrf)
            throw new ApiError(
              "UNAUTHENTICATED",
              "Sign in before changing your city.",
            );
        })
        .finally(() => {
          this.sessionReady = null;
        });
      await this.sessionReady;
    }
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (key) headers["Idempotency-Key"] = key;
    if (method !== "GET" && this.csrf) headers["X-CSRF-Token"] = this.csrf;
    let response: Response;
    try {
      response = await fetch(`${apiBase}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "include",
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)])
          : AbortSignal.timeout(timeoutMs),
      });
    } catch {
      throw new ApiError(
        "CONNECTION_ERROR",
        "Cannot reach the AgentCity server. The current view is preserved. Retry uses the same operation key.",
        true,
      );
    }
    let json: unknown;
    try {
      json = await response.json();
    } catch {
      throw new ApiError(
        "INVALID_RESPONSE",
        "The server did not return a JSON contract envelope. Check the API proxy.",
        true,
      );
    }
    if (path === "/session" && response.ok) {
      const parsed = json as T.Success<{ csrf_token: string | null }>;
      this.csrf = parsed.data?.csrf_token ?? null;
    }
    return json;
  }
}
