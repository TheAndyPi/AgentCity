import { Component, useMemo, useRef, type ReactNode } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls, OrthographicCamera } from "@react-three/drei";
import * as THREE from "three";
import type { SceneObject } from "../api/types";

type Point = [number, number, number];
function Box({
  p = [0, 0, 0],
  s = [1, 1, 1],
  color,
}: {
  p?: Point;
  s?: Point;
  color: string;
}) {
  return (
    <mesh position={p}>
      <boxGeometry args={s} />
      <meshStandardMaterial color={color} roughness={0.85} />
    </mesh>
  );
}
function Orb({
  p = [0, 0, 0],
  s = [1, 1, 1],
  color,
  detail = 1,
}: {
  p?: Point;
  s?: Point;
  color: string;
  detail?: number;
}) {
  return (
    <mesh position={p} scale={s}>
      <icosahedronGeometry args={[1, detail]} />
      <meshStandardMaterial color={color} flatShading roughness={0.85} />
    </mesh>
  );
}
function Cone({
  p,
  r,
  h,
  color,
}: {
  p: Point;
  r: number;
  h: number;
  color: string;
}) {
  return (
    <mesh position={p}>
      <coneGeometry args={[r, h, 6]} />
      <meshStandardMaterial color={color} flatShading />
    </mesh>
  );
}
function Ring({ p, r, color }: { p: Point; r: number; color: string }) {
  return (
    <mesh position={p}>
      <torusGeometry args={[r, 0.16, 5, 20]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.35}
      />
    </mesh>
  );
}

