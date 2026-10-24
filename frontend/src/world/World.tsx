import {
  Component,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  useId,
  type ReactNode,
} from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  OrbitControls,
  OrthographicCamera,
  Html,
  Line,
} from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsType } from "three-stdlib";
import type { AgentSummary, Metric, Vec2, WorldFrame } from "../api/types";
import { colors } from "../api/defaults";
import { subscribeToContextLoss } from "./contextLoss";
import Ground, { useGround } from "./Ground";
import { groundColors, type GroundRect } from "./groundLayout";
export type Overlay = Metric | "density" | null;
export type CameraAction =
  | "zoom_in"
  | "zoom_out"
  | "rotate_left"
  | "rotate_right"
  | "pan_up"
  | "pan_down"
  | "pan_left"
  | "pan_right"
  | "reset";
type Props = {
  frame: WorldFrame;
  mode: "2d" | "3d";
  selected: string | null;
  onSelect: (id: string) => void;
  onEmpty: () => void;
  overlay: Overlay;
  hazards: boolean;
  follow: string | null;
  onUnfollow: () => void;
  reducedMotion: boolean;
  onCameraReady: (action: (a: CameraAction) => void) => void;
  onFallback: () => void;
};
const palette = [
  "#af9ad4",
  "#799eaa",
  "#99aaa4",
  "#c2acb4",
  "#8e85bd",
  "#c8bdaf",
];
export const instanceAgentId = (
  agents: AgentSummary[],
  index: number | undefined,
) => (index === undefined ? null : (agents[index]?.id ?? null));
/** Interpolate only the acknowledged prefix of the PREVIOUS legal path. The current path can contain future positions and must never be traversed speculatively. */
export function boundedPosition(
  previous: Vec2,
  current: AgentSummary,
  t: number,
  previousPath: Vec2[] = [],
): Vec2 {
  if (t >= 1 || previousPath.length === 0) return current.position;
  const route = [previous, ...previousPath];
  const prefix: Vec2[] = [previous];
  let found = false;
  for (let i = 1; i < route.length; i++) {
    const a = route[i - 1],
      b = route[i],
      p = current.position;
    const length = Math.hypot(b.x - a.x, b.y - a.y),
      along = Math.hypot(p.x - a.x, p.y - a.y),
      rest = Math.hypot(b.x - p.x, b.y - p.y);
    if (Math.abs(along + rest - length) < 0.001) {
      prefix.push(p);
      found = true;
      break;
    }
    prefix.push(b);
  }
  if (!found) return current.position;
  const lengths = prefix
    .slice(1)
    .map((p, i) => Math.hypot(p.x - prefix[i].x, p.y - prefix[i].y));
  let distance =
    lengths.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(t, 1));
  for (let i = 0; i < lengths.length; i++) {
    if (distance <= lengths[i]) {
      const fraction = lengths[i] === 0 ? 1 : distance / lengths[i];
      return {
        x: prefix[i].x + (prefix[i + 1].x - prefix[i].x) * fraction,
        y: prefix[i].y + (prefix[i + 1].y - prefix[i].y) * fraction,
      };
    }
    distance -= lengths[i];
  }
  return current.position;
}

