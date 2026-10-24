import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { MapData } from "../api/types";
import {
  groundColors,
  groundLayout,
  groundSignature,
  type GroundRect,
} from "./groundLayout";

export function useGround(map: MapData) {
  const signature = groundSignature(map);
  return useMemo(() => groundLayout(map), [signature]);
}

// Local procedural grain keeps the ground detailed without downloaded textures.
function surfaceTexture(seed: number, grass: boolean) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  let state = seed >>> 0;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  context.fillStyle = grass ? groundColors.grass : groundColors.asphalt;
  context.fillRect(0, 0, 256, 256);
  for (let i = 0; i < (grass ? 16000 : 22000); i++) {
    const light = random() > 0.5;
    context.fillStyle = light
      ? grass
        ? "#adc18720"
        : "#d3d8db13"
      : grass
        ? "#1c402a25"
        : "#11182025";
    context.fillRect(
      random() * 256,
      random() * 256,
      grass ? 1 + random() * 2 : 1,
      grass ? 1 + random() * 5 : 1,
    );
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
}: {
  pieces: GroundRect[];
  color: string;
  elevation: number;
  thickness?: number;
  texture?: THREE.Texture;
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
      <meshStandardMaterial color={color} map={texture} roughness={1} />
    </instancedMesh>
  );
}

export default function Ground({ map }: { map: MapData }) {
  const layout = useGround(map);
  const grass = useMemo(() => {
    const texture = surfaceTexture(map.seed, true);
    texture.repeat.set(map.width_m / 8, map.height_m / 8);
    return texture;
  }, [map.seed, map.width_m, map.height_m]);
  const asphalt = useMemo(() => surfaceTexture(map.seed, false), [map.seed]);
  useEffect(() => () => grass.dispose(), [grass]);
  useEffect(() => () => asphalt.dispose(), [asphalt]);
  return (
    <group name="city-ground">
      <mesh position={[map.width_m / 2, -0.24, map.height_m / 2]}>
        <boxGeometry args={[map.width_m, 0.45, map.height_m]} />
        <meshStandardMaterial color="#51603d" roughness={1} />
      </mesh>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[map.width_m / 2, 0, map.height_m / 2]}
      >
        <planeGeometry args={[map.width_m, map.height_m]} />
        <meshStandardMaterial map={grass} roughness={1} />
      </mesh>
      <Patches
        pieces={layout.water}
        color={groundColors.water}
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
        color={groundColors.sidewalk}
        elevation={0.055}
        thickness={0.055}
      />
      <Patches
        pieces={layout.entrances}
        color={groundColors.sidewalk}
        elevation={0.058}
      />
      <Patches
        pieces={layout.curbs}
        color={groundColors.curb}
        elevation={0.085}
        thickness={0.06}
      />
      <Patches
        pieces={layout.markings}
        color={groundColors.markings}
        elevation={0.045}
        thickness={0.005}
      />
    </group>
  );
}
