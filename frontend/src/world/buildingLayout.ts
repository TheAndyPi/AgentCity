import type { MapData } from "../api/types";
import { neon, worldPalette, type WorldTheme } from "./palette";

export type Building = MapData["buildings"][number];
export type BuildingPurpose =
  | "apartments"
  | "townhouse"
  | "company"
  | "restaurant"
  | "shop"
  | "hospital"
  | "shelter"
  | "community";

type Look = { color: string; accent: string };
const purposes: Record<
  BuildingPurpose,
  { label: string; description: string; dark: Look; light: Look }
> = {
  apartments: {
    label: "Apartments",
    description: "Homes for city residents.",
    dark: { color: "#3b2f66", accent: neon.cyan },
    light: { color: "#d8ccf0", accent: "#22c7dd" },
  },
  townhouse: {
    label: "Townhouse",
    description: "Neighborhood housing.",
    dark: { color: "#4a2d5c", accent: neon.pink },
    light: { color: "#f0d2e6", accent: "#ec4fb4" },
  },
  company: {
    label: "Company offices",
    description: "Workplaces and local businesses.",
    dark: { color: "#283a66", accent: neon.violet },
    light: { color: "#cad7f2", accent: "#8f6ce0" },
  },
  restaurant: {
    label: "Restaurant",
    description: "Food and neighborhood retail.",
    dark: { color: "#572a4f", accent: neon.magenta },
    light: { color: "#f6d0dc", accent: "#ff3f7f" },
  },
  shop: {
    label: "Shop / market",
    description: "Everyday goods and local retail.",
    dark: { color: "#24474f", accent: neon.green },
    light: { color: "#cdeee0", accent: "#1fcf7a" },
  },
  hospital: {
    label: "Hospital",
    description: "Medical care and health services.",
    dark: { color: "#3c4566", accent: "#e8f6ff" },
    light: { color: "#f4f1fb", accent: "#7fd9f0" },
  },
  shelter: {
    label: "Emergency shelter",
    description: "A safe place during city emergencies.",
    dark: { color: "#2a4a55", accent: neon.yellow },
    light: { color: "#d3ecef", accent: "#e0b92a" },
  },
  community: {
    label: "Community center",
    description: "A gathering place for the neighborhood.",
    dark: { color: "#43356b", accent: neon.yellow },
    light: { color: "#efe3c4", accent: "#d9a520" },
  },
};
export const hospitalCross = neon.magenta;

export function buildingPurpose(building: Building): BuildingPurpose {
  if (building.kind === "home")
    return /townhouse|cottage|house\b/i.test(building.name)
      ? "townhouse"
      : "apartments";
  if (building.kind === "work") return "company";
  if (building.kind === "shop")
    return /restaurant|café|cafe|diner|bistro/i.test(building.name)
      ? "restaurant"
      : "shop";
  return building.kind;
}

export function buildingInfo(building: Building, theme: WorldTheme = "dark") {
  const purpose = buildingPurpose(building);
  const { label, description } = purposes[purpose];
  return { purpose, label, description, ...purposes[purpose][theme] };
}

