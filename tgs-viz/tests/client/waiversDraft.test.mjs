// Node test for the Waiver Claim merge (src/lib/waivers.js claim clock + 40-man,
// src/lib/waiverSmartRank.js) and the Draft Board marks (src/lib/draftMarks.js).
// Fixture: tests/client/fixtures/players_trim.json (SSB rows, unmodified).
// Run: node tgs-viz/tests/client/waiversDraft.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  waiverClock, evaluateClaim, buildClaimBoard, fortyManSpots,
  CLOCK_CLAIMABLE, CLOCK_CLEARED, CLOCK_DFA,
} from '../../src/lib/waivers.js';
import {
  rawIntangibles, intangiblesGrader, pronePenalty, intangiblesBonus, smartScore, sortBySmart, SMART_RANK_TUNING,
} from '../../src/lib/waiverSmartRank.js';
import {
  MARK_MINE, MARK_TAKEN, marksKey, loadMarks, saveMarks, toggleMark, livePickIndex,
  draftStatus, pickLabel, hiddenAsTaken, summarizeMarks,
} from '../../src/lib/draftMarks.js';

const F = JSON.parse(readFileSync(new URL('./fixtures/players_trim.json', import.meta.url)));
const S = F.SSB;
const close = (a, b, eps = 1e-9) => assert.ok(a != null && Math.abs(a - b) < eps, `${a} != ${b}`);

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// ── waiver clock ────────────────────────────────────────────────────────────
test('claim clock: days left, cleared at 0, DFA has no clock, none', () => {
  assert.deepEqual(waiverClock(S.onWaivers), { state: CLOCK_CLAIMABLE, daysLeft: 1, daysOn: 7 });
  assert.deepEqual(waiverClock(S.clearedWaivers), { state: CLOCK_CLEARED, daysLeft: 0, daysOn: 35 });
  // DFA only: the clock reads 0 because it never started, so it is not "cleared".
  const dfaOnly = { ...S.mlbHitter, DFA: true, OnWaivers: false, WaiverDaysLeft: 0 };
  assert.deepEqual(waiverClock(dfaOnly), { state: CLOCK_DFA, daysLeft: null, daysOn: null });
  assert.equal(waiverClock(S.mlbHitter), null);
});
test('claim clock: a row without the clock reads as claimable', () => {
  const noClock = { ...S.onWaivers };
  delete noClock.WaiverDaysLeft;
  delete noClock.WaiverDays;
  assert.deepEqual(waiverClock(noClock), { state: CLOCK_CLAIMABLE, daysLeft: null, daysOn: null });
  assert.equal(waiverClock({ ...S.mlbHitter, OnWaivers: 'True', WaiverDaysLeft: '3' }).daysLeft, 3);
});
test('evaluateClaim carries the clock', () => {
  const e = evaluateClaim(S.clearedWaivers, 'SSB');
  assert.equal(e.clock, CLOCK_CLEARED);
  assert.equal(e.daysLeft, 0);
  assert.equal(e.daysOn, 35);
});
test('buildClaimBoard splits live from cleared', () => {
  const hitters = [S.onWaivers, S.clearedWaivers, S.mlbHitter, { ...S.ssEligible, ID: 'dfa1', DFA: true, OnWaivers: false }];
  const b = buildClaimBoard(hitters, [S.starter], { league: 'SSB' });
  assert.equal(b.entries.length, 3);
  assert.deepEqual(b.live.map(e => e.name).sort(), [S.onWaivers.Name, S.ssEligible.Name].sort());
  assert.deepEqual(b.cleared.map(e => e.name), [S.clearedWaivers.Name]);
  assert.equal(b.counts.claimable, 1);
  assert.equal(b.counts.cleared, 1);
  assert.equal(b.counts.dfaOnly, 1);
  assert.equal(b.counts.clockKnown, 2);
  // live keeps the board's value order
  const vors = b.live.map(e => e.vor ?? -Infinity);
  assert.deepEqual(vors, [...vors].sort((x, y) => y - x));
});

// ── 40-man ──────────────────────────────────────────────────────────────────
test('40-man occupancy per org; unknown without the flag', () => {
  const org = S.mlbHitter.ORG;
  const { IsOnSecondary: _sp, ...base } = S.mlbHitter;   // export flag only
  const rows = [
    { ...base, ID: 'a', On40Man: true },
    { ...base, ID: 'b', On40Man: 'True' },
    { ...base, ID: 'c', On40Man: false },
    { ...base, ID: 'd', ORG: 'Elsewhere', On40Man: true },
  ];
  assert.deepEqual(fortyManSpots(rows, [], org), { used: 2, open: 38, limit: 40 });
  // StatsPlus's flag wins over a stale export
  const live = [...rows, { ...base, ID: 'e', On40Man: true, IsOnSecondary: false }];
  assert.deepEqual(fortyManSpots(live, [], org), { used: 2, open: 38, limit: 40 });
  const bare = rows.map(({ On40Man, IsOnSecondary, ...r }) => r);
  assert.equal(fortyManSpots(bare, [], org), null);
  const full = Array.from({ length: 41 }, (_, i) => ({ ...base, ID: `x${i}`, On40Man: true }));
  assert.equal(fortyManSpots(full, [], org).open, 0);
});

