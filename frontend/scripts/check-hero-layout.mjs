// Verifies that no two hero pieces intersect at any point of their float
// animation. Run: npm run check:hero
import { OBB } from 'three/examples/jsm/math/OBB.js';
import { THREE } from '../src/steel.js';
import { FLOAT_AMPLITUDE, TILT_AMPLITUDE, heroLayout } from '../src/hero-layout.js';

const pieces = heroLayout();
const margin = 0.04;
const states = [];
for (const dy of [-FLOAT_AMPLITUDE, 0, FLOAT_AMPLITUDE]) {
  for (const dz of [-TILT_AMPLITUDE, 0, TILT_AMPLITUDE]) states.push([dy, dz]);
}
function obbFor(piece, dy, dz) {
  piece.geometry.computeBoundingBox();
  const box = piece.geometry.boundingBox.clone().expandByScalar(margin);
  const matrix = new THREE.Matrix4().compose(
    new THREE.Vector3(piece.pos[0], piece.pos[1] + dy, piece.pos[2]),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(piece.rot[0], piece.rot[1], piece.rot[2] + dz)),
    new THREE.Vector3(1, 1, 1),
  );
  return new OBB().fromBox3(box).applyMatrix4(matrix);
}
const clashes = [];
for (let i = 0; i < pieces.length; i += 1) {
  for (let j = i + 1; j < pieces.length; j += 1) {
    const a = pieces[i], b = pieces[j];
    const together = a.group && a.group === b.group;
    const combos = together ? states.map((s) => [s, s]) : states.flatMap((s) => states.map((t) => [s, t]));
    if (combos.some(([s, t]) => obbFor(a, ...s).intersectsOBB(obbFor(b, ...t)))) clashes.push(`${a.key} × ${b.key}`);
  }
}
if (clashes.length) {
  console.error('Intersecting pieces:\n  ' + clashes.join('\n  '));
  process.exit(1);
}
console.log(`OK — ${pieces.length} pieces, no intersections across ${states.length} float states.`);
