// Node test for src/lib/rosterPlanning/* — the Roster Planner port
// (docs/phase4/roster_planner.md). Synthetic flat records in his field names,
// plus a smoke run on public/data/SSB when that file is present.
// Run: node tgs-viz/tests/client/rosterPlanning.test.mjs
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { enrichForPlanner } from '../../src/lib/rosterPlanning/enrich.js';
import { detectGameYear, detectContractYear, projectYearStatus, fromReportCell, fmtSalary } from '../../src/lib/rosterPlanning/status.js';
import { rosterState, r5Info, optionsInfo, filterR5Protect } from '../../src/lib/rosterPlanning/eligibility.js';
import { buildRosterProjection, bucketOf } from '../../src/lib/rosterPlanning/projection.js';
import { buildDepthChart, classifyPitchers } from '../../src/lib/rosterPlanning/depth.js';
import { analyzeCrunch, suggestActions } from '../../src/lib/rosterPlanning/crunch.js';

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// ── fixtures ────────────────────────────────────────────────────────────────
const hitter = (id, extra = {}) => ({
  ID: id, Name: `H${id}`, POS: 'SS', Age: 25, ORG: 'Cubs', Lev: 'MLB',
  'Max WAR wtd': 2, 'MAX WAR P': 3, 'SS Eligible': true, SS: 60, PotSS: 65,
  On40Man: true, ActiveRoster: true, OnDL: false, OnDL60: false, Rule5Eligible: false, OptionsUsed: 1,
  ...extra,
});
const pitcher = (id, extra = {}) => ({
  ID: id, Name: `P${id}`, POS: 'SP', Age: 27, ORG: 'Cubs', Lev: 'MLB', Starter: true,
  'WAR wtd': 1.5, WARP: 2, 'WAR wtd RP': 0.5, 'WARP RP': 0.8,
  On40Man: true, ActiveRoster: true, OnDL: false, OnDL60: false, Rule5Eligible: false,
  ...extra,
});
const report = (cells, span) => ({ SalaryReport: cells, SalaryReportSpan: span });

// ── status ──────────────────────────────────────────────────────────────────
test('detectGameYear reads metadata game_date, else the modal SalaryStartYr', () => {
  assert.deepEqual(detectGameYear({ game_date: '2044-05-09' }, []), { year: 2044, source: 'game_date', date: '2044-05-09' });
  const rows = [{ SalarySchedule: [1], SalaryStartYr: 2045 }, { SalarySchedule: [1], SalaryStartYr: 2045 }, { SalarySchedule: [1], SalaryStartYr: 2044 }];
  assert.equal(detectGameYear(null, rows).year, 2045);
  assert.equal(detectGameYear(null, []).year, null);
});

test('detectContractYear accepts only gameYear or gameYear + 1', () => {
  const rows = (y) => [{ SalarySchedule: [1], SalaryStartYr: y }];
  assert.equal(detectContractYear(rows(2045), 2044), 2045);
  assert.equal(detectContractYear(rows(2044), 2044), 2044);
  assert.equal(detectContractYear(rows(2047), 2044), 2044);
});

test('salary report cells map to statuses with OOTP labels', () => {
  assert.equal(fromReportCell({ type: 'fa' }).status, 'fa');
  assert.equal(fromReportCell({ type: 'arb_uncertain', salary: 1800000 }).statusLabel, 'Arb?');
  assert.equal(fromReportCell({ type: 'team_option', salary: 5e6 }).optionType, 'club');
  assert.equal(fromReportCell({ type: 'team_option', salary: 5e6 }, true).statusLabel, 'Accepted');
  assert.equal(fromReportCell({ type: 'milb', salary: 571000 }).status, 'minors');
  assert.equal(fromReportCell({ type: 'weird', raw: 'x' }).status, 'unknown');
  assert.equal(fmtSalary(1800000), '$1.8M');
  assert.equal(fmtSalary(571000), '$571K');
});

