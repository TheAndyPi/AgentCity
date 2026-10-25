/** Stable, texture-free character designs shared by the world and portraits. */
const skins = [
  "#f0c6a1",
  "#c98e69",
  "#8f5c43",
  "#e3ad83",
  "#654333",
  "#d9b396",
];
// Natural shades plus a few neon dye jobs.
const hairs = [
  "#2a2230",
  "#5b3426",
  "#d3a15e",
  "#1d2033",
  "#e8e4f0",
  "#ff4fc3",
  "#00f0ff",
  "#b98cff",
];
// Techwear jackets: saturated enough to read against the dark streets.
const shirts = [
  "#3b2d6b",
  "#6b1f4f",
  "#1f5560",
  "#2c3a78",
  "#5a2a7a",
  "#1f6b4e",
  "#7a2140",
  "#33456e",
  "#4b2a60",
  "#205a6e",
];
const trousers = ["#15131f", "#1e1a2e", "#24202f", "#2b2238", "#101820"];
const neons = ["#00f0ff", "#ff0055", "#00ff66", "#ffe45c", "#ff4fc3", "#b98cff"];
export function characterAppearance(name: string) {
  let seed = 2166136261;
  for (const char of name)
    seed = Math.imul(seed ^ char.charCodeAt(0), 16777619) >>> 0;
  const next = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const pick = (values: string[]) => values[Math.floor(next() * values.length)];
  const skin = pick(skins),
    hair = pick(hairs),
    shirt = pick(shirts),
    pants = pick(trousers),
    accent = pick(neons);
  const hairStyle = Math.floor(next() * 4);
  const eyewear = next();
  return {
    skin,
    hair,
    shirt,
    pants,
    accent,
    hairStyle,
    /** A glowing visor band; otherwise some citizens wear plain glasses. */
    visor: eyewear > 0.62,
    glasses: eyewear > 0.38 && eyewear <= 0.62,
    height: 0.88 + next() * 0.25,
    width: 0.85 + next() * 0.28,
    pattern: Math.floor(next() * 3),
  };
}
