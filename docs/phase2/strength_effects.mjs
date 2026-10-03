// strength_effects.mjs - what the Phase 2 gated changes would do to the Positional Strength board.
//
//   node docs/phase2/strength_effects.mjs [BLM|SSB ...]
//
// READ-ONLY. Imports the app's own positionalStrength.js / rosterOptimizer.js unmodified, feeds
// them the committed public/data/<LG>/{hitters,pitchers}.json, and recomputes the board with
//   (a) the shipped scoring (starter only for bats, top-5 SP / top-8 RP summed),
//   (b) slot-share weighting from docs/phase2/slot_shares.json (row 14), and
//   (c) eligibility flags rewritten in memory under the "rec" and "wide" rules of
//       tgs-viz/tools/eligibility_usage.py (row 3).
// It writes nothing and changes no app file. The z-score and rank are those the board shows.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const VIZ = path.join(HERE, '..', '..', 'tgs-viz');
const ps = await import(path.join(VIZ, 'src/lib/positionalStrength.js'));
const lc = await import(path.join(VIZ, 'src/lib/leagueCalib.js'));
const slots = JSON.parse(fs.readFileSync(path.join(HERE, 'slot_shares.json'), 'utf8'));

// ootp-dashboard app/src/utils/constants.js SLOT_SHARES (BLM-ATL 2058 + one other league's metadata): the
// borrowed constants, for comparison with the measured curves.
const OURS = {
  C: [0.674, 0.283, 0.038, 0.005], '1B': [0.698, 0.189, 0.066, 0.029, 0.012], '2B': [0.680, 0.208, 0.070, 0.028, 0.010],
  '3B': [0.686, 0.224, 0.063, 0.018, 0.006], SS: [0.738, 0.169, 0.063, 0.019, 0.007], LF: [0.664, 0.204, 0.077, 0.031, 0.014],
  CF: [0.697, 0.206, 0.064, 0.024, 0.006], RF: [0.705, 0.185, 0.071, 0.023, 0.009], DH: [0.607, 0.201],
  SP: [0.244, 0.229, 0.195, 0.163, 0.103, 0.036, 0.016, 0.008], RP: [0.224, 0.172, 0.149, 0.121, 0.096, 0.079, 0.054, 0.0],
};   // DH has no ours entry; the pooled measured DH curve stands in so the comparison covers it

const load = (lg, f) => JSON.parse(fs.readFileSync(path.join(VIZ, 'public/data', lg, f), 'utf8'));
const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };
const BATS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];

// ---- eligibility rewrites (the engine's `elig` dict, floors as data) ------------------------
const RULES = {
  rec:  { lf: 45, rf: 45, cf: 60, b2: [50, 45], b3: [40, 50], ss: [60, 50] },
  wide: { lf: 45, rf: 45, cf: 55, b2: [45, 45], b3: [40, 45], ss: [50, 45] },
};
function rewriteFlags(hitters, rule) {
  const r = RULES[rule];
  return hitters.map((h) => {
    const IFR = num(h['IF RNG']), IFA = num(h['IF ARM']), TDP = num(h['TDP']), OFR = num(h['OF RNG']);
    const R = h['T'] === 'R';
    return {
      ...h,
      '2B Eligible': IFR >= r.b2[0] && R && TDP >= r.b2[1],
      '3B Eligible': IFR >= r.b3[0] && IFA >= r.b3[1] && R,
      'SS Eligible': IFR >= r.ss[0] && IFA >= r.ss[1] && R,
      'LF Eligible': OFR >= r.lf, 'CF Eligible': OFR >= r.cf, 'RF Eligible': OFR >= r.rf,
    };
  });
}

// ---- slot-weighted score (shares x value; the tail beyond the modelled depth is charged at
// the league's org replacement level, so a missing body costs what it would in the shipped score)
function weightedBat(cell, shares, replWAA) {
  const w1 = shares[0], w2 = shares[1] ?? 0;
  const top = cell.filled ? cell.top.waa : replWAA;
  // next man up is floored at replacement: the app's "depth" is the second solver pass over the leftovers,
  // which can force a bench bat into a slot he cannot field (WAA -5 to -10); no club plays that man,
  // it signs a replacement-level body instead. Unfloored, a deeper roster would score LOWER than a thin one.
  const dep = cell.depth ? Math.max(cell.depth.waa, replWAA) : replWAA;
  return w1 * top + w2 * dep + (1 - w1 - w2) * replWAA;
}
function armList(pitchers, lens, role) {
  // mirrors positionalStrength.armGroups' selection: rotation from non-relievers first, pen from the rest
  const scored = pitchers.map((p) => {
    const pos = (p.POS || '').toUpperCase();
    return { p, sp: num(p[lens.spCol]), rp: num(p[lens.rpCol]),
      isStarter: pos === 'SP', isReliever: pos === 'RP' || pos === 'CL' || pos === 'MR' };
  });
  const spSorted = scored.filter((x) => (x.isStarter || !x.isReliever) && x.sp !== null).sort((a, b) => b.sp - a.sp);
  if (role === 'sp') return spSorted.map((x) => x.sp);
  const spIds = new Set(spSorted.slice(0, 5).map((x) => x.p.ID || x.p.Name));
  return scored.filter((x) => !spIds.has(x.p.ID || x.p.Name) && x.rp !== null).sort((a, b) => b.rp - a.rp).map((x) => x.rp);
}
function weightedArm(vals, shares, K, replWAA, counted) {
  // arms inside the shipped count (5 SP, 8 RP) keep their value as shipped; arms beyond it are floored at replacement
  let s = 0;
  for (let k = 0; k < K; k++) {
    const v = k < vals.length ? vals[k] : replWAA;
    s += shares[k] * (k < counted ? v : Math.max(v, replWAA));
  }
  return s;
}

