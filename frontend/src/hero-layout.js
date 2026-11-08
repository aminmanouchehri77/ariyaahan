// Composition of the 3D hero. Pieces share one dominant diagonal and sit in
// separate depth/height layers so they never intersect, even while floating
// (verified by scripts/check-hero-layout.mjs with oriented bounding boxes).
import {
  THREE, iBeamGeometry, rebarGeometry, tubeGeometry, boxSectionGeometry, angleGeometry, mergeGeometries,
} from './steel.js';

export const FLOAT_AMPLITUDE = 0.12;
export const TILT_AMPLITUDE = 0.03;

function plateStackGeometry(count = 3, width = 1.45, thickness = 0.045, length = 4.4, gap = 0.17) {
  const plates = [];
  for (let i = 0; i < count; i += 1) {
    const plate = new THREE.BoxGeometry(width, thickness, length, 1, 1, 1);
    // Each plate slightly offset, like sheets fanned off a stack.
    plate.translate(i * 0.12, i * gap, -i * 0.18);
    plates.push(plate);
  }
  return mergeGeometries(plates);
}

export function heroLayout() {
  const dir = [0.16, -0.62, 0.34];
  const tilt = (dx = 0, dy = 0, dz = 0) => [dir[0] + dx, dir[1] + dy, dir[2] + dz];
  const pieces = [
    { key: 'tube', geometry: tubeGeometry(5.2, 0.2, 0.02), material: 'bright', pos: [2.8, 2.75, -4.0], rot: tilt(0.02, 0.04, 0.06) },
    { key: 'angle', geometry: angleGeometry(4.8, 0.34, 0.04), material: 'mill', pos: [1.4, 1.45, -2.5], rot: tilt(-0.05, 0.02, 0.02) },
    { key: 'beam', geometry: iBeamGeometry(6.6, 0.62, 0.32, 0.045, 0.065), material: 'dark', pos: [0.7, 0.5, -1.5], rot: tilt() },
    { key: 'sheets', geometry: plateStackGeometry(), material: 'mill', pos: [-0.25, -1.4, 0.05], rot: tilt(0.1, 0, 0.7) },
    { key: 'box', geometry: boxSectionGeometry(5, 0.36, 0.36, 0.025, 0.035), material: 'dark', pos: [3.6, -0.2, -4.4], rot: tilt(-0.04, 0.06, -0.05) },
  ];
  const rebar = rebarGeometry(5.4, 0.07);
  for (let i = 0; i < 5; i += 1) {
    pieces.push({
      key: `rebar${i}`, geometry: rebar, material: 'rebar', group: 'rebars',
      pos: [-1.05 + i * 0.1, -2.75 - i * 0.26, 1.25 + i * 0.06], rot: tilt(0.02, -0.02, 0.02 + i * 0.01),
    });
  }
  return pieces;
}
