// Node test for src/lib/accessors.js — the adapter that gives ootp-dashboard's
// accessor API over this app's flat records (docs/phase4/bridge.md).
// Fixture: tests/client/fixtures/players_trim.json — whole, unmodified records
// copied from public/data/SSB and public/data/BLM (SSB carries the Phase 1-3
// keys, BLM does not: it is the absent-key case).
// Run: node tgs-viz/tests/client/accessors.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as A from '../../src/lib/accessors.js';

const F = JSON.parse(readFileSync(new URL('./fixtures/players_trim.json', import.meta.url)));
const S = F.SSB, B = F.BLM;
const close = (a, b, eps = 1e-9) => assert.ok(a != null && Math.abs(a - b) < eps, `${a} != ${b}`);

let passed = 0;
let failed = 0;
const covered = new Set();
// `uses` lists the exports a test exercises; the last test checks every export is listed.
function test(name, uses, fn) {
  uses.forEach((u) => covered.add(u));
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

test('num / type detection', ['num', 'isPitcher', 'getPlayerType'], () => {
  assert.equal(A.num('55'), 55);
  assert.equal(A.num('98-100'), 98);
  assert.equal(A.num(''), null);
  assert.equal(A.num('-'), null);
  assert.equal(A.num(NaN), null);
  assert.equal(A.isPitcher(S.starter), true);
  assert.equal(A.isPitcher(S.reliever), true);
  assert.equal(A.isPitcher(B.reliever), true);
  assert.equal(A.isPitcher(S.mlbHitter), false);
  assert.equal(A.getPlayerType(S.mlbHitter), 'hitter');
  assert.equal(A.getPlayerType({ ...S.mlbHitter, _type: 'pitcher' }), 'pitcher');
});

test('position WAA / WAR / RunsP read his {pos} columns', ['getWaa', 'getWaaP', 'getWar', 'getWarP', 'getRunsP'], () => {
  const p = S.mlbHitter;
  close(A.getWar(p, 'RF'), 0.5089187150026442);
  close(A.getWar(p, 'rf'.toUpperCase(), 'wtd'), 0.5089187150026442);
  close(A.getWarP(p, 'RF'), 1.1895220680827538);
  close(A.getWaa(p, 'SS'), -4.403869514211028);
  close(A.getWaa(p, '1B', 'vR'), -2.150493675957811);
  close(A.getWaaP(p, 'C'), -1.7094810408775023);
  close(A.getRunsP(p, 'LF'), -4.688492104376742);
  assert.equal(A.getRunsP(p, 'DH'), null);
  // BLM: WAA present, WAR absent -> null, never WAA + an offset.
  close(A.getWaa(B.mlbHitter, '3B'), 1.768827047965872);
  assert.equal(A.getWar(B.mlbHitter, '3B'), null);
  assert.equal(A.getWarP(B.mlbHitter, '3B'), null);
});

test('isEligible: his boolean, DH for every hitter, SP/RP false', ['isEligible', 'INF_POSITIONS', 'OF_POSITIONS'], () => {
  const p = S.mlbHitter;
  assert.equal(A.isEligible(p, 'LF'), true);
  assert.equal(A.isEligible(p, 'lf'), true);
  assert.equal(A.isEligible(p, 'SS'), false);
  assert.equal(A.isEligible(p, 'DH'), true);
  assert.equal(A.isEligible(S.starter, 'DH'), false);
  assert.equal(A.isEligible(S.starter, 'SP'), false);
  assert.equal(A.isEligible({ 'SS Eligible': 'True' }, 'SS'), true);
  assert.equal(A.isEligible(null, 'SS'), false);
  assert.deepEqual(A.INF_POSITIONS, ['1B', '2B', '3B', 'SS']);
  assert.deepEqual(A.OF_POSITIONS, ['LF', 'CF', 'RF']);
});

test('pickFielderPos: best eligible WAR, FV through the ported v21 curve', ['pickFielderPos'], () => {
  const p = S.ssEligible; // 2B 1.4955 > SS 0.0743 > 3B > 1B
  const r = A.pickFielderPos(p, 'INF');
  close(r.war, 1.495498430841877);
  close(r.warP, 1.7203823984319433);
  close(r.fv, r.war);
  assert.equal(A.pickFielderPos(p, 'OF'), null);              // not OF-eligible
  assert.equal(A.pickFielderPos(p, 'Hitters'), null);
  assert.equal(A.pickFielderPos(p, null), null);
  close(A.pickFielderPos(p, ['SS']).war, 0.07426163308673384);
  // age 31 >= maxCurrentAge 27 -> FV = cur
  close(A.pickFielderPos(p, 'INF', null, { gapMax: 0.8, gapExp: 3, maxCurrentAge: 27 }).fv, 1.495498430841877);
  // young player: FV between cur and pot
  const young = { ...p, _age: 20 };
  const y = A.pickFielderPos(young, 'INF', null, {});
  assert.ok(y.fv > y.war && y.fv < y.warP);
  // BLM: eligible but no WAR columns -> nulls, not WAA
  const b = A.pickFielderPos(B.mlbHitter, ['3B']);
  assert.deepEqual(b, { war: null, warP: null, fv: null });
});

test('levels: categories, INT from IntlComplex, FA/AMA are not levels', ['STANDARD_LEVELS', 'LEVEL_CATEGORY_ORDER', 'categorizeLevel', 'getLevel'], () => {
  assert.equal(A.categorizeLevel('AAA'), 'AAA');
  assert.equal(A.categorizeLevel('R+'), 'Rookie');
  assert.equal(A.categorizeLevel('R-'), 'Rookie');
  assert.equal(A.categorizeLevel('WL'), 'Rookie');
  assert.equal(A.categorizeLevel('INT'), 'INT');
  assert.equal(A.categorizeLevel('FA'), null);
  assert.equal(A.categorizeLevel('AMA'), null);
  assert.equal(A.categorizeLevel(''), null);
  assert.equal(A.getLevel(S.intlComplex), 'INT');               // Lev 'R-' + IntlComplex true
  assert.equal(A.getLevel(S.mlbHitter), 'MLB');
  assert.equal(A.getLevel(B.aMinus), 'A-');                     // BLM: no IntlComplex key
  assert.equal(A.getLevel({}), null);
  assert.ok(A.STANDARD_LEVELS.includes('A-'));
  assert.equal(A.LEVEL_CATEGORY_ORDER.at(-1), 'INT');
});

test('passesLevelFilter: category, team:<id>, tm: never matches', ['passesLevelFilter', 'getTeamId'], () => {
  assert.equal(A.passesLevelFilter(S.ssEligible, 'AAA'), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, 'ALL'), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, null), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, []), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, ['MLB', 'AAA']), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, ['MLB']), false);
  assert.equal(A.passesLevelFilter(S.ssEligible, ['team:162']), true);
  assert.equal(A.passesLevelFilter(S.ssEligible, ['tm:POR']), false);
  assert.equal(A.passesLevelFilter(S.intlComplex, ['INT']), true);
  assert.equal(A.passesLevelFilter(S.faHitter, ['Rookie']), false);
  assert.equal(A.getTeamId(S.ssEligible), '162');
  assert.equal(A.getTeamId(S.amateur), null);                   // Team '0'
});

