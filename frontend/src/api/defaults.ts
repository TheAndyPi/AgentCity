import type { Config, Profile, Settings } from "./types";
export const defaultTraits = {
  curiosity: 50,
  empathy: 50,
  sociability: 50,
  trust: 50,
  cooperation: 50,
  risk_tolerance: 50,
};
export const defaultConfig: Config = {
  name: "New Eden",
  seed: 42,
  mode: "sandbox",
  population: 80,
  population_traits: { ...defaultTraits },
  household_supplies: 50,
  personality_diversity: 50,
  environment: {
    resource_availability: 50,
    population_density: 75,
    infrastructure_capacity: 50,
    initial_community_trust: 50,
    settlement: "urban",
  },
  scenario_description: "",
  custom_agent_ids: [],
  tick_seconds: 10,
  max_ticks: 10000,
};
export const defaultProfile: Profile = {
  name: "",
  age: 30,
  role: "Resident",
  background: "",
  personality: "",
  values: [],
  traits: { ...defaultTraits },
  primary_goal: "",
  secondary_goals: [],
  desires: [],
  fears: [],
  personal_history: "",
  skills: [],
  intelligence: 50,
  mobility: 50,
  physical_attributes: "",
  social_needs: 50,
};
export const defaultSettings: Settings = {
  version: 0,
  theme: "dark",
  view_mode: "3d",
  autosave: true,
  reduce_motion:
    typeof matchMedia !== "undefined" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches,
  shortcuts: {
    pause: "Space",
    zoom_in: "Mod+Equal",
    zoom_out: "Mod+Minus",
    rotate_left: "Mod+ArrowLeft",
    rotate_right: "Mod+ArrowRight",
    pan_up: "ArrowUp",
    pan_down: "ArrowDown",
    pan_left: "ArrowLeft",
    pan_right: "ArrowRight",
  },
};
export const metricLabels = {
  happiness: "Happiness",
  safety: "Safety",
  trust: "Trust",
  resources: "Resources",
  stress: "Stress",
};
export const colors = {
  happiness: "#c5a0ff",
  safety: "#7ce9ba",
  trust: "#7bbdff",
  resources: "#ffda8c",
  stress: "#ff95bd",
};
export const pretty = (s: string) =>
  s.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
export const simTime = (seconds: number) =>
  `Day ${Math.floor(seconds / 86400) + 1} · ${String(Math.floor(seconds / 3600) % 24).padStart(2, "0")}:${String(Math.floor(seconds / 60) % 60).padStart(2, "0")}`;