// ── smart rank ──────────────────────────────────────────────────────────────
test('intangibles raw score: ours weights renormalised over his columns', () => {
  // all N -> 10 whatever the weights
  close(rawIntangibles({ Int: 'N', WrkEthic: 'N', Lead: 'N', Loy: 'N' }), 10);
  // we=H (17, w .35), int=L (4, w .25), lea/loy N (10, w .15/.10): (5.95+1+1.5+1)/.85
  close(rawIntangibles({ Int: 'L', WrkEthic: 'H', Lead: 'N', Loy: 'N' }), (17 * 0.35 + 4 * 0.25 + 10 * 0.15 + 10 * 0.10) / 0.85);
  assert.equal(rawIntangibles({ Name: 'nobody' }), null);
  // Greed is not ours' 'fin' (no mapping) and must not enter.
  close(rawIntangibles({ WrkEthic: 'N', Greed: 'H' }), 10);
});
test('intangibles grader: 50 + 10z, clamped 20-80, null without letters', () => {
  const rows = [
    { Int: 'H', WrkEthic: 'H', Lead: 'H', Loy: 'H' },
    { Int: 'N', WrkEthic: 'N', Lead: 'N', Loy: 'N' },
    { Int: 'L', WrkEthic: 'L', Lead: 'L', Loy: 'L' },
  ];
  const g = intangiblesGrader(rows);
  // raw scores 17 / 10 / 4: mean 31/3, population sd from those three
  const mean = 31 / 3;
  const sd = Math.sqrt(((17 - mean) ** 2 + (10 - mean) ** 2 + (4 - mean) ** 2) / 3);
  assert.equal(g(rows[1]), Math.round(50 + 10 * (10 - mean) / sd));
  assert.equal(g(rows[1]), 49);
  assert.ok(g(rows[0]) > 60 && g(rows[0]) <= 80);
  assert.ok(g(rows[2]) < 40 && g(rows[2]) >= 20);
  assert.equal(g({}), null);
  assert.equal(intangiblesGrader([])(rows[1]), 80); // no population: mean 0, sd 1, so 150 clamps to 80
});
test('prone penalty and intangibles bonus use ours tuning', () => {
  assert.equal(pronePenalty({ Prone: 'Wrecked' }), 2.0);
  assert.equal(pronePenalty({ Prone: 'Iron Man' }), -0.5);
  assert.equal(pronePenalty({ Prone: 'Normal' }), 0);
  assert.equal(pronePenalty({}), 0);
  close(intangiblesBonus(70), 0.30);
  close(intangiblesBonus(40), -0.15);
  assert.equal(intangiblesBonus(null), 0);
});
test('smartScore: adds on vor, RP scaled, toggles off = vor', () => {
  const base = { player: { Prone: 'Fragile' }, vor: 1.0, role: 'hitter' };
  assert.equal(smartScore(base, {}), 1.0);
  close(smartScore(base, { injury: true }), 1.0 - 0.9);
  close(smartScore(base, { intangibles: true }, 70), 1.3);
  close(smartScore({ ...base, role: 'rp' }, { injury: true, intangibles: true }, 70),
    1.0 + SMART_RANK_TUNING.RP_ADJUST_SCALE * (-0.9 + 0.3));
  assert.equal(smartScore({ ...base, vor: null }, { injury: true }), null);
});
test('sortBySmart: best first, null last, input untouched', () => {
  const es = [{ v: 1 }, { v: null }, { v: 3 }];
  const out = sortBySmart(es, e => e.v);
  assert.deepEqual(out.map(e => e.v), [3, 1, null]);
  assert.deepEqual(es.map(e => e.v), [1, null, 3]);
});

// ── draft marks ─────────────────────────────────────────────────────────────
function fakeStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), _m: m };
}
const PICKS = [
  { Overall: 1, Round: 1, Pick: 1, Team: 'Seattle Mariners', ID: '73110', Name: 'Mike Rowan' },
  { Overall: 4, Round: 1, Pick: 4, Team: 'Portland Loggers', ID: '73292', Name: 'Joe Brown' },
  { Overall: 5, Round: 1, Pick: 5, Team: 'Toronto Blue Jays', ID: '', Name: 'no id' },
];

