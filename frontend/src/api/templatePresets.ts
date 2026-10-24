import type { Config } from "./types";

type Preset = {
  traits: Config["population_traits"];
  household_supplies: number;
  personality_diversity: number;
  environment: Config["environment"];
};

const presets: Record<string, Preset> = {
  flood: {
    traits: { curiosity: 40, empathy: 70, sociability: 55, trust: 60, cooperation: 72, risk_tolerance: 35 },
    household_supplies: 45,
    personality_diversity: 55,
    environment: { resource_availability: 55, population_density: 45, infrastructure_capacity: 35, initial_community_trust: 60, settlement: "suburb" },
  },
  shortage: {
    traits: { curiosity: 35, empathy: 50, sociability: 45, trust: 40, cooperation: 55, risk_tolerance: 45 },
    household_supplies: 20,
    personality_diversity: 60,
    environment: { resource_availability: 18, population_density: 65, infrastructure_capacity: 50, initial_community_trust: 42, settlement: "urban" },
  },
  misinformation: {
    traits: { curiosity: 75, empathy: 45, sociability: 72, trust: 35, cooperation: 45, risk_tolerance: 55 },
    household_supplies: 60,
    personality_diversity: 75,
    environment: { resource_availability: 60, population_density: 70, infrastructure_capacity: 60, initial_community_trust: 30, settlement: "urban" },
  },
  festival: {
    traits: { curiosity: 70, empathy: 68, sociability: 88, trust: 72, cooperation: 78, risk_tolerance: 55 },
    household_supplies: 70,
    personality_diversity: 65,
    environment: { resource_availability: 75, population_density: 60, infrastructure_capacity: 70, initial_community_trust: 75, settlement: "suburb" },
  },
  policy: {
    traits: { curiosity: 55, empathy: 55, sociability: 50, trust: 50, cooperation: 60, risk_tolerance: 40 },
    household_supplies: 40,
    personality_diversity: 70,
    environment: { resource_availability: 40, population_density: 75, infrastructure_capacity: 55, initial_community_trust: 48, settlement: "urban" },
  },
  community: {
    traits: { curiosity: 60, empathy: 62, sociability: 70, trust: 65, cooperation: 65, risk_tolerance: 45 },
    household_supplies: 60,
    personality_diversity: 60,
    environment: { resource_availability: 65, population_density: 50, infrastructure_capacity: 65, initial_community_trust: 66, settlement: "suburb" },
  },
};

const kindOf = (id: string, title: string) =>
  Object.keys(presets).find((kind) =>
    new RegExp(kind, "i").test(`${id} ${title}`),
  );

export function withScenarioPreset(
  template: { id: string; title: string; config: Config },
): Config {
  const kind = kindOf(template.id, template.title);
  if (!kind) return template.config;
  const preset = presets[kind];
  return {
    ...template.config,
    population_traits: { ...template.config.population_traits, ...preset.traits },
    household_supplies: preset.household_supplies,
    personality_diversity: preset.personality_diversity,
    environment: { ...template.config.environment, ...preset.environment },
  };
}
