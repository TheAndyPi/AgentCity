import { z } from "zod";
import { evidence, ref } from "../api/schemas";

const impact = z
  .object({
    tick: z.number().int(),
    phase: z.string(),
    meter: z.enum(["mental", "social", "energy", "health", "fullness"]),
    reason: z.string(),
    delta: z.number().finite(),
    evidence,
  })
  .strict();
const episode = z
  .object({
    id: z.string(),
    mode: z.enum(["withdrawal", "panic", "support", "aggression", "fire"]),
    start_tick: z.number().int(),
    causes: z.array(z.string()),
    measurements: z.record(z.string(), z.number()),
    rationale: z.string(),
    stable_ticks: z.number().int(),
    last_checked_tick: z.number().int(),
    acted_tick: z.number().int(),
    ignited: z.boolean(),
    end_tick: z.number().int().nullable(),
  })
  .strict();
const condition = z
  .object({
    mental: z.number().min(0).max(100),
    life: z.enum(["alive", "unconscious", "dead"]),
    transition_tick: z.number().int().nullable(),
    causes: z.array(z.string()),
    evidence: evidence.nullable(),
    episode: episode.nullable(),
    cooldown_until: z.number().int(),
    last_coupling_tick: z.number().int(),
    last_passive_tick: z.number().int(),
    last_action_tick: z.number().int(),
    care: z.enum(["none", "claimed", "carried", "escorted", "hospital"]),
    helper_id: z.string().nullable(),
    patient_id: z.string().nullable(),
    hospital_id: z.string().nullable(),
    wealth_band: z.enum(["poor", "middle", "rich"]),
    class_beliefs: z.record(z.string(), z.string()),
    class_evidence_tick: z.record(z.string(), z.number().int()),
    impacts: z.array(impact),
  })
  .strict();
const event = z
  .object({
    id: z.string(),
    tick: z.number().int(),
    kind: z.string(),
    actor_id: z.string().nullable(),
    target_id: z.string().nullable(),
    description: z.string(),
    evidence,
  })
  .strict();
const decision = z
  .object({
    id: z.string(),
    tick: z.number().int(),
    actor_id: z.string(),
    action: z.enum([
      "attack",
      "ignite",
      "rescue",
      "admit",
      "comfort",
      "share",
      "suppress",
    ]),
    target_id: z.string(),
    accepted: z.boolean(),
    reason: z.string(),
    effects: z.record(z.string(), z.number()),
  })
  .strict();
const inventory = z
  .object({
    food: z.number().nonnegative(),
    water: z.number().nonnegative(),
    supplies: z.number().nonnegative(),
  })
  .strict();
const fire = z
  .object({
    id: z.string(),
    actor_id: z.string(),
    target_id: z.string(),
    position: z.object({ x: z.number(), y: z.number() }).strict(),
    radius: z.number(),
    severity: z.number(),
    start_tick: z.number().int(),
    end_tick: z.number().int(),
    extinguished: z.boolean(),
  })
  .strict();
export const behaviorResponse = z
  .object({
    schema_version: z.literal("2.0.0"),
    request_id: z.string(),
    data: z
      .object({
        simulation_id: z.string(),
        ref,
        seed: z.number().int(),
        rule_version: z.string(),
        activated_tick: z.number().int().nullable(),
        citizens: z.record(z.string(), condition),
        learned_rules: z.record(
          z.string(),
          z.array(
            z
              .object({
                id: z.string(),
                learner_id: z.string(),
                topic: z.literal("rest_energy"),
                context: z.string(),
                supporting_source_ids: z.array(z.string()),
                contradicting_source_ids: z.array(z.string()),
                origin: z.literal("observed"),
                outcome_tick: z.number().int(),
                outcome_revision: z.number().int(),
                confidence: z.number().min(0).max(100),
                baseline: z.number(),
                before: z.number(),
                after: z.number(),
                last_applied_tick: z.number().int().nullable(),
                rule_version: z.string(),
              })
              .strict(),
          ),
        ),
        fires: z.record(z.string(), fire),
        hospitals: z.record(
          z.string(),
          z
            .object({
              inventory,
              patients: z.array(z.string()),
              reservations: z.record(z.string(), z.string()),
            })
            .strict(),
        ),
        events: z.array(event),
        decisions: z.array(decision),
        analytics: z
          .object({
            population: z.number().int(),
            living: z.number().int(),
            unconscious: z.number().int(),
            dead: z.number().int(),
            survival_fraction: z.number().min(0).max(1),
            deaths_by_cause: z.record(z.string(), z.number().int()),
            counters: z.record(z.string(), z.number().int()),
            means_population: z.literal("living including unconscious"),
            population_composition_changed: z.boolean(),
            tiger_behavior_supported: z.literal(false),
            snowflake_behavior_supported: z.literal(false),
          })
          .strict(),
      })
      .strict(),
  })
  .strict();