function zrank(scores) {                       // same z and competition rank the board uses
  const teams = Object.keys(scores);
  const v = teams.map((t) => scores[t]);
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / v.length);
  const sorted = [...teams].sort((a, b) => scores[b] - scores[a]);
  const rank = {};
  sorted.forEach((t, i) => { rank[t] = (i > 0 && scores[t] === scores[sorted[i - 1]]) ? rank[sorted[i - 1]] : i + 1; });
  return { z: Object.fromEntries(teams.map((t) => [t, sd > 0 ? (scores[t] - mean) / sd : 0])), rank };
}
function spearman(rankA, rankB) {
  const t = Object.keys(rankA), n = t.length;
  const d2 = t.reduce((s, k) => s + (rankA[k] - rankB[k]) ** 2, 0);
  return 1 - (6 * d2) / (n * (n * n - 1));
}

const out = {};
for (const lg of (process.argv.slice(2).length ? process.argv.slice(2) : ['BLM', 'SSB'])) {
  const hitters = load(lg, 'hitters.json'), pitchers = load(lg, 'pitchers.json');
  const lens = ps.LENSES.mlb;
  // The app passes knownTeams only for TGS and BLM (TeamStandingsPage LEAGUE_TEAMS); SSB and RG fall back to
  // "any org with 20+ players", which for SSB keeps 22 foreign clubs with no MLB roster (50 orgs, 28 real
  // MLB clubs) and ranks every real club among 22 replacement-level empties. Here every league is
  // scored on its MLB clubs only, so the comparison below is not driven by that.
  const mlbCount = {};
  for (const h of hitters) if (h.Lev === 'MLB' && h.ORG) mlbCount[h.ORG] = (mlbCount[h.ORG] || 0) + 1;
  const known = new Set(Object.keys(mlbCount).filter((o) => mlbCount[o] >= 8));
  const BUILD = { league: lg, knownTeams: known };
  const base = ps.buildPositionalStrength(hitters, pitchers, BUILD);
  const teams = base.teams;
  const replBat = -lc.replacementOrgOffset(lg, 'hitter');
  const replSP = -lc.replacementOrgOffset(lg, 'sp'), replRP = -lc.replacementOrgOffset(lg, 'rp');
  const curve = slots.leagues[lg] || slots.leagues.ALL;
  const byOrgP = {};
  for (const p of pitchers) if (lens.inLens(p) && p.ORG) (byOrgP[p.ORG] = byOrgP[p.ORG] || []).push(p);

  // (b) slot-weighted board
  const weighted = {};
  for (const pos of BATS) {
    const sh = (curve[pos] || curve.ALL || { shares: [1, 0] }).shares;
    weighted[pos] = Object.fromEntries(teams.map((t) => [t, weightedBat(base.cells[t][pos], sh, replBat)]));
  }
  weighted.SP = Object.fromEntries(teams.map((t) => [t, weightedArm(armList(byOrgP[t] || [], lens, 'sp'), curve.SP.shares, 8, replSP, 5)]));
  weighted.RP = Object.fromEntries(teams.map((t) => [t, weightedArm(armList(byOrgP[t] || [], lens, 'rp'), curve.RP.shares, 8, replRP, 8)]));

  // the same board with ours' borrowed constants
  const oursW = {};
  for (const pos of BATS) oursW[pos] = Object.fromEntries(teams.map((t) => [t, weightedBat(base.cells[t][pos], OURS[pos], replBat)]));
  oursW.SP = Object.fromEntries(teams.map((t) => [t, weightedArm(armList(byOrgP[t] || [], lens, 'sp'), OURS.SP, 8, replSP, 5)]));
  oursW.RP = Object.fromEntries(teams.map((t) => [t, weightedArm(armList(byOrgP[t] || [], lens, 'rp'), OURS.RP, 8, replRP, 8)]));

  const rows = {};
  for (const pos of [...BATS, 'SP', 'RP']) {
    const cur = Object.fromEntries(teams.map((t) => [t, base.cells[t][pos].waa]));
    const a = zrank(cur), b = zrank(weighted[pos]);
    const moves = teams.map((t) => Math.abs(a.rank[t] - b.rank[t]));
    rows[pos] = {
      spearman: +spearman(a.rank, b.rank).toFixed(3),
      meanAbsRankMove: +(moves.reduce((x, y) => x + y, 0) / teams.length).toFixed(2),
      maxRankMove: Math.max(...moves),
      teamsMovingGE3: moves.filter((m) => m >= 3).length,
      spearmanMeasuredVsOurs: +spearman(b.rank, zrank(oursW[pos]).rank).toFixed(3),
      sdOfScoreShipped: +Math.sqrt(teams.reduce((s, t) => s + (cur[t] - teams.reduce((x, u) => x + cur[u], 0) / teams.length) ** 2, 0) / teams.length).toFixed(3),
    };
    rows[pos]._cur = a; rows[pos]._w = b;
  }
  // (c) eligibility rewrites
  const elig = {};
  for (const rule of ['rec', 'wide']) {
    const alt = ps.buildPositionalStrength(rewriteFlags(hitters, rule), pitchers, BUILD);
    elig[rule] = {};
    for (const pos of BATS) {
      const a = zrank(Object.fromEntries(teams.map((t) => [t, base.cells[t][pos].waa])));
      const b = zrank(Object.fromEntries(teams.map((t) => [t, alt.cells[t][pos].waa])));
      const moves = teams.map((t) => Math.abs(a.rank[t] - b.rank[t]));
      const changedStarter = teams.filter((t) => (base.cells[t][pos].top?.name) !== (alt.cells[t][pos].top?.name)).length;
      elig[rule][pos] = { teamsWithDifferentStarter: changedStarter, teamsRankChanged: moves.filter((m) => m > 0).length,
        maxRankMove: Math.max(...moves),
        meanWAAChange: +(teams.reduce((s, t) => s + (alt.cells[t][pos].waa - base.cells[t][pos].waa), 0) / teams.length).toFixed(4) };
    }
  }
  out[lg] = { curveUsed: lg in slots.leagues ? lg : 'ALL', slotWeighting: Object.fromEntries(Object.entries(rows).map(([k, v]) => { const { _cur, _w, ...r } = v; return [k, r]; })), eligibility: elig,
    _detail: { teams, rows } };
}