test('projectYearStatus: report span → FA past the last cell; no data → unknown (40-man) or MiLB', () => {
  const ctx = { gameYear: 2044, contractYear: 2044 };
  const ep = { ...report({ 2044: { type: 'signed', salary: 1e6, guaranteed: true }, 2045: { type: 'arb', salary: 3e6, guaranteed: false } }, [2044, 2053]), _st: { on40: true } };
  assert.equal(projectYearStatus(ep, 2045, ctx).status, 'arb');
  assert.equal(projectYearStatus(ep, 2046, ctx).status, 'fa');
  assert.equal(projectYearStatus({ _st: { on40: true } }, 2045, ctx).status, 'unknown');
  const milb = projectYearStatus({ _st: { on40: false } }, 2046, ctx);
  assert.equal(milb.status, 'minors');
  assert.equal(milb.termUnknown, true);
  assert.equal(projectYearStatus({ _st: { on40: false } }, 2044, ctx).termUnknown, undefined);
});

test('projectYearStatus: offseason roll prefers the contract; moves win', () => {
  const ep = {
    SalarySchedule: [4e6, 5e6], SalaryStartYr: 2045, ContractOptions: [{ yr: 2046, type: 'team', buyout: 5e5 }],
    ...report({ 2044: { type: 'signed', salary: 2e6 }, 2045: { type: 'arb', salary: 3e6 } }, [2044, 2053]), _st: { on40: true },
  };
  const ctx = { gameYear: 2044, contractYear: 2045 };
  const s45 = projectYearStatus(ep, 2045, ctx);
  assert.equal(s45.source, 'contract');
  assert.equal(s45.salary, 4e6);
  assert.equal(projectYearStatus(ep, 2046, ctx).optionType, 'club');
  assert.equal(projectYearStatus({ ...ep, _acceptedOptionYear: 2046 }, 2046, ctx).statusLabel, 'Accepted');
  assert.equal(projectYearStatus({ ...ep, _declinedOptionYear: 2046 }, 2046, ctx).status, 'fa');
  assert.equal(projectYearStatus({ ...ep, _signedFrom: 2046 }, 2047, ctx).statusLabel, 'Re-signed');
});

// ── eligibility ─────────────────────────────────────────────────────────────
test('rosterState: flags from data; minor-league OnDL is not an MLB IL stint', () => {
  assert.deepEqual(rosterState(hitter(1)), { on40: true, on40Known: true, act: true, ilShort: false, ilLong: false });
  assert.equal(rosterState(hitter(1, { OnDL: true })).ilShort, true);
  assert.equal(rosterState(hitter(1, { OnDL: true, OnDL60: true })).ilLong, true);
  assert.equal(rosterState(hitter(1, { On40Man: false, OnDL: true })).ilShort, false);
  // No export flags: StatsPlus IsOnSecondary is the fallback (accessors).
  const noExport = { ID: 9, IsOnSecondary: true, IsActive: false };
  assert.deepEqual(rosterState(noExport), { on40: true, on40Known: true, act: false, ilShort: false, ilLong: false });
  assert.equal(rosterState({ ID: 9 }).on40Known, false);
});

test('r5Info and optionsInfo read flags only; nothing derived', () => {
  const r = r5Info(hitter(1, { On40Man: false, Rule5Eligible: true, YearsProtectedFromRule5: 4 }), false);
  assert.deepEqual(r, { eligible: true, yearsProtected: 4, isProtected: false, exposed: true });
  assert.equal(r5Info(hitter(1, { Rule5Eligible: true }), true).exposed, false);
  assert.equal(r5Info({ ID: 1 }, false).eligible, null);
  assert.deepEqual(optionsInfo(hitter(1)), { used: 1, yearUsed: null, remaining: null, outOfOptions: null });
});

