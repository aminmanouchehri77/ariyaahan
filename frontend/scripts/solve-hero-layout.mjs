// Packs the hero bundle: starting from the seed, every group is pulled
// toward the cluster centre in small steps while it stays clear of every
// other piece both in 3D and on screen. Run: npm run solve:hero
import { writeFileSync } from 'node:fs';
import { seedLayout } from '../src/hero-layout.js';
import { SCREEN_GAP, STACK_AXIS } from '../src/hero-layout.js';
import { cameraFor, clash, clashes } from './hero-geometry-check.mjs';

const pieces = seedLayout();
let camera = cameraFor(pieces);
const groups = new Map();
for (const piece of pieces) {
  const id = piece.group || piece.key;
  if (!groups.has(id)) groups.set(id, []);
  groups.get(id).push(piece);
}
const groupOf = (p) => p.group || p.key;
const move = (id, d) => groups.get(id).forEach((p) => { p.pos = p.pos.map((v, i) => v + d[i]); });
const blocked = (id) => pieces.some((o) => groupOf(o) !== id && groups.get(id).some((p) => clash(p, o, camera, SCREEN_GAP * 2.5)));
const mean = (list) => list.reduce((acc, p) => acc.map((v, i) => v + p.pos[i] / list.length), [0, 0, 0]);

const initial = clashes(pieces, camera);
if (initial.length) {
  console.error('Seed already overlaps; spread the seed first:\n  ' + initial.map(([a, b, k]) => `${a.key} × ${b.key} (${k})`).join('\n  '));
  process.exit(1);
}
// Pull every group toward the cluster centre *along the stacking axis only*,
// so the bundle tightens without pieces sliding along each other.
const axis = [STACK_AXIS.x, STACK_AXIS.y, STACK_AXIS.z];
const dot = (v) => v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2];
for (let round = 0; round < 300; round += 1) {
  let moved = false;
  const centre = dot(mean(pieces));
  camera = cameraFor(pieces);
  for (const id of groups.keys()) {
    const delta = centre - dot(mean(groups.get(id)));
    if (Math.abs(delta) < 0.015) continue;
    const step = Math.sign(delta) * Math.min(0.015, Math.abs(delta));
    const d = axis.map((v) => v * step);
    move(id, d);
    if (blocked(id)) move(id, d.map((v) => -v));
    else moved = true;
  }
  if (!moved) break;
}
const out = {};
for (const piece of pieces) out[piece.key] = piece.pos.map((v) => Math.round(v * 1000) / 1000);
writeFileSync(new URL('../src/hero-layout.solved.json', import.meta.url), JSON.stringify(out, null, 2) + '\n');
console.log(clashes(pieces).length ? 'FAILED' : 'packed', out);