// ---- print --------------------------------------------------------------------------------
for (const [lg, o] of Object.entries(out)) {
  console.log(`\n=== ${lg}: slot-share weighting vs shipped score (curve: ${o.curveUsed}) ===`);
  console.log('pos   spearman  meanAbsRankMove  maxRankMove  teams>=3  sd(shipped score, WAA)  spearman(measured vs ours constants)');
  for (const [pos, r] of Object.entries(o.slotWeighting))
    console.log(pos.padEnd(5), String(r.spearman).padStart(8), String(r.meanAbsRankMove).padStart(16), String(r.maxRankMove).padStart(12), String(r.teamsMovingGE3).padStart(9), String(r.sdOfScoreShipped).padStart(14), String(r.spearmanMeasuredVsOurs).padStart(24));
  for (const rule of ['rec', 'wide']) {
    console.log(`--- ${lg}: eligibility rule '${rule}' vs shipped flags, effect on the board ---`);
    console.log('pos   teamsWithDifferentStarter  teamsRankChanged  maxRankMove  meanWAAChange');
    for (const [pos, r] of Object.entries(o.eligibility[rule]))
      console.log(pos.padEnd(5), String(r.teamsWithDifferentStarter).padStart(24), String(r.teamsRankChanged).padStart(17), String(r.maxRankMove).padStart(12), String(r.meanWAAChange).padStart(14));
  }
}
// a few orgs, shipped vs weighted
const SHOW = { BLM: ['Atlanta Braves', 'New York (N) Mets', 'Miami Marlins'], SSB: ['Atlanta Braves', 'New York (N) Mets', 'Miami Marlins'] };
for (const [lg, o] of Object.entries(out)) {
  console.log(`\n--- ${lg}: selected orgs, rank (of ${o._detail.teams.length}) shipped -> slot-weighted ---`);
  for (const team of SHOW[lg] || []) {
    if (!o._detail.teams.includes(team)) continue;
    const cells = Object.entries(o._detail.rows).map(([pos, r]) => `${pos} ${r._cur.rank[team]}->${r._w.rank[team]}`);
    console.log(team.padEnd(22), cells.join('  '));
  }
}
for (const [lg, o] of Object.entries(out)) {
  const mv = [];
  for (const [pos, r] of Object.entries(o._detail.rows)) for (const t of o._detail.teams) mv.push([Math.abs(r._cur.rank[t] - r._w.rank[t]), t, pos, r._cur.rank[t], r._w.rank[t]]);
  mv.sort((a, b) => b[0] - a[0]);
  console.log(`\n--- ${lg}: six biggest rank moves, shipped -> slot-weighted ---`);
  for (const [d, t, pos, a, b] of mv.slice(0, 6)) console.log(`${t.padEnd(24)} ${pos.padEnd(3)} ${a} -> ${b}`);
}
if (process.env.STRENGTH_JSON) fs.writeFileSync(process.env.STRENGTH_JSON, JSON.stringify(Object.fromEntries(Object.entries(out).map(([k, v]) => [k, { curveUsed: v.curveUsed, slotWeighting: v.slotWeighting, eligibility: v.eligibility }])), null, 1));