test('marks storage: per-league key, bad values dropped, empty removes', () => {
  assert.equal(marksKey('SSB'), 'tgs-draft-marks-SSB');
  assert.equal(marksKey(''), 'tgs-draft-marks-default');
  const st = fakeStorage({ 'tgs-draft-marks-SSB': JSON.stringify({ 1: 'mine', 2: 'taken', 3: 'bogus' }) });
  assert.deepEqual(loadMarks(st, 'SSB'), { 1: 'mine', 2: 'taken' });
  assert.deepEqual(loadMarks(st, 'BLM'), {});
  assert.deepEqual(loadMarks(fakeStorage({ 'tgs-draft-marks-SSB': '{not json' }), 'SSB'), {});
  assert.deepEqual(loadMarks(fakeStorage({ 'tgs-draft-marks-SSB': '[1,2]' }), 'SSB'), {});
  assert.deepEqual(loadMarks(null, 'SSB'), {});
  saveMarks(st, 'SSB', { 9: 'mine' });
  assert.equal(st.getItem('tgs-draft-marks-SSB'), '{"9":"mine"}');
  saveMarks(st, 'SSB', {});
  assert.equal(st.getItem('tgs-draft-marks-SSB'), null);
  saveMarks(null, 'SSB', { 1: 'mine' }); // blocked storage: no throw
});
test('toggleMark: set, switch, clear, immutable', () => {
  const a = toggleMark({}, 7, MARK_MINE);
  assert.deepEqual(a, { 7: 'mine' });
  const b = toggleMark(a, '7', MARK_TAKEN);
  assert.deepEqual(b, { 7: 'taken' });
  assert.deepEqual(toggleMark(b, 7, MARK_TAKEN), {});
  assert.deepEqual(a, { 7: 'mine' });
  assert.deepEqual(toggleMark(a, 7, 'nope'), {});
});
test('livePickIndex + pickLabel', () => {
  const idx = livePickIndex(PICKS);
  assert.equal(idx.size, 2);
  assert.deepEqual(idx.get('73292'), { overall: 4, round: 1, pick: 4, team: 'Portland Loggers', name: 'Joe Brown' });
  assert.equal(pickLabel(idx.get('73292')), '1.04');
  assert.equal(pickLabel(null), null);
  assert.equal(livePickIndex(null).size, 0);
});
test('draftStatus: live wins over a manual mark; mine by org or mark', () => {
  const idx = livePickIndex(PICKS);
  const marks = { 73292: MARK_TAKEN, 555: MARK_MINE, 556: MARK_TAKEN };
  const live = draftStatus('73292', marks, idx, 'Portland Loggers');
  assert.equal(live.source, 'live');
  assert.equal(live.mine, true);
  assert.equal(live.redundant, true);
  assert.equal(draftStatus(73110, marks, idx, 'Portland Loggers').mine, false);
  assert.equal(draftStatus(73292, {}, idx, null).mine, false); // no org set: never mine
  assert.deepEqual(draftStatus(555, marks, idx, 'Portland Loggers'),
    { source: 'manual', mine: true, taken: true, pick: null, mark: 'mine', redundant: false });
  assert.equal(draftStatus(556, marks, idx).mine, false);
  assert.equal(draftStatus(999, marks, idx), null);
  assert.equal(draftStatus(null, marks, idx), null);
});
test('hiddenAsTaken keeps my own picks', () => {
  const idx = livePickIndex(PICKS);
  assert.equal(hiddenAsTaken(draftStatus(73110, {}, idx, 'Portland Loggers')), true);
  assert.equal(hiddenAsTaken(draftStatus(73292, {}, idx, 'Portland Loggers')), false);
  assert.equal(hiddenAsTaken(draftStatus(1, { 1: MARK_MINE }, idx)), false);
  assert.equal(hiddenAsTaken(draftStatus(1, { 1: MARK_TAKEN }, idx)), true);
  assert.equal(hiddenAsTaken(null), false);
});
test('summarizeMarks counts each player once', () => {
  const idx = livePickIndex(PICKS);
  const marks = { 73292: MARK_MINE, 555: MARK_MINE, 556: MARK_TAKEN };
  assert.deepEqual(summarizeMarks(marks, idx, 'Portland Loggers'),
    { mine: 2, taken: 2, redundant: 1, live: 2, manual: 2 });
  assert.deepEqual(summarizeMarks({}, null, null), { mine: 0, taken: 0, redundant: 0, live: 0, manual: 0 });
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
