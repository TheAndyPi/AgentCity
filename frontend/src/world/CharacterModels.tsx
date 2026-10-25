import { useLayoutEffect, useMemo, useRef } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { AgentSummary, Vec2, WorldFrame } from "../api/types";
import { insideBuilding } from "./buildingAccess";
import { characterAppearance } from "./characterAppearance";
import {
  WalkingCadence,
  acknowledgedRoute,
  pointAlongRoute,
  separatePositions,
} from "./motion";
import { layoutSpeech, speechBySpeaker, speechScale } from "./speech";

// A fixed number of instanced draws for the whole cast. No downloaded models,
// skeletons, textures or per-frame React state updates.
const parts = [
  "body",
  "head",
  "hair",
  "sideHair",
  "arms",
  "legs",
  "hands",
  "shoes",
  "eyes",
  "nose",
  "glasses",
  "visor",
  "soles",
] as const;
type Part = (typeof parts)[number];
const double = new Set<Part>([
  "sideHair",
  "arms",
  "legs",
  "hands",
  "shoes",
  "eyes",
  "glasses",
  "soles",
]);
const glowing = new Set<Part>(["visor", "soles"]);
const object = new THREE.Object3D(),
  color = new THREE.Color();
const material = new THREE.MeshStandardMaterial({
  flatShading: true,
  roughness: 0.6,
  metalness: 0.15,
});
const glowMaterial = new THREE.MeshBasicMaterial({ toneMapped: false });
// Reveal only the fragments hidden by the city, preserving the normal model.
const highlightMaterial = new THREE.MeshBasicMaterial({
  color: "#00f0ff",
  transparent: true,
  opacity: 0.65,
  depthFunc: THREE.GreaterDepth,
  depthWrite: false,
  toneMapped: false,
});
const shape = {
  body: new THREE.CapsuleGeometry(0.38, 0.52, 2, 6),
  head: new THREE.SphereGeometry(0.43, 8, 6),
  hair: new THREE.SphereGeometry(0.45, 8, 5, 0, Math.PI * 2, 0, Math.PI * 0.56),
  sideHair: new THREE.BoxGeometry(1, 1, 1),
  arms: new THREE.CapsuleGeometry(0.105, 0.52, 2, 5),
  legs: new THREE.BoxGeometry(0.23, 0.66, 0.25),
  hands: new THREE.SphereGeometry(0.12, 5, 4),
  shoes: new THREE.BoxGeometry(0.26, 0.17, 0.4),
  eyes: new THREE.SphereGeometry(0.043, 5, 4),
  nose: new THREE.SphereGeometry(0.075, 5, 4),
  glasses: new THREE.TorusGeometry(0.11, 0.018, 3, 8),
  visor: new THREE.BoxGeometry(0.7, 0.13, 0.1),
  soles: new THREE.BoxGeometry(0.28, 0.04, 0.42),
};
/** Speech bubbles appear once the camera is close enough to read them. */
export const conversationZoom = 11;
export default function CharacterModels({
  frame,
  selected,
  focus = [],
  onSelect,
  reducedMotion,
}: {
  frame: WorldFrame;
  selected: string | null;
  focus?: string[];
  onSelect: (id: string) => void;
  reducedMotion: boolean;
}) {
  const meshes = useRef<Partial<Record<Part, THREE.InstancedMesh>>>({});
  const highlightMeshes = useRef<Partial<Record<Part, THREE.InstancedMesh>>>(
    {},
  );
  const speech = speechBySpeaker(frame, focus);
  const highlightedAgents = frame.agents.filter(
    (agent) =>
      agent.id === selected ||
      focus.includes(agent.id) ||
      speech.has(agent.id) ||
      agent.action === "talk" ||
      agent.action === "warn",
  );
  const highlightSlots = new Map(
    highlightedAgents.map((agent, index) => [agent.id, index]),
  );
  const labelElements = useRef(new Map<string, HTMLDivElement>());
  const bubbles = useRef(new Map<string, HTMLDivElement>());
  const labels = useRef(new Map<string, THREE.Group>());
  const displayed = useRef(new Map<string, Vec2>());
  const cadence = useRef(new WalkingCadence());
  const prior = useRef(new Map<string, AgentSummary>());
  const transition = useRef({
    routes: new Map<string, Vec2[]>(),
    changed: 0,
    id: "",
    tick: -1,
  });
  const looks = useMemo(
    () => frame.agents.map((a) => characterAppearance(a.name)),
    [frame.agents],
  );
  useLayoutEffect(() => {
    cadence.current.observe(
      frame.simulation.id,
      frame.ref.tick,
      performance.now(),
      frame.simulation.status === "running",
    );
    const last = transition.current;
    const reset = last.id !== frame.simulation.id || frame.ref.tick < last.tick;
    const changed =
      reset ||
      frame.agents.some((a) => {
        const old = prior.current.get(a.id);
        return (
          !old ||
          old.position.x !== a.position.x ||
          old.position.y !== a.position.y
        );
      });
    if (changed) {
      const routes = new Map(
        frame.agents.map((a) => {
          const start = reset
            ? a.position
            : (displayed.current.get(a.id) ??
              prior.current.get(a.id)?.position ??
              a.position);
          return [a.id, acknowledgedRoute(start, a.position, frame.map)];
        }),
      );
      transition.current = {
        routes,
        changed: performance.now(),
        id: frame.simulation.id,
        tick: frame.ref.tick,
      };
      if (reset) displayed.current.clear();
    } else transition.current.tick = frame.ref.tick;
    prior.current = new Map(frame.agents.map((a) => [a.id, a]));
  }, [frame]);
  useFrame(({ clock, camera, size }) => {
    const duration = cadence.current.duration;
    const t = reducedMotion
      ? 1
      : Math.min(
          1,
          (performance.now() - transition.current.changed) / duration,
        );
    const requestedPositions = frame.agents.map((a) =>
      pointAlongRoute(transition.current.routes.get(a.id) ?? [a.position], t),
    );
    const positions = separatePositions(requestedPositions, (p, index) => {
      const map = frame.map;
      if (p.x < 0 || p.y < 0 || p.x >= map.width_m || p.y >= map.height_m)
        return false;
      const cell =
        map.cells[
          Math.floor(p.y / map.cell_size_m) * map.columns +
            Math.floor(p.x / map.cell_size_m)
        ];
      const room = map.buildings.find((building) =>
        insideBuilding(requestedPositions[index], building),
      );
      return room ? insideBuilding(p, room) : (cell?.walkable ?? false);
    });
    frame.agents.forEach((a, i) => {
      const old = displayed.current.get(a.id);
      const p = positions[i];
      labels.current.get(a.id)?.position.set(p.x, 0, p.y);
      const moved = old ? Math.hypot(p.x - old.x, p.y - old.y) : 0;
      const yaw =
        old && moved > 0.001
          ? Math.atan2(p.x - old.x, p.y - old.y)
          : a.heading_rad;
      displayed.current.set(a.id, p);
      const label = labelElements.current.get(a.id);
      if (label) {
        label.dataset.worldX = String(p.x);
        label.dataset.worldY = String(p.y);
      }
      const look = looks[i];
      const moving = !reducedMotion && moved > 0.001;
      const phase = clock.elapsedTime * 9 + i * 2;
      const talking = a.action === "talk" || a.action === "warn";
      const bob = reducedMotion
        ? 0
        : moving
          ? Math.abs(Math.sin(phase)) * 0.07
          : Math.sin(clock.elapsedTime * 2 + i) * 0.012;
      const put = (
        part: Part,
        slot: number,
        x: number,
        y: number,
        z: number,
        sx: number,
        sy: number,
        sz: number,
        fill: string,
        rx = 0,
      ) => {
        const mesh = meshes.current[part];
        if (!mesh) return;
        object.position.set(
          p.x + (x * Math.cos(yaw) + z * Math.sin(yaw)) * look.width,
          (y + bob) * look.height,
          p.y + (-x * Math.sin(yaw) + z * Math.cos(yaw)) * look.width,
        );
        object.rotation.set(0, yaw, 0);
        object.rotateX(rx);
        object.scale.set(sx * look.width, sy * look.height, sz * look.width);
        object.updateMatrix();
        mesh.setMatrixAt(slot, object.matrix);
        mesh.setColorAt(slot, color.set(fill));
        const highlightIndex = highlightSlots.get(a.id);
        const overlay = highlightMeshes.current[part];
        if (highlightIndex !== undefined && overlay) {
          overlay.setMatrixAt(
            double.has(part) ? highlightIndex * 2 + (slot % 2) : highlightIndex,
            object.matrix,
          );
        }
      };
      put("body", i, 0, 1.14, 0, 1, 1, 0.76, look.shirt);
      put("head", i, 0, 2.0, 0, 1.03, 1.08, 0.94, look.skin);
      put(
        "hair",
        i,
        0,
        2.08,
        -0.015,
        look.hairStyle === 2 ? 1.15 : 1.04,
        look.hairStyle === 0 ? 0.75 : 1.1,
        1,
        look.hair,
      );
      put("nose", i, 0, 1.98, 0.4, 1, 0.9, 1.3, look.skin);
      put(
        "visor",
        i,
        0,
        2.04,
        0.37,
        look.visor ? 1 : 0,
        look.visor ? 1 : 0,
        look.visor ? 1 : 0,
        look.accent,
      );
      for (let side = 0; side < 2; side++) {
        const sign = side === 0 ? -1 : 1,
          slot = i * 2 + side;
        const swing = moving ? Math.sin(phase + side * Math.PI) * 0.6 : 0;
        const gesture =
          talking && !reducedMotion
            ? Math.sin(clock.elapsedTime * 4 + i) * 0.22
            : 0;
        put(
          "arms",
          slot,
          sign * 0.46,
          1.14,
          0,
          1,
          1,
          1,
          look.shirt,
          -swing + (side ? gesture : 0),
        );
        put(
          "hands",
          slot,
          sign * 0.46,
          0.78,
          moving ? Math.sin(swing) * -0.24 : gesture * 0.2,
          1,
          1,
          1,
          look.skin,
        );
        put("legs", slot, sign * 0.18, 0.48, 0, 1, 1, 1, look.pants, swing);
        put(
          "shoes",
          slot,
          sign * 0.18,
          0.12,
          0.07 + Math.sin(swing) * 0.26,
          1,
          1,
          1,
          "#1a1824",
        );
        put(
          "soles",
          slot,
          sign * 0.18,
          0.03,
          0.07 + Math.sin(swing) * 0.26,
          1,
          1,
          1,
          look.accent,
        );
        put(
          "eyes",
          slot,
          sign * 0.15,
          2.04,
          0.375,
          1,
          a.emotion === "happy" ? 0.6 : 1.3,
          0.65,
          "#292735",
        );
        put(
          "glasses",
          slot,
          sign * 0.15,
          2.045,
          0.405,
          look.glasses ? 1 : 0,
          look.glasses ? 1 : 0,
          look.glasses ? 1 : 0,
          "#c9c2dc",
        );
        const long = look.hairStyle === 1 || look.hairStyle === 3;
        put(
          "sideHair",
          slot,
          sign * 0.37,
          1.98,
          -0.03,
          long ? 0.15 : 0,
          long ? (look.hairStyle === 3 ? 0.65 : 0.35) : 0,
          long ? 0.45 : 0,
          look.hair,
        );
      }
    });
    const scale = speechScale(camera.zoom);
    const readable = camera.zoom >= conversationZoom;
    for (const [id, element] of bubbles.current)
      element.style.visibility =
        readable || id === selected || focus.includes(id) ? "" : "hidden";
    const screenBubbles = [...bubbles.current].flatMap(([id, element]) => {
      const label = labels.current.get(id);
      if (!label || element.style.visibility === "hidden") return [];
      const screen = new THREE.Vector3(
        label.position.x,
        2.65,
        label.position.z,
      ).project(camera);
      // Offscreen speakers must not push visible bubbles away from their anchors.
      if (
        Math.abs(screen.x) > 1 ||
        Math.abs(screen.y) > 1 ||
        Math.abs(screen.z) > 1
      )
        return [];
      return [
        {
          id,
          x:
            ((screen.x + 1) * size.width) / 2 -
            (element.offsetWidth * scale) / 2,
          y:
            ((1 - screen.y) * size.height) / 2 -
            element.offsetHeight * scale - 12,
          depth: screen.z,
          width: element.offsetWidth * scale,
          height: element.offsetHeight * scale,
        },
      ];
    });
    const offsets = layoutSpeech(screenBubbles, size.width, size.height);
    for (const [id, element] of bubbles.current) {
      const offset = offsets.get(id);
      element.style.filter = offset?.obscured
        ? "grayscale(1) brightness(0.65)"
        : "";
      element.dataset.obscured = String(offset?.obscured ?? false);
      // Html centers its content; lift the bubble's bottom above the head anchor.
      const lift = (element.offsetHeight * scale) / 2 + 12;
      element.style.transform = `translate(${offset?.x ?? 0}px, ${(offset?.y ?? 0) - lift}px) scale(${scale})`;
      element.style.setProperty(
        "--speech-tail-left",
        `${Math.max(12, Math.min(element.offsetWidth - 22, element.offsetWidth / 2 - (offset?.x ?? 0) / scale - 5))}px`,
      );
    }
    for (const part of parts) {
      const mesh = meshes.current[part];
      if (!mesh) continue;
      mesh.instanceMatrix.needsUpdate = true;
      const overlay = highlightMeshes.current[part];
      if (overlay) {
        overlay.instanceMatrix.needsUpdate = true;
        overlay.boundingSphere = null;
      }
      mesh.boundingSphere = null;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  });
  const pick = (
    part: Part,
    event: ThreeEvent<MouseEvent>,
    agents = frame.agents,
  ) => {
    event.stopPropagation();
    const index = event.instanceId;
    if (index !== undefined) {
      const agent =
        agents[double.has(part) ? Math.floor(index / 2) : index];
      if (agent) onSelect(agent.id);
    }
  };
  const labeled = frame.agents.filter(
    (a) =>
      !a.active ||
      a.emotion === "unconscious" ||
      speech.has(a.id) ||
      focus.includes(a.id) ||
      highlightSlots.has(a.id),
  );
  return (
    <>
      {parts.map((part) => (
        <instancedMesh
          key={`${part}-${frame.agents.length}`}
          ref={(mesh) => {
            if (mesh) meshes.current[part] = mesh;
          }}
          args={[
            shape[part],
            glowing.has(part) ? glowMaterial : material,
            frame.agents.length * (double.has(part) ? 2 : 1),
          ]}
          dispose={null}
          frustumCulled={false}
          onClick={(e) => pick(part, e)}
        />
      ))}
      {highlightedAgents.length > 0 &&
        parts.map((part) => (
          <instancedMesh
            key={`highlight-${part}-${highlightedAgents.length}`}
            ref={(mesh) => {
              if (mesh) highlightMeshes.current[part] = mesh;
              else delete highlightMeshes.current[part];
            }}
            args={[
              shape[part],
              highlightMaterial,
              highlightedAgents.length * (double.has(part) ? 2 : 1),
            ]}
            dispose={null}
            frustumCulled={false}
            renderOrder={10}
            userData={{ characterHighlight: true }}
            onClick={(event) => pick(part, event, highlightedAgents)}
          />
        ))}
      {labeled.map((a) => {
        const line = speech.get(a.id);
        const highlighted = highlightSlots.has(a.id);
        return (
          <group
            key={a.id}
            ref={(group) => {
              if (group) labels.current.set(a.id, group);
              else labels.current.delete(a.id);
            }}
            position={[a.position.x, 0, a.position.y]}
          >
            {highlighted && (
              <mesh
                rotation={[-Math.PI / 2, 0, 0]}
                position={[0, 0.12, 0]}
                renderOrder={11}
                userData={{ characterHighlight: true }}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(a.id);
                }}
              >
                <ringGeometry args={[0.8, 0.96, 24]} />
                <meshBasicMaterial
                  color="#00f0ff"
                  depthTest={false}
                  depthWrite={false}
                  side={THREE.DoubleSide}
                  toneMapped={false}
                />
              </mesh>
            )}
            <Html
              position={[0, line ? 2.65 : 3.0, 0]}
              center
              zIndexRange={[8, 0]}
              style={{ pointerEvents: "none" }}
            >
              <div
                ref={(element) => {
                  if (element) labelElements.current.set(a.id, element);
                  else labelElements.current.delete(a.id);
                  if (element && line) bubbles.current.set(a.id, element);
                  else bubbles.current.delete(a.id);
                }}
                className={line ? "character-speech" : "character-nameplate"}
                data-speaker-id={line ? a.id : undefined}
                data-character-id={a.id}
              >
                {line && <span>{a.name.split(" ")[0]}</span>}
                {line
                  ? line.text
                  : `${a.name.split(" ")[0]}${!a.active ? " · Dead" : a.emotion === "unconscious" ? " · Unconscious" : a.routine_state === "sleeping" ? " · Sleeping" : a.routine_state === "returning_home" ? " · Heading home" : ""}`}
              </div>
            </Html>
          </group>
        );
      })}
    </>
  );
}