function ContextGuard({ onFallback }: { onFallback: () => void }) {
  const gl = useThree((state) => state.gl);
  useEffect(
    () => subscribeToContextLoss(gl.domElement, onFallback),
    [gl, onFallback],
  );
  return null;
}
function PerformanceReadout({
  population,
  center,
}: {
  population: number;
  center: [number, number, number];
}) {
  const frames = useRef(0),
    elapsed = useRef(0);
  const [fps, setFps] = useState<number | null>(null);
  useFrame((_, dt) => {
    frames.current++;
    elapsed.current += dt;
    if (elapsed.current >= 2) {
      setFps(frames.current / elapsed.current);
      frames.current = 0;
      elapsed.current = 0;
    }
  });
  return (
    <Html
      fullscreen
      position={center}
      zIndexRange={[8, 0]}
      style={{ pointerEvents: "none" }}
    >
      <output className="qa-fps" data-qa-fps>
        {fps === null ? "Measuring…" : `${fps.toFixed(1)} FPS`} · {population}{" "}
        citizens
      </output>
    </Html>
  );
}
function Buildings({ frame }: { frame: WorldFrame }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const buildings = frame.map.buildings;
  const rectangular = buildings.filter(
    (b) =>
      b.footprint.length === 4 &&
      b.footprint.every(
        (p, i, all) => p.x === all[(i + 1) % 4].x || p.y === all[(i + 1) % 4].y,
      ),
  );
  useEffect(() => {
    if (!ref.current) return;
    const o = new THREE.Object3D(),
      color = new THREE.Color();
    rectangular.forEach((b, i) => {
      const xs = b.footprint.map((p) => p.x),
        ys = b.footprint.map((p) => p.y);
      o.position.set(
        (Math.min(...xs) + Math.max(...xs)) / 2,
        b.height_m / 2,
        (Math.min(...ys) + Math.max(...ys)) / 2,
      );
      o.scale.set(
        Math.max(...xs) - Math.min(...xs),
        b.height_m,
        Math.max(...ys) - Math.min(...ys),
      );
      o.updateMatrix();
      ref.current!.setMatrixAt(i, o.matrix);
      ref.current!.setColorAt(
        i,
        color.set(
          b.functional
            ? b.kind === "hospital"
              ? "#9dc5bc"
              : b.kind === "shelter"
                ? "#87b3c3"
                : b.kind === "community"
                  ? "#c6a1d1"
                  : palette[i % palette.length]
            : "#575263",
        ),
      );
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  }, [buildings]);
  return (
    <>
      <instancedMesh
        ref={ref}
        args={[undefined, undefined, rectangular.length]}
      >
        <boxGeometry />
        <meshStandardMaterial roughness={0.7} metalness={0.12} />
      </instancedMesh>
      {buildings
        .filter((b) => !rectangular.includes(b))
        .map((b) => (
          <PolyBuilding
            key={b.id}
            footprint={b.footprint}
            height={b.height_m}
          />
        ))}
      {rectangular.map((b, i) => {
        const xs = b.footprint.map((p) => p.x),
          ys = b.footprint.map((p) => p.y);
        const p = {
          x: (Math.min(...xs) + Math.max(...xs)) / 2,
          y: (Math.min(...ys) + Math.max(...ys)) / 2,
        };
        const width = Math.max(...xs) - Math.min(...xs),
          depth = Math.max(...ys) - Math.min(...ys);
        return (
          <group key={b.id}>
            <mesh position={[p.x, b.height_m + 0.4, p.y]}>
              <boxGeometry args={[width * 0.65, 0.7, depth * 0.6]} />
              <meshStandardMaterial color={palette[i % palette.length]} />
            </mesh>
            <mesh position={[b.entrance.x, 0.22, b.entrance.y]}>
              <boxGeometry args={[2.5, 0.15, 1]} />
              <meshBasicMaterial
                color={b.kind === "shelter" ? "#76e8c7" : "#c3afe3"}
              />
            </mesh>
            {(b.kind === "shelter" || b.kind === "community") && (
              <Html
                zIndexRange={[8, 0]}
                position={[p.x, b.height_m + 4, p.y]}
                center
              >
                <span className="building-label">
                  {b.kind === "shelter" ? "SHELTER" : "COMMUNITY"}
                </span>
              </Html>
            )}
          </group>
        );
      })}
    </>
  );
}
function PolyBuilding({
  footprint,
  height,
}: {
  footprint: Vec2[];
  height: number;
}) {
  const shape = useMemo(
    () => new THREE.Shape(footprint.map((p) => new THREE.Vector2(p.x, -p.y))),
    [footprint],
  );
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      <extrudeGeometry args={[shape, { depth: height, bevelEnabled: false }]} />
      <meshStandardMaterial color="#ac97c5" />
    </mesh>
  );
}
function Polygon({
  points,
  color,
  opacity = 0.3,
  elevation = 0.2,
}: {
  points: Vec2[];
  color: string;
  opacity?: number;
  elevation?: number;
}) {
  const shape = useMemo(
    () => new THREE.Shape(points.map((p) => new THREE.Vector2(p.x, -p.y))),
    [points],
  );
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, elevation, 0]}>
      <shapeGeometry args={[shape]} />
      <meshBasicMaterial
        color={color}
        transparent
        opacity={opacity}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}
