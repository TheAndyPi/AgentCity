import { z } from "zod";

const counter = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const finite = z.number().finite();
export const pinnedHistory = z
  .object({ simulation_id: z.string().min(1), revision: counter })
  .strict();
export const comparisonRequest = z
  .object({
    a: pinnedHistory,
    b: pinnedHistory,
    question: z.string().min(1).max(500),
  })
  .strict();
const provenance = pinnedHistory
  .extend({
    endpoint_tick: counter,
    metric_tick: counter,
    metric_revision: counter,
    sim_time_seconds: finite,
    parent_simulation_id: z.string().nullable(),
    fork_ref: z.record(z.string(), z.unknown()).nullable(),
    seed: z.number().int(),
    contract_version: z.literal("1.0.0"),
    engine_version: z.literal("1.0.0"),
    export_sha256: z.string().regex(/^[a-f0-9]{64}$/),
    ingested_at: z.string().nullable(),
  })
  .strict();
export const comparisonResponse = z
  .object({
    schema_version: z.literal("1.0.0"),
    request_id: z.string().uuid(),
    data: z
      .object({
        a: provenance,
        b: provenance,
        data_source: z.enum(["snowflake", "local_export"]),
        horizon: z.enum(["equal_endpoint_ticks", "unequal_endpoint_ticks"]),
        lineage: z.enum([
          "same_history",
          "parent_branch",
          "siblings",
          "unrelated",
        ]),
        differences: z
          .array(
            z
              .object({
                metric: z.string(),
                a: finite.nullable(),
                b: finite.nullable(),
                delta_b_minus_a: finite.nullable(),
                unit: z.enum([
                  "population_mean_0_100",
                  "recorded_count",
                  "resource_units",
                ]),
              })
              .strict(),
          )
          .max(10),
        citations: z
          .array(
            pinnedHistory
              .extend({
                id: z.string(),
                kind: z.enum(["event", "decision"]),
                record_id: z.string(),
                tick: counter,
                excerpt: z.string(),
                url: z.string(),
              })
              .strict(),
          )
          .max(96),
        explanation: z
          .object({
            source: z.enum(["cortex_selection", "deterministic"]),
            status: z.enum(["available", "unavailable"]),
            reason: z.string().nullable(),
            observations: z.array(
              z
                .object({
                  fact_id: z.string(),
                  text: z.string(),
                  citation_ids: z.array(z.string()),
                })
                .strict(),
            ),
          })
          .strict(),
        limitations: z.array(z.string()),
      })
      .strict(),
  })
  .strict();
export type ComparisonRequest = z.infer<typeof comparisonRequest>;
export type Comparison = z.infer<typeof comparisonResponse>["data"];
