// Node test for the pure helpers behind the ported Prospects / Scout / Player
// Compare pages: src/lib/prospectTiers.js, src/lib/scoutFit.js, src/lib/viewFormat.js.
// Run: node tgs-viz/tests/client/views.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FV_TIERS, isProspect, isOrgProspect, isMlbSquad, buildProspectPool, suggestThresholds, assignFVTier,
  tierStats, rankPool, countAtOrAbove, calcFarmRankings, defaultDollarValues, getDollarValue, buildScoutingReport,
} from '../../src/lib/prospectTiers.js';
import {
  rosterPos, eligiblePositions, teamZ, orgNeedFromZ, weakPositions, tradeOpportunities, fitScore, aboveReplacement, FIT_TUNING,
} from '../../src/lib/scoutFit.js';
import {
  fmtAge, fmtSigned, rankSuffix, orgLabel, playerUid, fmtService, calcRawIntangibles, intangibleGrades, fvSourceCounts,
} from '../../src/lib/viewFormat.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const SSB = path.resolve(here, '../../public/data/SSB');

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// A synthetic FV-enriched row (the fields usePlayersWithFV stamps).
let nextId = 1;
const row = (o = {}) => ({
  ID: String(nextId++), Name: `P${nextId}`, ORG: 'A', Lev: 'AA', POS: 'SS', Age: '21', MLBSvcDays: '0',
  'Max WAA wtd': '-1', _potentialWAA: 0, _rawPotentialWAA: 0, _currentWAA: -1, _potentialSource: 'DEV cell',
  _fvBreakdown: { potentialRole: 'hitter', potentialOffsetUsed: 1.9 }, ...o,
});

test('prospect rule: under 45 MLB days, missing counts as none; org excludes AMA / FA / no org', () => {
  assert.equal(isProspect(row({ MLBSvcDays: '44' })), true);
  assert.equal(isProspect(row({ MLBSvcDays: '45' })), false);
  assert.equal(isProspect(row({ MLBSvcDays: undefined })), true);
  assert.equal(isOrgProspect(row({ Lev: 'AMA' })), false);
  assert.equal(isOrgProspect(row({ ORG: '0' })), false);
  assert.equal(isOrgProspect(row({ FA: true })), false);
  assert.equal(isOrgProspect(row()), true);
});

test('pool carries his FV fields under ours\' names; pitcher role from the potential role', () => {
  const [h, p] = buildProspectPool([
    row({ _potentialWAA: 1.5, _rawPotentialWAA: 2.5, _currentWAA: -0.5 }),
    row({ POS: 'RP', 'WAA wtd RP': '0.1', _potentialWAA: 0.4, _fvBreakdown: { potentialRole: 'rp', potentialOffsetUsed: 0.31 } }),
  ]);
  assert.deepEqual([h._fv, h._baseVal, h._currentVal, h._poolType, h._role], [1.5, 2.5, -0.5, 'hitter', null]);
  assert.deepEqual([p._poolType, p._role], ['pitcher', 'rp']);
});

test('suggested cuts descend through the tiers, and tiering by them is ordered', () => {
  const pool = buildProspectPool(Array.from({ length: 2000 }, (_, i) => row({ _potentialWAA: 4 - i * 0.004, _rawPotentialWAA: 5 - i * 0.004 })));
  const th = suggestThresholds(pool, 30);
  const cuts = FV_TIERS.map((t) => th[t.id]);
  assert.ok(cuts.every(Number.isFinite), JSON.stringify(th));
  for (let i = 1; i < cuts.length; i++) assert.ok(cuts[i] <= cuts[i - 1], `tier ${FV_TIERS[i].id} cut ${cuts[i]} above ${cuts[i - 1]}`);
  const ranked = rankPool(pool, th, defaultDollarValues());
  const idx = (p) => FV_TIERS.findIndex((t) => t.id === p._tierId);
  for (let i = 1; i < ranked.length; i++) assert.ok(idx(ranked[i]) >= idx(ranked[i - 1]));
  assert.equal(ranked[0]._overallRank, 1);
  const st = tierStats(pool, th);
  assert.equal(st['35+'].cumulative, ranked.length);
});

