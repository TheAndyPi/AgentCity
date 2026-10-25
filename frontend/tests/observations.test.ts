import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Transport } from "../src/api/client";
import { ObservationsClient } from "../src/snowflake/observations/client";
import {
  formatObservation,
  TrendChart,
  trendSegments,
} from "../src/snowflake/observations/ObservationsPanel";
import {
  changesSchema,
  envelope,
  trendsSchema,
  type Trends,
} from "../src/snowflake/observations/schema";

const common = {
  source: "snowflake" as const,
  simulation_id: "city/a",
  requested_revision: 7,
  effective_revision: 6,
  coverage: { state: "partial" as const, from_tick: 0, through_tick: 3 },
};
const event = {
  event_id: "flood_1",
  title: "Flood",
  status: "resolved",
  start_tick: 1,
  end_tick: 2,
};
const point = (tick: number, mean: number | null) => ({
  tick,
  revision: tick + 2,
  mean,
  min: mean,
  max: mean,
  sample_count: 1,
  denominator: 2,
});
const trends = (): Trends => ({
  ...common,
  metric: "health",
  unit: "population_mean_0_100",
  items: [point(0, 100), point(1, 90), point(2, null), point(3, 94)],
  events: [event],
  distribution: [],
});
const response = (data: unknown) => ({
  schema_version: "1.0.0",
  request_id: "550e8400-e29b-41d4-a716-446655440000",
  data,
});
const selection = { through_revision: 7, agent_id: "agent one", start_tick: 0 };

describe("Snowflake observation client", () => {
  it("encodes selection, caches a pinned query for 30 seconds, and forwards cancellation", async () => {
    let now = 100;
    const request = vi.fn(async () => response(trends()));
    const client = new ObservationsClient({ mode: "live", request }, () => now);
    const controller = new AbortController();
    expect(
      (await client.trends("city/a", selection, "health", controller.signal))
        .effective_revision,
    ).toBe(6);
    await client.trends("city/a", selection, "health");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0]).toEqual([
      "GET",
      "/integrations/snowflake/observations/v1/simulations/city%2Fa/trends?agent_id=agent+one&metric=health&start_tick=0&through_revision=7",
      undefined,
      undefined,
      controller.signal,
    ]);
    now += 30_000;
    await client.trends("city/a", selection, "health");
    expect(request).toHaveBeenCalledTimes(2);
    client.invalidate();
    await client.trends("city/a", selection, "health");
    expect(request).toHaveBeenCalledTimes(3);
  });

  it("rejects another simulation, wrong requested revision, or future effective revision", async () => {
    for (const change of [
      { simulation_id: "someone_else" },
      { requested_revision: 8 },
      { effective_revision: 8 },
    ]) {
      const client = new ObservationsClient({
        mode: "live",
        async request() {
          return response({ ...trends(), ...change });
        },
      });
      await expect(
        client.trends("city/a", selection, "health"),
      ).rejects.toThrow(/provenance/);
    }
  });

  it("does not share caches across metric, interval, agent or historical revision", async () => {
    const request = vi.fn(async (_method: string, path: string) => {
      const query = new URLSearchParams(path.split("?")[1]);
      return response({
        ...trends(),
        metric: query.get("metric"),
        requested_revision: Number(query.get("through_revision")),
      });
    });
    const client = new ObservationsClient({ mode: "live", request });
    await client.trends("city/a", selection, "health");
    await client.trends("city/a", selection, "trust");
    await client.trends("city/a", { ...selection, start_tick: 1 }, "health");
    await client.trends(
      "city/a",
      { ...selection, agent_id: "other" },
      "health",
    );
    await client.trends(
      "city/a",
      { ...selection, through_revision: 9 },
      "health",
    );
    expect(request).toHaveBeenCalledTimes(5);
  });

  it("preserves safe failures and never sends mock requests", async () => {
    const mockRequest = vi.fn();
    await expect(
      new ObservationsClient({ mode: "mock", request: mockRequest }).trends(
        "city/a",
        selection,
        "health",
      ),
    ).rejects.toThrow(/live connection/);
    expect(mockRequest).not.toHaveBeenCalled();
    const transport: Transport = {
      mode: "live",
      async request() {
        return {
          schema_version: "1.0.0",
          request_id: "550e8400-e29b-41d4-a716-446655440000",
          error: {
            code: "SERVICE_UNAVAILABLE",
            message: "Warehouse catching up",
            retryable: true,
            details: [],
          },
        };
      },
    };
    await expect(
      new ObservationsClient(transport).trends("city/a", selection, "health"),
    ).rejects.toMatchObject({ code: "SERVICE_UNAVAILABLE", retryable: true });
  });

  it("does not cache aborted responses or query invalid revision boundaries", async () => {
    const controller = new AbortController();
    const request = vi.fn(async () => {
      controller.abort();
      return response(trends());
    });
    const client = new ObservationsClient({ mode: "live", request });
    await expect(
      client.trends("city/a", selection, "health", controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    await expect(
      client.trends("city/a", { through_revision: -1 }, "health"),
    ).rejects.toThrow(/revision/);
    expect(request).toHaveBeenCalledTimes(1);
  });
});

describe("observation contracts and chart", () => {
  it("rejects unknown fields, nonfinite numbers and oversized trend collections", () => {
    expect(
      envelope(trendsSchema).safeParse(
        response({ ...trends(), unexpected: true }),
      ).success,
    ).toBe(false);
    expect(
      trendsSchema.safeParse({ ...trends(), items: [point(0, Infinity)] })
        .success,
    ).toBe(false);
    expect(
      trendsSchema.safeParse({
        ...trends(),
        items: Array.from({ length: 501 }, (_, tick) => point(tick, 1)),
      }).success,
    ).toBe(false);
    expect(
      changesSchema.safeParse({
        ...common,
        items: [
          {
            id: "change",
            tick: 1,
            revision: 2,
            entity_kind: "relationship",
            entity_id: "A:B",
            agent_id: "A",
            field: "trust",
            before: 30,
            after: 40,
            link: "explicit",
            event_ids: ["flood_1"],
            evidence: { decision_ids: ["d1"] },
          },
        ],
        next_after: null,
      }).success,
    ).toBe(true);
  });

  it("preserves missing observations as gaps and provides accessible event controls and data labels", () => {
    expect(
      trendSegments(trends().items).map((segment) =>
        segment.map((p) => p.tick),
      ),
    ).toEqual([[0, 1], [3]]);
    const html = renderToStaticMarkup(
      createElement(TrendChart, {
        data: trends(),
        label: "Health",
        onEvent() {},
      }),
    );
    expect(html.match(/<polyline/g)).toHaveLength(2);
    expect(html).toContain("Event intervals are shaded");
    expect(html).toContain('role="button"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain("Flood, resolved, ticks 1 to 2");
    expect(html).not.toMatch(/NaN|Infinity/);
  });

  it("renders unavailable values truthfully and keeps flat or single-point graphs finite", () => {
    expect(formatObservation(null)).toBe("Unavailable");
    expect(formatObservation(0)).toBe("0");
    const html = renderToStaticMarkup(
      createElement(TrendChart, {
        data: { ...trends(), items: [point(0, 0)], events: [] },
        label: "Count",
        onEvent() {},
      }),
    );
    expect(html).not.toMatch(/NaN|Infinity/);
    const empty = renderToStaticMarkup(
      createElement(TrendChart, {
        data: { ...trends(), items: [point(0, null)] },
        label: "Count",
        onEvent() {},
      }),
    );
    expect(empty).toContain("No measured values");
    expect(empty).not.toContain("polyline");
  });
});
