import type { MapData } from "../api/types";

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

const purposes = {
  apartments: {
    label: "Apartments",
    description: "Homes for city residents.",
    color: "#c7a282",
    accent: "#ecce9a",
  },
  townhouse: {
    label: "Townhouse",
    description: "Neighborhood housing.",
    color: "#ba8377",
    accent: "#ead1a1",
  },
  company: {
    label: "Company offices",
    description: "Workplaces and local businesses.",
    color: "#668d9f",
    accent: "#b4d8db",
  },
  restaurant: {
    label: "Restaurant",
    description: "Food and neighborhood retail.",
    color: "#d4ac7e",
    accent: "#b85e4c",
  },
  shop: {
    label: "Shop / market",
    description: "Everyday goods and local retail.",
    color: "#91aaa0",
    accent: "#4e827e",
  },
  hospital: {
    label: "Hospital",
    description: "Medical care and health services.",
    color: "#dce0cf",
    accent: "#659e9b",
  },
  shelter: {
    label: "Emergency shelter",
    description: "A safe place during city emergencies.",
    color: "#9aafb5",
    accent: "#526f7d",
  },
  community: {
    label: "Community center",
    description: "A gathering place for the neighborhood.",
    color: "#b1a3c0",
    accent: "#785c87",
  },
} satisfies Record<
  BuildingPurpose,
  { label: string; description: string; color: string; accent: string }
>;

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

export function buildingInfo(building: Building) {
  const purpose = buildingPurpose(building);
  return { purpose, ...purposes[purpose] };
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

export function buildingLayout(buildings: Building[]) {
  const boxes: BuildingPart[] = [],
    roofs: BuildingPart[] = [],
    polygons: Building[] = [];
  for (const b of buildings) {
    const info = buildingInfo(b),
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
      color = b.functional ? info.color : "#65636a";
    const accent = b.functional ? info.accent : "#77727b";
    const add = (
      x: number,
      y: number,
      z: number,
      width: number,
      height: number,
      depth: number,
      tint: string,
      roof = false,
    ) => {
      (roof ? roofs : boxes).push({
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
            const tint = lit && b.functional ? "#f3d9a1" : "#536e7b";
            add(
              width * offset,
              y,
              zOffset + side * (depth / 2 + 0.015),
              width * 0.19,
              Math.min(0.8, (top / floors) * 0.4),
              0.035,
              tint,
            );
            add(
              side * (width / 2 + 0.015),
              y,
              zOffset + depth * offset,
              0.035,
              Math.min(0.8, (top / floors) * 0.4),
              depth * 0.19,
              tint,
            );
          }
        }
      }
    };
    switch (info.purpose) {
      case "apartments": {
        add(0, h * 0.12, 0, w, h * 0.24, d, color);
        add(0, h * 0.55, 0, w * 0.82, h * 0.62, d * 0.82, color);
        add(0, h * 0.93, 0, w * 0.62, h * 0.14, d * 0.68, accent);
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
            "#e2d1b7",
          );
        break;
      }
      case "company": {
        add(0, h * 0.08, 0, w, h * 0.16, d, "#adb8b4");
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
            accent,
          );
        for (const side of [-1, 1]) {
          add(
            side * w * 0.39,
            h * 0.53,
            -d * 0.425,
            0.09,
            h * 0.9,
            0.06,
            accent,
          );
          add(
            side * w * 0.39,
            h * 0.53,
            d * 0.425,
            0.09,
            h * 0.9,
            0.06,
            accent,
          );
        }
        add(w * 0.1, h * 0.99, d * 0.1, w * 0.3, h * 0.02, d * 0.3, "#647a80");
        break;
      }
      case "restaurant":
      case "shop": {
        add(0, h * 0.43, d * 0.04, w * 0.94, h * 0.86, d * 0.86, color);
        add(0, h * 0.9, d * 0.04, w * 0.98, h * 0.12, d * 0.9, "#e6d2b1");
        add(0, h * 0.35, -d * 0.397, w * 0.7, h * 0.5, 0.045, "#506f77");
        add(0, h * 0.64, -d * 0.4, w, 0.16, d * 0.2, accent);
        for (let i = 0; i < 6; i++)
          add(
            -w * 0.415 + (i * w) / 6,
            h * 0.65,
            -d * 0.4,
            w / 12,
            0.18,
            d * 0.2,
            "#f3e2bd",
          );
        add(0, h * 0.76, -d * 0.402, w * 0.55, h * 0.13, 0.06, accent);
        add(
          w * 0.24,
          h * 0.98,
          d * 0.25,
          w * 0.13,
          h * 0.04,
          d * 0.15,
          "#6a6b66",
        );
        break;
      }
      case "hospital": {
        add(0, h * 0.18, 0, w, h * 0.36, d, color);
        add(0, h * 0.62, d * 0.06, w * 0.7, h * 0.76, d * 0.75, color);
        add(0, h * 0.98, d * 0.06, w * 0.74, h * 0.04, d * 0.79, accent);
        windows(
          w * 0.7,
          d * 0.75,
          h * 0.85,
          Math.max(2, Math.floor(h / 2.8)),
          d * 0.06,
        );
        add(0, h * 0.29, -d * 0.46, w * 0.6, 0.2, d * 0.08, accent);
        add(0, h * 0.61, -d * 0.322, w * 0.3, h * 0.17, 0.05, "#f2efe0");
        add(0, h * 0.61, -d * 0.333, w * 0.19, h * 0.045, 0.04, "#c4625f");
        add(0, h * 0.61, -d * 0.335, w * 0.055, h * 0.13, 0.04, "#c4625f");
        break;
      }
      case "townhouse":
      case "shelter":
      case "community": {
        add(0, h * 0.35, 0, w * 0.9, h * 0.7, d * 0.9, color);
        add(0, h * 0.85, 0, w, h * 0.3, d, accent, true);
        windows(w * 0.9, d * 0.9, h * 0.65, h > 6 ? 2 : 1);
        add(0, h * 0.18, -d * 0.46, w * 0.18, h * 0.36, 0.06, "#53666b");
        if (info.purpose === "community")
          for (const side of [-1, 1])
            add(
              side * w * 0.32,
              h * 0.24,
              -d * 0.47,
              w * 0.06,
              h * 0.48,
              d * 0.06,
              "#e6d9cb",
            );
        break;
      }
    }
  }
  return { boxes, roofs, polygons };
}