test('filterR5Protect: threshold split and slot-aware tiers', () => {
  const mk = (id, fv, extra) => ({ _uid: id, _fv: fv, _st: { on40: false }, _r5: { eligible: true, exposed: true, isProtected: false }, ...extra });
  const forty = (id, fv) => ({ _uid: id, _fv: fv, _st: { on40: true, act: false }, _r5: {} });
  const rows = [mk('a', 2.0), mk('b', 1.5), mk('c', 0.2), forty('x', 1.0), forty('y', 1.8)];
  const res = filterR5Protect(rows, 1.0, { fortyManCapacity: 2 });
  assert.deepEqual(res.shortlist.map((r) => r._uid), ['a', 'b']);
  assert.deepEqual(res.others.map((r) => r._uid), ['c']);
  // No open slot: a (2.0) beats x (1.0) by the 0.2 buffer → must; b (1.5) vs y (1.8) → neither.
  assert.deepEqual(res.mustProtect.map((e) => e.player._uid), ['a']);
  assert.equal(res.mustProtect[0].displacedPlayer._uid, 'x');
  assert.equal(res.considerProtecting.length, 0);
  const open = filterR5Protect(rows, 1.0, { fortyManCapacity: 3 });
  assert.equal(open.mustProtect[0].reason, 'openSlot');
});

// ── enrich / projection ─────────────────────────────────────────────────────
test('enrichForPlanner: WAR / potential / FV per type, role-locked pitcher values', () => {
  const h = enrichForPlanner(hitter(1, { Age: 30 }));
  assert.equal(h._uid, '1');
  assert.equal(h._war, 2);
  assert.equal(h._warP, 3);
  assert.equal(h._fv, 2);                       // age ≥ 27: FV = current
  const young = enrichForPlanner(hitter(2, { Age: 20 }));
  assert.ok(young._fv > 2 && young._fv < 3);
  const p = enrichForPlanner(pitcher(3));
  assert.equal(p._type, 'pitcher');
  assert.equal(p._sp.war, 1.5);
  assert.equal(p._rp.war, 0.5);
  const bare = enrichForPlanner({ ID: 4, Name: 'x', POS: 'SS', Age: 22 });
  assert.equal(bare._fv, null);
});

const team = () => [
  hitter(1), hitter(2, { POS: 'C', 'C Eligible': true, C: 55, PotC: 55 }),
  hitter(3, { ActiveRoster: false }),
  hitter(4, { On40Man: false, ActiveRoster: false, Lev: 'AA', Rule5Eligible: true, Age: 22 }),
  hitter(5, { On40Man: false, ActiveRoster: false, Lev: 'A', Age: 19 }),
  hitter(6, { OnDL: true, OnDL60: true }),
  pitcher(7), pitcher(8, { Starter: false }),
  hitter(9, report({ 2044: { type: 'signed', salary: 9e6, guaranteed: true } }, [2044, 2053])),
].map(enrichForPlanner);

test('buildRosterProjection buckets and counts (60-day IL off the 40-man)', () => {
  const pr = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, displayYear: 2044, lastYear: 2046 });
  assert.deepEqual(pr.buckets.active.map((p) => p._uid).sort(), ['1', '2', '7', '8', '9']);
  assert.deepEqual(pr.buckets.fortyMan.map((p) => p._uid), ['3']);
  assert.deepEqual(pr.buckets.r5Risk.map((p) => p._uid), ['4']);
  assert.deepEqual(pr.buckets.prospects.map((p) => p._uid), ['5']);
  assert.deepEqual(pr.buckets.ilLong.map((p) => p._uid), ['6']);
  assert.equal(pr.fortyManCount, 6);
  assert.equal(pr.activeCount, 5);
  assert.deepEqual(Object.keys(pr.years).map(Number), [2044, 2045, 2046]);
  // Player 9's report ends after 2044 → FA in 2045 → departing in that year.
  const pr45 = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, displayYear: 2045 });
  assert.equal(bucketOf(pr45, '9'), 'departing');
  assert.equal(pr45.unknownStatus, 6);            // the 40-man rows (60-day IL included) with no report / contract
});

