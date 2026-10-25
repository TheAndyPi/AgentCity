import { describe, expect, it } from "vitest";
import { inferMetrics } from "../src/snowflake/observations/QuickSummary";
import type { MetricPoint } from "../src/api/types";
const point = (tick: number, happiness: number): MetricPoint => ({
  tick,
  revision: tick,
  values: { happiness, safety: 50, trust: 50, resources: 50, stress: 50 },
  cooperation_count: 2,
  conflict_count: 1,
  resources_consumed: 0,
  evacuated_count: 0,
  exposed_count: 0,
});
describe("immediate analytics inference", () => {
  it("does not invent data or trends before enough history exists", () => {
    expect(inferMetrics([])).toBeNull();
    expect(inferMetrics([point(0, 50)])?.text).toContain("baseline");
    expect(inferMetrics([point(0, 50), point(0, 60)])?.text).toContain(
      "baseline",
    );
  });
  it("finds the largest recorded change and preserves its direction", () => {
    const result = inferMetrics([point(0, 70), point(10, 40)]);
    expect(result?.text).toContain("happiness");
    expect(result?.text).toContain("falling 30.0");
    expect(result?.latest.tick).toBe(10);
  });
  it("reports stable metrics without inventing a cause", () => {
    expect(inferMetrics([point(0, 50), point(10, 50)])?.text).toContain(
      "stable",
    );
  });
});