test('passesPositionFilter: hitters, pitchers, SP/RP by Starter flag, INF/OF', ['passesPositionFilter'], () => {
  assert.equal(A.passesPositionFilter(S.starter, 'SP'), true);
  assert.equal(A.passesPositionFilter(S.reliever, 'RP'), true);
  assert.equal(A.passesPositionFilter(S.reliever, 'SP'), false);
  // BLM starter: no WAR columns, but the Starter flag still classes him SP
  assert.equal(A.passesPositionFilter(B.starter, 'SP'), true);
  assert.equal(A.passesPositionFilter(S.mlbHitter, 'OF'), true);
  assert.equal(A.passesPositionFilter(S.mlbHitter, 'INF'), true);   // 1B-eligible
  assert.equal(A.passesPositionFilter(S.mlbHitter, ['SS', 'CF']), false);
  assert.equal(A.passesPositionFilter(S.mlbHitter, 'Pitchers'), false);
  assert.equal(A.passesPositionFilter(S.starter, 'Hitters'), false);
  assert.equal(A.passesPositionFilter(S.starter, 'ALL'), true);
  assert.equal(A.passesPositionFilter(S.starter, []), true);
});

test('position ratings: bare column / Pot{pos}, 0 -> null; currently-eligible status', ['POS_RATING_MIN', 'POS_RATING_PCT', 'getPosRating', 'getPosPotential', 'isCurrentlyEligible', 'eligibilityStatus'], () => {
  const p = S.mlbHitter;
  assert.equal(A.getPosRating(p, 'LF'), 55);
  assert.equal(A.getPosPotential(p, 'lf'), 60);
  assert.equal(A.getPosRating(p, 'SS'), null);                   // '0'
  assert.equal(A.getPosRating(p, 'DH'), null);
  assert.equal(A.isCurrentlyEligible(p, 'LF'), true);            // 55 >= 50
  assert.equal(A.isCurrentlyEligible(p, 'RF'), true);            // 50 >= 50
  assert.equal(A.eligibilityStatus(p, 'LF'), 'current');
  assert.equal(A.eligibilityStatus(p, 'SS'), 'none');
  // 1B-eligible with no 1B rating ('0'): potential-only, as ours treats a missing rating
  assert.equal(A.getPosRating(p, '1B'), 40);
  assert.equal(A.eligibilityStatus(p, '1B'), 'current');        // 40 >= .75 * 45
  assert.equal(A.eligibilityStatus({ '1B Eligible': true, '1B': '30', Pot1B: '60' }, '1B'), 'potential');
  assert.equal(A.eligibilityStatus({ '1B Eligible': true, '1B': '0', Pot1B: '0' }, '1B'), 'potential');
  assert.equal(A.eligibilityStatus(p, 'DH'), 'current');         // non-field position
  assert.equal(A.POS_RATING_MIN, 50);
  assert.equal(A.POS_RATING_PCT, 0.75);
});

