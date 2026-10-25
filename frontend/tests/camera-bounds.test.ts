import { expect, it } from "vitest";
import * as THREE from "three";
import { fitCityDepth } from "../src/world/cameraBounds";

it("keeps the whole city visible at a low angle without changing its framing", () => {
  const camera = new THREE.OrthographicCamera(-36, 36, 24, -24, 0.1, 1000);
  const target = new THREE.Vector3(95, 1, 30);
  camera.position.copy(target).add(new THREE.Vector3(24, 2, 28));
  camera.lookAt(target);
  camera.updateMatrixWorld();
  const box = new THREE.Box3(
    new THREE.Vector3(0, -1, 0),
    new THREE.Vector3(100, 40, 120),
  );
  const corners: THREE.Vector3[] = [];
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y])
      for (const z of [box.min.z, box.max.z])
        corners.push(new THREE.Vector3(x, y, z));
  const before = corners.map((p) => p.clone().project(camera));
  expect(before.some((p) => p.z < -1)).toBe(true);
  fitCityDepth(camera, target, box.getBoundingSphere(new THREE.Sphere()));
  corners.forEach((point, i) => {
    const after = point.clone().project(camera);
    expect(after.x).toBeCloseTo(before[i].x, 10);
    expect(after.y).toBeCloseTo(before[i].y, 10);
    expect(after.z).toBeGreaterThanOrEqual(-1);
    expect(after.z).toBeLessThanOrEqual(1);
  });
  // Ground layers separated by millimeters need depth precision at close zoom.
  expect(camera.far).toBeLessThan(400);
});

it("keeps tall event props and ground inside the clip planes throughout close-up moves", () => {
  const ground = new THREE.Box3(
    new THREE.Vector3(0, -1, 0),
    new THREE.Vector3(128, 30, 128),
  );
  const prop = new THREE.Box3(
    new THREE.Vector3(-15, 0, 115),
    new THREE.Vector3(15, 180, 145),
  );
  const bounds = ground
    .clone()
    .union(prop)
    .getBoundingSphere(new THREE.Sphere());
  const camera = new THREE.OrthographicCamera(-36, 36, 24, -24, 0.1, 1000);
  for (const target of [
    new THREE.Vector3(4, 1, 120),
    new THREE.Vector3(120, 1, 4),
  ]) {
    for (const height of [2, 19, 95]) {
      camera.position.copy(target).add(new THREE.Vector3(24, height, 28));
      camera.zoom = 160;
      camera.lookAt(target);
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld();
      const before = target.clone().project(camera);
      fitCityDepth(camera, target, bounds);
      const after = target.clone().project(camera);
      expect(after.x).toBeCloseTo(before.x, 10);
      expect(after.y).toBeCloseTo(before.y, 10);
      for (const box of [ground, prop])
        for (const x of [box.min.x, box.max.x])
          for (const y of [box.min.y, box.max.y])
            for (const z of [box.min.z, box.max.z]) {
              const point = new THREE.Vector3(x, y, z).project(camera);
              expect(point.z).toBeGreaterThanOrEqual(-1);
              expect(point.z).toBeLessThanOrEqual(1);
            }
    }
  }
});

it("retains distant city geometry after panning without pulling the target", () => {
  const camera = new THREE.OrthographicCamera(-36, 36, 24, -24, 0.1, 1000);
  const target = new THREE.Vector3(10000, 0, 10000);
  camera.position.copy(target).add(new THREE.Vector3(24, 2, 28));
  camera.lookAt(target);
  camera.updateMatrixWorld();
  const bounds = new THREE.Sphere(new THREE.Vector3(50, 20, 60), 100);
  const originalTarget = target.clone();
  fitCityDepth(camera, target, bounds);
  expect(target).toEqual(originalTarget);
  expect(camera.far).toBeGreaterThan(1000);
  const projected = bounds.center.clone().project(camera);
  expect(projected.z).toBeGreaterThan(-1);
  expect(projected.z).toBeLessThan(1);
});
