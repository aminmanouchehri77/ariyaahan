// Shared checks for the hero layout: 3D oriented-bounding-box intersection
// and on-screen overlap of each piece's projected silhouette hull.
import { OBB } from 'three/examples/jsm/math/OBB.js';
import { THREE } from '../src/steel.js';
import { CLEARANCE, FLOAT_AMPLITUDE, SCREEN_GAP, TILT_AMPLITUDE } from '../src/hero-layout.js';

export const STATES = [];
for (const dy of [-FLOAT_AMPLITUDE, FLOAT_AMPLITUDE]) for (const dz of [-TILT_AMPLITUDE, TILT_AMPLITUDE]) STATES.push([dy, dz]);

const boxCache = new WeakMap();
function box(piece) {
  if (!boxCache.has(piece.geometry)) {
    piece.geometry.computeBoundingBox();
    boxCache.set(piece.geometry, piece.geometry.boundingBox.clone());
  }
  return boxCache.get(piece.geometry);
}
function matrix(piece, dy, dz) {
  return new THREE.Matrix4().compose(
    new THREE.Vector3(piece.pos[0], piece.pos[1] + dy, piece.pos[2]),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(piece.rot[0], piece.rot[1], piece.rot[2] + dz)),
    new THREE.Vector3(1, 1, 1),
  );
}
export function obbFor(piece, dy = 0, dz = 0) {
  return new OBB().fromBox3(box(piece).clone().expandByScalar(CLEARANCE)).applyMatrix4(matrix(piece, dy, dz));
}

// Camera framing the cluster the same way the hero does (centred, ~9 units away).
export function cameraFor(pieces) {
  const c = pieces.reduce((acc, p) => acc.map((v, i) => v + p.pos[i] / pieces.length), [0, 0, 0]);
  const camera = new THREE.PerspectiveCamera(34, 1600 / 860, 0.1, 60);
  camera.position.set(c[0], c[1] + 0.3, c[2] + 9 / 0.66);
  camera.lookAt(c[0], c[1], c[2]);
  camera.updateMatrixWorld();
  return camera;
}

function cross(o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }
function hull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const lower = [], upper = [];
  for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
  for (const p of pts.reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}
export function screenHull(piece, camera, dy = 0, dz = 0) {
  const b = box(piece);
  const m = matrix(piece, dy, dz);
  const pts = [];
  for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) {
    const v = new THREE.Vector3(x, y, z).applyMatrix4(m).project(camera);
    pts.push([v.x * camera.aspect, v.y]);
  }
  return hull(pts);
}
function separated(a, b, gap) {
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i += 1) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      const n = [q[1] - p[1], p[0] - q[0]];
      const len = Math.hypot(...n) || 1;
      const proj = (pt) => (pt[0] * n[0] + pt[1] * n[1]) / len;
      const pa = a.map(proj), pb = b.map(proj);
      if (Math.max(...pa) + gap < Math.min(...pb) || Math.max(...pb) + gap < Math.min(...pa)) return true;
    }
  }
  return false;
}

export function clash(a, b, camera, gap = SCREEN_GAP) {
  const together = a.group && a.group === b.group;
  const pairs = together ? STATES.map((s) => [s, s]) : STATES.flatMap((s) => STATES.map((t) => [s, t]));
  for (const [s, t] of pairs) {
    if (obbFor(a, ...s).intersectsOBB(obbFor(b, ...t))) return '3d';
    if (!together && camera && !separated(screenHull(a, camera, ...s), screenHull(b, camera, ...t), gap)) return 'screen';
  }
  return '';
}

export function clashes(pieces, camera = cameraFor(pieces)) {
  const out = [];
  for (let i = 0; i < pieces.length; i += 1) for (let j = i + 1; j < pieces.length; j += 1) {
    const kind = clash(pieces[i], pieces[j], camera);
    if (kind) out.push([pieces[i], pieces[j], kind]);
  }
  return out;
}
