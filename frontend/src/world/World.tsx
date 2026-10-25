import {
  Component,
  Suspense,
  useEffect,
  useLayoutEffect,
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
import CharacterModels from "./CharacterModels";
import { characterAppearance } from "./characterAppearance";
import { subscribeToContextLoss } from "./contextLoss";
import Ground, { useGround } from "./Ground";
import Buildings, { BuildingTag } from "./Buildings";
import { buildingBounds, buildingInfo, type Building } from "./buildingLayout";
import type { GroundRect } from "./groundLayout";
import { neon, worldPalette } from "./palette";
import { acknowledgedRoute, pointAlongRoute } from "./motion";
import { insideBuilding } from "./buildingAccess";
import { speechBySpeaker } from "./speech";
import ScenarioScene from "./ScenarioScene";
import type { DisasterState } from "../disasters/client";
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
  disasters?: DisasterState | null;
  onListenerMoved?: (point: Vec2) => void;
  frame: WorldFrame;
  mode: "2d" | "3d";
  selected: string | null;
  onSelect: (id: string) => void;
  onEmpty: () => void;
  overlay: Overlay;
  hazards: boolean;
  follow: string | null;
  focus?: string[];
  onUnfollow: () => void;
  reducedMotion: boolean;
  theme?: "dark" | "light";
  onCameraReady: (action: (a: CameraAction) => void) => void;
  onFallback: () => void;
};
export const instanceAgentId = (
  agents: AgentSummary[],
  index: number | undefined,
) => (index === undefined ? null : (agents[index]?.id ?? null));
export { boundedPosition } from "./motion";
/** Close enough to read speech bubbles above citizens. */
export const maxZoom = 160;

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
function closeupOffset(agents: AgentSummary[]) {
  if (agents.length !== 2) return new THREE.Vector3(24, 19, 28);
  const dx = agents[1].position.x - agents[0].position.x,
    dz = agents[1].position.y - agents[0].position.y;
  if (Math.hypot(dx, dz) < 0.1) return new THREE.Vector3(24, 19, 28);
  // View across their line of conversation so one person cannot hide the other.
  const offset = new THREE.Vector3(dz, 0, -dx).normalize().multiplyScalar(34);
  if (offset.x + offset.z < 0) offset.multiplyScalar(-1);
  offset.y = 20;
  return offset;
}
function Camera({
  frame,
  follow,
  focus = [],
  reducedMotion,
  onCameraReady,
  onUnfollow,
  onListenerMoved,
}: {
  onListenerMoved?: (point: Vec2) => void;
  frame: WorldFrame;
  follow: string | null;
  focus?: string[];
  reducedMotion: boolean;
  onCameraReady: Props["onCameraReady"];
  onUnfollow: () => void;
}) {
  const controls = useRef<OrbitControlsType>(null);
  const { size } = useThree();
  const frameRef = useRef(frame);
  frameRef.current = frame;
  const transition = useRef<{
    center: THREE.Vector3;
    offset: THREE.Vector3;
    zoom: number;
  } | null>(null);
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const current = frameRef.current;
    const agents = focus.length
      ? current.agents.filter((a) => focus.includes(a.id))
      : current.agents;
    if (!agents.length) return;
    // Existing larger saves retain a neighborhood overview; the intimate cast
    // opens framed around their homes rather than the entire map boundary.
    if (!focus.length && current.agents.length > 10) return;
    const xs = agents.map((a) => a.position.x),
      zs = agents.map((a) => a.position.y);
    const center = new THREE.Vector3(
      (Math.min(...xs) + Math.max(...xs)) / 2,
      focus.length ? 1.1 : 0,
      (Math.min(...zs) + Math.max(...zs)) / 2,
    );
    const span = Math.max(
      Math.max(...xs) - Math.min(...xs),
      Math.max(...zs) - Math.min(...zs),
    );
    const zoom = focus.length
      ? Math.min(
          72,
          Math.max(
            12,
            Math.min(size.width * 0.65, size.height * 0.64) / (span + 9),
          ),
        )
      : Math.min(size.width, size.height) / Math.max(45, span + 26);
    transition.current = {
      center,
      offset: focus.length
        ? closeupOffset(agents)
        : new THREE.Vector3(90, 95, 100),
      zoom,
    };
  }, [focus, frame.simulation.id, size.width, size.height]);
  useEffect(() => {
    onCameraReady((action) => {
      const c = controls.current;
      if (!c) return;
      transition.current = null;
      const cam = c.object as THREE.OrthographicCamera;
      if (
        ["zoom_in", "zoom_out", "rotate_left", "rotate_right"].includes(action)
      )
        onUnfollow();
      if (action === "zoom_in") cam.zoom = Math.min(maxZoom, cam.zoom * 1.2);
      else if (action === "zoom_out") cam.zoom = Math.max(2, cam.zoom / 1.2);
      else if (action === "rotate_left" || action === "rotate_right") {
        const d = cam.position.clone().sub(c.target);
        d.applyAxisAngle(
          new THREE.Vector3(0, 1, 0),
          action === "rotate_left" ? 0.2 : -0.2,
        );
        cam.position.copy(c.target).add(d);
      } else if (action === "reset") {
        const agents = frameRef.current.agents;
        const center =
          agents.length <= 10 && agents.length
            ? new THREE.Vector3(
                agents.reduce((v, a) => v + a.position.x, 0) / agents.length,
                0,
                agents.reduce((v, a) => v + a.position.y, 0) / agents.length,
              )
            : new THREE.Vector3(
                frame.map.width_m / 2,
                0,
                frame.map.height_m / 2,
              );
        c.target.copy(center);
        cam.position.copy(center).add(new THREE.Vector3(90, 95, 100));
        cam.zoom =
          agents.length <= 10 ? Math.min(size.width, size.height) / 55 : 4.4;
      } else {
        const delta = new THREE.Vector3(
          action === "pan_left" ? -3 : action === "pan_right" ? 3 : 0,
          0,
          action === "pan_up" ? -3 : action === "pan_down" ? 3 : 0,
        );
        c.target.add(delta);
        cam.position.add(delta);
        onUnfollow();
      }
      cam.updateProjectionMatrix();
      c.update();
    });
  }, [
    onCameraReady,
    frame.map.width_m,
    frame.map.height_m,
    onUnfollow,
    size.width,
    size.height,
  ]);
  useFrame((_, dt) => {
    const c = controls.current;
    if (!c) return;
    const cam = c.object as THREE.OrthographicCamera;
    const goal = transition.current;
    if (goal) {
      const t = reducedMotion ? 1 : Math.min(1, dt * 5);
      c.target.lerp(goal.center, t);
      cam.position.lerp(goal.center.clone().add(goal.offset), t);
      cam.zoom = THREE.MathUtils.lerp(cam.zoom, goal.zoom, t);
      cam.updateProjectionMatrix();
      c.update();
      if (
        c.target.distanceTo(goal.center) < 0.02 &&
        Math.abs(cam.zoom - goal.zoom) < 0.02
      )
        transition.current = null;
      return;
    }
    if (!follow) return;
    const agents = frame.agents.filter((a) =>
      focus.length > 1 ? focus.includes(a.id) : a.id === follow,
    );
    if (!agents.length) {
      onUnfollow();
      return;
    }
    const next = new THREE.Vector3(
      agents.reduce((v, a) => v + a.position.x, 0) / agents.length,
      1.1,
      agents.reduce((v, a) => v + a.position.y, 0) / agents.length,
    );
    const delta = next
      .sub(c.target)
      .multiplyScalar(reducedMotion ? 1 : Math.min(1, dt * 4));
    c.target.add(delta);
    cam.position.add(delta);
    if (focus.length > 1 && agents.length > 1) {
      cam.position.lerp(
        c.target.clone().add(closeupOffset(agents)),
        reducedMotion ? 1 : Math.min(1, dt * 3),
      );
      const span =
        Math.max(...agents.map((a) => a.position.x)) -
        Math.min(...agents.map((a) => a.position.x));
      const depth =
        Math.max(...agents.map((a) => a.position.y)) -
        Math.min(...agents.map((a) => a.position.y));
      const zoom = Math.min(
        72,
        Math.max(
          12,
          Math.min(size.width * 0.65, size.height * 0.64) /
            (Math.max(span, depth) + 9),
        ),
      );
      cam.zoom = THREE.MathUtils.lerp(
        cam.zoom,
        zoom,
        reducedMotion ? 1 : Math.min(1, dt * 3),
      );
      cam.updateProjectionMatrix();
    }
    c.update();
  });
  return (
    <OrbitControls
      ref={controls}
      makeDefault
      target={[frame.map.width_m / 2, 0, frame.map.height_m / 2]}
      minZoom={2}
      maxZoom={maxZoom}
      maxPolarAngle={Math.PI / 2.05}
      minPolarAngle={0.18}
      enableDamping={!reducedMotion}
      dampingFactor={0.12}
      onChange={() => {
        const target = controls.current?.target;
        if (target) onListenerMoved?.({ x: target.x, y: target.z });
      }}
      onStart={() => {
        transition.current = null;
        onUnfollow();
      }}
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
  const light = props.theme === "light";
  const palette = worldPalette(light ? "light" : "dark");
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
          <color attach="background" args={[palette.sky]} />
          <fog attach="fog" args={[palette.sky, 260, 600]} />
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
          {light ? (
            <>
              <ambientLight intensity={1.4} />
              <directionalLight
                position={[50, 100, 30]}
                intensity={2.1}
                color="#f5e7ff"
              />
              <hemisphereLight args={["#c8b6e4", "#37314a", 1]} />
            </>
          ) : (
            <>
              <ambientLight intensity={1.4} color="#8f85ff" />
              <directionalLight
                position={[50, 100, 30]}
                intensity={1.9}
                color="#b9c4ff"
              />
              <directionalLight
                position={[-60, 40, -40]}
                intensity={0.9}
                color={neon.magenta}
              />
              <hemisphereLight args={[neon.cyan, "#2a0a2e", 0.55]} />
            </>
          )}
          <Ground map={props.frame.map} theme={light ? "light" : "dark"} />
          <Buildings
            onClick={props.onEmpty}
            theme={light ? "light" : "dark"}
            reducedMotion={props.reducedMotion}
            conditions={props.disasters?.conditions}
            buildings={props.frame.map.buildings.map((b) =>
              props.disasters?.conditions[b.id]?.integrity === 0
                ? { ...b, height_m: 0.5 }
                : b,
            )}
            cutaway={props.frame.map.buildings
              .filter((b) =>
                props.frame.agents.some(
                  (a) =>
                    (a.id === props.selected || props.focus?.includes(a.id)) &&
                    insideBuilding(a.position, b),
                ),
              )
              .map((b) => b.id)}
          />
          {props.disasters && (
            <group>
              {props.disasters.terrain
                .filter((t) => t.blocked || t.stage === "charred")
                .map((t) => (
                  <mesh
                    key={`${t.col}:${t.row}`}
                    rotation={[-Math.PI / 2, 0, 0]}
                    position={[
                      (t.col + 0.5) * props.frame.map.cell_size_m,
                      0.31,
                      (t.row + 0.5) * props.frame.map.cell_size_m,
                    ]}
                  >
                    <planeGeometry
                      args={[
                        props.frame.map.cell_size_m * 0.9,
                        props.frame.map.cell_size_m * 0.9,
                      ]}
                    />
                    <meshBasicMaterial
                      color={t.blocked ? "#a26f52" : "#332c2b"}
                    />
                  </mesh>
                ))}
              {props.frame.map.buildings
                .filter(
                  (b) => props.disasters!.conditions[b.id]?.integrity < 100,
                )
                .map((b) => {
                  const bounds = buildingBounds(b);
                  const c = props.disasters!.conditions[b.id];
                  return (
                    <group key={b.id}>
                      <Line
                        points={[
                          [bounds.x - 1, 0.5, bounds.y - 1],
                          [bounds.x + 1, 0.5, bounds.y + 1],
                          [bounds.x, 0.5, bounds.y],
                          [bounds.x + 1, 0.5, bounds.y - 1],
                          [bounds.x - 1, 0.5, bounds.y + 1],
                        ]}
                        color={c.integrity < 50 ? "#f58064" : "#eabb75"}
                        lineWidth={2}
                      />
                      <Html
                        position={[bounds.x, b.height_m + 1, bounds.y]}
                        center
                        distanceFactor={110}
                      >
                        <span className="damage-label">
                          {c.stage} · {c.integrity.toFixed(0)}%
                        </span>
                      </Html>
                    </group>
                  );
                })}
              {props.disasters.events
                .filter((e) => e.phase === "active")
                .map((e) => (
                  <group key={e.id}>
                    <Polygon
                      points={e.footprint}
                      color="#eaa16d"
                      opacity={0.07}
                    />
                    <Polygon
                      points={e.current_footprint}
                      color="#eaa16d"
                      opacity={0.22}
                      elevation={0.35}
                    />
                  </group>
                ))}
            </group>
          )}
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
            props.frame.active_hazards
              .filter(
                (h) =>
                  !props.disasters?.events.some((e) => e.id === h.event_id),
              )
              .map((h) => (
                <group key={h.event_id}>
                  <Polygon
                    points={h.polygon}
                    color={
                      h.kind === "fire"
                        ? "#eaa16d"
                        : h.kind === "storm"
                          ? "#a1adbf"
                          : "#729be8"
                    }
                    opacity={0.45}
                    elevation={0.5}
                  />
                  <Line
                    points={[...h.polygon, h.polygon[0]].map(
                      (p) => [p.x, 0.6, p.y] as [number, number, number],
                    )}
                    color={
                      h.kind === "fire"
                        ? "#ffc888"
                        : h.kind === "storm"
                          ? "#d4deeb"
                          : "#a4cbff"
                    }
                    lineWidth={1.5}
                  />
                </group>
              ))}
          <CharacterModels
            frame={props.frame}
            selected={props.selected}
            focus={props.focus}
            onSelect={props.onSelect}
            reducedMotion={props.reducedMotion}
          />
          {props.frame.events
            .filter((e) => e.status === "active")
            .map((e) => (
              <ScenarioScene
                key={e.id}
                objects={e.scene ?? []}
                animated={
                  !props.reducedMotion &&
                  props.frame.simulation.status === "running"
                }
              />
            ))}
          <Camera
            frame={props.frame}
            follow={props.follow}
            focus={props.focus}
            reducedMotion={props.reducedMotion}
            onCameraReady={props.onCameraReady}
            onUnfollow={props.onUnfollow}
            onListenerMoved={props.onListenerMoved}
          />
        </Canvas>
      </Suspense>
    </WebGLErrorBoundary>
  );
}
function MapWalker({
  agent,
  frame,
  reducedMotion,
  children,
}: {
  agent: AgentSummary;
  frame: WorldFrame;
  reducedMotion: boolean;
  children: ReactNode;
}) {
  const group = useRef<SVGGElement>(null);
  const position = useRef(agent.position);
  const simulation = useRef(frame.simulation.id);
  const tick = useRef(frame.ref.tick);
  useLayoutEffect(() => {
    const reset =
      simulation.current !== frame.simulation.id ||
      frame.ref.tick < tick.current;
    const start = reset ? agent.position : position.current;
    const route = acknowledgedRoute(start, agent.position, frame.map);
    const began = performance.now();
    const duration = Math.min(
      4000,
      Math.max(600, 200 / frame.simulation.speed_multiplier),
    );
    let request = 0;
    const draw = () => {
      const t =
        reducedMotion || reset
          ? 1
          : Math.min(1, (performance.now() - began) / duration);
      const p = pointAlongRoute(route, t);
      position.current = p;
      group.current?.setAttribute(
        "transform",
        `translate(${p.x},${frame.map.height_m - p.y})`,
      );
      if (t < 1) request = requestAnimationFrame(draw);
    };
    draw();
    simulation.current = frame.simulation.id;
    tick.current = frame.ref.tick;
    return () => cancelAnimationFrame(request);
  }, [agent.position.x, agent.position.y, frame.simulation.id, reducedMotion]);
  return <g ref={group}>{children}</g>;
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
  const theme = props.theme === "light" ? "light" : "dark";
  const palette = worldPalette(theme);
  const speech = speechBySpeaker(frame, props.focus);
  const patternId = useId().replace(/:/g, "");
  const [hovered, setHovered] = useState<Building | null>(null);
  const currentBuilding = frame.map.buildings.find((b) => b.id === hovered?.id);
  const hoveredBounds = currentBuilding
    ? buildingBounds(currentBuilding)
    : null;
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
  useEffect(() => {
    props.onListenerMoved?.({
      x: view.x + view.w / 2,
      y: frame.map.height_m - (view.y + view.h / 2),
    });
  }, [
    props.onListenerMoved,
    view.x,
    view.y,
    view.w,
    view.h,
    frame.map.height_m,
  ]);
  const viewNow = useRef(view);
  viewNow.current = view;
  const glide = useRef(0);
  const stopGlide = () => cancelAnimationFrame(glide.current);
  useEffect(() => stopGlide, []);
  const glideTo = (target: typeof view, duration: number) => {
    stopGlide();
    if (props.reducedMotion) {
      setView(target);
      return;
    }
    const from = viewNow.current,
      start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      setView({
        x: from.x + (target.x - from.x) * e,
        y: from.y + (target.y - from.y) * e,
        w: from.w + (target.w - from.w) * e,
        h: from.h + (target.h - from.h) * e,
      });
      if (t < 1) glide.current = requestAnimationFrame(step);
    };
    glide.current = requestAnimationFrame(step);
  };
  useEffect(
    () =>
      onCameraReady((a) => {
        onUnfollow();
        stopGlide();
        setView((v) => {
          if (a === "reset")
            return {
              x: -8,
              y: -8,
              w: frame.map.width_m + 16,
              h: frame.map.height_m + 16,
            };
          const scale = a === "zoom_in" ? 0.85 : a === "zoom_out" ? 1.15 : 1,
            w = Math.max(4, Math.min(200, v.w * scale));
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
        });
      }),
    [onCameraReady, onUnfollow],
  );
  const lastViewFocus = useRef<{
    ids: string[] | undefined;
    simulation: string;
  }>({ ids: undefined, simulation: "" });
  useEffect(() => {
    const changed =
      lastViewFocus.current.ids !== props.focus ||
      lastViewFocus.current.simulation !== frame.simulation.id;
    lastViewFocus.current = {
      ids: props.focus,
      simulation: frame.simulation.id,
    };
    if (!props.follow && !changed) return;
    if (!props.focus?.length && !props.follow && frame.agents.length > 10)
      return;
    const agents = frame.agents.filter((a) =>
      props.focus?.length
        ? props.focus.includes(a.id)
        : props.follow
          ? a.id === props.follow
          : true,
    );
    if (!agents.length) return;
    const xs = agents.map((a) => a.position.x),
      ys = agents.map((a) => a.position.y);
    const centerX = (Math.min(...xs) + Math.max(...xs)) / 2,
      centerY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(
      Math.max(...xs) - Math.min(...xs),
      Math.max(...ys) - Math.min(...ys),
    );
    const v = viewNow.current;
    const w = changed
      ? props.focus?.length
        ? Math.max(48, span + 24)
        : Math.max(45, span + 20)
      : v.w;
    glideTo(
      { x: centerX - w / 2, y: frame.map.height_m - centerY - w / 2, w, h: w },
      changed ? 900 : 450,
    );
  }, [frame.agents, props.focus, props.follow, frame.map.height_m]);
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
      aria-label="Interactive top-down city map. Hover or focus a building for its purpose. Select a citizen or use Search agent."
      viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
      onPointerDown={(e) => {
        stopGlide();
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
        if (
          !drag.current?.moved &&
          !(e.target as Element).closest('[role="button"]')
        )
          onEmpty();
      }}
    >
      <defs>
        <pattern
          id={`${patternId}-grass`}
          width="4"
          height="4"
          patternUnits="userSpaceOnUse"
        >
          <rect width="4" height="4" fill={palette.land} />
          <path
            d="M0 0H4M0 0V4"
            stroke={palette.grid}
            strokeWidth=".05"
            opacity=".22"
          />
        </pattern>
        <pattern
          id={`${patternId}-asphalt`}
          width="2"
          height="2"
          patternUnits="userSpaceOnUse"
        >
          <rect width="2" height="2" fill={palette.asphalt} />
          <path
            d="M.3 .3h.1M1.2 .7h.12M.7 1.5h.1M1.7 1.7h.1"
            stroke={palette.asphaltGrain[0]}
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
      {patches("water", ground.water, palette.water)}
      {patches("roads", ground.roads, `url(#${patternId}-asphalt)`)}
      {patches("sidewalks", ground.sidewalks, palette.sidewalk)}
      {patches("entrances", ground.entrances, palette.sidewalk)}
      {patches("curbs", ground.curbs, palette.curb)}
      {patches("markings", ground.markings, palette.markings)}
      {frame.events
        .filter((e) => e.status === "active")
        .flatMap((e) =>
          (e.scene ?? []).map((o, i) => (
            <g key={`${e.id}:${i}`} data-scenario-model={o.model}>
              <title>
                {o.label} — {o.model}
              </title>
              <circle
                cx={o.position.x}
                cy={frame.map.height_m - o.position.y}
                r={1.8 * o.scale}
                fill={o.color}
                stroke="#f3e9d1"
                strokeWidth={0.2}
              />
              <text
                x={o.position.x}
                y={frame.map.height_m - o.position.y + 0.7}
                textAnchor="middle"
                fill="#26333c"
                fontSize={2}
                pointerEvents="none"
              >
                ✦
              </text>
            </g>
          )),
        )}
      {props.disasters?.terrain
        .filter((t) => t.blocked || t.stage === "charred")
        .map((t) => (
          <g key={`damage-${t.col}:${t.row}`} pointerEvents="none">
            <rect
              x={t.col * frame.map.cell_size_m}
              y={frame.map.height_m - (t.row + 1) * frame.map.cell_size_m}
              width={frame.map.cell_size_m}
              height={frame.map.cell_size_m}
              fill={t.blocked ? "#a26f52" : "#332c2b"}
            />
            {t.blocked && (
              <path
                d={`M${t.col * 2} ${frame.map.height_m - t.row * 2}l2 -2`}
                stroke="#f0cfb7"
                strokeWidth={0.2}
              />
            )}
          </g>
        ))}
      {props.disasters?.events
        .filter((e) => e.phase === "active")
        .map((e) => (
          <g key={`physical-${e.id}`} pointerEvents="none">
            <polygon
              points={polygon(e.footprint)}
              fill="none"
              stroke="#eaa16d"
              strokeWidth={0.4}
              strokeDasharray="1 1"
            />
            <polygon
              points={polygon(e.current_footprint)}
              fill="#eaa16d"
              fillOpacity={0.2}
              stroke="#eaa16d"
              strokeWidth={0.3}
            />
          </g>
        ))}
      {frame.map.buildings.map((b) => {
        const info = buildingInfo(b, theme),
          bounds = buildingBounds(b);
        return (
          <g
            key={b.id}
            role="button"
            tabIndex={0}
            aria-label={`${info.label}: ${b.name}`}
            data-building-id={b.id}
            data-building-purpose={info.purpose}
            onPointerEnter={() => setHovered(b)}
            onPointerLeave={() => setHovered(null)}
            onFocus={() => setHovered(b)}
            onBlur={() => setHovered(null)}
            onClick={(event) => {
              event.stopPropagation();
              if (drag.current?.moved) return;
              setHovered(b);
              onEmpty();
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") setHovered(null);
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setHovered(b);
              }
            }}
          >
            <polygon
              points={polygon(b.footprint)}
              fill={b.functional ? info.color : palette.offline}
              stroke={b.functional ? info.accent : palette.trimOffline}
              strokeWidth=".22"
            />
            <rect
              x={bounds.x - bounds.width * 0.3}
              y={frame.map.height_m - bounds.y - bounds.depth * 0.3}
              width={bounds.width * 0.6}
              height={bounds.depth * 0.6}
              fill="none"
              stroke={info.accent}
              strokeWidth=".14"
              opacity=".7"
              pointerEvents="none"
            />
            {props.disasters &&
              props.disasters.conditions[b.id]?.integrity < 100 && (
                <text
                  x={bounds.x}
                  y={frame.map.height_m - bounds.y + 1}
                  textAnchor="middle"
                  fontSize={3}
                  fill="#ffb58e"
                  pointerEvents="none"
                >
                  <title>
                    {props.disasters.conditions[b.id].stage} · Integrity{" "}
                    {props.disasters.conditions[b.id].integrity.toFixed(1)} ·{" "}
                    {props.disasters.conditions[b.id].cause_ids.join(", ")}
                  </title>
                  ×
                </text>
              )}
            {b.kind === "hospital" && (
              <path
                d={`M${bounds.x - 0.7} ${frame.map.height_m - bounds.y}h1.4 M${bounds.x} ${frame.map.height_m - bounds.y - 0.7}v1.4`}
                stroke={neon.magenta}
                strokeWidth=".42"
                pointerEvents="none"
              />
            )}
          </g>
        );
      })}
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
        frame.active_hazards
          .filter(
            (h) => !props.disasters?.events.some((e) => e.id === h.event_id),
          )
          .map((h) => (
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
          <MapWalker
            agent={a}
            frame={frame}
            reducedMotion={props.reducedMotion}
          >
            {(a.id === selected || props.focus?.includes(a.id)) && (
              <circle
                r="1.6"
                fill="none"
                stroke={neon.cyan}
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
            )}
            <circle r="2.6" fill="transparent" />
            {(!a.active || a.emotion === "unconscious") && (
              <text y={-2} textAnchor="middle" fontSize={1.5} fill={neon.cyan}>
                {!a.active ? "Dead" : "Unconscious"}
              </text>
            )}
            <ellipse
              cy=".55"
              rx=".7"
              ry=".85"
              fill={characterAppearance(a.name).shirt}
            />
            <circle cy="-.4" r=".65" fill={characterAppearance(a.name).skin} />
            <path
              d="M-.65 -.4 Q-.7 -1.2 0 -1.1 Q.7 -1.2 .65 -.4 L.4 -.8 L-.3 -.65Z"
              fill={characterAppearance(a.name).hair}
            />
            <circle cx="-.23" cy="-.35" r=".08" fill="#302a30" />
            <circle cx=".23" cy="-.35" r=".08" fill="#302a30" />
            {speech.has(a.id) && (
              <foreignObject
                x={-4}
                y={-8}
                width={8}
                height={6}
                pointerEvents="none"
                overflow="visible"
              >
                <div
                  className="character-speech"
                  data-speaker-id={a.id}
                  style={{
                    width: "100%",
                    fontSize: 0.38,
                    padding: 0.4,
                    borderRadius: 0.4,
                  }}
                >
                  <strong>{a.name.split(" ")[0]}</strong>
                  <br />
                  {speech.get(a.id)!.text}
                </div>
              </foreignObject>
            )}
          </MapWalker>
        </g>
      ))}
      {currentBuilding && hoveredBounds && (
        <foreignObject
          x={Math.max(
            view.x,
            Math.min(
              view.x + view.w - Math.min(40, view.w),
              hoveredBounds.x - 20,
            ),
          )}
          y={Math.max(
            view.y,
            Math.min(
              view.y + view.h - Math.min(29, view.h),
              frame.map.height_m - hoveredBounds.y - 32,
            ),
          )}
          width={Math.min(40, view.w)}
          height={Math.min(29, view.h)}
          pointerEvents="none"
        >
          <div className="building-tag-2d">
            <BuildingTag
              building={currentBuilding}
              theme={theme}
              condition={props.disasters?.conditions[currentBuilding.id]}
            />
          </div>
        </foreignObject>
      )}
    </svg>
  );
}
