import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { MapData } from "../api/types";
import { groundLayout, groundSignature, type GroundRect } from "./groundLayout";
import { worldPalette, type WorldTheme } from "./palette";

export function useGround(map: MapData) {
  const signature = groundSignature(map);
  return useMemo(() => groundLayout(map), [signature]);
}

// Local procedural grain keeps the ground detailed without downloaded textures.
function surfaceTexture(seed: number, land: boolean, theme: WorldTheme) {
  const palette = worldPalette(theme);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  let state = seed >>> 0;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const [light, dark] = land ? palette.landGrain : palette.asphaltGrain;
  context.fillStyle = land ? palette.land : palette.asphalt;
  context.fillRect(0, 0, 256, 256);
  for (let i = 0; i < (land ? 9000 : 16000); i++) {
    context.fillStyle = (random() > 0.5 ? light : dark) + "22";
    context.fillRect(random() * 256, random() * 256, 1 + random() * 2, 1);
  }
  if (land) {
    // A faint holographic survey grid across the open ground.
    context.strokeStyle = palette.grid + "26";
    context.lineWidth = 1;
    for (let i = 0; i <= 256; i += 32) {
      context.beginPath();
      context.moveTo(i + 0.5, 0);
      context.lineTo(i + 0.5, 256);
      context.moveTo(0, i + 0.5);
      context.lineTo(256, i + 0.5);
      context.stroke();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function Patches({
  pieces,
  color,
  elevation,
  thickness = 0.02,
  texture,
  glow = false,
  emissive,
}: {
  pieces: GroundRect[];
  color: string;
  elevation: number;
  thickness?: number;
  texture?: THREE.Texture;
  glow?: boolean;
  emissive?: string;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    if (!ref.current) return;
    const object = new THREE.Object3D();
    pieces.forEach((piece, i) => {
      object.position.set(piece.x, elevation - thickness / 2, piece.y);
      object.rotation.set(0, -(piece.angle || 0), 0);
      object.scale.set(piece.width, thickness, piece.depth);
      object.updateMatrix();
      ref.current!.setMatrixAt(i, object.matrix);
    });
    ref.current.instanceMatrix.needsUpdate = true;
    ref.current.computeBoundingSphere();
  }, [pieces, elevation, thickness]);
  if (!pieces.length) return null;
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, pieces.length]}>
      <boxGeometry />
      {glow ? (
        <meshBasicMaterial color={color} toneMapped={false} />
      ) : (
        <meshStandardMaterial
          color={color}
          map={texture}
          roughness={emissive ? 0.25 : 1}
          metalness={emissive ? 0.4 : 0}
          emissive={emissive ?? "#000000"}
          emissiveIntensity={emissive ? 0.35 : 0}
        />
      )}
    </instancedMesh>
  );
}

export default function Ground({
  map,
  theme = "dark",
}: {
  map: MapData;
  theme?: WorldTheme;
}) {
  const palette = worldPalette(theme);
  const layout = useGround(map);
  const land = useMemo(() => {
    const texture = surfaceTexture(map.seed, true, theme);
    texture.repeat.set(map.width_m / 16, map.height_m / 16);
    return texture;
  }, [map.seed, map.width_m, map.height_m, theme]);
  const asphalt = useMemo(
    () => surfaceTexture(map.seed, false, theme),
    [map.seed, theme],
  );
  useEffect(() => () => land.dispose(), [land]);
  useEffect(() => () => asphalt.dispose(), [asphalt]);
  return (
    <group name="city-ground">
      <mesh position={[map.width_m / 2, -0.24, map.height_m / 2]}>
        <boxGeometry args={[map.width_m, 0.45, map.height_m]} />
        <meshStandardMaterial color={palette.base} roughness={1} />
      </mesh>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[map.width_m / 2, 0, map.height_m / 2]}
      >
        <planeGeometry args={[map.width_m, map.height_m]} />
        <meshStandardMaterial map={land} roughness={1} />
      </mesh>
      <Patches
        pieces={layout.water}
        color={palette.water}
        emissive={palette.waterGlow}
        elevation={0.018}
      />
      <Patches
        pieces={layout.roads}
        color="white"
        texture={asphalt}
        elevation={0.035}
      />
      <Patches
        pieces={layout.sidewalks}
        color={palette.sidewalk}
        elevation={0.055}
        thickness={0.055}
      />
      <Patches
        pieces={layout.entrances}
        color={palette.sidewalk}
        elevation={0.058}
      />
      <Patches
        pieces={layout.curbs}
        color={palette.curb}
        elevation={0.085}
        thickness={0.06}
        glow
      />
      <Patches
        pieces={layout.markings}
        color={palette.markings}
        elevation={0.045}
        thickness={0.005}
        glow
      />
    </group>
  );
}
