/** Stable, texture-free character designs shared by the world and portraits. */
const skins = [
  "#f0c6a1",
  "#c98e69",
  "#8f5c43",
  "#e3ad83",
  "#654333",
  "#d9b396",
];
const hairs = [
  "#332820",
  "#71442d",
  "#d3a15e",
  "#292c39",
  "#a45137",
  "#ddd5c0",
];
const shirts = [
  "#dc745b",
  "#69a9a1",
  "#e5b85b",
  "#8298ca",
  "#b586ab",
  "#8fa668",
  "#e3a28b",
  "#6494ac",
  "#cb766f",
  "#8c82b4",
];
const trousers = ["#354857", "#685a4c", "#434a44", "#73575c", "#ece0c6"];
export function characterAppearance(name: string) {
  let seed = 2166136261;
  for (const char of name)
    seed = Math.imul(seed ^ char.charCodeAt(0), 16777619) >>> 0;
  const next = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const pick = (values: string[]) => values[Math.floor(next() * values.length)];
  return {
    skin: pick(skins),
    hair: pick(hairs),
    shirt: pick(shirts),
    pants: pick(trousers),
    accent: pick(shirts),
    hairStyle: Math.floor(next() * 4),
    glasses: next() > 0.58,
    height: 0.88 + next() * 0.25,
    width: 0.85 + next() * 0.28,
    pattern: Math.floor(next() * 3),
  };
}
