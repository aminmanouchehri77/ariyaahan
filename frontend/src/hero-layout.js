// Composition of the 3D hero.
//
// Pieces form one dense, parallel bundle: they must not intersect in 3D and
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

// All pieces share one length axis and are stacked across it like a fanned
// bundle: close together, never crossing in 3D or on screen.
export const LENGTH_AXIS = new THREE.Vector3(-0.8, 0.46, 0.38).normalize();
// Stacking direction: perpendicular to the length axis in the picture plane.
export const STACK_AXIS = new THREE.Vector3(-LENGTH_AXIS.y, LENGTH_AXIS.x, 0).normalize().multiplyScalar(-1);

function orient(roll = 0) {
  const align = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), LENGTH_AXIS);
  const spin = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), roll);
  const euler = new THREE.Euler().setFromQuaternion(align.multiply(spin), 'XYZ');
  return [euler.x, euler.y, euler.z];
}

export function seedLayout() {
  const slot = (k, stagger = 0, depth = 0) => {
    const p = STACK_AXIS.clone().multiplyScalar(k * 2.0).addScaledVector(LENGTH_AXIS, stagger);
    return [p.x, p.y, depth];
  };
  const pieces = [
    { key: 'tube', geometry: tubeGeometry(5.0, 0.2, 0.02), material: 'bright', pos: slot(0, 0.9, -0.3), rot: orient(0) },
    { key: 'angle', geometry: angleGeometry(5.2, 0.34, 0.04), material: 'mill', pos: slot(1, 0.5, -0.2), rot: orient(0.6) },
    { key: 'beam', geometry: iBeamGeometry(6.6, 0.62, 0.32, 0.045, 0.065), material: 'dark', pos: slot(2, 0.1, -0.1), rot: orient(0.25) },
    { key: 'sheets', geometry: plateStackGeometry(), material: 'mill', pos: slot(3.3, -0.2, 0), rot: orient(1.15) },
    { key: 'box', geometry: boxSectionGeometry(5.6, 0.36, 0.36, 0.025, 0.035), material: 'dark', pos: slot(4.6, -0.5, 0.1), rot: orient(0.3) },
  ];
  const rebar = rebarGeometry(5.6, 0.07);
  for (let i = 0; i < 5; i += 1) {
    const base = slot(5.6 + i * 0.2, -0.8 - i * 0.12, 0.2 + i * 0.02);
    pieces.push({ key: `rebar${i}`, geometry: rebar, material: 'rebar', group: 'rebars', pos: base, rot: orient(i * 0.4) });
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
