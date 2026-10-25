import * as THREE from "three";

/** Moving an orthographic eye backward preserves framing and visible scale. */
export function fitCityDepth(
  camera: THREE.OrthographicCamera,
  target: THREE.Vector3,
  bounds: THREE.Sphere,
) {
  const direction = target.clone().sub(camera.position).normalize();
  const centerDepth = bounds.center.clone().sub(camera.position).dot(direction);
  const padding = Math.max(2, bounds.radius * 0.05);
  const retreat = Math.max(
    0,
    camera.near + padding + bounds.radius - centerDepth,
  );
  if (retreat > 0) {
    camera.position.addScaledVector(direction, -retreat);
    camera.updateMatrixWorld();
  }
  // A tight depth range keeps thin road/floor layers distinct at close zoom.
  const far = Math.max(
    camera.near + padding,
    centerDepth + retreat + bounds.radius + padding,
  );
  if (far !== camera.far) {
    camera.far = far;
    camera.updateProjectionMatrix();
  }
}
