// Composition of the 3D hero.
//
// Pieces keep their individual angles; they must not intersect in 3D and
// must not overlap each other on screen either. The seed below is the art direction; the final positions
// in hero-layout.solved.json are produced by scripts/solve-hero-layout.mjs,
// which resolves any 3D overlap and then pulls every piece as close to the
// cluster as possible. scripts/check-hero-layout.mjs re-verifies the result.
import {
  THREE, iBeamGeometry, rebarGeometry, tubeGeometry, boxSectionGeometry, angleGeometry, mergeGeometries,
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

// The original art direction: pieces at different angles around a hero
// I-beam, like steel sections tossed into the air. The solver keeps every
// angle and only moves pieces apart/together so nothing intersects in 3D or
// overlaps on screen.
export function seedLayout() {
  const pieces = [
    { key: 'beam', geometry: iBeamGeometry(6.5, 0.62, 0.32, 0.045, 0.065), material: 'dark', pos: [1.8, 0.9, -1.2], rot: [0.35, -0.55, 0.62], anchor: true },
    { key: 'beam2', geometry: iBeamGeometry(5.5, 0.5, 0.26), material: 'mill', pos: [3.2, -1.1, -2.6], rot: [-0.2, 0.5, -0.35] },
    { key: 'box', geometry: boxSectionGeometry(5, 0.36, 0.36, 0.025, 0.035), material: 'dark', pos: [0.2, -1.6, -0.6], rot: [0.1, 0.9, 0.18] },
    { key: 'tube', geometry: tubeGeometry(5, 0.2, 0.02), material: 'bright', pos: [2.6, 2.2, -3.4], rot: [0.5, 0.2, 1.1] },
    { key: 'angle', geometry: angleGeometry(4.6, 0.34, 0.04), material: 'mill', pos: [-1.6, 1.7, -2.8], rot: [-0.4, 0.8, 0.4] },
    { key: 'sheets', geometry: plateStackGeometry(4, 1.4, 0.04, 3.8, 0.11), material: 'mill', pos: [-1.2, -0.4, -1.8], rot: [0.95, 0.45, -0.25] },
  ];
  const rebar = rebarGeometry(5.2, 0.07);
  // Five parallel bars, stepped apart perpendicular to their on-screen axis
  // so each one reads as a separate bar.
  const rebarRot = [0.2, -0.95, -0.42];
  const axis = new THREE.Vector3(0, 0, 1).applyEuler(new THREE.Euler(...rebarRot));
  const side = new THREE.Vector2(-axis.y, axis.x).normalize();
  for (let i = 0; i < 5; i += 1) {
    const k = i - 2;
    pieces.push({
      key: `rebar${i}`, geometry: rebar, material: 'rebar', group: 'rebars',
      pos: [0.6 + side.x * k * 0.25, -0.1 + side.y * k * 0.25, 0.6 - k * 0.05], rot: rebarRot,
    });
  }
  return pieces;
}

export function heroLayout() {
  const pieces = seedLayout();
  for (const piece of pieces) {
    if (solved[piece.key]) piece.pos = solved[piece.key];
  }
  return pieces;
}
