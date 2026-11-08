// Packs the hero composition while keeping every piece's angle. Pieces may
// pass behind each other in depth; what matters is that no two overlap on
// screen.
//  1. separation — overlapping pieces are nudged apart along the axis of
//     least on-screen overlap (the hero I-beam never moves);
//  2. compaction — every piece slides back toward the I-beam, trying eight
//     directions, as far as it can without touching anything on screen.
// Run: npm run solve:hero  (writes src/hero-layout.solved.json)
import { writeFileSync } from 'node:fs';
import { SCREEN_GAP, seedLayout } from '../src/hero-layout.js';
import { camerasFor, clash, clashes, push } from './hero-geometry-check.mjs';

const SOLVE_GAP = SCREEN_GAP * 2;
const pieces = seedLayout();
const groups = new Map();
for (const piece of pieces) {
  const id = piece.group || piece.key;
  if (!groups.has(id)) groups.set(id, []);
  groups.get(id).push(piece);
}
const groupOf = (p) => p.group || p.key;
const anchorId = groupOf(pieces.find((p) => p.anchor));
const move = (id, d) => groups.get(id).forEach((p) => { p.pos = p.pos.map((v, i) => v + d[i]); });
const mean = (list) => list.reduce((acc, p) => acc.map((v, i) => v + p.pos[i] / list.length), [0, 0, 0]);
// The camera stays fixed on the seed's centre so the solve converges.
let camera = camerasFor(pieces);
const blocked = (id) => pieces.some((o) => groupOf(o) !== id && groups.get(id).some((p) => clash(p, o, camera, SOLVE_GAP)));

function separate() {
// 1. Separation.
for (let round = 0; round < 3000; round += 1) {
  let any = false;
  for (let i = 0; i < pieces.length; i += 1) for (let j = i + 1; j < pieces.length; j += 1) {
    const a = pieces[i], b = pieces[j];
    if (groupOf(a) === groupOf(b)) continue;
    const m = push(a, b, camera, SOLVE_GAP);
    if (!m) continue;
    any = true;
    const step = Math.min(0.04, m[2] * 3 + 0.005);
    if (groupOf(a) === anchorId) move(groupOf(b), [m[0] * step, m[1] * step, 0]);
    else if (groupOf(b) === anchorId) move(groupOf(a), [-m[0] * step, -m[1] * step, 0]);
    else {
      move(groupOf(b), [m[0] * step / 2, m[1] * step / 2, 0]);
      move(groupOf(a), [-m[0] * step / 2, -m[1] * step / 2, 0]);
    }
  }
  if (!any) break;
}
}

function compact() {
// 2. Compaction toward the anchor.
const DIRS = [];
for (let k = 0; k < 16; k += 1) DIRS.push([Math.cos((k / 16) * Math.PI * 2), Math.sin((k / 16) * Math.PI * 2)]);
for (const stepSize of [0.08, 0.04, 0.02, 0.01]) {
  camera = camerasFor(pieces);
  for (let round = 0; round < 400; round += 1) {
    let moved = false;
    const target = mean(groups.get(anchorId));
    for (const id of groups.keys()) {
      if (id === anchorId) continue;
      const c = mean(groups.get(id));
      const dist = Math.hypot(target[0] - c[0], target[1] - c[1]);
      if (dist < 0.05) continue;
      // Best direction that still gets closer to the anchor and stays clear.
      const ranked = DIRS.map((d) => {
        const nx = c[0] + d[0] * stepSize, ny = c[1] + d[1] * stepSize;
        return [Math.hypot(target[0] - nx, target[1] - ny), d];
      }).filter(([nd]) => nd < dist - stepSize * 0.3).sort((x, y) => x[0] - y[0]);
      for (const [, d] of ranked) {
        const delta = [d[0] * stepSize, d[1] * stepSize, 0];
        move(id, delta);
        if (blocked(id)) move(id, delta.map((v) => -v));
        else { moved = true; break; }
      }
    }
    if (!moved) break;
  }
}
}

for (let pass = 0; pass < 12; pass += 1) {
  camera = camerasFor(pieces);
  separate();
  compact();
  camera = camerasFor(pieces);
  separate();
  if (!clashes(pieces).length) break;
}

const out = {};
for (const piece of pieces) out[piece.key] = piece.pos.map((v) => Math.round(v * 1000) / 1000);
writeFileSync(new URL('../src/hero-layout.solved.json', import.meta.url), JSON.stringify(out, null, 2) + '\n');
const remaining = clashes(pieces);
console.log(remaining.length ? `FAILED: ${remaining.map(([a, b, k]) => `${a.key}×${b.key}(${k})`).join(', ')}` : 'packed', out);
