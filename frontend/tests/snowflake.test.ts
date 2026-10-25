import { describe, expect, it } from "vitest";
import { SnowflakeClient } from "../src/snowflake/client";
import { comparisonRequest, comparisonResponse } from "../src/snowflake/schema";
import type { Transport } from "../src/api/client";

const key = "550e8400-e29b-41d4-a716-446655440000";
const body = {
  a: { simulation_id: "a", revision: 2 },
  b: { simulation_id: "b", revision: 3 },
  question: "Recorded differences?",
};
const pin = (simulation_id: string, revision: number) => ({
  simulation_id,
  revision,
  endpoint_tick: 2,
  metric_tick: 2,
  metric_revision: revision,
  sim_time_seconds: 10,
  parent_simulation_id: null,
  fork_ref: null,
  seed: 42,
  contract_version: "1.0.0",
  engine_version: "1.0.0",
  export_sha256: "a".repeat(64),
  ingested_at: null,
});
const response = () => ({
  schema_version: "1.0.0",
  request_id: key,
  data: {
    a: pin("a", 2),
    b: pin("b", 3),
    data_source: "local_export",
    horizon: "equal_endpoint_ticks",
    lineage: "unrelated",
    differences: [
      {
        metric: "happiness",
        a: 61.25,
        b: 59,
        delta_b_minus_a: -2.25,
        unit: "population_mean_0_100",
      },
    ],
    citations: [],
    explanation: {
      source: "deterministic",
      status: "unavailable",
      reason: "Unavailable",
      observations: [],
    },
    limitations: [],
  },
});

describe("Snowflake extension client", () => {
  it("preserves pinned bodies and operation keys across exact retries", async () => {
    const requests: unknown[] = [];
    const transport: Transport = {
      mode: "live",
      async request(...args) {
        requests.push(args);
        return response();
      },
    };
    const client = new SnowflakeClient(transport);
    expect(
      (await client.compare(body, key)).differences[0].delta_b_minus_a,
    ).toBe(-2.25);
    await client.compare(body, key);
    expect(requests).toEqual([
      ["POST", "/integrations/snowflake/comparisons", body, key],
      ["POST", "/integrations/snowflake/comparisons", body, key],
    ]);
  });
  it("rejects wrong revisions, identity, and operation key in returned provenance", async () => {
    for (const change of [
      (r: ReturnType<typeof response>) => {
        r.data.b.revision++;
      },
      (r: ReturnType<typeof response>) => {
        r.data.a.simulation_id = "other";
      },
      (r: ReturnType<typeof response>) => {
        r.request_id = "550e8400-e29b-41d4-a716-446655440001";
      },
    ]) {
      const r = response();
      change(r);
      const client = new SnowflakeClient({
        mode: "live",
        async request() {
          return r;
        },
      });
      await expect(client.compare(body, key)).rejects.toThrow(/provenance/);
    }
  });
  it("keeps safe failure envelopes and rejects malformed schema and arbitrary SQL", async () => {
    const client = new SnowflakeClient({
      mode: "live",
      async request() {
        return {
          schema_version: "1.0.0",
          request_id: key,
          error: {
            code: "RATE_LIMITED",
            message: "Retry later",
            retryable: true,
            details: [],
          },
        };
      },
    });
    await expect(client.compare(body, key)).rejects.toMatchObject({
      code: "RATE_LIMITED",
      retryable: true,
    });
    expect(
      comparisonRequest.safeParse({ ...body, sql: "SELECT secrets" }).success,
    ).toBe(false);
    expect(
      comparisonRequest.safeParse({ ...body, a: { ...body.a, revision: -1 } })
        .success,
    ).toBe(false);
    const r = response();
    r.data.differences[0].a = Infinity;
    expect(comparisonResponse.safeParse(r).success).toBe(false);
  });
});
