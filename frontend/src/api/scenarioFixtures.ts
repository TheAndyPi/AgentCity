/** The review adapter shares recipe vocabulary with the live scenario compiler. */
import catalog from "../../../contracts/scenario-catalog.json";
import palette from "../../../contracts/scenario-palette.json";
import type {
  EffectSpec,
  EventSpec,
  ScenarioPreview,
  SceneObject,
  Vec2,
  WorldFrame,
} from "./types";
const INTERPRETATION_FAILURE =
  "The model failed to interpret this scenario input as simulation effects. Specify these parameters: " +
  "the kind of event (for example a flood, fire, storm, food or water shortage, power outage, rumor, " +
  "festival, market, concert, community aid, clinic, illness, snow, heatwave, visitors, wildlife, " +
  "robots or dinosaurs), and optionally where (north, east, south, west or citywide), how severe " +
  '(mild, severe or "severity 70") and how long (for example "for 20 ticks"). Or describe the ' +
  "scenario prompt in another way so that its effects can be interpreted.";
function pointInPolygon(p: Vec2, polygon: Vec2[]) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i],
      b = polygon[j];
    if (
      a.y > p.y !== b.y > p.y &&
      p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x
    )
      inside = !inside;
  }
  return inside;
}

export function scenarioFixture(
  frame: WorldFrame,
  source: ScenarioPreview["source"],
  prompt: string,
): ScenarioPreview {
  const premise =
    prompt.trim() ||
    (source === "policy" ? "Community aid policy" : "A sudden flood");
  const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const recipes = catalog
    .filter((r) =>
      r.terms.some(
        (t) =>
          new RegExp(`\\b${escape(t)}\\b`, "i").test(premise) &&
          !new RegExp(
            `\\b(?:no|without|not)\\s+(?:a\\s+|any\\s+)?${escape(t)}\\b`,
            "i",
          ).test(premise),
      ),
    )
    .slice(0, 8)
    .filter(
      (r) => !(r.id === "shortage" && /\bwater shortage\b/i.test(premise)),
    )
    .map((r) => {
      const terms = `(?:${r.terms.map(escape).join("|")})`;
      const colors = Object.keys(palette).join("|");
      const count = premise.match(
        new RegExp(`\\b(\\d+)\\s+(?:(?:${colors})\\s+)?${terms}\\b`, "i"),
      );
      const color = premise.match(
        new RegExp(`\\b(${colors})\\s+${terms}\\b`, "i"),
      );
      return {
        ...r,
        count: count ? Math.min(8, Math.max(1, Number(count[1]))) : r.count,
        color: color
          ? palette[color[1].toLowerCase() as keyof typeof palette]
          : r.color,
      };
    });
  const { width_m: w, height_m: h } = frame.map;
  const hazard = ["flood", "fire", "storm"].includes(recipes[0]?.kind ?? "");
  let x0 = 0,
    y0 = 0,
    x1 = hazard ? w / 2 : w,
    y1 = hazard ? h * 0.5625 : h;
  if (/\b(?:whole city|entire city|citywide)\b/i.test(premise)) {
    x1 = w;
    y1 = h;
  }
  if (/\bnorth\b/i.test(premise)) {
    y0 = h / 2;
    x1 = w;
    y1 = h;
  } else if (/\beast\b/i.test(premise)) {
    x0 = w / 2;
    x1 = w;
    y1 = h;
  } else if (/\bwest\b/i.test(premise)) {
    x1 = w / 2;
    y1 = h;
  } else if (/\bsouth\b/i.test(premise)) {
    x1 = w;
    y1 = h / 2;
  }
  const polygon = [
    { x: x0, y: y0 },
    { x: x1, y: y0 },
    { x: x1, y: y1 },
    { x: x0, y: y1 },
  ];
  const title = premise.replace(/\s+/g, " ").slice(0, 80).trim();
  const severity = Number(
    premise.match(/severity\s*[:=]?\s*(\d+(?:\.\d+)?)/i)?.[1] ??
      (/severe|major|extreme/i.test(premise)
        ? 85
        : /mild|minor|small/i.test(premise)
          ? 25
          : 50),
  );
  const effects: EffectSpec[] = [];
  for (const r of recipes)
    for (const raw of r.effects) {
      const e = structuredClone(raw) as EffectSpec;
      if (e.type === "hazard") e.severity = severity;
      if (e.type === "community") e.capacity = frame.agents.length;
      if (!effects.some((v) => JSON.stringify(v) === JSON.stringify(e)))
        effects.push(e);
    }
  effects.splice(19);
  effects.push({
    type: "information",
    message: premise.slice(0, 2000),
    reliability: recipes.some((r) => r.id === "misinformation") ? 25 : 100,
    delivery: "local",
  });
  const positions: Vec2[] = frame.map.cells
    .filter((c) => c.walkable && c.terrain !== "water")
    .map((c) => ({
      x: (c.col + 0.5) * frame.map.cell_size_m,
      y: (c.row + 0.5) * frame.map.cell_size_m,
    }))
    .filter((p) => pointInPolygon(p, polygon));
  const center = { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
  positions.sort(
    (a, b) =>
      Math.hypot(a.x - center.x, a.y - center.y) -
      Math.hypot(b.x - center.x, b.y - center.y),
  );
  const scene: SceneObject[] = [];
  for (const r of recipes.length
    ? recipes
    : [
        { model: "monument", color: "#b8cbd6", count: 1, id: "your scenario" },
      ]) {
    for (let i = 0; i < r.count && scene.length < 24; i++) {
      const position = positions.find((p) =>
        scene.every(
          (o) => Math.hypot(p.x - o.position.x, p.y - o.position.y) >= 6,
        ),
      );
      if (!position) break;
      scene.push({
        model: r.model as SceneObject["model"],
        color: r.color,
        label: recipes.length <= 1 ? title : r.id,
        position,
        scale: 1,
        rotation: 0,
      });
    }
  }
  return {
    id: crypto.randomUUID(),
    simulation_id: frame.simulation.id,
    source,
    source_event_id: null,
    based_on: frame.ref,
    expires_at: new Date(Date.now() + 600000).toISOString(),
    interpretation: recipes.length
      ? `${premise} Citizens respond in their own way.`
      : INTERPRETATION_FAILURE,
    spec: {
      title,
      description: premise,
      kind: (recipes[0]?.kind ?? "custom") as EventSpec["kind"],
      origin: center,
      affected_polygon: polygon,
      severity,
      duration_ticks: Number(premise.match(/(\d+)\s*ticks?/i)?.[1] ?? 8),
      effects: effects.slice(0, 20),
      success_condition: "duration_elapsed",
      scene,
    },
    affected_agent_ids: frame.agents
      .filter((a) => pointInPolygon(a.position, polygon))
      .map((a) => a.id),
    affected_building_ids: frame.map.buildings
      .filter((b) => pointInPolygon(b.entrance, polygon))
      .map((b) => b.id),
    warnings: [],
    unsupported_requests: recipes.length ? [] : [INTERPRETATION_FAILURE],
    can_commit: !!premise && recipes.length > 0,
  };
}