test('max / batting / baserunning values', ['getMaxWaa', 'getMaxWaaP', 'getMaxWar', 'getMaxWarP', 'getBatR', 'getBsr'], () => {
  const p = S.mlbHitter;
  close(A.getMaxWar(p), 0.5089187150026442);
  close(A.getMaxWar(p, 'vL'), -0.8240786064594479);
  close(A.getMaxWarP(p), 1.1895220680827538);
  close(A.getMaxWaa(p), -1.4010812849973557);
  close(A.getMaxWaaP(p), -0.7204779319172461);
  close(A.getBatR(p), -7.584385500543734);
  close(A.getBsr(p, 'vR'), -2.5214184987038846);
  assert.equal(A.getMaxWar(B.mlbHitter), null);
  assert.equal(A.getMaxWarP(B.mlbHitter), null);
  close(A.getMaxWaa(B.mlbHitter), 1.768827047965872);
  assert.equal(A.getMaxWar(S.starter), null);                    // pitcher row
});

test('pitcher SP/RP values gated on Starter; BLM WAR absent -> null', ['isStarter', 'isStarterP', 'getSpWaa', 'getRpWaa', 'getSpWaaP', 'getRpWaaP', 'getSpWar', 'getRpWar', 'getSpWarP', 'getRpWarP'], () => {
  const sp = S.starter, rp = S.reliever;
  assert.equal(A.isStarter(sp), true);
  assert.equal(A.isStarterP(sp), true);
  assert.equal(A.isStarter(rp), false);
  close(A.getSpWar(sp), 3.6907058949890725);
  close(A.getSpWar(sp, 'vR'), 4.102959433042962);
  close(A.getSpWarP(sp), 4.2691084668996915);
  close(A.getRpWar(sp), 0.9579854875231679);
  close(A.getRpWarP(sp), 1.1061087885197478);
  close(A.getSpWaa(sp), 1.1907058949890723);
  close(A.getSpWaaP(sp), 1.7691084668996917);
  close(A.getRpWaaP(sp), 0.7961087885197478);
  close(A.getRpWaa(rp), 0.30882066266534464);
  assert.equal(A.getSpWar(rp), null);
  assert.equal(A.getSpWaaP(rp), null);
  close(A.getRpWarP(rp), 0.6697659095122221);
  assert.equal(A.getSpWar(B.starter), null);
  assert.equal(A.getSpWarP(B.starter), null);
  assert.equal(A.getRpWar(B.starter), null);
  close(A.getSpWaa(B.starter), -0.06051773949716676);
  assert.equal(A.getSpWar(S.mlbHitter), null);
});

test('floor accessors: no floor projection in his data', ['getFloorWaa', 'getSpFloor', 'getRpFloor', 'getFloorWar', 'getSpFloorWar', 'getRpFloorWar'], () => {
  for (const f of ['getFloorWaa', 'getSpFloor', 'getRpFloor', 'getFloorWar', 'getSpFloorWar', 'getRpFloorWar']) {
    assert.equal(A[f](S.starter), null, f);
    assert.equal(A[f](S.mlbHitter, 'wtd'), null, f);
  }
});

test('injury: OnDL / OnDL60 only', ['isInjured', 'isOnIL', 'isOnIL60', 'getInjuryDaysLeft', 'isInjuredNotOnIL'], () => {
  assert.equal(A.isInjured(S.onDL), true);
  assert.equal(A.isOnIL(S.onDL), true);
  assert.equal(A.isOnIL60(S.onDL), false);
  assert.equal(A.isInjured(S.mlbHitter), false);
  assert.equal(A.isInjured({ OnDL60: 'Yes' }), true);
  assert.equal(A.isInjured({}), false);
  assert.equal(A.getInjuryDaysLeft(S.onDL), 0);
  assert.equal(A.getInjuryDaysLeft({}), null);
  assert.equal(A.isInjuredNotOnIL(S.onDL), null);
});

