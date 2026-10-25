import { z } from "zod";
import type { AgentCityClient } from "../api/client";
import { preview as scenarioPreview } from "../api/schemas";

export const kinds = [
  "earthquake",
  "tornado",
  "flood",
  "fire",
  "storm",
] as const;
export type DisasterKind = (typeof kinds)[number];
export const limits = {
  earthquake: {
    min: 2,
    max: 9,
    step: 0.1,
    default: 5.5,
    unit: "Mw",
    label: "Moment magnitude",
    description:
      "Source magnitude. Local shaking attenuates with distance; simplified gameplay curve.",
  },
  tornado: {
    min: 0,
    max: 130,
    step: 1,
    default: 50,
    unit: "m/s",
    label: "Peak wind speed",
    description:
      "Wind follows the moving track and fades toward its edge. Zero wind causes no damage.",
  },
  flood: {
    min: 0,
    max: 5,
    step: 0.1,
    default: 1,
    unit: "m",
    label: "Water depth",
    description:
      "Uniform inundation inside the selected area. Receding water does not repair damage.",
  },
  fire: {
    min: 0,
    max: 100,
    step: 1,
    default: 50,
    unit: "/100",
    label: "Gameplay heat",
    description:
      "Bounded fire exposure inside the selected area; no spread beyond the envelope.",
  },
  storm: {
    min: 0,
    max: 75,
    step: 1,
    default: 30,
    unit: "m/s",
    label: "Peak wind speed",
    description: "Uniform storm exposure; no tornado rotation or track.",
  },
};
const point = z
  .object({ x: z.number().finite(), y: z.number().finite() })
  .strict();
export const parameters = z
  .object({
    kind: z.enum(kinds),
    intensity: z.number().finite(),
    extent_m: z.number().positive(),
    origin: point,
    track_end: point.nullable(),
    duration_ticks: z.number().int().min(1).max(1000),
    seed: z.number().int().nonnegative(),
    rule_version: z.literal("disasters-2.0.0"),
  })
  .strict();
export type DisasterParameters = z.infer<typeof parameters>;
export const disasterPreview = z
  .object({
    schema_version: z.literal("2.0.0"),
    damage_projection: z.object({
      min_integrity_loss: z.number(),
      max_integrity_loss: z.number(),
      description: z.string(),
    }),
    parameters,
    preview: scenarioPreview,
    bounds: z.object({ min_extent_m: z.number(), max_extent_m: z.number() }),
    duration_seconds: z.number(),
  })
  .strict();
const condition = z.object({
  integrity: z.number(),
  design_capacity: z.number(),
  baseline_functional: z.boolean(),
  resistance: z.number(),
  cause_ids: z.array(z.string()),
  stage: z.string(),
});
const event = z.object({
  legacy_projection: z.boolean(),
  id: z.string(),
  phase: z.string(),
  phase_id: z.string(),
  parameters,
  normalized_intensity: z.number(),
  unit: z.string(),
  start_tick: z.number().nullable(),
  end_tick: z.number().nullable(),
  footprint: z.array(point),
  current_footprint: z.array(point),
  current_origin: point,
  exposure_count: z.number(),
  damage_ids: z.array(z.string()),
});
const reaction = z.object({
  id: z.string(),
  event_id: z.string(),
  agent_id: z.string(),
  tick: z.number(),
  revision: z.number(),
  sim_time_seconds: z.number(),
  position: point,
  threat: z.number(),
  kind: z.enum(["scream", "help", "warning"]),
  text: z.string(),
  episode_id: z.string(),
  evidence_ids: z.array(z.string()),
  alive: z.boolean(),
  conscious: z.boolean(),
});
export const disasterState = z
  .object({
    schema_version: z.literal("2.0.0"),
    rule_version: z.string(),
    simulation_id: z.string(),
    ref: z.object({ tick: z.number(), revision: z.number() }),
    sim_time_seconds: z.number(),
    events: z.array(event),
    vocal_states: z.record(
      z.string(),
      z.object({ alive: z.boolean(), conscious: z.boolean() }),
    ),
    service_changes: z.array(z.record(z.string(), z.unknown())),
    conditions: z.record(z.string(), condition),
    terrain: z.array(
      z.object({
        col: z.number(),
        row: z.number(),
        stage: z.string(),
        blocked: z.boolean(),
        cause_ids: z.array(z.string()),
      }),
    ),
    damage: z.array(
      z.object({
        id: z.string(),
        event_id: z.string(),
        entity_id: z.string(),
        tick: z.number(),
        revision: z.number(),
        sim_time_seconds: z.number(),
        exposure: z.number(),
        before: z.number(),
        after: z.number(),
        units: z.enum(["health", "stock", "integrity"]),
        rule_version: z.string(),
      }),
    ),
    reactions: z.array(reaction),
    repairs: z.array(
      z.object({
        id: z.string(),
        action: z.enum(["repair", "clear"]),
        building_id: z.string(),
        start_tick: z.number(),
        finish_tick: z.number(),
        before: z.number(),
        supplies: z.number(),
        resource_id: z.string(),
        status: z.string(),
        after: z.number().nullable(),
      }),
    ),
    rescue_needs: z.array(
      z.object({ agent_id: z.string(), building_id: z.string() }),
    ),
  })
  .strict();