test('a pool smaller than the tier populations still gets finite, ordered cuts', () => {
  const pool = buildProspectPool(Array.from({ length: 300 }, (_, i) => row({ _potentialWAA: 3 - i * 0.02 })));
  const cuts = FV_TIERS.map((t) => suggestThresholds(pool, 30)[t.id]);
  assert.ok(cuts.every(Number.isFinite), JSON.stringify(cuts));
});

test('assignFVTier / getDollarValue / countAtOrAbove', () => {
  const th = { 80: 5, 70: 4, 65: 3, 60: 2, 55: 1, 50: 0, '45+': -0.5, 45: -1, '40+': -1.5, 40: -2, '35+': -3 };
  assert.equal(assignFVTier(4.2, th), '70');
  assert.equal(assignFVTier(-3, th), '35+');
  assert.equal(assignFVTier(-3.1, th), null);
  assert.equal(assignFVTier(null, th), null);
  assert.equal(getDollarValue('60', 'pitcher', defaultDollarValues()), 60);
  assert.equal(getDollarValue('60', 'hitter', defaultDollarValues()), 55);
  assert.equal(countAtOrAbove([5, 3, 3, 1], 3), 3);
  assert.equal(countAtOrAbove([5, 3, 3, 1], 6), 0);
  assert.equal(countAtOrAbove([5, 3], null), null);
});

test('farm rankings: value sums, rank order, 20-80 grades, report text', () => {
  const th = { 80: 5, 70: 4, 65: 3, 60: 2, 55: 1, 50: 0, '45+': -0.5, 45: -1, '40+': -1.5, 40: -2, '35+': -3 };
  const pool = buildProspectPool([
    row({ ORG: 'A', _potentialWAA: 2.5 }), row({ ORG: 'A', _potentialWAA: 0.2 }),
    row({ ORG: 'B', _potentialWAA: -1.2 }),
  ]);
  const r = calcFarmRankings(pool, th, defaultDollarValues(), ['A', 'B', 'C']);
  assert.deepEqual(r.map((x) => x.team), ['A', 'B', 'C']);
  assert.equal(r[0].totalValue, 55 + 28);
  assert.equal(r[0].count50Plus, 2);
  assert.ok(r.every((x) => Number.isInteger(x.ceiling) && typeof x.report === 'string'));
  assert.equal(buildScoutingReport(72, 30, 50, 50).startsWith('Average System'), true);
});

test('MLB squad: MLB level and not known off the 40-man', () => {
  assert.equal(isMlbSquad(row({ Lev: 'MLB', On40Man: true })), true);
  assert.equal(isMlbSquad(row({ Lev: 'MLB', On40Man: false })), false);
  assert.equal(isMlbSquad(row({ Lev: 'MLB' })), true);
  assert.equal(isMlbSquad(row({ Lev: 'AAA', On40Man: true })), false);
});

test('scout fit: no toggle = listed potential; bonuses add in wins; replacement test adds the offset', () => {
  const e = { ...row({ Prone: 'Fragile' }), _baseVal: 1, _fv: 2, _role: null, _intangibles: 70 };
  const need = { SS: 1.5 };
  assert.equal(fitScore(e, {}, need), 1);
  assert.equal(fitScore(e, { fv: true }, need), 2);
  assert.ok(Math.abs(fitScore(e, { orgNeed: true }, need) - (1 + FIT_TUNING.ORG_NEED_BONUS_SCALE * 1.5)) < 1e-9);
  assert.ok(Math.abs(fitScore(e, { injury: true }, need) - (1 - 0.9)) < 1e-9);
  assert.ok(Math.abs(fitScore(e, { intangibles: true }, need) - (1 + 2 * FIT_TUNING.INT_BONUS)) < 1e-9);
  const rp = { ...e, POS: 'CL', 'WAA wtd RP': '0', _role: 'rp' };
  assert.ok(Math.abs(fitScore(rp, { injury: true }, need) - (1 - 0.375 * 0.9)) < 1e-9);
  assert.equal(rosterPos(rp), 'RP');
  assert.equal(aboveReplacement(-1.5, 1.9), true);
  assert.equal(aboveReplacement(-2.0, 1.9), false);
  assert.equal(aboveReplacement(0.1, null), true);
  assert.equal(aboveReplacement(null, 1.9), false);
});

