import type { AgentCityClient } from "./client";

export const nameKey = (name: string) => name.trim().toLowerCase();

export const takenMessage =
  "A simulation with this name already exists. Choose a different name.";

export async function simulationNames(client: AgentCityClient) {
  const [active, archived] = await Promise.all([
    client.simulations(),
    client.simulations(true),
  ]);
  return new Set([...active, ...archived].map((s) => nameKey(s.name)));
}

export function uniqueName(name: string, taken: Set<string>) {
  if (!taken.has(nameKey(name))) return name;
  const base = name.replace(/\s+\d+$/, "").slice(0, 74);
  let n = 2;
  while (taken.has(nameKey(`${base} ${n}`))) n++;
  return `${base} ${n}`;
}