export type DisasterState = z.infer<typeof disasterState>;
const base = (sid: string) =>
  `/integrations/disasters/v2/simulations/${encodeURIComponent(sid)}`;
export const loadDisasters = (
  client: AgentCityClient,
  sid: string,
  revision: number,
  signal?: AbortSignal,
) =>
  client.call(
    "GET",
    `${base(sid)}/state?revision=${revision}`,
    disasterState,
    undefined,
    undefined,
    signal,
  );
export const previewDisaster = (
  client: AgentCityClient,
  sid: string,
  intervention: string,
  value: DisasterParameters,
  key: string,
  signal?: AbortSignal,
  originalPrompt?: string,
  editorGeneration = 0,
) =>
  client.call(
    "POST",
    `${base(sid)}/previews`,
    disasterPreview,
    {
      intervention_id: intervention,
      parameters: value,
      original_prompt: originalPrompt ?? null,
      editor_generation: editorGeneration,
    },
    key,
    signal,
  );
export const commitDisaster = (
  client: AgentCityClient,
  sid: string,
  body: {
    intervention_id: string;
    preview_id: string;
    expected_control_version: number;
  },
  key: string,
) =>
  client.call(
    "POST",
    `${base(sid)}/commits`,
    z.object({
      simulation: z.unknown(),
      event: z.unknown(),
      snapshot: z.unknown(),
    }),
    body,
    key,
  );
export const repairBuilding = (
  client: AgentCityClient,
  sid: string,
  building_id: string,
  expected_control_version: number,
  key: string,
  action: "repair" | "clear" = "repair",
) =>
  client.call(
    "POST",
    `${base(sid)}/repairs`,
    z.unknown(),
    { building_id, expected_control_version, action },
    key,
  );
export const stopDisaster = (
  client: AgentCityClient,
  sid: string,
  eid: string,
  expected_control_version: number,
  key: string,
) =>
  client.call(
    "POST",
    `${base(sid)}/events/${encodeURIComponent(eid)}/cancel`,
    disasterState,
    { expected_control_version },
    key,
  );
export function defaults(
  kind: DisasterKind,
  width: number,
  height: number,
  seed: number,
): DisasterParameters {
  return {
    kind,
    intensity: limits[kind].default,
    extent_m: 24,
    origin: { x: width / 2, y: height / 2 },
    track_end:
      kind === "tornado"
        ? { x: Math.min(width, width / 2 + 32), y: height / 2 }
        : null,
    duration_ticks: 12,
    seed: seed % 2147483648,
    rule_version: "disasters-2.0.0",
  };
}
export function fromPrompt(
  prompt: string,
  width: number,
  height: number,
  seed: number,
): DisasterParameters | null {
  const kind = kinds.find((k) => new RegExp(`\\b${k}\\b`, "i").test(prompt));
  if (!kind) return null;
  const result = defaults(kind, width, height, seed);
  const patterns = {
    earthquake: /(?:magnitude|mw)\s*([\d.]+)/i,
    tornado: /([\d.]+)\s*m\/s/i,
    storm: /([\d.]+)\s*m\/s/i,
    flood: /([\d.]+)\s*(?:m|meters?)\s*(?:deep|depth)/i,
    fire: /(?:heat|danger)\s*([\d.]+)/i,
  };
  const intensity = prompt.match(patterns[kind]);
  const extent = prompt.match(
    /([\d.]+)[ -]*(?:m|meters?)[ -]*(?:width|radius)/i,
  );
  const duration = prompt.match(/(\d+)\s*ticks?/i);
  if (intensity) result.intensity = Number(intensity[1]);
  if (extent) result.extent_m = Number(extent[1]);
  if (duration) result.duration_ticks = Number(duration[1]);
  return result;
}
