// Shared check for the hero layout: no two pieces may overlap on screen.
// Each piece is judged by the convex hull of its real projected vertices
// (pieces may pass behind one another in depth — only what the visitor
// sees matters).
import { OBB } from 'three/examples/jsm/math/OBB.js';
import { THREE } from '../src/steel.js';
import {
  CAMERA_Y, CAMERA_Z, CHECK_VIEWPORTS, CLEARANCE, FLOAT_AMPLITUDE, SCREEN_GAP, TILT_AMPLITUDE, heroFraming,
} from '../src/hero-layout.js';

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

// Cameras that see the layout exactly as the live hero does at each checked
// viewport: same box, same framing maths, expressed in layout coordinates.
function layoutBox(pieces) {
  const group = new THREE.Group();
  for (const p of pieces) {
    const mesh = new THREE.Mesh(p.geometry);
    mesh.position.set(...p.pos);
    mesh.rotation.set(...p.rot);
    group.add(mesh);
  }
  return new THREE.Box3().setFromObject(group);
}
export function cameraFor(pieces, [width, height]) {
  const box = layoutBox(pieces);
  const f = heroFraming(box.getSize(new THREE.Vector3()), box.getCenter(new THREE.Vector3()), width, height);
  const camera = new THREE.PerspectiveCamera(f.fov, f.aspect, 0.01, 200);
  camera.position.set(
    (0 - f.position[0]) / f.scale,
    (CAMERA_Y - f.position[1]) / f.scale,
    (CAMERA_Z - f.position[2]) / f.scale,
  );
  camera.updateMatrixWorld();
  return camera;
}
export const camerasFor = (pieces) => CHECK_VIEWPORTS.map((viewport) => cameraFor(pieces, viewport));

function cross(o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }
function hull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const lower = [], upper = [];
  for (const p of pts) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop(); lower.push(p); }
  for (const p of pts.reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop(); upper.push(p); }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}
const vertexCache = new WeakMap();
function vertices(piece) {
  if (!vertexCache.has(piece.geometry)) {
    // Hull of the object's own vertices (subsampled) — far tighter than its box.
    const attr = piece.geometry.attributes.position;
    const local = [];
    for (let i = 0; i < attr.count; i += 1) local.push([attr.getX(i), attr.getY(i), attr.getZ(i)]);
    const keep = hull3dCandidates(local);
    vertexCache.set(piece.geometry, keep.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
  }
  return vertexCache.get(piece.geometry);
}
// Keep only points on the extremes along many directions: a cheap superset
// of the 3D convex hull vertices that preserves the projected silhouette.
function hull3dCandidates(points) {
  const keep = new Set();
  const dirs = [];
  for (let a = 0; a < 24; a += 1) for (let b = 0; b < 12; b += 1) {
    const t = (a / 24) * Math.PI * 2, f = ((b + 0.5) / 12) * Math.PI;
    dirs.push([Math.sin(f) * Math.cos(t), Math.sin(f) * Math.sin(t), Math.cos(f)]);
  }
  for (const d of dirs) {
    let best = -Infinity, idx = 0;
    points.forEach((p, i) => { const v = p[0] * d[0] + p[1] * d[1] + p[2] * d[2]; if (v > best) { best = v; idx = i; } });
    keep.add(idx);
  }
  return [...keep].map((i) => points[i]);
}
const hullMemo = new Map();
export function screenHull(piece, camera, dy = 0, dz = 0) {
  const key = `${piece.key}|${piece.pos}|${dy}|${dz}|${camera.position.toArray()}|${camera.fov}|${camera.aspect}`;
  if (hullMemo.has(key)) return hullMemo.get(key);
  if (hullMemo.size > 50000) hullMemo.clear();
  const m = matrix(piece, dy, dz);
  const pts = vertices(piece).map((p) => {
    const v = p.clone().applyMatrix4(m).project(camera);
    return [v.x * camera.aspect, v.y];
  });
  const h = hull(pts);
  hullMemo.set(key, h);
  return h;
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
  if (Array.isArray(camera)) {
    for (const cam of camera) { const k = clash(a, b, cam, gap); if (k) return k; }
    return '';
  }
  const together = a.group && a.group === b.group;
  const pairs = together ? STATES.map((s) => [s, s]) : STATES.flatMap((s) => STATES.map((t) => [s, t]));
  for (const [s, t] of pairs) {
    if (!separated(screenHull(a, camera, ...s), screenHull(b, camera, ...t), gap)) return 'screen';
  }
  return '';
}

export function clashes(pieces, camera = camerasFor(pieces)) {
  const out = [];
  for (let i = 0; i < pieces.length; i += 1) for (let j = i + 1; j < pieces.length; j += 1) {
    const kind = clash(pieces[i], pieces[j], camera);
    if (kind) out.push([pieces[i], pieces[j], kind]);
  }
  return out;
}

// Minimum translation (screen units) that would separate b from a, as
// [axisX, axisY, depth] with the axis pointing from a toward b; null if apart.
function mtv(a, b, gap) {
  let best = null;
  const ca = a.reduce((s, p) => [s[0] + p[0] / a.length, s[1] + p[1] / a.length], [0, 0]);
  const cb = b.reduce((s, p) => [s[0] + p[0] / b.length, s[1] + p[1] / b.length], [0, 0]);
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i += 1) {
      const p = poly[i], q = poly[(i + 1) % poly.length];
      let n = [q[1] - p[1], p[0] - q[0]];
      const len = Math.hypot(...n) || 1;
      n = [n[0] / len, n[1] / len];
      const proj = (pt) => pt[0] * n[0] + pt[1] * n[1];
      const pa = a.map(proj), pb = b.map(proj);
      const overlap = Math.min(Math.max(...pa), Math.max(...pb)) - Math.max(Math.min(...pa), Math.min(...pb)) + gap;
      if (overlap <= 0) return null;
      if (!best || overlap < best[2]) {
        const sign = proj(cb) - proj(ca) >= 0 ? 1 : -1;
        best = [n[0] * sign, n[1] * sign, overlap];
      }
    }
  }
  return best;
}
export function push(a, b, camera, gap = SCREEN_GAP) {
  if (Array.isArray(camera)) {
    let worst = null;
    for (const cam of camera) { const m = push(a, b, cam, gap); if (m && (!worst || m[2] > worst[2])) worst = m; }
    return worst;
  }
  let worst = null;
  for (const s of STATES) for (const t of STATES) {
    const m = mtv(screenHull(a, camera, ...s), screenHull(b, camera, ...t), gap);
    if (m && (!worst || m[2] > worst[2])) worst = m;
  }
  return worst;
}