test('resolveKey: ours column keys -> his values', ['resolveKey'], () => {
  const h = S.mlbHitter, sp = S.starter;
  close(A.resolveKey(h, 'Max WAR wtd'), 0.5089187150026442);
  close(A.resolveKey(h, 'Max WAR vR'), 0.9259218579851429);
  close(A.resolveKey(h, 'Max WAA wtd'), -1.4010812849973557);
  close(A.resolveKey(h, 'Max WAA vL'), -2.734078606459448);
  close(A.resolveKey(h, 'MAX WAR P'), 1.1895220680827538);
  close(A.resolveKey(h, 'MAX WAA P'), -0.7204779319172461);
  close(A.resolveKey(sp, 'WAR wtd'), 3.6907058949890725);
  close(A.resolveKey(sp, 'WAR wtd RP'), 0.9579854875231679);
  close(A.resolveKey(sp, 'WARP'), 4.2691084668996915);
  close(A.resolveKey(sp, 'WARP RP'), 1.1061087885197478);
  close(A.resolveKey(sp, 'WAA wtd'), 1.1907058949890723);
  close(A.resolveKey(sp, 'WAA wtd RP'), 0.6479854875231679);
  close(A.resolveKey(sp, 'WAP'), 1.7691084668996917);
  close(A.resolveKey(sp, 'WAP RP'), 0.7961087885197478);
  close(A.resolveKey(h, 'OBP vR'), 0.2884618711605935);
  close(A.resolveKey(h, 'wOBA vL'), 0.26352920099646276);
  assert.equal(A.resolveKey(sp, 'wOBA vR'), null);              // pitcher wOBA-against is not batting
  assert.equal(A.resolveKey(h, 'Name'), 'Maximino Spuri');
  assert.equal(A.resolveKey(h, 'POS'), 'LF');
  assert.equal(A.resolveKey(h, 'ORG'), 'Cincinnati Reds');
  assert.equal(A.resolveKey(S.faHitter, 'ORG'), '-');
  assert.equal(A.resolveKey(S.intlComplex, 'Lev'), 'INT');
  assert.equal(A.resolveKey(h, 'Prone'), 'Normal');
  assert.equal(A.resolveKey(h, 'Price'), 570500);
  assert.equal(A.resolveKey(S.faHitter, 'Price'), null);
  assert.equal(A.resolveKey(h, 'PROY'), 8);
  assert.equal(A.resolveKey(B.mlbHitter, 'PROY'), null);
  assert.equal(A.resolveKey(h, 'B'), 'L');
  assert.equal(A.resolveKey(h, 'Age'), 25);
  assert.equal(A.resolveKey({ ...h, _age: 25.4 }, 'Age'), 25.4);
  assert.equal(A.resolveKey(h, 'INT'), 'L');
  assert.equal(A.resolveKey(h, 'WE'), 'N');
  assert.equal(A.resolveKey(h, 'LEA'), 'N');
  assert.equal(A.resolveKey(h, 'AD'), null);
  assert.equal(A.resolveKey(h, '_intangibles'), null);
  assert.equal(A.resolveKey(sp, 'STM'), 50);
  assert.equal(A.resolveKey(sp, 'VELO'), '98-100');
  assert.equal(A.resolveKey(sp, 'Starter'), true);
  assert.equal(A.resolveKey(sp, 'Starter P'), true);
  assert.equal(A.resolveKey(h, 'Starter'), null);
  assert.equal(A.resolveKey(sp, 'MLD'), 574);
  assert.equal(A.resolveKey(S.ssEligible, 'OY'), 0);
  assert.equal(A.resolveKey(B.mlbHitter, 'OY'), null);
  assert.equal(A.resolveKey(h, 'OVR'), 40);
  assert.equal(A.resolveKey(h, 'POT'), 45);
  assert.equal(A.resolveKey(h, 'BatR wtd'), h['BatR wtd']);      // default: his column
  assert.equal(A.resolveKey(null, 'Name'), undefined);
});