export function buildingBounds(building: Building) {
  const xs = building.footprint.map((p) => p.x),
    ys = building.footprint.map((p) => p.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  return {
    x: (minX + maxX) / 2,
    y: (minY + maxY) / 2,
    width: maxX - minX,
    depth: maxY - minY,
  };
}

// Live frames update occupancy every tick, but the neighborhood geometry stays put.
export const buildingSignature = (buildings: Building[]) =>
  JSON.stringify(
    buildings.map((b) => [
      b.id,
      b.name,
      b.kind,
      b.footprint,
      b.entrance,
      b.height_m,
      b.functional,
    ]),
  );

export type BuildingPart = {
  buildingId: string;
  position: [number, number, number];
  scale: [number, number, number];
  rotation: number;
  color: string;
};

/** Towers above this height get setbacks, neon corner strips and a spire. */
export const skyscraperHeight = 25;
const windowNeons = [neon.cyan, neon.pink, neon.yellow, neon.cyan, neon.violet];

export function buildingLayout(
  buildings: Building[],
  theme: WorldTheme = "dark",
) {
  const palette = worldPalette(theme);
  const boxes: BuildingPart[] = [],
    roofs: BuildingPart[] = [],
    glows: BuildingPart[] = [],
    beacons: BuildingPart[] = [],
    polygons: Building[] = [];
  for (const b of buildings) {
    const info = buildingInfo(b, theme),
      bounds = buildingBounds(b);
    const rectangular =
      b.footprint.length === 4 &&
      b.footprint.every(
        (p, i, all) => p.x === all[(i + 1) % 4].x || p.y === all[(i + 1) % 4].y,
      );
    if (!rectangular) {
      polygons.push(b);
      continue;
    }
    const dx = b.entrance.x - bounds.x,
      dz = b.entrance.y - bounds.y;
    // Local front is -Z; face the entrance on whichever street borders this lot.
    const angle =
      Math.abs(dx) > Math.abs(dz)
        ? dx < 0
          ? Math.PI / 2
          : -Math.PI / 2
        : dz < 0
          ? 0
          : Math.PI;
    const sideways = Math.abs(dx) > Math.abs(dz);
    const w = sideways ? bounds.depth : bounds.width,
      d = sideways ? bounds.width : bounds.depth;
    const h = Math.max(0.2, b.height_m),
      color = b.functional ? info.color : palette.offline;
    const accent = b.functional ? info.accent : palette.trimOffline;
    const seed = Math.abs(Math.round(bounds.x * 7 + bounds.y * 13));
    const add = (
      x: number,
      y: number,
      z: number,
      width: number,
      height: number,
      depth: number,
      tint: string,
      kind: "box" | "roof" | "glow" | "beacon" = "box",
    ) => {
      if (!b.functional && (kind === "glow" || kind === "beacon")) {
        kind = "box";
        tint = palette.trimOffline;
      }
      const list =
        kind === "roof"
          ? roofs
          : kind === "glow"
            ? glows
            : kind === "beacon"
              ? beacons
              : boxes;
      list.push({
        buildingId: b.id,
        position: [
          bounds.x + x * Math.cos(angle) + z * Math.sin(angle),
          y,
          bounds.y - x * Math.sin(angle) + z * Math.cos(angle),
        ],
        scale: [width, height, depth],
        rotation: angle,
        color: tint,
      });
    };
    // Thin neon strips along the top edges of a volume.
    const outline = (
      width: number,
      depth: number,
      top: number,
      tint: string,
      z = 0,
    ) => {
      const t = 0.07;
      add(0, top - t / 2, z - depth / 2 + t / 2, width, t, t, tint, "glow");
      add(0, top - t / 2, z + depth / 2 - t / 2, width, t, t, tint, "glow");
      add(-width / 2 + t / 2, top - t / 2, z, t, t, depth, tint, "glow");
      add(width / 2 - t / 2, top - t / 2, z, t, t, depth, tint, "glow");
    };
    const windows = (
      width: number,
      depth: number,
      top: number,
      floors: number,
      zOffset = 0,
    ) => {
      for (let floor = 0; floor < floors; floor++) {
        const y = ((floor + 0.65) * top) / floors;
        for (const side of [-1, 1]) {
          for (const offset of [-0.23, 0.23]) {
            const lit =
              (floor + (side > 0 ? 1 : 0) + Math.round(bounds.x)) % 3 === 0;
            const tint = lit
              ? windowNeons[(floor + seed) % windowNeons.length]
              : palette.unlit;
            const kind = lit ? "glow" : "box";
            const tall = Math.min(0.8, (top / floors) * 0.4);
            add(
              width * offset,
              y,
              zOffset + side * (depth / 2 + 0.015),
              width * 0.19,
              tall,
              0.035,
              tint,
              kind,
            );
            add(
              side * (width / 2 + 0.015),
              y,
              zOffset + depth * offset,
              0.035,
              tall,
              depth * 0.19,
              tint,
              kind,
            );
          }
        }
      }
    };
    const tower =
      h >= skyscraperHeight &&
      info.purpose !== "shop" &&
      info.purpose !== "restaurant";
    if (tower) {
      // Podium, three setbacks and a spire, all inside the authoritative lot.
      add(0, h * 0.04, 0, w, h * 0.08, d, color);
      const tiers = [
        [0.08, 0.56, 0.86],
        [0.56, 0.82, 0.7],
        [0.82, 0.94, 0.52],
      ] as const;
      tiers.forEach(([from, to, size], tier) => {
        const tw = w * size,
          td = d * size,
          height = h * (to - from),
          mid = h * (from + to) / 2;
        add(0, mid, 0, tw, height, td, color);
        for (const [sx, sz] of [
          [-1, -1],
          [1, -1],
          [-1, 1],
          [1, 1],
        ])
          add(
            sx * (tw / 2 - 0.04),
            mid,
            sz * (td / 2 - 0.04),
            0.08,
            height,
            0.08,
            tier === 1 ? neon.pink : accent,
            "glow",
          );
        outline(tw, td, h * to, tier === 2 ? neon.yellow : accent);
        if (tier === 2) return;
        const floors = Math.min(14, Math.max(2, Math.floor(height / 6.4)));
        for (let floor = 0; floor < floors; floor++) {
          const y = h * from + ((floor + 0.5) * height) / floors;
          const tint = windowNeons[(floor + seed + tier) % windowNeons.length];
          const lit = (floor + seed) % 4 !== 0;
          for (const side of [-1, 1]) {
            add(
              0,
              y,
              side * (td / 2 + 0.012),
              tw * 0.82,
              0.16,
              0.025,
              lit ? tint : palette.unlit,
              lit ? "glow" : "box",
            );
            add(
              side * (tw / 2 + 0.012),
              y,
              0,
              0.025,
              0.16,
              td * 0.82,
              lit ? tint : palette.unlit,
              lit ? "glow" : "box",
            );
          }
        }
      });
      // A holographic billboard on the second setback faces the street.
      add(
        0,
        h * 0.69,
        -(d * 0.7) / 2 - 0.03,
        w * 0.42,
        h * 0.07,
        0.05,
        info.purpose === "hospital" ? hospitalCross : neon.magenta,
        "glow",
      );
      add(0, h * 0.97, 0, 0.14, h * 0.06, 0.14, palette.unlit);
      add(0, h * 0.995, 0, 0.3, h * 0.01, 0.3, neon.magenta, "beacon");
      continue;
    }
    switch (info.purpose) {
      case "apartments": {
        add(0, h * 0.12, 0, w, h * 0.24, d, color);
        add(0, h * 0.55, 0, w * 0.82, h * 0.62, d * 0.82, color);
        add(0, h * 0.93, 0, w * 0.62, h * 0.14, d * 0.68, color);
        outline(w * 0.62, d * 0.68, h, accent);
        const floors = Math.max(2, Math.min(7, Math.floor(h / 2.4)));
        windows(w * 0.82, d * 0.82, h * 0.85, floors);
        for (let floor = 1; floor <= floors; floor++)
          add(
            0,
            (floor * h * 0.85) / floors,
            -d * 0.43,
            w * 0.82,
            0.12,
            d * 0.12,
            floor === floors ? accent : palette.unlit,
            floor === floors ? "glow" : "box",
          );
        break;
      }
      case "company": {
        add(0, h * 0.08, 0, w, h * 0.16, d, color);
        add(0, h * 0.53, 0, w * 0.84, h * 0.9, d * 0.84, color);
        const floors = Math.max(2, Math.min(9, Math.floor(h / 2.3)));
        for (let floor = 1; floor <= floors; floor++)
          add(
            0,
            (floor * h * 0.96) / floors,
            0,
            w * 0.87,
            0.1,
            d * 0.87,
            floor % 2 ? accent : neon.cyan,
            "glow",
          );
        for (const side of [-1, 1]) {
          add(side * w * 0.39, h * 0.53, -d * 0.425, 0.09, h * 0.9, 0.06, accent, "glow");
          add(side * w * 0.39, h * 0.53, d * 0.425, 0.09, h * 0.9, 0.06, accent, "glow");
        }
        add(w * 0.1, h * 0.99, d * 0.1, w * 0.3, h * 0.02, d * 0.3, palette.unlit);
        break;
      }
      case "restaurant":
      case "shop": {
        add(0, h * 0.43, d * 0.04, w * 0.94, h * 0.86, d * 0.86, color);
        add(0, h * 0.9, d * 0.04, w * 0.98, h * 0.12, d * 0.9, color);
        outline(w * 0.98, d * 0.9, h * 0.96, accent, d * 0.04);
        add(0, h * 0.35, -d * 0.397, w * 0.7, h * 0.5, 0.045, palette.unlit);
        add(0, h * 0.64, -d * 0.4, w, 0.16, d * 0.2, accent, "glow");
        for (let i = 0; i < 6; i++)
          add(
            -w * 0.415 + (i * w) / 6,
            h * 0.65,
            -d * 0.4,
            w / 12,
            0.18,
            d * 0.2,
            i % 2 ? neon.yellow : accent,
            "glow",
          );
        add(0, h * 0.76, -d * 0.402, w * 0.55, h * 0.13, 0.06, accent, "glow");
        add(w * 0.24, h * 0.98, d * 0.25, w * 0.13, h * 0.04, d * 0.15, palette.unlit);
        break;
      }
      case "hospital": {
        add(0, h * 0.18, 0, w, h * 0.36, d, color);
        add(0, h * 0.6, d * 0.06, w * 0.7, h * 0.72, d * 0.75, color);
        // One solid roof slab that fully covers the tower top, so the two
        // surfaces never share a visible plane.
        add(0, h * 0.98, d * 0.06, w * 0.74, h * 0.04, d * 0.79, color);
        outline(w * 0.74, d * 0.79, h, accent, d * 0.06);
        windows(
          w * 0.7,
          d * 0.75,
          h * 0.85,
          Math.max(2, Math.floor(h / 2.8)),
          d * 0.06,
        );
        add(0, h * 0.29, -d * 0.46, w * 0.6, 0.2, d * 0.08, accent, "glow");
        add(0, h * 0.61, -d * 0.322, w * 0.3, h * 0.17, 0.05, palette.unlit);
        add(0, h * 0.61, -d * 0.333, w * 0.19, h * 0.045, 0.04, hospitalCross, "glow");
        add(0, h * 0.61, -d * 0.335, w * 0.055, h * 0.13, 0.04, hospitalCross, "glow");
        break;
      }
      case "townhouse":
      case "shelter":
      case "community": {
        add(0, h * 0.35, 0, w * 0.9, h * 0.7, d * 0.9, color);
        add(0, h * 0.85, 0, w, h * 0.3, d, color, "roof");
        outline(w * 0.9, d * 0.9, h * 0.7, accent);
        windows(w * 0.9, d * 0.9, h * 0.65, h > 6 ? 2 : 1);
        add(0, h * 0.18, -d * 0.46, w * 0.18, h * 0.36, 0.06, accent, "glow");
        if (info.purpose === "community")
          for (const side of [-1, 1])
            add(
              side * w * 0.32,
              h * 0.24,
              -d * 0.47,
              w * 0.06,
              h * 0.48,
              d * 0.06,
              neon.cyan,
              "glow",
            );
        break;
      }
    }
  }
  return { boxes, roofs, glows, beacons, polygons };
}