function Citizens({
  frame,
  selected,
  onSelect,
  reducedMotion,
}: {
  frame: WorldFrame;
  selected: string | null;
  onSelect: (id: string) => void;
  reducedMotion: boolean;
}) {
  const body = useRef<THREE.InstancedMesh>(null),
    heads = useRef<THREE.InstancedMesh>(null);
  const received = useRef(new Map<string, AgentSummary>());
  const state = useRef({
    previous: new Map<string, AgentSummary>(),
    changed: 0,
    revision: -1,
    id: "",
  });
  useEffect(() => {
    const jump =
      state.current.id !== frame.simulation.id ||
      frame.ref.revision <= state.current.revision ||
      frame.simulation.status !== "running";
    state.current = {
      previous: jump ? new Map() : new Map(received.current),
      changed: performance.now(),
      revision: frame.ref.revision,
      id: frame.simulation.id,
    };
    received.current = new Map(frame.agents.map((a) => [a.id, a]));
  }, [frame]);
  useFrame(() => {
    if (!body.current || !heads.current) return;
    const o = new THREE.Object3D(),
      c = new THREE.Color();
    const t = reducedMotion
      ? 1
      : Math.min(1, (performance.now() - state.current.changed) / 400);
    frame.agents.forEach((a, i) => {
      const p = boundedPosition(
        state.current.previous.get(a.id)?.position ?? a.position,
        a,
        t,
        state.current.previous.get(a.id)?.path ?? [],
      );
      o.position.set(p.x, 1.1, p.y);
      o.rotation.set(0, a.heading_rad, 0);
      o.scale.set(1, 1, 1);
      o.updateMatrix();
      body.current!.setMatrixAt(i, o.matrix);
      body.current!.setColorAt(
        i,
        c.set(
          a.id === selected
            ? "#7ffff0"
            : a.action === "help"
              ? "#83dbb6"
              : palette[i % palette.length],
        ),
      );
      o.position.y = 2.2;
      o.updateMatrix();
      heads.current!.setMatrixAt(i, o.matrix);
    });
    body.current.instanceMatrix.needsUpdate = true;
    heads.current.instanceMatrix.needsUpdate = true;
    if (body.current.instanceColor)
      body.current.instanceColor.needsUpdate = true;
  });
  const chosen = frame.agents.find((a) => a.id === selected);
  return (
    <>
      <instancedMesh
        ref={body}
        args={[undefined, undefined, frame.agents.length]}
        onClick={(e) => {
          e.stopPropagation();
          const id = instanceAgentId(frame.agents, e.instanceId);
          if (id) onSelect(id);
        }}
      >
        <capsuleGeometry args={[0.5, 1.1, 3, 6]} />
        <meshStandardMaterial roughness={0.8} />
      </instancedMesh>
      <instancedMesh
        ref={heads}
        args={[undefined, undefined, frame.agents.length]}
        onClick={(e) => {
          e.stopPropagation();
          const id = instanceAgentId(frame.agents, e.instanceId);
          if (id) onSelect(id);
        }}
      >
        <sphereGeometry args={[0.42, 8, 6]} />
        <meshStandardMaterial color="#e8d7d8" />
      </instancedMesh>
      {chosen && (
        <>
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[chosen.position.x, 0.3, chosen.position.y]}
          >
            <ringGeometry args={[1.3, 1.7, 32]} />
            <meshBasicMaterial color="#80ffe8" side={THREE.DoubleSide} />
          </mesh>
          {chosen.thought_bubble && (
            <Html
              zIndexRange={[8, 0]}
              position={[chosen.position.x, 6, chosen.position.y]}
              center
            >
              <div className="thought-bubble">
                {chosen.thought_bubble.slice(0, 90)}
              </div>
            </Html>
          )}
        </>
      )}
    </>
  );
}
function Camera({
  frame,
  follow,
  reducedMotion,
  onCameraReady,
  onUnfollow,
}: {
  frame: WorldFrame;
  follow: string | null;
  reducedMotion: boolean;
  onCameraReady: Props["onCameraReady"];
  onUnfollow: () => void;
}) {
  const controls = useRef<OrbitControlsType>(null);
  useEffect(() => {
    onCameraReady((action) => {
      const c = controls.current;
      if (!c) return;
      const cam = c.object as THREE.OrthographicCamera;
      if (action === "zoom_in") cam.zoom = Math.min(15, cam.zoom * 1.15);
      else if (action === "zoom_out") cam.zoom = Math.max(2, cam.zoom / 1.15);
      else if (action === "rotate_left" || action === "rotate_right") {
        const d = cam.position.clone().sub(c.target);
        d.applyAxisAngle(
          new THREE.Vector3(0, 1, 0),
          action === "rotate_left" ? 0.2 : -0.2,
        );
        cam.position.copy(c.target).add(d);
      } else if (action === "reset") {
        c.target.set(frame.map.width_m / 2, 0, frame.map.height_m / 2);
        cam.position.set(
          frame.map.width_m * 1.4,
          Math.max(frame.map.width_m, frame.map.height_m) * 1.2,
          frame.map.height_m * 1.45,
        );
        cam.zoom = 4.4;
      } else {
        const delta = new THREE.Vector3(
          action === "pan_left" ? -5 : action === "pan_right" ? 5 : 0,
          0,
          action === "pan_up" ? -5 : action === "pan_down" ? 5 : 0,
        );
        c.target.add(delta);
        cam.position.add(delta);
        onUnfollow();
      }
      cam.updateProjectionMatrix();
      c.update();
    });
  }, [onCameraReady, frame.map.width_m, frame.map.height_m, onUnfollow]);
  useFrame((_, dt) => {
    if (!follow || !controls.current) return;
    const a = frame.agents.find((a) => a.id === follow);
    if (!a) {
      onUnfollow();
      return;
    }
    const c = controls.current;
    const next = new THREE.Vector3(a.position.x, 0, a.position.y);
    const delta = next
      .sub(c.target)
      .multiplyScalar(reducedMotion ? 1 : Math.min(1, dt * 3));
    c.target.add(delta);
    c.object.position.add(delta);
    c.update();
  });
  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={[frame.map.width_m / 2, 0, frame.map.height_m / 2]}
      minZoom={2}
      maxZoom={15}
      maxPolarAngle={Math.PI / 2.15}
      minPolarAngle={0.18}
      enableDamping={!reducedMotion}
      dampingFactor={0.12}
      onStart={onUnfollow}
    />
  );
}
class WebGLErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; onError: () => void },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
export default function World(props: Props) {
  if (props.mode === "2d") return <World2D {...props} />;
  return (
    <WebGLErrorBoundary
      onError={props.onFallback}
      fallback={<World2D {...props} />}
    >
      <Suspense
        fallback={<div className="world-loading">Preparing the viewport…</div>}
      >
        <Canvas
          dpr={[1, 1.5]}
          orthographic
          onPointerMissed={(e) => {
            if (e.type === "click") props.onEmpty();
          }}
          camera={{
            position: [180, 155, 185],
            zoom: 4.4,
            near: 0.1,
            far: 1000,
          }}
        >
          {import.meta.env.DEV &&
            new URLSearchParams(window.location.search).has("qa") && (
              <PerformanceReadout
                population={props.frame.agents.length}
                center={[
                  props.frame.map.width_m / 2,
                  0,
                  props.frame.map.height_m / 2,
                ]}
              />
            )}
          <ContextGuard onFallback={props.onFallback} />
          <color attach="background" args={["#171322"]} />
          <fog attach="fog" args={["#171322", 260, 600]} />
          <OrthographicCamera
            makeDefault
            position={[
              props.frame.map.width_m * 1.4,
              Math.max(props.frame.map.width_m, props.frame.map.height_m) * 1.2,
              props.frame.map.height_m * 1.45,
            ]}
            zoom={4.4}
            near={0.1}
            far={1000}
          />
          <ambientLight intensity={1.4} />
          <directionalLight
            position={[50, 100, 30]}
            intensity={2.1}
            color="#f5e7ff"
          />
          <hemisphereLight args={["#c8b6e4", "#37314a", 1]} />
          <Ground map={props.frame.map} />
          <Buildings frame={props.frame} />
          {props.overlay &&
            props.frame.map.zones.map((z) => (
              <Polygon
                key={z.id}
                points={z.polygon}
                color={
                  props.overlay === "density"
                    ? "#bfa4ff"
                    : colors[props.overlay as Metric]
                }
                opacity={
                  0.12 +
                  0.42 *
                    (props.overlay === "density"
                      ? Math.min(1, z.population_density_per_km2 / 10000)
                      : z.metrics[props.overlay as Metric] / 100)
                }
              />
            ))}
          {props.hazards &&
            props.frame.active_hazards.map((h) => (
              <group key={h.event_id}>
                <Polygon
                  points={h.polygon}
                  color="#729be8"
                  opacity={0.45}
                  elevation={0.5}
                />
                <Line
                  points={[...h.polygon, h.polygon[0]].map(
                    (p) => [p.x, 0.6, p.y] as [number, number, number],
                  )}
                  color="#a4cbff"
                  lineWidth={1.5}
                />
              </group>
            ))}
          <Citizens
            frame={props.frame}
            selected={props.selected}
            onSelect={props.onSelect}
            reducedMotion={props.reducedMotion}
          />
          <Camera
            frame={props.frame}
            follow={props.follow}
            reducedMotion={props.reducedMotion}
            onCameraReady={props.onCameraReady}
            onUnfollow={props.onUnfollow}
          />
        </Canvas>
      </Suspense>
    </WebGLErrorBoundary>
  );
}
function World2D(props: Props) {
  const {
    frame,
    selected,
    onSelect,
    onEmpty,
    overlay,
    hazards,
    onCameraReady,
    onUnfollow,
  } = props;
  const ground = useGround(frame.map);
  const patternId = useId().replace(/:/g, "");
  const [view, setView] = useState({
    x: -8,
    y: -8,
    w: frame.map.width_m + 16,
    h: frame.map.height_m + 16,
  });
  const drag = useRef<{
    x: number;
    y: number;
    vx: number;
    vy: number;
    moved: boolean;
  } | null>(null);
  useEffect(
    () =>
      onCameraReady((a) =>
        setView((v) => {
          if (a === "reset")
            return {
              x: -8,
              y: -8,
              w: frame.map.width_m + 16,
              h: frame.map.height_m + 16,
            };
          const scale = a === "zoom_in" ? 0.85 : a === "zoom_out" ? 1.15 : 1,
            w = Math.max(35, Math.min(200, v.w * scale));
          return {
            x:
              v.x +
              (v.w - w) / 2 +
              (a === "pan_right" ? 5 : a === "pan_left" ? -5 : 0),
            y:
              v.y +
              (v.h - w) / 2 +
              (a === "pan_down" ? 5 : a === "pan_up" ? -5 : 0),
            w,
            h: v.h * (w / v.w),
          };
        }),
      ),
    [onCameraReady],
  );
  useEffect(() => {
    if (!props.follow) return;
    const a = frame.agents.find((a) => a.id === props.follow);
    if (!a) {
      onUnfollow();
      return;
    }
    setView((v) => ({
      ...v,
      x: a.position.x - v.w / 2,
      y: frame.map.height_m - a.position.y - v.h / 2,
    }));
  }, [frame.agents, props.follow, onUnfollow, frame.map.height_m]);
  const polygon = (p: Vec2[]) =>
    p.map((p) => `${p.x},${frame.map.height_m - p.y}`).join(" ");
  const patches = (name: string, pieces: GroundRect[], fill: string) => (
    <g data-ground={name} fill={fill} pointerEvents="none">
      {pieces.map((p, i) => (
        <rect
          key={i}
          x={p.x - p.width / 2}
          y={frame.map.height_m - p.y - p.depth / 2}
          width={p.width}
          height={p.depth}
          transform={
            p.angle
              ? `rotate(${(-p.angle * 180) / Math.PI} ${p.x} ${frame.map.height_m - p.y})`
              : undefined
          }
        />
      ))}
    </g>
  );
  return (
    <svg
      className="world-2d"
      role="img"
      aria-label="Interactive top-down city map. Select a citizen or use Search agent."
      viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
      onPointerDown={(e) => {
        drag.current = {
          x: e.clientX,
          y: e.clientY,
          vx: view.x,
          vy: view.y,
          moved: false,
        };
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d || e.buttons !== 1) return;
        if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 5) {
          d.moved = true;
          onUnfollow();
          const ratio = view.w / e.currentTarget.getBoundingClientRect().width;
          setView((v) => ({
            ...v,
            x: d.vx - (e.clientX - d.x) * ratio,
            y: d.vy - (e.clientY - d.y) * ratio,
          }));
        }
      }}
      onClick={(e) => {
        if (!drag.current?.moved && e.target === e.currentTarget) onEmpty();
      }}
    >
      <defs>
        <pattern
          id={`${patternId}-grass`}
          width="4"
          height="4"
          patternUnits="userSpaceOnUse"
        >
          <rect width="4" height="4" fill={groundColors.grass} />
          <path
            d="M.5 1l.15-.4M2 2l-.1-.45M3.2 3.6l.15-.5M.7 3.3l-.1-.3"
            stroke="#91ad70"
            strokeWidth=".08"
            opacity=".45"
          />
          <path
            d="M3 .7l.1-.3M1.6 3.3l.2-.35"
            stroke="#315c38"
            strokeWidth=".1"
            opacity=".5"
          />
        </pattern>
        <pattern
          id={`${patternId}-asphalt`}
          width="2"
          height="2"
          patternUnits="userSpaceOnUse"
        >
          <rect width="2" height="2" fill={groundColors.asphalt} />
          <path
            d="M.3 .3h.1M1.2 .7h.12M.7 1.5h.1M1.7 1.7h.1"
            stroke="#879099"
            strokeWidth=".06"
            opacity=".4"
          />
        </pattern>
      </defs>
      <rect
        width={frame.map.width_m}
        height={frame.map.height_m}
        fill={`url(#${patternId}-grass)`}
        pointerEvents="none"
      />
      {patches("water", ground.water, groundColors.water)}
      {patches("roads", ground.roads, `url(#${patternId}-asphalt)`)}
      {patches("sidewalks", ground.sidewalks, groundColors.sidewalk)}
      {patches("entrances", ground.entrances, groundColors.sidewalk)}
      {patches("curbs", ground.curbs, groundColors.curb)}
      {patches("markings", ground.markings, groundColors.markings)}
      {frame.map.buildings.map((b, i) => (
        <polygon
          key={b.id}
          points={polygon(b.footprint)}
          fill={palette[i % palette.length]}
          stroke="#dacded"
          strokeWidth=".25"
          pointerEvents="none"
        />
      ))}
      {overlay &&
        frame.map.zones.map((z) => (
          <polygon
            key={z.id}
            points={polygon(z.polygon)}
            fill={overlay === "density" ? "#bfa4ff" : colors[overlay]}
            opacity={
              overlay === "density"
                ? Math.min(1, z.population_density_per_km2 / 10000) * 0.55
                : z.metrics[overlay] / 200
            }
            pointerEvents="none"
          />
        ))}
      {hazards &&
        frame.active_hazards.map((h) => (
          <polygon
            key={h.event_id}
            points={polygon(h.polygon)}
            fill="#81a6ff"
            fillOpacity=".35"
            stroke="#aecaff"
            strokeWidth=".6"
            pointerEvents="none"
          />
        ))}
      {frame.agents.map((a) => (
        <g
          key={a.id}
          role="button"
          tabIndex={0}
          aria-label={`${a.name}, ${a.role}`}
          onClick={(e) => {
            e.stopPropagation();
            if (!drag.current?.moved) onSelect(a.id);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect(a.id);
            }
          }}
        >
          <circle
            cx={a.position.x}
            cy={frame.map.height_m - a.position.y}
            r="2.6"
            fill="transparent"
          />
          <circle
            cx={a.position.x}
            cy={frame.map.height_m - a.position.y}
            r={a.id === selected ? 1.5 : 0.9}
            fill={a.id === selected ? "#81ffe7" : "#efe4ff"}
            stroke={a.id === selected ? "#81ffe7" : "#5d506f"}
            strokeWidth=".4"
          />
        </g>
      ))}
    </svg>
  );
}