test('scout strength helpers read his positionalStrength cells', () => {
  const build = { cells: { A: { C: { z: -1.2, rank: 20 }, SS: { z: 0.4, rank: 8 } }, B: { C: { z: 0.9, rank: 3 } } } };
  const za = teamZ(build, 'A'), zb = teamZ(build, 'B');
  assert.equal(za.C, -1.2);
  assert.equal(za.RP, null);
  assert.deepEqual(orgNeedFromZ(za).C, 1.2);
  assert.equal(orgNeedFromZ(za).SS, 0);
  assert.deepEqual([...weakPositions(za)], ['C']);
  assert.deepEqual(tradeOpportunities(zb, za), ['C']);
  assert.ok(eligiblePositions(row({ 'SS Eligible': true, '2B Eligible': true })).includes('DH'));
});

test('format helpers', () => {
  assert.equal(fmtAge(22), '22');
  assert.equal(fmtAge(22.47), '22.4');
  assert.equal(fmtAge(null), '—');
  assert.equal(fmtSigned(1.234), '+1.23');
  assert.equal(fmtSigned(-0.5), '-0.50');
  assert.equal(rankSuffix(1), '1st');
  assert.equal(rankSuffix(12), '12th');
  assert.equal(rankSuffix(23), '23rd');
  assert.equal(orgLabel(row({ ORG: '0', Lev: 'AMA' })), 'AMA');
  assert.equal(orgLabel(row({ ORG: '0', Lev: 'FA' })), 'FA');
  assert.equal(fmtService(row({ MLBSvcDays: '619', MLBSvcYrs: '3' })), '3 yr · 619 d');
  assert.equal(fmtService(row({ MLBSvcDays: undefined, MLBSvcYrs: undefined })), '—');
  assert.notEqual(playerUid(row({ ID: '9' })), playerUid(row({ ID: '9', 'WAA wtd RP': '0' })));
  assert.deepEqual(fvSourceCounts([row(), row({ _potentialSource: 'ML' })]).map((s) => s.key), ['ML', 'DEV cell']);
});

test('intangibles: weights renormalise without Adaptability; greed is inverted', () => {
  const allH = row({ Int: 'H', WrkEthic: 'H', Lead: 'H', Loy: 'H', Greed: 'L' });
  const allL = row({ Int: 'L', WrkEthic: 'L', Lead: 'L', Loy: 'L', Greed: 'H' });
  assert.equal(calcRawIntangibles(allH), 17);
  assert.equal(calcRawIntangibles(allL), 4);
  assert.equal(calcRawIntangibles(row()), null);
  const g = intangibleGrades([allH, allL, row({ Int: 'N', WrkEthic: 'N', Lead: 'N', Loy: 'N', Greed: 'N' })]);
  assert.ok(g.get(playerUid(allH)) > 50 && g.get(playerUid(allL)) < 50);
});

test("SSB's saved rows: prospect pool size and intangibles coverage", () => {
  const hp = path.join(SSB, 'hitters.json');
  if (!fs.existsSync(hp)) { console.log('skip SSB (missing)'); return; }
  const hitters = JSON.parse(fs.readFileSync(hp, 'utf8'));
  const pitchers = JSON.parse(fs.readFileSync(path.join(SSB, 'pitchers.json'), 'utf8'));
  const all = [...hitters, ...pitchers];
  const pros = all.filter(isOrgProspect);
  console.log(`     SSB: ${pros.length} org prospects of ${all.length} rows`);
  assert.ok(pros.length > 1000 && pros.length < all.length);
  assert.ok(pros.every((p) => p.Lev !== 'AMA' && p.Lev !== 'FA'));
  const g = intangibleGrades(all);
  const graded = [...g.values()].filter((v) => v != null);
  assert.ok(graded.length / all.length > 0.95, `graded ${graded.length} of ${all.length}`);
  const mean = graded.reduce((a, b) => a + b, 0) / graded.length;
  assert.ok(Math.abs(mean - 50) < 1.5, `mean grade ${mean}`);
});

console.log(`\nviews: ${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
