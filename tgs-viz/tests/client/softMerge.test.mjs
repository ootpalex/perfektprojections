// Node test for src/lib/softMerge.js (DESIGN 9.4, 15.3 step 1).
// Run: node tgs-viz/tests/client/softMerge.test.mjs
import assert from 'node:assert/strict';
import { keysToFetch, mergeRaw, baseName, OBJECT_KEYS } from '../../src/lib/softMerge.js';

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// Same shape as usePlayerData.getDataFiles.
function dataFiles(league, parkMode) {
  const p = `/data/${league}`;
  const s = parkMode === 'park' ? '_park' : '';
  return {
    hitters: `${p}/hitters${s}.json`, pitchers: `${p}/pitchers${s}.json`,
    hitters_draft: `${p}/hitters_draft${s}.json`, pitchers_draft: `${p}/pitchers_draft${s}.json`,
    hitters_draft_all: `${p}/hitters_draft_all${s}.json`, pitchers_draft_all: `${p}/pitchers_draft_all${s}.json`,
    draft_picks: `${p}/draft_picks.json`, iafa: `${p}/iafa.json`, r5: `${p}/r5.json`,
    parks: `${p}/parks.json`, park_list: `${p}/park_list.json`,
  };
}
const NEUTRAL = dataFiles('TGS', 'neutral');
const PARK = dataFiles('TGS', 'park');

test('baseName handles POSIX, Windows and bare names', () => {
  assert.equal(baseName('TGS/hitters.json'), 'hitters.json');
  assert.equal(baseName('TGS\\hitters.json'), 'hitters.json');
  assert.equal(baseName('/data/TGS/r5.json'), 'r5.json');
  assert.equal(baseName('hitters.json'), 'hitters.json');
});

test('null means everything: every list key and every object key', () => {
  const keys = keysToFetch(null, NEUTRAL, 'neutral');
  assert.deepEqual(keys, [...Object.keys(NEUTRAL), ...OBJECT_KEYS]);
  assert.ok(keys.includes('metadata') && keys.includes('marketBank') && keys.includes('devSignals') && keys.includes('devMl'));
});

test('neutral: hitters.json changed fetches hitters only', () => {
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters.json']), NEUTRAL, 'neutral'), ['hitters']);
});

test('neutral: hitters_park.json is not used, so it fetches nothing', () => {
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters_park.json']), NEUTRAL, 'neutral'), []);
});

test('park: hitters_park.json fetches hitters; the neutral hitters.json fetches nothing', () => {
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters_park.json']), PARK, 'park'), ['hitters']);
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters.json']), PARK, 'park'), []);
});

test('park: a changed neutral draft file fetches the draft key (the _park fallback)', () => {
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters_draft.json']), PARK, 'park'), ['hitters_draft']);
  assert.deepEqual(keysToFetch(new Set(['TGS/pitchers_draft_all.json']), PARK, 'park'), ['pitchers_draft_all']);
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters_draft_park.json']), PARK, 'park'), ['hitters_draft']);
});

test('neutral: a changed _park draft file fetches nothing', () => {
  assert.deepEqual(keysToFetch(new Set(['TGS/hitters_draft_park.json']), NEUTRAL, 'neutral'), []);
});

test('files shared by both bases (r5, iafa, parks) fetch in either mode', () => {
  for (const [files, mode] of [[NEUTRAL, 'neutral'], [PARK, 'park']]) {
    assert.deepEqual(keysToFetch(new Set(['TGS/r5.json', 'TGS/iafa.json', 'TGS/parks.json']), files, mode), ['iafa', 'r5', 'parks']);
  }
});

test('object files map to their own inputs', () => {
  const keys = keysToFetch(new Set(['TGS/metadata.json', 'TGS/market_fit.json', 'TGS/dev_signals.json', 'TGS/dev_ml.json']), NEUTRAL, 'neutral');
  assert.deepEqual(keys, ['metadata', 'marketBank', 'devSignals', 'devMl']);
});

test('an empty change set and unknown files fetch nothing', () => {
  assert.deepEqual(keysToFetch(new Set(), NEUTRAL, 'neutral'), []);
  assert.deepEqual(keysToFetch(['TGS/hitters.json.bak-20261001', 'TGS/calibration.json'], NEUTRAL, 'neutral'), []);
});

test('an array of changed files works like a Set', () => {
  assert.deepEqual(keysToFetch(['TGS\\pitchers.json'], NEUTRAL, 'neutral'), ['pitchers']);
});

test('mergeRaw lays fetched values over the previous ones', () => {
  const prev = { hitters: ['old h'], pitchers: ['old p'], metadata: { a: 1 } };
  const out = mergeRaw(prev, { hitters: ['new h'] }, []);
  assert.deepEqual(out, { hitters: ['new h'], pitchers: ['old p'], metadata: { a: 1 } });
  assert.deepEqual(prev.hitters, ['old h'], 'the previous object is not changed');
});

test('mergeRaw keeps a failed key at its old value', () => {
  const prev = { hitters: ['old h'], iafa: ['old i'] };
  const out = mergeRaw(prev, { hitters: ['new h'], iafa: [] }, ['iafa']);
  assert.deepEqual(out.iafa, ['old i']);
  assert.deepEqual(out.hitters, ['new h']);
});

test('mergeRaw: a failed key with nothing fetched keeps its old value', () => {
  const out = mergeRaw({ devMl: { pull: 3 } }, {}, ['devMl']);
  assert.deepEqual(out.devMl, { pull: 3 });
});

test('mergeRaw with no previous raw', () => {
  assert.deepEqual(mergeRaw(null, { r5: [1] }, []), { r5: [1] });
});

console.log(`\nsoftMerge: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
