// Verifies that no two hero pieces intersect in 3D or overlap on screen at
// any point of their drift animation. Run: npm run check:hero
import { heroLayout } from '../src/hero-layout.js';
import { clashes, STATES } from './hero-geometry-check.mjs';

const pieces = heroLayout();
const found = clashes(pieces);
if (found.length) {
  console.error('Overlapping pieces:\n  ' + found.map(([a, b, kind]) => `${a.key} × ${b.key} (${kind})`).join('\n  '));
  process.exit(1);
}
console.log(`OK — ${pieces.length} pieces, no 3D or on-screen overlap across ${STATES.length} drift states.`);