test('genericSort: numbers, strings, nulls last, position order, override', ['genericSort', 'POS_SORT_ORDER', 'SORT_KEY_OVERRIDE'], () => {
  const rows = [S.mlbHitter, B.mlbHitter, S.ssEligible, S.faHitter];
  const a = [...rows]; A.genericSort(a, 'Max WAR wtd', 'desc');
  assert.deepEqual(a.map((p) => p.ID), [S.ssEligible.ID, S.mlbHitter.ID, S.faHitter.ID, B.mlbHitter.ID]); // BLM null last
  const b = [...rows]; A.genericSort(b, 'Name', 'asc');
  assert.equal(b[0].Name, 'Gus Garcia');
  const c = [S.starter, S.mlbHitter, S.ssEligible]; A.genericSort(c, '_bestPos', 'asc');
  assert.deepEqual(c.map(A.getBestPos), ['2B', 'RF', 'SP']);
  const d = [{ ...S.reliever, _warSort: 9 }, { ...S.starter, _warSort: 1 }]; A.genericSort(d, 'war', 'desc');
  assert.equal(d[0].ID, S.reliever.ID);
  const e = [S.mlbHitter, S.ssEligible]; A.genericSort(e, 'x', 'asc', { x: (p) => -A.getAge(p) });
  assert.equal(e[0].ID, S.ssEligible.ID);
  assert.equal(A.POS_SORT_ORDER.SS, 4);
  assert.equal(A.SORT_KEY_OVERRIDE.war, '_warSort');
});

test('RP scalers and pickPitcherRole', ['scaleRpWaaP', 'scaleRpWarP', 'pickPitcherRole', 'getBestPitcherWar', 'getBestPitcherWarP', 'getBestPitcherFv'], () => {
  assert.equal(A.scaleRpWaaP(null), null);
  assert.equal(A.scaleRpWaaP(0.4), 0.4);
  close(A.scaleRpWaaP(-1), -1 * (185.47 / 69.55));
  assert.equal(A.scaleRpWarP(-3), -3);
  const sp = A.pickPitcherRole(S.starter);
  assert.equal(sp.role, 'sp');
  close(sp.war, 3.6907058949890725);
  close(sp.warPSort, 4.2691084668996915);
  assert.equal(sp.floorSort, null);
  assert.equal(sp.devPct, null);
  const rp = A.pickPitcherRole(S.reliever);
  assert.equal(rp.role, 'rp');
  close(rp.war, 0.6188206626653446);
  assert.equal(A.pickPitcherRole(S.starter, null, null, 'rp').role, 'rp');
  assert.equal(A.pickPitcherRole(S.reliever, null, null, 'sp').role, 'rp');
  const curve = [{ age: 20, p10: 0, p25: 1, p50: 2, p75: 3, p90: 4, p95: 5, p99: 6 }];
  const withCurve = A.pickPitcherRole(S.starter, { sp: curve, rp: curve }, {});
  close(withCurve.devPct, 0.75 + (3.6907058949890725 - 3) * 0.15);   // between p75=3 and p90=4
  const t = (25 - 14) / (27 - 14), credit = 0.8 * (1 - t ** 3);   // v21 defaults, age 25
  close(withCurve.fv, 3.6907058949890725 + (4.2691084668996915 - 3.6907058949890725) * credit);
  assert.ok(withCurve.fv >= sp.war);
  const blm = A.pickPitcherRole(B.starter);
  assert.equal(blm.war, null);
  assert.equal(blm.role, 'rp');
  close(A.getBestPitcherWar(S.starter), 3.6907058949890725);
  close(A.getBestPitcherWarP(S.reliever), 0.6697659095122221);
  assert.ok(A.getBestPitcherFv(S.starter, null, { maxCurrentAge: 27 }) > 3.69);
});

test('blendPlatoon', ['blendPlatoon'], () => {
  close(A.blendPlatoon(1, 0, 'R', null, 'hit'), 0.62);
  close(A.blendPlatoon(1, 0, 'L', { hit: { L: { vR: 0.7, vL: 0.3 } } }, 'hit'), 0.7);
  assert.equal(A.blendPlatoon(null, 2, 'R'), 2);
  assert.equal(A.blendPlatoon(null, null, 'R'), null);
});

test('identity / org / FA / amateur', ['getId', 'getName', 'getPos', 'getOrg', 'getOrgId', 'getTeamAbbr', 'isFreeAgent', 'isAmateur'], () => {
  assert.equal(A.getId(S.mlbHitter), '43954');
  assert.equal(A.getName(B.starter), 'Daniel Jimenez');
  assert.equal(A.getPos(S.reliever), 'RP');
  assert.equal(A.getOrg(S.amateur), '-');
  assert.equal(A.getOrgId(S.mlbHitter), '37');
  assert.equal(A.getOrgId(S.amateur), null);
  assert.equal(A.getTeamAbbr(S.mlbHitter), null);
  assert.equal(A.isFreeAgent(S.faHitter), true);
  assert.equal(A.isFreeAgent(S.amateur), false);
  assert.equal(A.isFreeAgent({ ORG: '0', Lev: 'FA' }), true);    // pre-stamp row
  assert.equal(A.isAmateur(S.amateur), true);
  assert.equal(A.isAmateur(S.faHitter), false);
});

