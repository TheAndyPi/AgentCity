import { useEffect, useMemo, useRef, useState } from "react";
import { Html } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import {
  buildingBounds,
  buildingInfo,
  buildingLayout,
  buildingSignature,
  type Building,
  type BuildingPart,
} from "./buildingLayout";
import { worldPalette, type WorldTheme } from "./palette";

export function BuildingTag({
  building,
  theme = "dark",
}: {
  building: Building;
  theme?: WorldTheme;
}) {
  const info = buildingInfo(building, theme);
  return (
    <div
      className="building-tag"
      role="tooltip"
      data-building-tooltip={building.id}
    >
      <span className="building-tag-purpose" style={{ color: info.accent }}>
        {info.label}
      </span>
      <strong>{building.name}</strong>
      <span>{info.description}</span>
      <small>
        {building.functional ? "Open" : "Out of service"} · Capacity{" "}
        {building.capacity}
      </small>
    </div>
  );
}

function Parts({
  parts,
  roof = false,
  glow = false,
  blink = false,
  onHover,
  onPick = onHover,
}: {
  parts: BuildingPart[];
  roof?: boolean;
  glow?: boolean;
  blink?: boolean;
  onHover: (id: string | null) => void;
  onPick?: (id: string | null) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const beacon = useRef<THREE.MeshBasicMaterial>(null);
  useFrame(({ clock }) => {
    if (blink && beacon.current)
      beacon.current.opacity =
        0.2 + 0.8 * Math.max(0, Math.sin(clock.elapsedTime * 2.4));
  });
  useEffect(() => {
    if (!ref.current) return;
    const object = new THREE.Object3D(),
      color = new THREE.Color();
    parts.forEach((part, i) => {
      object.position.set(...part.position);
      object.rotation.set(0, part.rotation + (roof ? Math.PI / 4 : 0), 0);
      object.scale.set(
        part.scale[0] / (roof ? Math.SQRT2 : 1),
        part.scale[1],
        part.scale[2] / (roof ? Math.SQRT2 : 1),
      );
      object.updateMatrix();
      ref.current!.setMatrixAt(i, object.matrix);
      ref.current!.setColorAt(i, color.set(part.color));
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
    // Instanced raycasting must include the full city, including tall buildings.
    ref.current.computeBoundingSphere();
  }, [parts, roof]);
  const hover = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHover(parts[event.instanceId ?? -1]?.buildingId ?? null);
  };
  if (!parts.length) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, parts.length]}
      onPointerMove={hover}
      onPointerOut={() => onHover(null)}
      onClick={(event) => {
        event.stopPropagation();
        onPick(parts[event.instanceId ?? -1]?.buildingId ?? null);
      }}
    >
      {roof ? <coneGeometry args={[1, 1, 4]} /> : <boxGeometry />}
      {glow ? (
        <meshBasicMaterial
          ref={beacon}
          toneMapped={false}
          transparent={blink}
          depthWrite={!blink}
        />
      ) : (
        <meshStandardMaterial roughness={0.7} metalness={0.1} />
      )}
    </instancedMesh>
  );
}

function PolygonBuilding({
  building,
  theme,
  onHover,
  onPick = onHover,
}: {
  building: Building;
  theme: WorldTheme;
  onHover: (id: string | null) => void;
  onPick?: (id: string | null) => void;
}) {
  const shape = useMemo(
    () =>
      new THREE.Shape(
        building.footprint.map((p) => new THREE.Vector2(p.x, -p.y)),
      ),
    [building.footprint],
  );
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      onPointerMove={(e) => {
        e.stopPropagation();
        onHover(building.id);
      }}
      onPointerOut={() => onHover(null)}
      onClick={(e) => {
        e.stopPropagation();
        onPick(building.id);
      }}
    >
      <extrudeGeometry
        args={[shape, { depth: building.height_m, bevelEnabled: false }]}
      />
      <meshStandardMaterial
        color={
          building.functional
            ? buildingInfo(building, theme).color
            : worldPalette(theme).offline
        }
        emissive={buildingInfo(building, theme).accent}
        emissiveIntensity={building.functional ? 0.08 : 0}
      />
    </mesh>
  );
}

export default function Buildings({
  buildings,
  cutaway = [],
  theme = "dark",
  reducedMotion = false,
  onClick,
}: {
  buildings: Building[];
  cutaway?: string[];
  theme?: WorldTheme;
  reducedMotion?: boolean;
  /** A building was clicked, which also counts as clicking away from a citizen. */
  onClick?: () => void;
}) {
  const signature = buildingSignature(buildings);
  // Reuse thousands of facade instances while citizens and occupancy update.
  const layout = useMemo(
    () => buildingLayout(buildings, theme),
    [signature, theme],
  );
  const visible = (parts: BuildingPart[]) =>
    parts.filter((p) => !cutaway.includes(p.buildingId));
  const [hovered, setHovered] = useState<string | null>(null);
  const building = buildings.find((b) => b.id === hovered);
  const bounds = building ? buildingBounds(building) : null;
  const pick = (id: string | null) => {
    setHovered(id);
    onClick?.();
  };
  return (
    <>
      <Parts parts={visible(layout.boxes)} onHover={setHovered} onPick={pick} />
      <Parts parts={visible(layout.roofs)} roof onHover={setHovered} onPick={pick} />
      <Parts parts={visible(layout.glows)} glow onHover={setHovered} onPick={pick} />
      <Parts
        parts={visible(layout.beacons)}
        glow
        blink={!reducedMotion}
        onHover={setHovered}
        onPick={pick}
      />
      {layout.polygons
        .filter((b) => !cutaway.includes(b.id))
        .map((b) => (
          <PolygonBuilding
            key={b.id}
            building={b}
            theme={theme}
            onHover={setHovered}
            onPick={pick}
          />
        ))}
      {buildings
        .filter((b) => cutaway.includes(b.id))
        .map((b) => {
          const bounds = buildingBounds(b);
          return (
            <group key={`interior-${b.id}`}>
              <PolygonBuilding
                building={{ ...b, height_m: 0.04 }}
                theme={theme}
                onHover={setHovered}
                onPick={pick}
              />
              {b.footprint.map((a, i) => {
                const next = b.footprint[(i + 1) % b.footprint.length];
                return (
                  <mesh
                    key={i}
                    position={[(a.x + next.x) / 2, 0.16, (a.y + next.y) / 2]}
                    rotation={[0, -Math.atan2(next.y - a.y, next.x - a.x), 0]}
                  >
                    <boxGeometry
                      args={[
                        Math.hypot(next.x - a.x, next.y - a.y),
                        0.24,
                        0.08,
                      ]}
                    />
                    <meshBasicMaterial
                      color={buildingInfo(b, theme).accent}
                      toneMapped={false}
                    />
                  </mesh>
                );
              })}
              <Html
                position={[bounds.x, 0.3, bounds.y - bounds.depth / 2]}
                center
                zIndexRange={[5, 0]}
                style={{ pointerEvents: "none" }}
              >
                <div className="character-nameplate">
                  Inside {b.name} · {b.occupancy}/{b.capacity}
                </div>
              </Html>
            </group>
          );
        })}
      {building && bounds && (
        <Html
          position={[bounds.x, building.height_m + 2, bounds.y]}
          center
          zIndexRange={[12, 0]}
          style={{ pointerEvents: "none" }}
        >
          <BuildingTag building={building} theme={theme} />
        </Html>
      )}
    </>
  );
}
