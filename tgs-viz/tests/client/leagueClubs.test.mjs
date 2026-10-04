// Node test for src/lib/leagueClubs.js: which clubs the standings / strength / org pages rank.
// Run: node tgs-viz/tests/client/leagueClubs.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveLeagueClubs } from '../../src/lib/leagueClubs.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const SSB_META = path.resolve(here, '../../public/data/SSB/metadata.json');

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

const BUILT_IN = { AL: new Set(['A1', 'A2']), NL: new Set(['N1', 'N2']) };
const team = (id, name, sub) => ({ id, name, sub_league: sub });
const META = {
  clubs: {
    teams: [team('1', 'A1', 'American League'), team('2', 'N1', 'National League'),
      team('3', 'A2', 'American League'), team('4', 'N2', 'National League'), team('5', 'N3', 'National League')],
    sub_leagues: [{ name: 'National League', abbr: 'NL' }, { name: 'American League', abbr: 'AL' }],
  },
};

test('metadata clubs win over the built-in sets, slots by abbreviation', () => {
  const r = resolveLeagueClubs(META, BUILT_IN);
  assert.deepEqual([...r.known].sort(), ['A1', 'A2', 'N1', 'N2', 'N3']);
  assert.deepEqual([...r.map.AL].sort(), ['A1', 'A2']);
  assert.deepEqual([...r.map.NL].sort(), ['N1', 'N2', 'N3']);
  assert.deepEqual(r.names, { AL: 'American League', NL: 'National League' });
  assert.deepEqual(r.abbrs, { AL: 'AL', NL: 'NL' });
});

test('other sub-league names fill the slots in page order', () => {
  const m = { clubs: { teams: [team('1', 'X', 'Adams League'), team('2', 'Y', 'Zotti League')],
    sub_leagues: [{ name: 'Adams League', abbr: 'AL2' }, { name: 'Zotti League', abbr: 'ZL' }] } };
  const r = resolveLeagueClubs(m, null);
  assert.deepEqual([...r.map.AL], ['X']);
  assert.deepEqual([...r.map.NL], ['Y']);
  assert.deepEqual(r.names, { AL: 'Adams League', NL: 'Zotti League' });
  assert.deepEqual(r.abbrs, { AL: 'AL2', NL: 'ZL' });
});

test('clubs without a split: known list, one combined table', () => {
  const m = { clubs: { teams: META.clubs.teams.map((t) => ({ ...t, sub_league: null })), sub_leagues: [] } };
  const r = resolveLeagueClubs(m, BUILT_IN);
  assert.equal(r.known.size, 5);
  assert.equal(r.map, null);
});

test('a club outside both sub-leagues drops the split, keeps the list', () => {
  const m = { clubs: { ...META.clubs, teams: [...META.clubs.teams, team('6', 'Z', 'Somewhere')] } };
  const r = resolveLeagueClubs(m, null);
  assert.equal(r.known.size, 6);
  assert.equal(r.map, null);
});

test('no metadata clubs: the built-in sets (TGS / BLM), unchanged', () => {
  for (const meta of [null, {}, { matchups: { 'OVR vR': 0.7 } }, { clubs: { teams: [] } }]) {
    const r = resolveLeagueClubs(meta, BUILT_IN);
    assert.equal(r.map, BUILT_IN);
    assert.deepEqual([...r.known].sort(), ['A1', 'A2', 'N1', 'N2']);
    assert.deepEqual(r.names, { AL: 'American League', NL: 'National League' });
  }
});

test('nothing at all: null, the pages keep their real-roster fallback', () => {
  const r = resolveLeagueClubs(null, undefined);
  assert.equal(r.known, null);
  assert.equal(r.map, null);
});

test("SSB's committed metadata: 28 clubs, 14 AL / 14 NL, no foreign club", () => {
  if (!fs.existsSync(SSB_META)) { console.log('skip SSB metadata (missing)'); return; }
  const meta = JSON.parse(fs.readFileSync(SSB_META, 'utf8'));
  const r = resolveLeagueClubs(meta, null);
  assert.equal(r.known.size, 28);
  assert.equal(r.map.AL.size, 14);
  assert.equal(r.map.NL.size, 14);
  for (const name of ['Nashville Stars', 'Chicago Cubs', 'Milwaukee Brewers']) assert.ok(r.map.NL.has(name), name);
  for (const name of ['Portland Loggers', 'Chicago White Sox', 'Cleveland Guardians']) assert.ok(r.map.AL.has(name), name);
  assert.ok(!r.known.has('Samsung Lions'));
});

console.log(`\nleagueClubs: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