test('bio and personality', ['getAge', 'getDob', 'getBats', 'getThrows', 'getHeightCm', 'getWeight', 'getProne', 'getIntangible', 'getOvr', 'getPot', 'getScoutAccuracy'], () => {
  const p = S.mlbHitter;
  assert.equal(A.getAge(p), 25);
  assert.equal(A.getAge(S.amateur), 17);
  assert.equal(A.getDob(p), null);
  assert.equal(A.getBats(p), 'L');
  assert.equal(A.getThrows(p), 'L');
  assert.equal(A.getHeightCm(p), 192);
  assert.equal(A.getWeight(p), null);
  assert.equal(A.getProne(p), 'Normal');
  assert.equal(A.getIntangible(p, 'int'), 'L');
  assert.equal(A.getIntangible(p, 'WE'), 'N');
  assert.equal(A.getIntangible(p, 'loy'), 'L');
  assert.equal(A.getIntangible(p, 'ad'), null);
  assert.equal(A.getIntangible(p, 'fin'), null);
  assert.equal(A.getOvr(p), 40);
  assert.equal(A.getPot(p), 45);
  assert.equal(A.getScoutAccuracy(p), 'VH');
});

test('ratings, pitch grades, velocity', ['getRating', 'getPitchGrade', 'PITCH_KEYS', 'getPitchCount', 'getVelo', 'getVeloPotential'], () => {
  const h = S.mlbHitter, sp = S.starter;
  assert.equal(A.getRating(h, 'con', 'vR'), 40);                 // Cntct_R, NOT 'CON vR' (pitcher control)
  assert.equal(A.getRating(h, 'con', 'potential'), 45);
  assert.equal(A.getRating(h, 'ht', 'potential'), 55);
  assert.equal(A.getRating(h, 'ba', 'vR'), 50);
  assert.equal(A.getRating(h, 'spe'), 55);
  assert.equal(A.getRating(h, 'bun'), 45);
  assert.equal(A.getRating(h, 'ofArm'), 60);
  assert.equal(A.getRating(h, 'spe', 'potential'), null);        // no potential speed column
  assert.equal(A.getRating(sp, 'stm'), 50);
  assert.equal(A.getRating(sp, 'hld'), 80);
  assert.equal(A.getRating(sp, 'mov', 'vR'), 50);
  assert.equal(A.getRating(sp, 'mov', 'potential'), 55);
  assert.equal(A.getRating(sp, 'pcon', 'vR'), 55);
  assert.equal(A.getRating(sp, 'nope'), null);
  assert.equal(A.getPitchGrade(sp, 'fb'), 70);
  assert.equal(A.getPitchGrade(sp, 'FB', true), 70);
  assert.equal(A.getPitchGrade(sp, 'cb'), null);                 // '0' = not thrown
  assert.equal(A.getPitchGrade(sp, 'cu'), null);                 // not a key
  assert.equal(A.PITCH_KEYS.length, 12);
  assert.equal(A.getPitchCount(sp), 3);
  assert.equal(A.getVelo(sp), '98-100');
  assert.equal(A.getVeloPotential(sp), '98-100');
});

test('getBestPos: stamped, his Best Pos WAR, ours pitcher rule, BLM fallbacks', ['getBestPos'], () => {
  assert.equal(A.getBestPos(S.mlbHitter), 'RF');
  assert.equal(A.getBestPos({ ...S.mlbHitter, _bestPos: 'LF' }), 'LF');
  assert.equal(A.getBestPos(B.mlbHitter), '3B');                  // 'Best Pos' (no WAR key)
  assert.equal(A.getBestPos(S.starter), 'SP');                    // WARP 4.27 vs RP 1.11
  assert.equal(A.getBestPos(S.reliever), 'RP');                   // not a starter
  assert.equal(A.getBestPos(B.starter), 'SP');                    // no WAR -> listed POS
  assert.equal(A.getBestPos(null), null);
});

