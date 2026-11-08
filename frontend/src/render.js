// Offline renderer: builds each product, frames it, returns a WebP data URL.
import { PRODUCTS, createRenderer, createStudio, enableShadows, fitToGround, THREE } from './steel.js';

const VIEWS = {
  rebar: { rot: [0.0, 0.62, 0], cam: [0, 1.3, 5.4], fov: 30, pad: 0.82 },
  beam: { rot: [0, 0.62, 0], cam: [0, 1.6, 5.6], fov: 30, pad: 0.85 },
  'steel-sheet': { rot: [0, 0.5, 0], cam: [0, 2.2, 5.0], fov: 34 },
  pipe: { rot: [0, 0.62, 0], cam: [0, 1.4, 5.6], fov: 30, pad: 0.85 },
  profiles: { rot: [0, 0.62, 0], cam: [0, 1.6, 5.6], fov: 30, pad: 0.85 },
  'angles-channels': { rot: [0, 0.62, 0], cam: [0, 1.6, 5.4], fov: 30, pad: 0.85 },
  'wire-products': { rot: [0.05, 0.3, 0], cam: [0, 2.0, 4.6], fov: 34 },
  billets: { rot: [0, 0.62, 0], cam: [0, 1.7, 5.6], fov: 30, pad: 0.88 },
  'raw-materials': { rot: [0, 0, 0], cam: [0, 2.3, 4.2], fov: 34 },
  ferroalloy: { rot: [0, 0, 0], cam: [0, 2.0, 4.0], fov: 34 },
};

window.renderProduct = async (name, width = 1200, height = 900, type = 'image/webp') => {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const renderer = createRenderer(canvas);
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  const scene = createStudio(renderer);
  const view = VIEWS[name] || VIEWS.beam;
  const object = enableShadows(PRODUCTS[name]());
  object.rotation.set(...view.rot);
  const holder = new THREE.Group();
  holder.add(object);
  scene.add(holder);
  // Centre horizontally, rest on the floor.
  const box = new THREE.Box3().setFromObject(holder);
  const centre = box.getCenter(new THREE.Vector3());
  holder.position.x -= centre.x;
  holder.position.z -= centre.z;
  fitToGround(holder, -0.6);
  const bounds = new THREE.Box3().setFromObject(holder);
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const camera = new THREE.PerspectiveCamera(view.fov, width / height, 0.1, 100);
  const direction = new THREE.Vector3(...view.cam).normalize();
  const vertical = THREE.MathUtils.degToRad(view.fov) / 2;
  const horizontal = Math.atan(Math.tan(vertical) * camera.aspect);
  const distance = (sphere.radius * (view.pad || 1.08)) / Math.sin(Math.min(vertical, horizontal));
  camera.position.copy(sphere.center).addScaledVector(direction, distance);
  camera.lookAt(sphere.center);
  renderer.render(scene, camera);
  const url = canvas.toDataURL(type, 0.9);
  renderer.dispose();
  return url;
};
window.rendererReady = true;
