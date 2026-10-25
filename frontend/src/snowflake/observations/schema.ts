import { z } from "zod";

const counter = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const finite = z.number().finite();
const object = z.record(z.string(), z.json());
const common = {
  source: z.literal("snowflake"),
  simulation_id: z.string().min(1),
  requested_revision: counter,
  effective_revision: counter.nullable(),
  coverage: z
    .object({
      state: z.enum(["complete", "partial", "unavailable"]),
      from_tick: counter.nullable(),
      through_tick: counter.nullable(),
    })
    .strict(),
};

export const statusSchema = z
  .object({
    ...common,
    enabled: z.boolean(),
    state: z.enum(["disabled", "healthy", "backfilling", "lagged", "failed"]),
    published_revision: counter,
    ingested_revision: z.number().int().min(-1),
    lag_revisions: counter,
    error_code: z.string().nullable(),
  })
  .strict();
export const metricsSchema = z
  .object({
    ...common,
    items: z.array(
      z
        .object({
          id: z.string(),
          label: z.string(),
          unit: z.string(),
          denominator: z.string(),
        })
        .strict(),
    ),
  })
  .strict();
export const eventSchema = z
  .object({
    event_id: z.string(),
    title: z.string(),
    status: z.string(),
    start_tick: counter.nullable(),
    end_tick: counter.nullable(),
  })
  .strict();
export const trendPointSchema = z
  .object({
    tick: counter,
    revision: counter,
    mean: finite.nullable(),
    min: finite.nullable(),
    max: finite.nullable(),
    sample_count: counter,
    denominator: finite.nonnegative(),
  })
  .strict();
export const trendsSchema = z
  .object({
    ...common,
    metric: z.string(),
    unit: z.string(),
    items: z.array(trendPointSchema).max(500),
    events: z.array(eventSchema),
    distribution: z.array(
      z.object({ label: z.string(), count: counter }).strict(),
    ),
  })
  .strict();
export const changeSchema = z
  .object({
    id: z.string(),
    tick: counter,
    revision: counter,
    entity_kind: z.string(),
    entity_id: z.string(),
    agent_id: z.string().nullable(),
    field: z.string(),
    before: z.json(),
    after: z.json(),
    link: z.enum(["explicit", "temporal"]),
    event_ids: z.array(z.string()),
    evidence: object,
  })
  .strict();
export const changesSchema = z
  .object({
    ...common,
    items: z.array(changeSchema).max(100),
    next_after: z.string().nullable(),
  })
  .strict();
export const eventsSchema = z
  .object({
    ...common,
    items: z.array(eventSchema).max(100),
    next_after: z.string().nullable(),
  })
  .strict();
const measurement = z
  .object({
    tick: counter.nullable(),
    city: z.record(z.string(), finite.nullable()),
    cohort: z.record(z.string(), finite.nullable()),
  })
  .strict();
export const eventDetailSchema = z
  .object({
    ...common,
    event: eventSchema,
    baseline: measurement,
    resolution: measurement,
    followup: measurement,
    followup_complete: z.boolean(),
    observations: z.array(
      z
        .object({
          id: z.string(),
          text: z.string(),
          citation_ids: z.array(z.string()),
        })
        .strict(),
    ),
    citations: z.array(
      z
        .object({
          id: z.string(),
          tick: counter,
          revision: counter,
          description: z.string(),
        })
        .strict(),
    ),
    overlaps: z.array(eventSchema),
    changes: z.array(changeSchema),
  })
  .strict();
export const envelope = <T extends z.ZodType>(data: T) =>
  z
    .object({
      schema_version: z.literal("1.0.0"),
      request_id: z.string().uuid(),
      data,
    })
    .strict();

export type ObservationStatus = z.infer<typeof statusSchema>;
export type Metrics = z.infer<typeof metricsSchema>;
export type Trends = z.infer<typeof trendsSchema>;
export type Changes = z.infer<typeof changesSchema>;
export type Events = z.infer<typeof eventsSchema>;
export type EventDetail = z.infer<typeof eventDetailSchema>;
export type TrendPoint = z.infer<typeof trendPointSchema>;
export type ObservationEvent = z.infer<typeof eventSchema>;
export type Change = z.infer<typeof changeSchema>;