/** Shared low-poly vocabulary. Every model uses bounded built-in geometry. */
export function ScenarioModel({
  model,
  color: c,
  parts = [],
}: Pick<SceneObject, "model" | "color" | "parts">) {
  const dark = "#35424b",
    pale = "#f3e9d1";
  switch (model) {
    case "generated":
      return (
        <>
          {parts.slice(0, 8).map((part, i) => (
            <mesh
              key={i}
              position={[part.offset.x, part.offset.y, part.offset.z]}
              scale={[part.size.x, part.size.y, part.size.z]}
            >
              {part.shape === "box" ? (
                <boxGeometry />
              ) : part.shape === "sphere" ? (
                <icosahedronGeometry args={[0.5, 1]} />
              ) : part.shape === "cone" ? (
                <coneGeometry args={[0.5, 1, 8]} />
              ) : (
                <cylinderGeometry args={[0.5, 0.5, 1, 8]} />
              )}
              <meshStandardMaterial
                color={part.color}
                flatShading
                roughness={0.85}
              />
            </mesh>
          ))}
        </>
      );
    case "dinosaur":
    case "deer": {
      const dino = model === "dinosaur";
      return (
        <>
          <Orb p={[0, 1.6, 0]} s={[1.7, 0.9, 0.7]} color={c} />
          <Orb p={[1.4, 2.35, 0]} s={[0.5, 1.1, 0.45]} color={c} />
          <Box p={[1.75, 3.1, 0]} s={[1.25, 0.65, 0.7]} color={c} />
          {[-0.4, 0.4].flatMap((z) =>
            [-0.9, 0.8].map((x) => (
              <Box
                key={`${x}:${z}`}
                p={[x, 0.65, z]}
                s={[0.35, 1.3, 0.3]}
                color={c}
              />
            )),
          )}
          <Orb p={[2, 3.25, 0.37]} s={[0.09, 0.09, 0.05]} color={dark} />
          {dino ? (
            <>
              <Orb p={[-1.9, 1.5, 0]} s={[1.2, 0.3, 0.3]} color={c} />
              {[-1, -0.3, 0.4].map((x) => (
                <Cone
                  key={x}
                  p={[x, 2.55, 0]}
                  r={0.3}
                  h={0.65}
                  color="#e6cd8c"
                />
              ))}
            </>
          ) : (
            [-0.25, 0.25].map((z) => (
              <Box
                key={z}
                p={[1.4, 3.85, z]}
                s={[0.12, 1, 0.12]}
                color="#e6cd8c"
              />
            ))
          )}
        </>
      );
    }
    case "spacecraft":
      return (
        <>
          <Orb p={[0, 4.4, 0]} s={[3.4, 0.6, 3.4]} color={c} />
          <Orb p={[0, 5.1, 0]} s={[1.4, 1, 1.4]} color="#9dd9e7" />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Orb
              key={i}
              p={[
                Math.cos((i * Math.PI) / 3) * 2.7,
                4.4,
                Math.sin((i * Math.PI) / 3) * 2.7,
              ]}
              s={[0.25, 0.15, 0.25]}
              color={pale}
            />
          ))}
          <mesh position={[0, 2.1, 0]}>
            <coneGeometry args={[2, 4, 16]} />
            <meshBasicMaterial
              color={c}
              transparent
              opacity={0.12}
              depthWrite={false}
            />
          </mesh>
        </>
      );
    case "robot":
    case "visitor": {
      const robot = model === "robot";
      return (
        <>
          <Box p={[0, 1.65, 0]} s={[1.1, 1.3, 0.7]} color={c} />
          {robot ? (
            <Box p={[0, 2.8, 0]} s={[1, 0.8, 0.8]} color={c} />
          ) : (
            <Orb p={[0, 2.8, 0]} s={[0.5, 0.55, 0.5]} color="#e3b48e" />
          )}
          {[-0.35, 0.35].map((x) => (
            <group key={x}>
              <Box p={[x, 0.55, 0]} s={[0.3, 1.1, 0.4]} color={dark} />
              <Box p={[x * 2.1, 1.65, 0]} s={[0.3, 1.1, 0.35]} color={c} />
              <Box
                p={[x * 0.65, 2.85, 0.42]}
                s={[0.14, 0.16, 0.08]}
                color={dark}
              />
            </group>
          ))}
          {robot && (
            <>
              <Box p={[0, 3.45, 0]} s={[0.1, 0.5, 0.1]} color={dark} />
              <Orb p={[0, 3.75, 0]} s={[0.18, 0.18, 0.18]} color="#f1b86e" />
            </>
          )}
        </>
      );
    }
    case "stage":
    case "stall":
    case "clinic": {
      const stage = model === "stage",
        clinic = model === "clinic";
      return (
        <>
          <Box p={[0, 0.35, 0]} s={[4.8, 0.7, 3.2]} color={dark} />
          {[-2, 2].map((x) => (
            <Box key={x} p={[x, 1.85, 0]} s={[0.16, 3, 0.16]} color={pale} />
          ))}
          <Box p={[0, 3.4, 0]} s={[5, 0.35, 3.6]} color={c} />
          {stage ? (
            <>
              <Box p={[-1.6, 1.2, 0]} s={[0.65, 1.1, 0.7]} color={dark} />
              <Box p={[1.6, 1.2, 0]} s={[0.65, 1.1, 0.7]} color={dark} />
              <Box p={[0, 1.4, 0]} s={[0.09, 1.4, 0.1]} color={pale} />
              <Orb p={[0, 2.15, 0]} s={[0.18, 0.18, 0.18]} color={dark} />
            </>
          ) : (
            <Box p={[0, 1.15, 0.8]} s={[3.8, 0.8, 0.9]} color={pale} />
          )}
          {clinic ? (
            <>
              <Box p={[0, 3.65, 0.5]} s={[1.2, 0.12, 0.4]} color={pale} />
              <Box p={[0, 3.65, 0.5]} s={[0.4, 0.12, 1.2]} color={pale} />
            </>
          ) : (
            [-1.2, 0, 1.2].map((x) => (
              <Orb key={x} p={[x, 1.8, 0.8]} s={[0.3, 0.25, 0.3]} color={c} />
            ))
          )}
        </>
      );
    }
    case "tree":
      return (
        <>
          <Box p={[0, 1.2, 0]} s={[0.5, 2.4, 0.5]} color="#9b7859" />
          <Orb p={[0, 3.2, 0]} s={[1.8, 1.9, 1.6]} color={c} />
          <Orb p={[0.8, 2.9, 0.5]} s={[1, 1.2, 1]} color="#a8c980" />
        </>
      );
    case "fire":
      return (
        <>
          <Box p={[0, 0.2, 0]} s={[2.4, 0.4, 1.4]} color="#6c5750" />
          <Cone p={[0, 1.7, 0]} r={1.1} h={3} color={c} />
          <Cone p={[0.35, 1.3, 0.3]} r={0.6} h={2.4} color="#f4d273" />
          <Orb p={[0.2, 4.2, 0]} s={[1.2, 1.4, 1.1]} color="#8c8a8a" />
        </>
      );
    case "cloud":
      return (
        <>
          {[-1.5, 0, 1.5].map((x, i) => (
            <Orb
              key={x}
              p={[x, 5 + (i % 2) * 0.4, 0]}
              s={[1.5, 1, 1.2]}
              color={c}
            />
          ))}
          {[-1, 0, 1].map((x) => (
            <Box key={x} p={[x, 2, 0]} s={[0.07, 1.2, 0.07]} color="#8ac8e6" />
          ))}
        </>
      );
    case "flood":
    case "snow":
      return (
        <>
          {[0, 1, 2].map((i) => (
            <Orb
              key={i}
              p={[i - 1, model === "flood" ? 0.25 : 0.5, (i % 2) - 0.5]}
              s={[2, model === "flood" ? 0.2 : 0.5, 1.6]}
              color={c}
            />
          ))}
        </>
      );
    case "heat":
      return (
        <>
          <Orb p={[0, 4.5, 0]} s={[1.3, 1.3, 1.3]} color={c} detail={0} />
          <Ring p={[0, 4.5, 0]} r={1.9} color={c} />
        </>
      );
    case "portal":
      return (
        <>
          <Box p={[0, 0.25, 0]} s={[4, 0.5, 2]} color={dark} />
          <Ring p={[0, 2.5, 0]} r={2.1} color={c} />
          <Orb
            p={[0, 2.5, 0]}
            s={[1.7, 1.7, 0.15]}
            color="#707cba"
            detail={0}
          />
        </>
      );
    case "meteor":
      return (
        <>
          <Orb p={[0, 0.2, 0]} s={[2.5, 0.25, 2.5]} color="#716c69" />
          <Orb p={[0, 1, 0]} s={[1.4, 1.5, 1.2]} color={c} detail={0} />
        </>
      );
    case "barrier":
      return (
        <>
          {[-1.6, 1.6].map((x) => (
            <Box key={x} p={[x, 0.9, 0]} s={[0.2, 1.8, 0.3]} color={dark} />
          ))}
          <Box p={[0, 1.3, 0]} s={[4, 0.7, 0.3]} color={c} />
          {[-1.3, 0, 1.3].map((x) => (
            <Box key={x} p={[x, 1.3, 0.17]} s={[0.4, 0.7, 0.05]} color={pale} />
          ))}
        </>
      );
    case "crates":
      return (
        <>
          {[
            [0, 0.6, 0],
            [1.3, 0.6, 0],
            [0.65, 1.8, 0],
          ].map((p, i) => (
            <group key={i}>
              <Box p={p as Point} s={[1.1, 1.1, 1.1]} color={c} />
              <Box p={[p[0], p[1], 0.57]} s={[0.14, 1.1, 0.05]} color={pale} />
            </group>
          ))}
        </>
      );
    case "generator":
      return (
        <>
          <Box p={[0, 1, 0]} s={[2.5, 1.6, 1.5]} color={c} />
          <Box p={[0.7, 2.2, 0]} s={[0.25, 1, 0.25]} color={dark} />
          {[-0.6, 0, 0.6].map((x) => (
            <Box key={x} p={[x, 1, 0.78]} s={[0.12, 0.8, 0.06]} color={dark} />
          ))}
        </>
      );
    case "broadcast":
      return (
        <>
          <Box p={[0, 1.7, 0]} s={[0.18, 3.4, 0.18]} color={dark} />
          <Box p={[0, 3, 0]} s={[1.8, 1.1, 0.5]} color={c} />
          <Ring p={[0, 3.2, 0]} r={1.5} color={c} />
        </>
      );
    case "monument":
      return (
        <>
          <Box p={[0, 0.3, 0]} s={[3, 0.6, 3]} color={dark} />
          <Box p={[0, 1, 0]} s={[1.8, 0.8, 1.8]} color={c} />
          <Orb p={[0, 2.6, 0]} s={[1.2, 1.5, 1.2]} color={c} detail={0} />
          <Ring p={[0, 2.6, 0]} r={1.8} color={pale} />
        </>
      );
  }
}

