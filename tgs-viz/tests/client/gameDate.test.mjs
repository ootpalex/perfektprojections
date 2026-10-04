// Node test for src/lib/gameDate.js: the sidebar's Game Date.
// Run: node tgs-viz/tests/client/gameDate.test.mjs
import assert from 'node:assert/strict';
import { pickGameDate, loadLeagueMetadata } from '../../src/lib/gameDate.js';

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

const TRENDS = { pulls: [{ g: '2044-04-01' }, { g: '2044-05-02' }] };

await test('metadata game_date first', () => {
  assert.equal(pickGameDate({ game_date: '2044-05-09' }, TRENDS), '2044-05-09');
  assert.equal(pickGameDate({ game_date: '2044-05-09T00:00:00' }, null), '2044-05-09');
});
await test('falls back to the newest trends pull', () => {
  assert.equal(pickGameDate(null, TRENDS), '2044-05-02');
  assert.equal(pickGameDate({ league: 'TGS', matchups: {} }, TRENDS), '2044-05-02');
  assert.equal(pickGameDate({ game_date: 'soon' }, TRENDS), '2044-05-02');
});
await test('nothing known: null', () => {
  assert.equal(pickGameDate(null, null), null);
  assert.equal(pickGameDate({}, { pulls: [] }), null);
});

const reply = (ok, ctype, body) => async () => ({
  ok, headers: { get: () => ctype }, json: async () => (typeof body === 'function' ? body() : body),
});
await test('loadLeagueMetadata: object, else null', async () => {
  assert.deepEqual(await loadLeagueMetadata('SSB', reply(true, 'application/json', { game_date: '2044-05-09' })),
    { game_date: '2044-05-09' });
  assert.equal(await loadLeagueMetadata('SSB', reply(false, 'text/html', null)), null);
  assert.equal(await loadLeagueMetadata('SSB', reply(true, 'text/html', '<html>')), null);   // dev server index fallback
  assert.equal(await loadLeagueMetadata('SSB', reply(true, 'application/json', [1])), null);
  assert.equal(await loadLeagueMetadata('SSB', reply(true, 'application/json', () => { throw new Error('bad'); })), null);
  assert.equal(await loadLeagueMetadata('SSB', async () => { throw new Error('offline'); }), null);
});

console.log(`\ngameDate: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
