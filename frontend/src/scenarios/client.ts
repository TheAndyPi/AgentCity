import type { z } from "zod";
import { ApiError, type Transport } from "../api/client";
import { failure } from "../api/schemas";
import type { Intervention } from "../api/types";
import {
  agentTraces,
  commitResult,
  engineCapabilities,
  eventAnalysis,
  initialPlan,
  planResult,
  systemsState,
  type Plan,
} from "./schema";

const BASE = "/integrations/scenarios";
const INTERPRET_TIMEOUT_MS = 95000;
const sim = (id: string) => `${BASE}/simulations/${encodeURIComponent(id)}`;
const query = (revision?: number) =>
  revision === undefined ? "" : `?revision=${revision}`;

/** The scenario engine lives on the integrations sub-app; mock mode has no engine. */
export class ScenarioEngineClient {
  constructor(private transport: Transport) {}

  get available() {
    return this.transport.mode === "live";
  }

  private async call<T>(
    schema: z.ZodType<T>,
    method: string,
    path: string,
    body?: unknown,
    key?: string,
    timeoutMs?: number,
  ): Promise<T> {
    const raw = await this.transport.request(
      method,
      path,
      body,
      method === "GET" ? undefined : (key ?? crypto.randomUUID()),
      timeoutMs,
    );
    const failed = failure.safeParse(raw);
    if (failed.success) {
      const e = failed.data.error;
      if (e.code === "UNAUTHENTICATED" && typeof window !== "undefined")
        window.dispatchEvent(new Event("agentcity:session-expired"));
      throw new ApiError(e.code, e.message, e.retryable, e.details);
    }
    const data = (raw as { data?: unknown } | null)?.data;
    const parsed = schema.safeParse(data);
    if (!parsed.success)
      throw new ApiError(
        "CONTRACT_ERROR",
        `Scenario engine response is malformed: ${parsed.error.issues[0]?.path.join(".")} ${parsed.error.issues[0]?.message}`,
      );
    return parsed.data;
  }

  capabilities = () =>
    this.call(engineCapabilities, "GET", `${BASE}/capabilities`);
  interpret = (sid: string, intervention: Intervention, prompt: string) =>
    this.call(
      planResult,
      "POST",
      `${sim(sid)}/plans`,
      { intervention_id: intervention.id, prompt },
      undefined,
      INTERPRET_TIMEOUT_MS,
    );
  validate = (sid: string, plan: Plan) =>
    this.call(planResult, "POST", `${sim(sid)}/plans/validate`, { plan });
  commit = (sid: string, intervention: Intervention, plan: Plan, key: string) =>
    this.call(
      commitResult,
      "POST",
      `${sim(sid)}/commits`,
      {
        intervention_id: intervention.id,
        expected_control_version: intervention.control_version,
        plan,
      },
      key,
    );
  state = (sid: string, revision?: number) =>
    this.call(systemsState, "GET", `${sim(sid)}/state${query(revision)}`);
  event = (sid: string, eid: string, revision?: number) =>
    this.call(
      eventAnalysis,
      "GET",
      `${sim(sid)}/events/${encodeURIComponent(eid)}${query(revision)}`,
    );
  traces = (sid: string, aid: string, revision?: number) =>
    this.call(
      agentTraces,
      "GET",
      `${sim(sid)}/agents/${encodeURIComponent(aid)}/traces${query(revision)}`,
    );
  initialPlan = (sid: string) =>
    this.call(initialPlan, "GET", `${sim(sid)}/initial-plan`);
}
