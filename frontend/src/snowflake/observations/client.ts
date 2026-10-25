import { z } from "zod";
import { ApiError, type Transport } from "../../api/client";
import { failure } from "../../api/schemas";
import {
  changesSchema,
  envelope,
  eventDetailSchema,
  eventsSchema,
  metricsSchema,
  statusSchema,
  trendsSchema,
} from "./schema";

export type Selection = {
  through_revision: number;
  start_tick?: number;
  end_tick?: number;
  agent_id?: string;
  event_id?: string;
};
type Cache = { expires: number; data: unknown };

export class ObservationsClient {
  private cache = new Map<string, Cache>();
  constructor(
    private transport: Transport,
    private now = () => Date.now(),
  ) {}
  invalidate() {
    this.cache.clear();
  }

  private async get<
    T extends {
      simulation_id: string;
      requested_revision: number;
      effective_revision: number | null;
    },
  >(
    sid: string,
    route: string,
    schema: z.ZodType<T>,
    params: Selection & Record<string, string | number | undefined>,
    signal?: AbortSignal,
  ): Promise<T> {
    signal?.throwIfAborted();
    if (this.transport.mode !== "live")
      throw new ApiError(
        "FEATURE_UNAVAILABLE",
        "Snowflake observations require a live connection.",
      );
    if (
      !Number.isSafeInteger(params.through_revision) ||
      params.through_revision < 0
    )
      throw new ApiError(
        "INVALID_REQUEST",
        "An explicit historical revision is required.",
      );
    const search = new URLSearchParams();
    Object.entries(params)
      .sort(([a], [b]) => a.localeCompare(b))
      .forEach(([key, value]) => {
        if (value !== undefined && value !== "") search.set(key, String(value));
      });
    const path = `/integrations/snowflake/observations/v1/simulations/${encodeURIComponent(sid)}/${route}?${search}`;
    const cached = this.cache.get(path);
    if (cached && cached.expires > this.now()) return cached.data as T;
    const raw = await this.transport.request(
      "GET",
      path,
      undefined,
      undefined,
      signal,
    );
    signal?.throwIfAborted();
    const failed = failure.safeParse(raw);
    if (failed.success) {
      const error = failed.data.error;
      if (
        route === "status" &&
        error.code === "NOT_FOUND" &&
        ["not found", "extension route unavailable"].includes(
          error.message.trim().toLowerCase(),
        )
      )
        throw new ApiError(
          "SERVICE_UNAVAILABLE",
          "The running backend does not include observation routes. Restart AgentCity to load the updated API, then refresh this panel. Your saved simulation history is preserved.",
          true,
        );
      if (error.code === "UNAUTHENTICATED" && typeof window !== "undefined")
        window.dispatchEvent(new Event("agentcity:session-expired"));
      throw new ApiError(
        error.code,
        error.message,
        error.retryable,
        error.details,
      );
    }
    const parsed = envelope(schema).safeParse(raw);
    if (!parsed.success)
      throw new ApiError(
        "INVALID_RESPONSE",
        "Observation response does not match its versioned contract.",
      );
    const data = parsed.data.data;
    if (
      data.simulation_id !== sid ||
      data.requested_revision !== params.through_revision ||
      (data.effective_revision !== null &&
        data.effective_revision > params.through_revision)
    )
      throw new ApiError(
        "INVALID_RESPONSE",
        "Observation provenance does not match the pinned request.",
      );
    if (this.cache.size >= 100)
      this.cache.delete(this.cache.keys().next().value!);
    this.cache.set(path, { expires: this.now() + 30_000, data });
    return data;
  }
  status(sid: string, selection: Selection, signal?: AbortSignal) {
    return this.get(sid, "status", statusSchema, selection, signal);
  }
  metrics(sid: string, selection: Selection, signal?: AbortSignal) {
    return this.get(sid, "metrics", metricsSchema, selection, signal);
  }
  trends(
    sid: string,
    selection: Selection,
    metric: string,
    signal?: AbortSignal,
  ) {
    return this.get(
      sid,
      "trends",
      trendsSchema,
      { ...selection, metric },
      signal,
    );
  }
  events(
    sid: string,
    selection: Selection,
    after?: string,
    signal?: AbortSignal,
  ) {
    return this.get(
      sid,
      "events",
      eventsSchema,
      { ...selection, after, limit: 50 },
      signal,
    );
  }
  event(
    sid: string,
    selection: Selection,
    eventId: string,
    signal?: AbortSignal,
  ) {
    return this.get(
      sid,
      `events/${encodeURIComponent(eventId)}`,
      eventDetailSchema,
      selection,
      signal,
    );
  }
  changes(
    sid: string,
    selection: Selection,
    after?: string,
    signal?: AbortSignal,
  ) {
    return this.get(
      sid,
      "changes",
      changesSchema,
      { ...selection, after, limit: 50 },
      signal,
    );
  }
}
