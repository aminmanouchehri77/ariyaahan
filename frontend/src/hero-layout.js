// Composition of the 3D hero.
//
// Pieces keep their individual angles; they must not overlap each other on
// screen (they may pass behind one another in depth). The seed below is the art direction; the final positions
// in hero-layout.solved.json are produced by scripts/solve-hero-layout.mjs,
// which resolves any 3D overlap and then pulls every piece as close to the
// cluster as possible. scripts/check-hero-layout.mjs re-verifies the result.
import {
  THREE, iBeamGeometry, tubeGeometry, boxSectionGeometry, angleGeometry, mergeGeometries,
} from './steel.js';
import solved from './hero-layout.solved.json';

// The whole cluster floats together; each piece only drifts slightly, so
// relative distances stay almost constant and pieces can sit close together.
export const CLUSTER_FLOAT = 0.14;
export const FLOAT_AMPLITUDE = 0.03;
export const TILT_AMPLITUDE = 0.012;
export const CLEARANCE = 0.035;
// Minimum on-screen gap between pieces, in normalised device units.
export const SCREEN_GAP = 0.012;

function plateStackGeometry(count = 4, width = 1.5, thickness = 0.04, length = 4.6, gap = 0.12) {
  const plates = [];
  for (let i = 0; i < count; i += 1) {
    const plate = new THREE.BoxGeometry(width, thickness, length, 1, 1, 1);
    // Sheets fanned off a stack: each one shifted and slightly turned.
    plate.rotateY(i * 0.045);
    plate.translate(i * 0.1, i * gap, -i * 0.16);
    plates.push(plate);
  }
  return mergeGeometries(plates);
}

// A tied bundle of rebars as delivered from the mill: bars packed in a
// hexagon, ends slightly staggered, held by three wire ties.
function bundleBar(length, radius, ribbed) {
  // Low-poly bar: the bundle has 19 of them, so detail goes only where the
  // eye sees it (ribs on the outer ring; inner bars only show their ends).
  const parts = [];
  const core = new THREE.CylinderGeometry(radius, radius, length, 12, 1, false);
  core.rotateX(Math.PI / 2);
  parts.push(core);
  if (ribbed) {
    const spacing = radius * 2.1;
    const count = Math.floor(length / spacing);
    for (let i = 0; i < count; i += 1) {
      const rib = new THREE.TorusGeometry(radius * 1.02, radius * 0.16, 3, 10, Math.PI * 0.9);
      rib.rotateZ((i % 2) * Math.PI);
      rib.rotateY(0.24 * (i % 2 ? 1 : -1));
      rib.translate(0, 0, -length / 2 + i * spacing + spacing / 2);
      parts.push(rib);
    }
  }
  return mergeGeometries(parts);
}

function rebarBundleGeometry(length = 5.6, radius = 0.062, rings = 2) {
  const step = radius * 2.06;
  const plain = bundleBar(length, radius, false);
  const ribbed = bundleBar(length, radius, true);
  const parts = [];
  const cells = [[0, 0]];
  for (let ring = 1; ring <= rings; ring += 1) {
    for (let side = 0; side < 6; side += 1) {
      for (let k = 0; k < ring; k += 1) {
        const a = (Math.PI / 3) * side, b = (Math.PI / 3) * (side + 2);
        cells.push([ring * Math.cos(a) + k * Math.cos(b), ring * Math.sin(a) + k * Math.sin(b)]);
      }
    }
  }
  let outer = 0;
  cells.forEach(([u, v], index) => {
    const copy = (Math.hypot(u, v) > rings - 0.6 ? ribbed : plain).clone();
    // Deterministic stagger so the bundle's ends look cut, not rendered.
    const stagger = Math.sin(index * 12.9898) * 0.22;
    copy.translate(u * step, v * step, stagger);
    parts.push(copy);
    outer = Math.max(outer, Math.hypot(u * step, v * step));
  });
  for (const z of [-length * 0.32, 0, length * 0.32]) {
    const tie = new THREE.TorusGeometry(outer + radius * 1.25, 0.018, 5, 36);
    tie.translate(0, 0, z);
    parts.push(tie);
  }
  return mergeGeometries(parts);
}

// The original art direction: pieces at different angles around a large
// hero I-beam that juts out toward the viewer. The solver keeps every angle
// and only slides pieces so nothing overlaps on screen.
export function seedLayout() {
  return [
    { key: 'beam', geometry: iBeamGeometry(7.8, 0.84, 0.44, 0.06, 0.085), material: 'dark', pos: [1.6, 0.7, 0.6], rot: [0.3, -0.42, 0.6], anchor: true },
    { key: 'beam2', geometry: iBeamGeometry(5.5, 0.5, 0.26), material: 'mill', pos: [3.2, -1.1, -2.6], rot: [-0.2, 0.62, -0.35] },
    { key: 'box', geometry: boxSectionGeometry(5, 0.36, 0.36, 0.025, 0.035), material: 'dark', pos: [0.2, -1.6, -0.6], rot: [0.12, 1.0, 0.18] },
    { key: 'tube', geometry: tubeGeometry(5, 0.2, 0.02), material: 'bright', pos: [2.6, 2.2, -3.4], rot: [0.5, 0.2, 1.1] },
    { key: 'angle', geometry: angleGeometry(4.6, 0.34, 0.04), material: 'mill', pos: [-1.6, 1.7, -2.8], rot: [-0.4, 0.8, 0.4] },
    { key: 'sheets', geometry: plateStackGeometry(4, 1.4, 0.04, 3.8, 0.11), material: 'mill', pos: [-1.2, -0.4, -1.8], rot: [0.95, 0.45, -0.25] },
    { key: 'bundle', geometry: rebarBundleGeometry(), material: 'rebar', pos: [0.4, -0.3, -0.2], rot: [0.22, -0.78, -0.4] },
  ];
}

// Camera and framing shared by the live hero and the layout checker, so the
// overlap check sees exactly what the visitor sees. A close camera with a
// wide lens exaggerates perspective: near ends of the sections loom out.
export const CAMERA_Y = 0.3;
export const CAMERA_Z = 4.4;
export function heroFraming(size, center, width, height) {
  const aspect = width / height;
  const wide = width > 900;
  const medium = wide && width < 1240;
  const fov = wide ? 62 : 68;
  const visibleH = 2 * CAMERA_Z * Math.tan(THREE.MathUtils.degToRad(fov / 2));
  const visibleW = visibleH * aspect;
  // Region of the hero the cluster fills: left half on wide screens (text is
  // on the right in RTL), the upper area on phones.
  let region = { w: visibleW * 0.92, h: visibleH * 0.46, x: 0, y: visibleH * 0.2 };
  if (wide) region = { w: visibleW * 0.42, h: visibleH * 0.84, x: -visibleW * 0.23, y: 0 };
  if (medium) region = { w: visibleW * 0.32, h: visibleH * 0.64, x: -visibleW * 0.3, y: visibleH * 0.04 };
  const scale = Math.min(region.w / size.x, region.h / size.y);
  return {
    fov,
    aspect,
    scale,
    position: [region.x - center.x * scale, region.y - center.y * scale, -center.z * scale],
  };
}
// Viewports the checker verifies (desktop, laptop, tablet, phone).
export const CHECK_VIEWPORTS = [[1600, 860], [1100, 760], [820, 1000], [390, 860]];

export function heroLayout() {
  const pieces = seedLayout();
  for (const piece of pieces) {
    if (solved[piece.key]) piece.pos = solved[piece.key];
  }
  return pieces;
}
