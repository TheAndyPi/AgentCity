import * as THREE from "three";

/** Moving an orthographic eye backward preserves framing and visible scale. */
export function fitCityDepth(
  camera: THREE.OrthographicCamera,
  target: THREE.Vector3,
  bounds: THREE.Sphere,
) {
  const direction = target.clone().sub(camera.position).normalize();
  const centerDepth = bounds.center.clone().sub(camera.position).dot(direction);
  const retreat = Math.max(0, camera.near + 1 + bounds.radius - centerDepth);
  if (retreat > 0) {
    camera.position.addScaledVector(direction, -retreat);
    camera.updateMatrixWorld();
  }
  const far = Math.max(1000, centerDepth + retreat + bounds.radius + 1);
  if (far !== camera.far) {
    camera.far = far;
    camera.updateProjectionMatrix();
  }
}