test('roster status: SSB export keys, StatsPlus fallback, BLM unknown', ['isOn40Man', 'isActiveRoster', 'isRule5Eligible', 'getYearsProtectedFromRule5', 'getOptionsUsed', 'getOptionYearUsed', 'getOptionsRemaining', 'isRookie', 'isIntlComplex', 'getYearsLeftStatus', 'getRosterExportDate', 'getRosterExportGapDays'], () => {
  const p = S.ssEligible;
  assert.equal(A.isOn40Man(S.mlbHitter), true);
  assert.equal(A.isOn40Man(p), false);
  assert.equal(A.isOn40Man({ IsOnSecondary: true }), true);       // fallback
  assert.equal(A.isOn40Man(B.mlbHitter), null);                   // unknown, not false
  assert.equal(A.isActiveRoster(S.starter), true);
  assert.equal(A.isActiveRoster({ IsActive: false }), false);
  assert.equal(A.isActiveRoster(B.starter), null);
  assert.equal(A.isRule5Eligible(p), true);
  assert.equal(A.isRule5Eligible(B.mlbHitter), null);
  assert.equal(A.getYearsProtectedFromRule5(p), 5);
  assert.equal(A.getOptionsUsed(p), 3);
  assert.equal(A.getOptionYearUsed(p), 0);
  assert.equal(A.getOptionsUsed(B.mlbHitter), null);
  assert.equal(A.getOptionsRemaining(p), null);
  assert.equal(A.isRookie(p), false);
  assert.equal(A.isIntlComplex(S.intlComplex), true);
  assert.equal(A.isIntlComplex(B.aMinus), null);
  assert.equal(A.getYearsLeftStatus(p), '1 (auto.)');
  assert.equal(A.getYearsLeftStatus(B.mlbHitter), null);
  assert.equal(A.getRosterExportDate(p), '2043-12-28');
  assert.equal(A.getRosterExportGapDays(p), 133);
});

test('waivers', ['isOnWaivers', 'isDFA', 'getWaiverDaysLeft', 'getWaiverDays'], () => {
  assert.equal(A.isOnWaivers(S.onWaivers), true);
  assert.equal(A.isDFA(S.onWaivers), true);
  assert.equal(A.getWaiverDaysLeft(S.onWaivers), 1);
  assert.equal(A.getWaiverDays(S.onWaivers), 7);
  assert.equal(A.getWaiverDaysLeft(S.clearedWaivers), 0);
  assert.equal(A.isOnWaivers(S.mlbHitter), false);
  assert.equal(A.getWaiverDaysLeft(B.mlbHitter), null);
});

test('service time', ['getMlbServiceDays', 'getMlbServiceYears', 'getMlbServiceDaysThisYear', 'getProServiceYears', 'getProServiceDays', 'getSecServiceYears', 'getSecServiceDays', 'getDraftYear'], () => {
  const sp = S.starter;
  assert.equal(A.getMlbServiceDays(sp), 574);
  assert.equal(A.getMlbServiceYears(sp), 3);
  assert.equal(A.getMlbServiceDaysThisYear(sp), 35);
  assert.equal(A.getProServiceYears(sp), 8);
  assert.equal(A.getProServiceDays(sp), 1508);
  assert.equal(A.getSecServiceYears(sp), 3);
  assert.equal(A.getSecServiceDays(sp), 574);
  assert.equal(A.getMlbServiceDays(B.mlbHitter), 1443);
  assert.equal(A.getProServiceYears(B.mlbHitter), null);
  assert.equal(A.getDraftYear(sp), null);
});

test('money: price, demand, sign, FA type, no-trade', ['getPrice', 'getSalary', 'getContractValue', 'getDemand', 'getDemandValue', 'getSignDifficulty', 'getFaType', 'hasNoTrade'], () => {
  assert.equal(A.getPrice(S.starter), 3360000);
  assert.equal(A.getSalary(S.starter), 3360000);
  assert.equal(A.getContractValue(S.starter), 3360000);
  assert.equal(A.getPrice(S.faHitter), null);                     // no league-minimum floor
  assert.equal(A.getPrice(B.mlbHitter), 30000000);
  assert.equal(A.getDemand(S.demand), '$5.0m');
  assert.equal(A.getDemandValue(S.demand), 5000000);
  assert.equal(A.getDemandValue({ ContractDemand: '$860k' }), 860000);
  assert.equal(A.getDemandValue({ ContractDemand: 'n/a' }), null);
  assert.equal(A.getDemand(S.mlbHitter), null);
  assert.equal(A.getSignDifficulty(S.demand), 'Easy');
  assert.equal(A.getFaType(S.mlbHitter), null);
  assert.equal(A.getFaType({ FAType: 'B' }), 'B');
  assert.equal(A.hasNoTrade(S.starter), false);
  assert.equal(A.hasNoTrade({}), null);
});