function Prop({
  object,
  animated,
  label,
}: {
  object: SceneObject;
  animated: boolean;
  label: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const floating = ["spacecraft", "cloud", "heat", "portal"].includes(
      object.model,
    );
    ref.current.position.y =
      animated && floating
        ? Math.sin(clock.elapsedTime * 1.2 + object.position.x) * 0.18
        : 0;
  });
  return (
    <group
      position={[object.position.x, 0.08, object.position.y]}
      rotation={[0, object.rotation, 0]}
      scale={object.scale}
    >
      <group ref={ref}>
        <ScenarioModel
          model={object.model}
          color={object.color}
          parts={object.parts}
        />
      </group>
      {label && (
        <Html
          position={[0, 6.8, 0]}
          center
          zIndexRange={[7, 0]}
          style={{ pointerEvents: "none" }}
        >
          <span className="scenario-world-label">{object.label}</span>
        </Html>
      )}
    </group>
  );
}
export default function ScenarioScene({
  objects,
  animated = false,
  labels = true,
}: {
  objects: SceneObject[];
  animated?: boolean;
  labels?: boolean;
}) {
  const first = new Set<string>();
  return (
    <group name="scenario-scene">
      {objects.slice(0, 24).map((o, i) => {
        const label = labels && !first.has(o.label);
        first.add(o.label);
        return (
          <Prop
            key={`${i}:${o.model}`}
            object={o}
            animated={animated}
            label={label}
          />
        );
      })}
    </group>
  );
}

class PreviewBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
function Diorama({ objects }: { objects: SceneObject[] }) {
  const { size } = useThree();
  const bounds = useMemo(() => {
    const xs = objects.map((o) => o.position.x),
      zs = objects.map((o) => o.position.y);
    return {
      x: (Math.min(...xs) + Math.max(...xs)) / 2,
      z: (Math.min(...zs) + Math.max(...zs)) / 2,
      span: Math.max(
        15,
        Math.max(...xs) - Math.min(...xs) + 12,
        Math.max(...zs) - Math.min(...zs) + 12,
      ),
    };
  }, [objects]);
  return (
    <>
      <color attach="background" args={["#202931"]} />
      <OrthographicCamera
        makeDefault
        position={[bounds.x + 40, 38, bounds.z + 40]}
        zoom={Math.min(
          size.width / (bounds.span * 1.45),
          size.height / (bounds.span * 0.95),
        )}
        near={0.1}
        far={300}
      />
      <ambientLight intensity={1.7} />
      <directionalLight
        position={[20, 40, 10]}
        intensity={2.5}
        color="#fff1d4"
      />
      <Box
        p={[bounds.x, -0.4, bounds.z]}
        s={[bounds.span, 0.7, bounds.span]}
        color="#647d69"
      />
      <ScenarioScene
        objects={objects.map((o) => ({ ...o, scale: o.scale * 1.5 }))}
        labels={false}
      />
      <OrbitControls
        target={[bounds.x, 1, bounds.z]}
        enablePan={false}
        enableZoom={false}
        minPolarAngle={0.35}
        maxPolarAngle={Math.PI / 2.4}
      />
    </>
  );
}
export function ScenarioDiorama({ objects }: { objects: SceneObject[] }) {
  if (!objects.length) return null;
  const fallback = (
    <div className="scenario-scene-fallback">
      Scene:{" "}
      {[
        ...new Set(
          objects.map((o) => (o.model === "generated" ? o.label : o.model)),
        ),
      ].join(" · ")}
    </div>
  );
  return (
    <div
      className="scenario-diorama"
      role="img"
      aria-label={`3D scenario preview: ${[...new Set(objects.map((o) => (o.model === "generated" ? o.label : o.model)))].join(", ")}`}
      data-scene-models={objects.map((o) => o.model).join(",")}
    >
      <PreviewBoundary fallback={fallback}>
        <Canvas
          dpr={[1, 1.5]}
          gl={{ antialias: true, powerPreference: "low-power" }}
          fallback={fallback}
        >
          <Diorama objects={objects} />
        </Canvas>
      </PreviewBoundary>
      <span className="scenario-diorama-caption">
        PROCEDURAL SCENE <span>Drag to orbit</span>
      </span>
    </div>
  );
}