test('moves: protect, dfa, demote, il, re-sign, non-tender', () => {
  const moves = {
    4: { action: 'protect', startYear: 2045 },
    1: { action: 'dfa', startYear: 2045 },
    2: { action: 'demote', startYear: 2045 },
    3: { action: 'ilShort', startYear: 2045 },
    9: { action: 'sign', startYear: 2045 },
    't:7:2045': { action: 'nonTender', uid: '7', startYear: 2045 },
  };
  const now = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, moves, displayYear: 2044 });
  assert.equal(bucketOf(now, '4'), 'r5Risk');      // not yet: the move starts in 2045
  const pr = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, moves, displayYear: 2045 });
  assert.equal(bucketOf(pr, '4'), 'fortyMan');
  assert.equal(bucketOf(pr, '1'), null);
  assert.equal(bucketOf(pr, '7'), null);
  assert.equal(bucketOf(pr, '2'), 'fortyMan');
  assert.equal(bucketOf(pr, '3'), 'ilShort');
  assert.equal(bucketOf(pr, '9'), 'active');
  assert.equal(pr.years[2045]['9'].statusLabel, 'Re-signed');
});

// ── depth / crunch ──────────────────────────────────────────────────────────
test('depth chart: slots, coverage and pitcher roles', () => {
  const pr = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, displayYear: 2044 });
  const d = buildDepthChart(pr.enriched);
  assert.equal(d.counts.active, 5);
  assert.equal(d.counts.inactive40, 1);
  assert.equal(d.counts.ilLong, 1);
  assert.deepEqual(d.activeSlots.C.map((p) => p._uid), ['2']);
  assert.equal(d.coverage.coverage.SS, 3);          // 1, 9 and the catcher (fixture SS ratings)
  assert.equal(d.coverage.spCount, 1);
  assert.ok(d.warnings.some((w) => w.type === 'role'));
  const { sp, rp } = classifyPitchers(pr.enriched.filter((p) => p._type === 'pitcher'), 5);
  assert.deepEqual(sp.map((p) => p._uid), ['7']);
  assert.equal(sp[0]._war, 1.5);
  assert.equal(rp[0]._war, 0.5);
});

test('crunch warnings and suggestions', () => {
  const pr = buildRosterProjection(team(), { gameYear: 2044, contractYear: 2044, displayYear: 2045 });
  const w = analyzeCrunch(pr, { r5Shortlist: [{}, {}], r5Threshold: 1 });
  assert.ok(w.some((x) => x.type === 'r5'));
  assert.ok(w.some((x) => x.type === 'unknown'));
  const s = suggestActions(pr);
  assert.ok(s.some((x) => x.type === 'dfa'));
  assert.ok(s.some((x) => x.type === 'promote' && x.playerId === '3'));   // inactive, WAR 2 > 1.5
});

// ── smoke run on SSB ────────────────────────────────────────────────────────
const SSB = new URL('../../public/data/SSB/', import.meta.url);
if (existsSync(new URL('hitters.json', SSB))) {
  test('SSB: a whole org plans without throwing; 40-man and active counts are plausible', () => {
    const rows = ['hitters.json', 'pitchers.json'].flatMap((f) => JSON.parse(readFileSync(new URL(f, SSB))))
      .filter((p) => p.Name && String(p.Name).trim() && p.Name !== '-').map(enrichForPlanner);
    const meta = JSON.parse(readFileSync(new URL('metadata.json', SSB)));
    const { year } = detectGameYear(meta, rows);
    const cy = detectContractYear(rows, year);
    const orgRows = rows.filter((p) => p.ORG === 'Chicago Cubs');
    for (let y = year; y < year + 4; y++) {
      const pr = buildRosterProjection(orgRows, { gameYear: year, contractYear: cy, displayYear: y, lastYear: year + 3 });
      buildDepthChart(pr.enriched);
      filterR5Protect(pr.enriched, 1.0);
      if (y === year) {
        assert.ok(pr.fortyManCount > 20 && pr.fortyManCount <= 40, `40-man ${pr.fortyManCount}`);
        assert.ok(pr.activeCount > 15 && pr.activeCount <= 26, `active ${pr.activeCount}`);
      }
    }
  });
} else {
  console.log('skip SSB smoke run (public/data/SSB not present)');
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
