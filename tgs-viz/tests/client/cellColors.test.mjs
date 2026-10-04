// Node test for the Night Scorecard colour classes in src/lib/columns.js
// (Phase 4 restyle, docs/phase4/restyle_pattern.md): getCellColorClass,
// posClass, levelKey.
// Run: node tgs-viz/tests/client/cellColors.test.mjs
// columns.js imports its siblings without file extensions (Vite style), so it is
// bundled with esbuild (already in node_modules through Vite) before import.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cellColors-'));
const out = path.join(tmp, 'columns.mjs');
await build({
  entryPoints: [path.join(here, '../../src/lib/columns.js')],
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'error',
});
const { getCellColorClass: cc, posClass, levelKey, HITTER_COLUMN_GROUPS, PITCHER_COLUMN_GROUPS } = await import(pathToFileURL(out).href);
fs.rmSync(tmp, { recursive: true, force: true });

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// His Tailwind palette must not come back through this function.
const PALETTE = /(^|\s)(text|bg|border)-(slate|gray|zinc|green|red|orange|yellow|amber|cyan|purple|blue|sky|emerald|lime|rose|teal|indigo|violet|pink|white|black)\b/;
const ALLOWED = /^(ns-[a-z0-9-]+|font-(bold|semibold))$/;

test('no Tailwind palette class for any column x value', () => {
  const cols = new Set([...Object.values(HITTER_COLUMN_GROUPS), ...Object.values(PITCHER_COLUMN_GROUPS)].flatMap((g) => g.columns));
  ['Dev_Odds', '_durability', '_highINT', '_wrecked', '_surplus', '_marketValue', '_marketRole', '_agePercentile', 'RA/9 wtd', 'wOBA wtd']
    .forEach((c) => cols.add(c));
  const values = [-50, -6e6, -5, -1, -0.5, 0, 0.1, 0.3, 0.5, 1, 1.5, 3, 5, 20, 34, 35, 45, 55, 65, 75, 80, 95, 2e7,
    'up', 'down', 'flat', 'keep', 'move', 'Wrecked', 'Fragile', 'Normal', 'Durable', 'Iron Man',
    true, false, 'scarcity', 'replaceable', 'SP', 'RP', 'CL', '1B', 'C', '', null, undefined];
  for (const col of cols) {
    for (const v of values) {
      const cls = cc(v, col);
      assert.ok(!PALETTE.test(cls), `${col} ${v} -> ${cls}`);
      for (const token of cls.split(/\s+/).filter(Boolean)) assert.match(token, ALLOWED, `${col} ${v} -> ${cls}`);
    }
  }
});

test('value (WAA) ladder: his thresholds 5 / 3 / 1.5 / 0 / -1, onto the grade ramp', () => {
  const at = (v) => cc(v, 'Max WAA wtd');
  assert.equal(at(5), 'ns-g80');
  assert.equal(at(4.99), 'ns-g70');
  assert.equal(at(3), 'ns-g70');
  assert.equal(at(2.99), 'ns-g55');
  assert.equal(at(1.5), 'ns-g55');
  assert.equal(at(1.49), 'ns-text-2');
  assert.equal(at(0), 'ns-text-2');
  assert.equal(at(-0.01), 'ns-g30');
  assert.equal(at(-1), 'ns-g30');
  assert.equal(at(-1.01), 'ns-g20');
});

test('20-80 rating ladder: his thresholds 75 / 65 / 55 / 45 / 35', () => {
  const at = (v) => cc(v, 'POW vR');
  assert.deepEqual([80, 75, 74, 65, 64, 55, 54, 45, 44, 35, 34, 20].map(at),
    ['ns-g80', 'ns-g80', 'ns-g70', 'ns-g70', 'ns-g55', 'ns-g55', 'ns-text-2', 'ns-text-2', 'ns-g30', 'ns-g30', 'ns-g20', 'ns-g20']);
});

test('RA/9 ladder runs the other way (lower is better)', () => {
  assert.equal(cc(3.0, 'RA/9 wtd'), 'ns-g80');
  assert.equal(cc(3.01, 'RA/9 wtd'), 'ns-g70');
  assert.equal(cc(5.5, 'RA/9 wtd'), 'ns-g30');
  assert.equal(cc(5.51, 'RA/9 wtd'), 'ns-g20');
});

test('meaning columns use good / bad / warn and keep his weight', () => {
  assert.equal(cc('keep', 'Dev_Flag'), 'ns-good font-bold');
  assert.equal(cc('move', 'Dev_Flag'), 'ns-bad font-bold');
  assert.equal(cc(true, 'OnDL'), 'ns-bad font-semibold');
  assert.equal(cc(false, 'OnDL'), 'ns-dim');
  assert.equal(cc(true, 'NoTrade'), 'ns-warn');
  assert.equal(cc(10_000_001, '_surplus'), 'ns-good font-bold');
  assert.equal(cc(-5_000_000, '_surplus'), 'ns-bad');
  assert.equal(cc(-4_999_999, '_surplus'), 'ns-warn');
  assert.equal(cc(0.6, 'Dev_PeakMlb'), 'ns-good font-semibold');
  assert.equal(cc(0.25, 'Dev_PeakMlb'), 'ns-bad');
  assert.equal(cc(0.4, 'Dev_PeakMlb'), 'ns-text-2');
});

test('proneness uses the theme proneness encoding for both columns', () => {
  for (const col of ['Prone', '_durability']) {
    assert.equal(cc('Iron Man', col), 'ns-prone-iron-man');
    assert.equal(cc('Wrecked', col), 'ns-prone-wrecked');
    assert.equal(cc('Normal', col), 'ns-prone-normal');
    assert.equal(cc('Unknown', col), '');
  }
});

test('position columns get the position hue; non-positions get nothing', () => {
  assert.equal(cc('1B', 'POS'), 'ns-pos ns-pos-1b');
  assert.equal(cc('SS', 'Best Pos'), 'ns-pos ns-pos-ss');
  assert.equal(cc('CL', 'POS'), 'ns-pos ns-pos-cl');
  assert.equal(posClass('RP*'), 'ns-pos ns-pos-rp');
  assert.equal(posClass('XX'), '');
  assert.equal(posClass(undefined), '');
});

test('levelKey maps OOTP levels to chip keys; FA / AMA get none', () => {
  assert.equal(levelKey('MLB'), 'mlb');
  assert.equal(levelKey('A+'), 'aplus');
  assert.equal(levelKey('R+'), 'r');
  assert.equal(levelKey('R-'), 'r');
  assert.equal(levelKey('INT'), 'int');
  assert.equal(levelKey('FA'), null);
  assert.equal(levelKey('AMA'), null);
});

console.log(`cellColors: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
