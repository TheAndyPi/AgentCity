import { z } from "zod";
import * as S from "../api/schemas";

const record = z.record(z.string(), z.unknown());
const timing = z.object({
  start_tick: z.number(),
  duration_ticks: z.number().nullable(),
  repeat_every: z.number().nullable(),
  repeat_count: z.number().nullable(),
});

export const planSummary = z.object({
  operations: z.array(
    z.object({
      id: z.string(),
      type: z.string(),
      label: z.string(),
      rationale: z.string(),
      timing,
      physical: z.boolean(),
    }),
  ),
  affected_systems: z.array(z.string()),
  metrics: z.array(z.object({ id: z.string(), description: z.string() })),
  event_kind: z.string(),
  region_polygon: z.array(z.object({ x: z.number(), y: z.number() })),
  affected_agent_count: z.number(),
  affected_building_count: z.number(),
  measurement_ticks: z.number(),
  warnings: z.array(z.string()),
});

export const planResult = z.object({
  status: z.enum([
    "ready",
    "invalid",
    "unsupported",
    "needs_clarification",
    "unavailable",
  ]),
  plan: record.nullable(),
  errors: z.array(z.string()),
  warnings: z.array(z.string()),
  unsupported: z.array(z.string()),
  clarification: z.string(),
  attempts: z.number().optional(),
  summary: planSummary.nullable(),
});

export const commitResult = z.object({
  simulation: S.simulation,
  event: S.event,
  snapshot: record,
  plan: record,
  queued_until_play: z.boolean(),
});

export const policyTarget = z.object({
  target: z.string(),
  minimum: z.number(),
  maximum: z.number(),
  unit: z.string(),
  nullable: z.boolean(),
  description: z.string(),
  systems: z.array(z.string()),
});

export const engineCapabilities = z.object({
  operations: z.array(
    z.object({
      type: z.string(),
      description: z.string(),
      systems: z.array(z.string()),
      physical: z.boolean(),
      parameters: record,
    }),
  ),
  policy_targets: z.array(policyTarget),
  regions: z.array(z.string()),
  norms: z.record(z.string(), z.string()),
  organizations: z.record(z.string(), z.string()),
  incentives: z.record(z.string(), z.string()),
  metrics: z.record(z.string(), z.string()),
  systems: z.array(z.string()),
  interpreter: z.boolean(),
});

const measurement = z.record(
  z.string(),
  z.union([z.number(), z.boolean(), z.null()]),
);

export const trace = z.object({
  id: z.string(),
  tick: z.number(),
  kind: z.enum(["operation", "decision"]),
  event_id: z.string().nullable(),
  op_id: z.string().nullable(),
  agent_id: z.string().nullable(),
  title: z.string(),
  observations: z.array(z.string()),
  candidates: z.array(record),
  selected: z.string().nullable(),
  motivation: z.string(),
  memory_ids: z.array(z.string()),
  changes: z.array(record),
  affected_ids: z.array(z.string()),
  significance: z.number(),
});

export const systemsState = z.object({
  enabled: z.boolean(),
  tick: z.number(),
  revision: z.number(),
  policy: z.record(z.string(), z.record(z.string(), z.number().nullable())),
  treasury: z.number(),
  organizations: z.array(
    z.object({
      id: z.string(),
      kind: z.string(),
      name: z.string(),
      members: z.number(),
      active: z.boolean(),
      event_id: z.string().nullable(),
    }),
  ),
  norms: z.record(z.string(), z.number()),
  conditions: z.array(record),
  closed_buildings: z.array(
    z.object({ id: z.string(), name: z.string(), kind: z.string() }),
  ),
  plans: z.array(
    z.object({
      event_id: z.string(),
      title: z.string(),
      status: z.string(),
      activated_tick: z.number().nullable(),
      resolved_tick: z.number().nullable(),
    }),
  ),
  live: measurement.nullable(),
  active_event_id: z.string().nullable(),
});

const finding = z.object({ text: z.string(), evidence: record });

export const eventAnalysis = z.object({
  event_id: z.string(),
  status: z.string(),
  plan: record,
  operations: z.array(
    z.object({ id: z.string(), type: z.string(), label: z.string() }),
  ),
  activated_tick: z.number().nullable(),
  resolved_tick: z.number().nullable(),
  baseline: measurement,
  current: measurement.nullable(),
  series: z.array(measurement),
  findings: z.array(finding),
  policy_before: record,
  policy_after: record,
  operation_traces: z.array(trace),
  decisions: z.array(trace),
  decision_count: z.number(),
});

export const agentTraces = z.object({
  agent_id: z.string(),
  enabled: z.boolean(),
  systems: z
    .object({
      wallet: z.number(),
      income: z.string(),
      owns_car: z.boolean(),
      habit: z.string(),
      institutional_trust: z.number(),
      housing_status: z.string(),
      renter: z.boolean(),
      home_id: z.string().nullable(),
      norms: z.record(z.string(), z.number()),
      organizations: z.array(z.object({ id: z.string(), name: z.string() })),
      incentives: z.record(z.string(), z.number()),
      beliefs: z.array(record),
      trips: z.record(z.string(), z.number()),
      satisfaction: z.number(),
    })
    .nullable(),
  traces: z.array(trace),
});

export const initialPlan = z.object({
  plan: record.nullable(),
  summary: planSummary.nullable(),
});

export type PlanSummary = z.infer<typeof planSummary>;
export type PlanResult = z.infer<typeof planResult>;
export type EngineCapabilities = z.infer<typeof engineCapabilities>;
export type Trace = z.infer<typeof trace>;
export type SystemsState = z.infer<typeof systemsState>;
export type EventAnalysis = z.infer<typeof eventAnalysis>;
export type AgentTraces = z.infer<typeof agentTraces>;
export type Plan = Record<string, unknown>;