test('contract: schedule, per-year resolution with options and extension', ['getSalarySchedule', 'getContractYearsRemaining', 'getExtension', 'getContractYear'], () => {
  const oc = S.optionsContract, ex = S.extension;
  assert.deepEqual(A.getSalarySchedule(oc), { startYear: 2044, salaries: [40000000, 40000000] });
  assert.equal(A.getContractYearsRemaining(oc), 2);
  assert.deepEqual(A.getContractYear(oc, 2044), { salary: 40000000, optionType: null, buyout: 0 });
  assert.deepEqual(A.getContractYear(oc, 2045), { salary: 40000000, optionType: 'vesting', buyout: 0 });
  assert.equal(A.getContractYear(oc, 2046), null);
  assert.equal(A.getExtension(oc), null);
  assert.deepEqual(A.getExtension(ex), { startYear: 2045, years: 7, salaries: [4000000, 8000000, 10000000, 12000000, 15000000, 15000000, 15000000] });
  assert.deepEqual(A.getContractYear(ex, 2044), { salary: 5300000, optionType: null, buyout: 0 });
  assert.deepEqual(A.getContractYear(ex, 2046), { salary: 8000000, optionType: null, buyout: 0 });
  assert.deepEqual(A.getContractYear(ex, 2050), { salary: 15000000, optionType: 'player', buyout: 1560000 });
  assert.deepEqual(A.getContractYear(ex, 2051), { salary: 15000000, optionType: 'player', buyout: 0 });
  assert.equal(A.getContractYear(ex, 2052), null);
  assert.equal(A.getExtension({ ContractExt: { yr: 0, years: 1, salaries: [0] } }), null);  // placeholder
  // BLM: schedule but no start year -> schedule only, no calendar resolution
  assert.deepEqual(A.getSalarySchedule(B.mlbHitter), { startYear: null, salaries: [30000000, 30000000, 30000000] });
  assert.equal(A.getContractYear(B.mlbHitter, 2044), null);
  assert.equal(A.getSalarySchedule(S.faHitter), null);
  assert.equal(A.getContractYearsRemaining(S.faHitter), null);
  assert.equal(A.getContractYear(oc, 'x'), null);
});

test('salary report, arbitration projection, opt-outs', ['getSalaryReportCell', 'getSalaryReportSpan', 'getArbProjection', 'getOptOutYears'], () => {
  const p = S.mlbHitter;
  assert.deepEqual(A.getSalaryReportCell(p, 2046), { salary: 1800000, type: 'arb_uncertain', guaranteed: false, ann: 'A*' });
  assert.equal(A.getSalaryReportCell(p, 2060), null);
  assert.deepEqual(A.getSalaryReportSpan(p), [2044, 2053]);
  assert.equal(A.getArbProjection(p).yr, 2046);
  assert.equal(A.getArbProjection(S.optionsContract), null);
  assert.deepEqual(A.getOptOutYears(S.optOut), [2044]);
  assert.equal(A.getOptOutYears(p), null);
  assert.equal(A.getSalaryReportCell(B.mlbHitter, 2044), null);
});

test('always-null fields his data lacks', ['getSourceTag', 'isTwoWay'], () => {
  assert.equal(A.getSourceTag(S.amateur), null);
  assert.equal(A.isTwoWay(S.starter), null);
});

test('projected stat lines', ['getBattingStat', 'getBaserunningStat', 'getPitchingStat'], () => {
  const h = S.mlbHitter, sp = S.starter;
  close(A.getBattingStat(h, 'obp', 'vR'), 0.2884618711605935);
  close(A.getBattingStat(h, 'so', 'vR'), 194.28564269579863);
  close(A.getBattingStat(h, 'woba', 'P'), 0.30593743057040385);
  assert.equal(A.getBattingStat(h, 'nope'), null);
  assert.equal(A.getBattingStat(sp, 'woba', 'vR'), null);
  close(A.getBaserunningStat(h, 'sbPct'), 0.5856437772138737);
  close(A.getBaserunningStat(h, 'wsb'), -0.7967884850163771);
  close(A.getBaserunningStat(h, 'ubr', 'vL'), -1.6192363288907745);
  assert.equal(A.getBaserunningStat(h, 'bsr', 'P'), null);
  close(A.getPitchingStat(sp, 'sp', 'ra9', 'wtd'), 3.7142400912699918);
  close(A.getPitchingStat(sp, 'rp', 'ra9', 'wtd'), 3.5188500102139164);
  close(A.getPitchingStat(sp, 'sp', 'so', 'P'), 205.08471418123463);
  close(A.getPitchingStat(sp, 'sp', 'singles', 'vR'), 111.64838714715344);
  assert.equal(A.getPitchingStat(sp, 'sp', 'so', 'wtd'), null);     // no wtd counting stats
  close(A.getPitchingStat(sp, 'sp', 'war', 'P'), 4.2691084668996915);
  close(A.getPitchingStat(sp, 'rp', 'waa', 'wtd'), 0.6479854875231679);
  assert.equal(A.getPitchingStat(S.reliever, 'sp', 'woba', 'vR'), null);
  assert.equal(A.getPitchingStat(h, 'sp', 'woba', 'vR'), null);
});

test('every export is exercised by a test above', [], () => {
  const missing = Object.keys(A).filter((k) => !covered.has(k));
  assert.deepEqual(missing, []);
});

console.log(`\naccessors: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
