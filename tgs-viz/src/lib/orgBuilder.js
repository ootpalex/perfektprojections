// orgBuilder.js — Organization analysis (read-only on the projection JSON).
//
// Provides: per-level talent calibration, per-player level-fit assessment
// (too-low / right / too-high + prospect-vs-filler + age-for-level), and
// per-org affiliate rosters with roster-balance / org-need flags.
//
// "Value" = projected WAA: hitters use Max WAA wtd (current); pitchers use
// the better of SP/RP (WAA wtd / WAA wtd RP). Potential is the app's Proj
// Potential (_potentialWAA, the projected peak of the measured path) when
// the rows carry it, else the DEV cell median, else the listed MAX WAA P /
// WAP / WAP RP (see potentialValue). Nothing here touches the Excel sheets.
//
// Chance first (user, 2026-09-24): minors playing time ranks on the CHANCE
// a player is ever anything in the majors (MLB %, chanceOf) before anything
// else, and a player with no chance (noChance) is a filler at any age. The
// chance is measured from where he is now (his current WAA), so a player
// already at a bar reads 100% there (user, 2026-09-24).

export const LEVELS = ["INT", "WL", "R-", "R+", "A-", "A+", "AA", "AAA", "MLB"]; // low -> high (INT = international complex, WL = winter league — the bottom rungs)
export const LEVEL_RANK = Object.fromEntries(LEVELS.map((l, i) => [l, i]));

// Age caps per level: a player older than the cap is too old for that rung and is
// pushed UP to the lowest level he's young enough for (AA and up have no cap). If
// his ability can't hold that level he's org filler -> depth. Tunable.
export const MAX_AGE_BY_LEVEL = { INT: 19, WL: 20, "R-": 21, "R+": 23, "A-": 25, "A+": 27, AA: Infinity, AAA: Infinity, MLB: Infinity };
// Lowest level a player of this age is young enough for (his age floor, as a rank).
function ageFloorRank(age) {
  if (age == null) return 0;
  for (let i = 0; i < LEVELS.length; i++) if (age <= (MAX_AGE_BY_LEVEL[LEVELS[i]] ?? Infinity)) return i;
  return LEVELS.length - 1;
}

import { optimizeRoster } from './rosterOptimizer.js';

const num = (v) => {
  if (v === null || v === undefined || v === "" || v === "-") return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

export const isAffiliate = (lev) => LEVEL_RANK[lev] !== undefined;

// ---- value extractors ----
export function currentValue(p, isPitcher) {
  if (isPitcher) {
    const sp = num(p["WAA wtd"]);
    const rp = num(p["WAA wtd RP"]);
    const vals = [sp, rp].filter((x) => x !== null);
    return vals.length ? Math.max(...vals) : null;
  }
  return num(p["Max WAA wtd"]);
}
export function potentialValue(p, isPitcher) {
  // What we actually project he becomes (user, 2026-09-24: the Org tab must
  // use what we actually project). First the app's Proj Potential
  // (_potentialWAA from usePlayersWithFV: the projected peak of the measured
  // path, current + the DEV cell's typical gain, the same number the lists
  // show). Then the DEV cell's median peak (Dev_PeakP50, attached by
  // usePlayerData for 16-26-year-olds with a filled cell). The listed
  // potential ratings are the last fallback. For a pitcher _potentialWAA is
  // the potential-role peak. Who STARTS in the minors is decided chance
  // first (chanceOf, user 2026-09-24), no longer on spPot (WAP).
  const proj = num(p["_potentialWAA"]);
  if (proj !== null) return proj;
  const dev = num(p["Dev_PeakP50"]);
  if (dev !== null) return dev;
  if (isPitcher) {
    const sp = num(p["WAP"]);
    const rp = num(p["WAP RP"]);
    const vals = [sp, rp].filter((x) => x !== null);
    return vals.length ? Math.max(...vals) : null;
  }
  return num(p["MAX WAA P"]);
}
// best-case value used for level-fit: a prospect is judged on the higher of
// current and potential (he'll develop), an established player on current.
export function fitValue(p, isPitcher) {
  const cur = currentValue(p, isPitcher);
  const pot = potentialValue(p, isPitcher);
  if (cur === null) return pot;
  if (pot === null) return cur;
  return Math.max(cur, pot);
}

export function pitcherRole(p, { developmental = false } = {}) {
  // SP-eligible ONLY if the sheet's Starter rule passed (enough starter pitches +
  // stamina). A non-qualifier is a reliever regardless of POS.
  const starter = p["Starter"] === true || String(p["Starter"]).toUpperCase() === "TRUE";
  if (!starter) return "RP";
  // Developmental (minor-league) context: a starter-capable arm STARTS, to develop
  // him. Prospects almost always grade out better in relief on paper — a developing
  // arm gets unloaded on the 3rd time through the order, so current RP value tops
  // current SP value for nearly every minor-leaguer. Judging role on that buries
  // every starter prospect in the bullpen and leaves the minor rotations empty.
  // We'd rather a possible starter actually start; rotations fill chance
  // first downstream (chanceOf, user 2026-09-24), not on the relief line.
  if (developmental) return "SP";
  // Established (MLB) context: play him where he projects best right now. A guy who
  // is genuinely better in short relief should be a reliever in the majors.
  const sp = num(p["WAA wtd"]), rp = num(p["WAA wtd RP"]);
  if (sp !== null && rp !== null) return sp >= rp ? "SP" : "RP";
  return sp !== null ? "SP" : "RP";
}

// hitter position bucket for roster-balance (C / IF / OF / DH)
export function hitterBucket(p) {
  const pos = String(p["POS"] || "").toUpperCase();
  if (pos === "C" || p["C Eligible"] === true) return "C";
  if (["1B", "2B", "3B", "SS"].includes(pos)) return "IF";
  if (["LF", "CF", "RF", "OF"].includes(pos)) return "OF";
  if (p["SS Eligible"] === true || p["2B Eligible"] === true) return "IF";
  if (p["CF Eligible"] === true) return "OF";
  return "DH";
}

function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// ---- calibrate each level's talent + age band from league incumbents ----
export function calibrateLevels(hitters, pitchers, { excludeOrgs = new Set() } = {}) {
  const byLevel = {};
  for (const l of LEVELS) byLevel[l] = { vals: [], ages: [] };
  const add = (p, isP) => {
    const lev = p["Lev"];
    if (!isAffiliate(lev)) return;
    if (excludeOrgs.has(p["ORG"])) return;
    const v = currentValue(p, isP);
    const a = num(p["Age"]);
    if (v !== null) byLevel[lev].vals.push(v);
    if (a !== null) byLevel[lev].ages.push(a);
  };
  hitters.forEach((p) => add(p, false));
  pitchers.forEach((p) => add(p, true));
  const calib = {};
  for (const l of LEVELS) {
    const v = byLevel[l].vals.slice().sort((a, b) => a - b);
    const a = byLevel[l].ages.slice().sort((x, y) => x - y);
    calib[l] = {
      n: v.length,
      p20: quantile(v, 0.2), p50: quantile(v, 0.5), p80: quantile(v, 0.8),
      ageLo: quantile(a, 0.25), ageMed: quantile(a, 0.5), ageHi: quantile(a, 0.75),
    };
  }
  return calib;
}

// highest level where the player's fit-value clears that level's ~25th pct floor
function suggestLevel(value, calib) {
  if (value === null) return null;
  for (let i = LEVELS.length - 1; i >= 0; i--) {
    const c = calib[LEVELS[i]];
    if (c.n >= 10 && c.p20 !== null && value >= c.p20) return LEVELS[i];
  }
  return LEVELS[0];
}

// ---- per-player level-fit assessment ----
export function assessPlayer(p, isPitcher, calib) {
  const lev = p["Lev"];
  const cur = currentValue(p, isPitcher);
  const pot = potentialValue(p, isPitcher);
  const fit = fitValue(p, isPitcher);
  const age = num(p["Age"]);
  const out = {
    lev, cur, pot, age,
    suggested: suggestLevel(fit, calib),
    fitFlag: "ok",        // too_low | ok | too_high
    track: "depth",       // prospect | depth | filler
    ageFlag: "ok",        // young | ok | old
  };
  if (!isAffiliate(lev)) return out;
  const c = calib[lev];
  // ability fit at current level (use current value; overmatched if below p20).
  // "too_low" (promote) only applies below MLB — an MLB star isn't a promote.
  if (cur !== null && c.p20 !== null) {
    if (cur > c.p80 && LEVEL_RANK[lev] < LEVEL_RANK["MLB"]) out.fitFlag = "too_low";
    else if (cur < c.p20) out.fitFlag = "too_high";  // overmatched -> demote/bury risk
  }
  // age for level
  if (age !== null && c.ageLo !== null) {
    if (age > c.ageHi) out.ageFlag = "old";
    else if (age < c.ageLo) out.ageFlag = "young";
  }
  // prospect vs filler: young + meaningful ceiling = prospect; old + low = filler
  const ceiling = pot !== null ? pot : cur;
  if (age !== null) {
    if (age <= (c.ageMed ?? 99) && ceiling !== null && ceiling > (c.p50 ?? -99)) out.track = "prospect";
    else if (age > (c.ageHi ?? 99) && (cur === null || cur < (c.p50 ?? -99))) out.track = "filler";
  }
  return out;
}

// ---- build one org's affiliate rosters + flags ----
const ROSTER_TARGETS = { C: 2, IF: 6, OF: 5, DH: 1, SP: 5, RP: 7 };

export function buildOrg(orgName, hitters, pitchers, calib) {
  const orgHit = hitters.filter((p) => p["ORG"] === orgName);
  const orgPit = pitchers.filter((p) => p["ORG"] === orgName);
  const levels = {};
  for (const l of LEVELS) levels[l] = { hitters: [], pitchers: [], flags: [] };
  const other = { hitters: [], pitchers: [] }; // WL/INT/unsigned

  for (const p of orgHit) {
    const a = assessPlayer(p, false, calib);
    const rec = { p, isPitcher: false, ...a, bucket: hitterBucket(p) };
    (isAffiliate(p["Lev"]) ? levels[p["Lev"]].hitters : other.hitters).push(rec);
  }
  for (const p of orgPit) {
    const a = assessPlayer(p, true, calib);
    // developmental role: a starter-capable arm counts as an SP prospect (and
    // fills SP in the per-level balance), matching how the rotations are built.
    const rec = { p, isPitcher: true, ...a, role: pitcherRole(p, { developmental: true }) };
    (isAffiliate(p["Lev"]) ? levels[p["Lev"]].pitchers : other.pitchers).push(rec);
  }

  // roster-balance flags per affiliate
  for (const l of LEVELS) {
    const lv = levels[l];
    const counts = { C: 0, IF: 0, OF: 0, DH: 0 };
    lv.hitters.forEach((r) => (counts[r.bucket] = (counts[r.bucket] || 0) + 1));
    const sp = lv.pitchers.filter((r) => r.role === "SP").length;
    const rp = lv.pitchers.filter((r) => r.role === "RP").length;
    const lhp = lv.pitchers.filter((r) => r.p["T"] === "L").length;
    lv.counts = { ...counts, SP: sp, RP: rp, LHP: lhp, hitters: lv.hitters.length, pitchers: lv.pitchers.length };
    const f = lv.flags;
    if (lv.hitters.length + lv.pitchers.length === 0) continue; // empty affiliate, skip noise
    if (counts.C < 1) f.push({ sev: "error", msg: "No catcher" });
    else if (counts.C < ROSTER_TARGETS.C) f.push({ sev: "warn", msg: "Only 1 catcher" });
    if (sp < ROSTER_TARGETS.SP) f.push({ sev: sp < 3 ? "error" : "warn", msg: `Only ${sp} starters (want ${ROSTER_TARGETS.SP})` });
    if (rp < 4) f.push({ sev: "warn", msg: `Thin bullpen (${rp} RP)` });
    if (lhp === 0 && lv.pitchers.length > 0) f.push({ sev: "warn", msg: "No left-handed pitching" });
    if (counts.IF < 4 && lv.hitters.length > 0) f.push({ sev: "warn", msg: `Light infield (${counts.IF})` });
    if (counts.OF < 3 && lv.hitters.length > 0) f.push({ sev: "warn", msg: `Light outfield (${counts.OF})` });
  }

  // org-wide needs: promote candidates (too_low), buried (too_high), and
  // pipeline holes (no prospect above replacement at a position group).
  const promote = [], buried = [];
  for (const l of LEVELS) {
    for (const r of [...levels[l].hitters, ...levels[l].pitchers]) {
      if (r.fitFlag === "too_low") promote.push(r);
      if (r.fitFlag === "too_high") buried.push(r);
    }
  }
  promote.sort((a, b) => (b.cur ?? -99) - (a.cur ?? -99));
  buried.sort((a, b) => (a.cur ?? 99) - (b.cur ?? 99));

  // prospect pipeline by bucket (any affiliate prospect with positive ceiling)
  const pipeline = { C: 0, IF: 0, OF: 0, SP: 0, RP: 0 };
  for (const l of LEVELS) {
    levels[l].hitters.forEach((r) => { if (r.track === "prospect" && (r.pot ?? r.cur ?? -9) > 0) pipeline[r.bucket] = (pipeline[r.bucket] || 0) + 1; });
    levels[l].pitchers.forEach((r) => { if (r.track === "prospect" && (r.pot ?? r.cur ?? -9) > 0) pipeline[r.role] = (pipeline[r.role] || 0) + 1; });
  }
  const needs = [];
  for (const [grp, cnt] of Object.entries(pipeline)) {
    if (cnt === 0) needs.push({ grp, msg: `No ${grp} prospect in the system` });
  }

  return { orgName, levels, other, promote: promote.slice(0, 12), buried: buried.slice(0, 12), pipeline, needs };
}

// ===================================================================
// v2 — constraint-based roster construction
//   * hitters are placed at the HIGHEST level where they can still HIT
//     (offense floor), not just where their glove plays — a glove-only
//     guy who can't hit won't develop there.
//   * within a level, playing time goes to the BEST POTENTIAL.
//   * position logjams (e.g. two elite C) cascade the extra down a level
//     so both get to start ("split across teams").
//   * empty positions are flagged as needing a filler.
//   * pitchers: no hitting gate; placed by ability, prioritized by potential.
// ===================================================================

const POS9 = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"];
const posWAA = (p, pos) => num(p[`${pos} WAA wtd`]);
const eligibleAt = (p, pos) => (pos === "DH" ? true : p[`${pos} Eligible`] === true);

export function bestPosition(p) {
  let bp = "DH", bv = -Infinity;
  for (const pos of POS9) {
    if (!eligibleAt(p, pos)) continue;
    const v = posWAA(p, pos);
    if (v !== null && v > bv) { bv = v; bp = pos; }
  }
  return bp;
}

// ---- placement philosophy (tunable) ------------------------------------------
// Place a player EXACTLY at the level his ability fits — the highest level where he
// still projects around average-or-better for that level (so he competes and performs
// well), NOT a bottom-of-the-level "survive" bar. NO challenge reach: overplacing a
// developing player gets him demolished and tanks his potential (OOTP 26 punishes
// being overmatched — seen it a million times). Underplacing wastes reps against weak
// competition. The bar is his ability; he develops by succeeding there and earning up.
// Placement bar (user philosophy, 2026-08-30: "where they can hit WELL, not
// hit ok"): a player is promoted to the highest level where he'd be a top-third
// performer among its current players — comfortably good, never a bare-median
// reach. 0.67 (not 0.70): a knife-edge player exactly ON a 70th-pct bar was
// flipping levels with tiny basis shifts (James Barbera: 70.2th neutral /
// 69.2th park) — two points of headroom keep "good for the level" guys from
// being hard-stuck below it. History: 0.35 survive -> 0.50 median -> 0.70 -> 0.67.
const FIT_PCT_HIT = 0.67;   // hitters: highest level where wOBA >= the level's 67th percentile
const FIT_PCT_PIT = 0.67;   // pitchers: same philosophy, on developed-role value

// Pitchers are judged for LEVEL FIT in the role they'll actually be DEVELOPED in — a
// future starter on his STARTER projection, not the relief line he won't pitch. (Fixes
// placing a starter-prospect high on relief value while developing him as a starter.)
const isStarterCapable = (p) => p["Starter"] === true || String(p["Starter"]).toUpperCase() === "TRUE";
const devRoleValue = (p) => (isStarterCapable(p) ? num(p["WAA wtd"]) : num(p["WAA wtd RP"]));

// Per-level talent floors from league incumbents (NPB-excludable).
export function offenseFloors(hitters, { excludeOrgs = new Set(), pct = 0.35 } = {}) {
  const by = {}; for (const l of LEVELS) by[l] = [];
  for (const p of hitters) {
    const lev = p["Lev"]; if (!isAffiliate(lev) || excludeOrgs.has(p["ORG"])) continue;
    const w = num(p["wOBA wtd"]); if (w !== null) by[lev].push(w);
  }
  const out = {}; for (const l of LEVELS) out[l] = quantile(by[l].sort((a, b) => a - b), pct);
  return out;
}
// Filler bats (dev done) are placed on WAA, not on the bat: "for guys who are
// 24 and older we are just trying to get WAA results out of them" (user,
// 2026-09-22, Ariza case). Same percentile bars as the hit gate, on Max WAA wtd.
export function waaFloors(hitters, { excludeOrgs = new Set(), pct = 0.35 } = {}) {
  const by = {}; for (const l of LEVELS) by[l] = [];
  for (const p of hitters) {
    const lev = p["Lev"]; if (!isAffiliate(lev) || excludeOrgs.has(p["ORG"])) continue;
    const w = num(p["Max WAA wtd"]); if (w !== null) by[lev].push(w);
  }
  const out = {}; for (const l of LEVELS) out[l] = quantile(by[l].sort((a, b) => a - b), pct);
  return out;
}
export function pitcherFloors(pitchers, { excludeOrgs = new Set(), pct = 0.40 } = {}) {
  const by = {}; for (const l of LEVELS) by[l] = [];
  for (const p of pitchers) {
    const lev = p["Lev"]; if (!isAffiliate(lev) || excludeOrgs.has(p["ORG"])) continue;
    const v = devRoleValue(p); if (v !== null) by[lev].push(v);   // role-clean: starters on their starter line
  }
  const out = {}; for (const l of LEVELS) out[l] = quantile(by[l].sort((a, b) => a - b), pct);
  return out;
}
// Reliever talent bar — relief-only arms judged on their RELIEF line. Kept SEPARATE from
// pitcherFloors on purpose: the mixed floor is dragged way down by starters' (grim) starting
// grades, so a mediocre reliever clears it and floats up several levels (e.g. a WL arm landing
// at A+). Measuring relievers against relievers keeps them at their real level and is stable
// when the starter threshold changes (flipping starter flags doesn't move this bar much).
export function relieverFloors(pitchers, { excludeOrgs = new Set(), pct = 0.40 } = {}) {
  const by = {}; for (const l of LEVELS) by[l] = [];
  for (const p of pitchers) {
    const lev = p["Lev"]; if (!isAffiliate(lev) || excludeOrgs.has(p["ORG"])) continue;
    if (isStarterCapable(p)) continue;                       // relievers vs relievers
    const v = num(p["WAA wtd RP"]); if (v !== null) by[lev].push(v);
  }
  const out = {}; for (const l of LEVELS) out[l] = quantile(by[l].sort((a, b) => a - b), pct);
  return out;
}
// Highest level whose talent floor the player clears, but never below `minLev`.
// A player in the affiliate system bottoms out at R-; a winter-league player can
// sit on the WL rung beneath it (so WL fills with the guys too raw even for R-).
function highestClearing(val, floors, minLev = LEVELS[0]) {
  if (val === null) return null;
  const minRank = LEVEL_RANK[minLev] ?? 0;
  for (let i = LEVELS.length - 1; i >= 0; i--) {
    if (LEVEL_RANK[LEVELS[i]] < minRank) break;
    const f = floors[LEVELS[i]];
    if (f != null && val >= f) return LEVELS[i];
  }
  return minLev;
}

// Slots are filled hardest-position-first (C/SS/CF…) so scarce gloves win their
// spot before flexible bats. MLB = your exact 13-man distribution.
// MLB lineup: 9 starters (filled hardest-position-first for assignment quality),
// then 4 bench (backup C + two utility + best remaining bat) — kept as a separate
// group so the UI shows backups UNDER the starters, the same as the minor levels.
const MLB_STARTER_SLOTS = [
  ["C", ["C"]], ["SS", ["SS"]], ["CF", ["CF"]], ["2B", ["2B"]], ["3B", ["3B"]],
  ["RF", ["RF"]], ["LF", ["LF"]], ["1B", ["1B"]], ["DH", ["DH", "1B"]],
];
const MLB_BENCH_SLOTS = [
  ["BU C", ["C"]], ["UTIL IF", ["SS", "2B", "3B", "1B"]],
  ["UTIL OF", ["CF", "LF", "RF"]], ["BEST", POS9],
];
const MINOR_SLOTS = [
  ["C", ["C"]], ["SS", ["SS"]], ["CF", ["CF"]], ["2B", ["2B"]], ["3B", ["3B"]],
  ["RF", ["RF"]], ["LF", ["LF"]], ["1B", ["1B"]], ["DH", ["DH", "1B"]],
];
const MINOR_BENCH = 4;   // backup C + 3 depth bats -> ~13 position players per affiliate
const cnt = (sp, rp, h, bench = []) => ({ SP: sp.length, RP: rp.length,
  hitters: h.length + bench.length, starters: h.length, bench: bench.length,
  LHP: [...sp, ...rp].filter((x) => x.p["T"] === "L").length });

function fillSlots(pool, slots, used, valueFn) {
  const roster = [], gaps = [];
  for (const [label, elig] of slots) {
    let best = null, bestVal = -Infinity, bestPos = null;
    for (const h of pool) {
      if (used.has(h)) continue;
      for (const pos of elig) {
        if (!eligibleAt(h.p, pos)) continue;
        const v = valueFn(h, pos);
        if (v > bestVal) { bestVal = v; best = h; bestPos = pos; }
      }
    }
    if (best) { used.add(best); best.slot = label; best.slotPos = bestPos; roster.push(best); }
    else gaps.push(label);
  }
  return { roster, gaps };
}

// Minors lineup scoring (user, 2026-09-22, Dale Wosick case: a 24-yo with no
// future started AAA 2B at -4.2 because the old score used his BEST position
// and credited potential he has no time left to reach).
//  * isFillerBat: 27+ is filler (dev done); 23-26 is filler unless his potential
//    is about 0 WAA or better (-0.25 tolerance) and he still has room to grow.
//    The dev-done age moved from 25 to 27 (user, 2026-09-24: "move those to
//    27 based on our data"). The DEV league's mean WAA change per year is
//    +0.21 at 24, +0.13 at 25, +0.07 at 26, +0.01 at 27 and -0.03 at 28, so
//    growth tails off at 27 and decline starts at 28. The Wosick check still
//    starts at 23: pot is Proj Potential (the top of his measured path), so a
//    24-yo with a negative projected peak stays a filler.
//  * No chance = filler at ANY age (noChance, user 2026-09-24): the 27+ and
//    the 23-26 tests stay; a younger bat with no chance joins them.
//  * A filler starts only on what he is worth NOW at that exact position; a
//    prospect keeps the potential-first blend, with a light pull toward the
//    position he actually plays well.
//  * assignLineup fills the 9 slots together (exact bitmask assignment: most
//    slots filled first, then best total score) instead of one slot at a time.

// ---- chance first (user, 2026-09-24) -----------------------------------------
// The user: "we should probably base it on if they will ever be anything in
// the mlb first and foremost and what degree of a chance do they have ...
// if a guy is 26 and his growth rate is declined to an average of like 0.5
// or whatever it is and they arent close to making it then whats the point".
// So minors playing time ranks on the CHANCE first, and a player with no
// chance is a filler at any age. The shares come from his DEV lookalikes
// (same age, Pot bucket and growth; devSignals.js) and, since 2026-09-24,
// are CONDITIONAL ON HIS CURRENT: each is the chance his eventual peak
// reaches the bar from where he is now, the share of the lookalikes at a
// similar current (the now-WAA tercile holding his own, Dev_ShareBasis)
// whose gain covered the distance from his current (Dev_ShareNow) to the
// bar. A player already at or above a bar reads 100% there. The old shares
// were the whole cell's peak distribution, blind to his current (user,
// 2026-09-24: "there are a ton of guys who are already at 0+ WAA that are
// getting like tagged as less than 100% to reach it"). dev_signals ships
// them as Dev_CellMlb / Dev_CellUseful / Dev_CellGood. On a row the ML model
// covers (devMl.js, Dev_Source 'ML', 2026-09-25) the Dev_Peak* chances below
// are the ML's; Dev_CellMlb / Useful / Good then hold the cell method's
// CONDITIONAL chances (for reference) and the old unconditional shares move
// to Dev_CellShareMlb / Useful / Good. Nothing here reads any Dev_Cell* field.
//   Dev_PeakMlb    = chance his peak reaches -1 (an MLB-level player: a 5th
//                    starter or bench bat) = MLB %, the chance he is ever
//                    anything in the majors;
//   Dev_PeakUseful = the same chance at 0 (an average starter) = Starter %;
//   Dev_PeakGood   = the same chance at +1.5 (a star) = Star %.
// chanceOf(p) returns { mlb, useful, good, source }. source is "cell" when
// the row has a DEV cell. A thin growth cell now falls back to the pot-only
// cell (same age and Pot) upstream, so the stand-in only fires for a row
// with no cell at all (both thin, outside 16-26, or not in the signals
// file): it comes from Proj Potential (p._potentialWAA, else the listed
// potential, see potentialValue): >= 0 -> 0.5, >= -1.0 -> 0.25, else 0,
// with useful and good null (unknown) and source "stand-in", so the UI can
// say so.
export const CHANCE_STAND_IN = { POS: 0.5, NEAR: 0.25, NONE: 0 };
const isPitcherRow = (p) => !!p && p["Max WAA wtd"] === undefined;
export function chanceOf(p, isPitcher = null) {
  const mlb = num(p?.["Dev_PeakMlb"]);
  if (mlb !== null) {
    return { mlb, useful: num(p?.["Dev_PeakUseful"]), good: num(p?.["Dev_PeakGood"]), source: "cell" };
  }
  const pot = potentialValue(p || {}, isPitcher === null ? isPitcherRow(p) : isPitcher);
  const standIn = pot === null ? CHANCE_STAND_IN.NONE
    : pot >= 0 ? CHANCE_STAND_IN.POS : pot >= NO_CHANCE_POT ? CHANCE_STAND_IN.NEAR : CHANCE_STAND_IN.NONE;
  return { mlb: standIn, useful: null, good: null, source: "stand-in" };
}
// No chance = a filler at any age (user, 2026-09-24: "whats the point"):
// MLB % known and under 5% (since 2026-09-24 the chance from his current:
// his lookalikes at a similar current almost never gained enough to reach
// -1) AND Proj Potential under -1.0 WAA. With the share
// unknown (no DEV cell): Proj Potential under -1.0 AND age 21 or older. A
// younger player without a cell is unknown, not hopeless, so he keeps his
// prospect status until the data says otherwise.
export const NO_CHANCE_MLB = 0.05, NO_CHANCE_POT = -1.0, NO_CHANCE_AGE_UNKNOWN = 21;
export function noChance(p, pot) {
  const pt = num(pot);
  if (pt === null || pt >= NO_CHANCE_POT) return false;
  const mlb = num(p?.["Dev_PeakMlb"]);
  if (mlb !== null) return mlb < NO_CHANCE_MLB;
  const age = num(p?.["Age"]);
  return age !== null && age >= NO_CHANCE_AGE_UNKNOWN;
}

const posPot = (p, pos) => num(p[`${pos} WAA P`]);
const BAT_POT_OK = -0.25;
export const isFillerBat = (h) => (h.age ?? 99) >= 27 ||
  ((h.age ?? 99) >= 23 && !((h.pot ?? -99) >= BAT_POT_OK && (h.pot ?? -99) > (h.cur ?? -99))) ||
  noChance(h.p, h.pot);   // no chance = filler at any age (user, 2026-09-24)

// ---- training positions (user, 2026-09-24) -----------------------------------
// The user: "add a thing in the org builder beside players who may become good
// any positions that they could play at a 0 WAA or higher if they reach peak
// but have not mastered like if a catcher is 45/50 for the position rating or
// maybe they haven't started even training to be a RF yet but they have 60
// range or something ... Would be good to notate the positions they lack
// training by each of the prospects to work as a reminder. I forget all the
// time to change positions during the season in the minors for training."
// So, for a hitter who is not a filler, list every position (never DH) where
// BOTH hold:
//   1. his WAA at THAT POSITION if he reaches his potential ratings is
//      TRAIN_PEAK_BAR (0 WAA) or better: the engine's "P WAA P" line (his
//      potential ratings at P, fielded with his tools: range, error, arm,
//      the catcher skills). The engine never reads the position rating, so
//      that line is already his value at full training. "If they reach
//      peak" means his potential, not the median projection (Proj
//      Potential): until 2026-09-26 this read Proj Potential + the position
//      offset, and the median sits below 0 for nearly every minor leaguer,
//      so almost no one got a chip (user, 2026-09-26: "none of my prospects
//      are being tagged to train any position").
//   2. he has not mastered P: position rating current < potential (the
//      user's 45/50), OR he has never trained there at all. OOTP exports a
//      never-trained position as 0/0 (no potential until training starts),
//      so "haven't started even training to be a RF yet but they have 60
//      range" only shows through the tools line: a 0/0 position whose
//      projected peak clears the bar is listed as NEW (untrained: true, pot
//      null). Catcher is the exception: a non-catcher's C tools are not a
//      real read of catching, so C is listed only when he already has a C
//      rating above 0.
// Returns [{ pos, cur, pot, peak, untrained }], best peak first (peak = the
// P WAA P line); cur reads 0 when untrained. Pure: reads the row, nothing
// else. The caller decides who gets the note (the Org page: non-filler
// minors bats and MLB bats under 27; the card: any hitter).
export const TRAIN_PEAK_BAR = 0.0;
export const TRAIN_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"];
export function trainingNotes(p) {
  if (!p) return [];
  const out = [];
  for (const pos of TRAIN_POS) {
    const pot = num(p[`Pot${pos}`]);
    const cur = num(p[pos]) ?? 0;                     // blank = never trained
    const untrained = !(pot > 0);                     // 0/0: training never started
    if (untrained && (cur > 0 || pos === "C")) continue;   // odd export, or catching without a C rating
    if (!untrained && cur >= pot) continue;           // mastered already
    const peak = num(p[`${pos} WAA P`]);              // his WAA there at his potential
    if (peak === null || peak < TRAIN_PEAK_BAR) continue;
    out.push({ pos, cur, pot: untrained ? null : pot, peak, untrained });
  }
  out.sort((a, b) => b.peak - a.peak);
  return out;
}
function assignLineup(pool, slots, used, scoreAt) {
  const avail = pool.filter((h) => !used.has(h));
  const nS = slots.length, nM = 1 << nS, BONUS = 1e6;
  const opts = avail.map((h) => {
    const o = [];
    slots.forEach(([, elig], si) => {
      let bv = -Infinity, bp = null;
      for (const pos of elig) { if (!eligibleAt(h.p, pos)) continue; const v = scoreAt(h, pos); if (v != null && v > bv) { bv = v; bp = pos; } }
      if (bp) o.push([si, bv, bp]);
    });
    return o;
  });
  let prev = new Float64Array(nM).fill(-Infinity); prev[0] = 0;
  const ch = [];
  for (let i = 0; i < avail.length; i++) {
    const cur = new Float64Array(nM).fill(-Infinity), c = new Int8Array(nM).fill(-1);
    for (let m = 0; m < nM; m++) {
      const b = prev[m]; if (b === -Infinity) continue;
      if (b > cur[m]) { cur[m] = b; c[m] = -1; }
      for (const [si, v] of opts[i]) { if (m & (1 << si)) continue; const nm = m | (1 << si), nv = b + v + BONUS; if (nv > cur[nm]) { cur[nm] = nv; c[nm] = si; } }
    }
    ch.push(c); prev = cur;
  }
  let bm = 0; for (let m = 1; m < nM; m++) if (prev[m] > prev[bm]) bm = m;
  const bySlot = new Array(nS).fill(null);
  let m = bm;
  for (let i = avail.length - 1; i >= 0 && m; i--) { const si = ch[i][m]; if (si >= 0) { bySlot[si] = [avail[i], opts[i].find((o) => o[0] === si)[2]]; m &= ~(1 << si); } }
  const roster = [], gaps = [];
  slots.forEach(([label], si) => {
    const e = bySlot[si];
    if (!e) { gaps.push(label); return; }
    const [h, pos] = e; used.add(h); h.slot = label; h.slotPos = pos; roster.push(h);
  });
  return { roster, gaps };
}
// The DH slot is scored on the DH line only (a DH does not field 1B).
const MINOR_LINEUP = MINOR_SLOTS.map(([l, e]) => [l, l === "DH" ? ["DH"] : e]);
const minorSlotScore = (h, pos) => {
  const c = posWAA(h.p, pos); if (c == null) return null;
  if (isFillerBat(h)) return c;
  const EPS = 0.1;   // light position pull for prospects: they still start on their future
  // + somethingBonus: chance first, the guys who have one play (user, 2026-09-24).
  return WIN_W * (h.cur ?? c) + GROW_W * (h.pot ?? h.cur ?? c) + EPS * (c - (h.cur ?? c)) + somethingBonus(h.p);
};
// Best slot score over a slot's eligible positions -> [score, pos].
const bestSlotScore = (h, elig) => {
  let bv = -Infinity, bp = null;
  for (const pos of elig) { if (!eligibleAt(h.p, pos)) continue; const v = minorSlotScore(h, pos); if (v != null && v > bv) { bv = v; bp = pos; } }
  return [bv, bp];
};

// ---- minor-league playing-time philosophy -------------------------------------
// Goal: win at every level AND develop. So the most play time (the starting jobs)
// goes to the best blend of winning NOW (current ability) and GROWTH (potential),
// with an emphasis on winning. The bench is depth that can win now but has less
// ceiling than the guys who beat them out — genuine high-ceiling prospects who
// get blocked cascade DOWN a level to keep starting (play time develops them).
// Within a level, who gets the starting jobs (the most reps). Potential-weighted so
// the best-FUTURE guys play no matter what, with current ability as a tiebreak so a
// totally washed prospect doesn't start over a useful filler. (User: potential WAA is
// the most important factor for prioritizing playing time.) Tunable — raise WIN_W to
// favor win-now over ceiling.
const WIN_W = 0.4, GROW_W = 0.6;
const blendScore = (cur, pot) => WIN_W * (cur ?? pot ?? -99) + GROW_W * (pot ?? cur ?? -99);

// ---- "will he be something" (user, 2026-09-24) ------------------------------
// Make it % (Dev_Odds) is PLAYING TIME: the share of DEV lookalikes (same age,
// Pot bucket and growth) who got 300 PA / 150 BF in a season. It says nothing
// about whether they were any good. The user asked: "does make it consider
// that their projected WAA might just not be good enough at all?" It does
// not. So minors playing time ranks on the CHANCE shares of the same DEV
// cell, each the chance from where he is now (chanceOf above): MLB % first
// and foremost (user, 2026-09-24: "if
// they will ever be anything in the mlb first and foremost and what degree
// of a chance do they have"), then Starter % and Star %.
// somethingBonus adds CHANCE_W x (mlb + useful + good) WAA of playing-time
// priority to a PROSPECT's play score and lineup slot score, and takes it
// off his bench score, so a blocked prospect with a real chance cascades
// down and starts rather than sits. CHANCE_W = 2.0: a 60 / 40 / 20 prospect
// carries +2.4 WAA of priority; one whose lookalikes all busted carries 0.
// A row with no cell at all uses the stand-in MLB % from Proj Potential (at
// most +1.0). Fillers (isFillerBat, isFillerArm) never get it: they play on what
// they are worth now. Placement (which level) is untouched; this is only
// who plays there. Rotations and pens rank on the same shares through the
// chance-first order in buildRosters (chanceCmp / chanceScore).
export const CHANCE_W = 2.0;
export const somethingBonus = (p) => {
  const c = chanceOf(p);
  return CHANCE_W * (c.mlb + (c.useful ?? 0) + (c.good ?? 0));
};

// ---- keep-before-cut value (depth pass and the Org page's cuts list) --------
// keepValue = Proj Potential + youthBonus, and for a PROSPECT also the
// something bonus (the chance bonus above). Chance first (user, 2026-09-24:
// "if they will ever be anything in the mlb first and foremost"), so a
// 20-year-old with MLB 52% is not cut or pushed off a roster seat by a
// 19-year-old at 40% (checker, 2026-09-25: Kilbourne vs Weng). Fillers
// (isFillerRec: a filler bat, or an arm 27+ or with no chance) are unchanged:
// no chance bonus. youthBonus rewards TCR upside (a 20-yo's talent can still
// randomly jump); its steps end at 26 (turn-27 rule, DEV data, 2026-09-24):
// a 25-26-year-old still gains a little.
export const youthBonus = (age) => (age == null ? 0 : age <= 20 ? 2.5 : age <= 22 ? 1.5 : age <= 24 ? 0.9 : age <= 26 ? 0.4 : 0);
// Same test as buildRosters' isFillerArm for arms and isFillerBat for bats.
export const isFillerRec = (x) => (x.isPitcher
  ? !((x.age ?? 99) <= 26 && !noChance(x.p, x.pot))
  : isFillerBat(x));
export const keepValue = (x) => (x.pot ?? x.cur ?? -99) + youthBonus(x.age)
  + (isFillerRec(x) ? 0 : somethingBonus(x.p));
// Keep order for depth seats and the cuts list, best to keep first (user,
// 2026-09-25: "if you think chance is better then yeah we can go with
// chance"). Prospects come before fillers; prospects rank by their chance
// (MLB %, then Starter %, then Star %; chanceOf, a stand-in when he has no
// DEV group) and only then by keepValue. The ML chance already knows his
// age, so the youth bonus no longer outranks a real chance gap (it kept
// 19-year-olds at 21-31% MLB over 21-22-year-olds at 34-38%). Fillers
// keep the keepValue order.
export const keepCmp = (a, b) => {
  const fa = isFillerRec(a) ? 1 : 0, fb = isFillerRec(b) ? 1 : 0;
  if (fa !== fb) return fa - fb;
  if (!fa) {
    const ca = chanceOf(a.p, a.isPitcher), cb = chanceOf(b.p, b.isPitcher);
    const d = ((cb.mlb ?? 0) - (ca.mlb ?? 0)) || ((cb.useful ?? 0) - (ca.useful ?? 0))
      || ((cb.good ?? 0) - (ca.good ?? 0));
    if (d) return d;
  }
  return keepValue(b) - keepValue(a);
};

// Bench value: current production, penalized for unused upside so a prospect with
// room to grow would rather cascade down and start than sit as a backup here.
// A prospect also gives up his something bonus here (user, 2026-09-24).
const benchScore = (rec) => (!rec.isPitcher && isFillerBat(rec)) ? (rec.cur ?? -99)
  : (rec.cur ?? -99) - GROW_W * Math.max(0, (rec.pot ?? rec.cur ?? -99) - (rec.cur ?? -99)) - somethingBonus(rec.p);
// A captain needs leadership + work ethic + loyalty together (not leadership alone,
// which over-counts ~7x). All three high = a lock; leadership & work ethic high with
// normal loyalty = a likely captain (the game also factors hidden values we can't see).
const captainTier = (rec) => {
  const U = (v) => String(v).toUpperCase();
  const L = U(rec.p["Lead"]), W = U(rec.p["WrkEthic"]), Lo = U(rec.p["Loy"]);
  if (L === "H" && W === "H" && Lo === "H") return 2;   // lock — all three high
  if (L === "H" && W === "H" && Lo === "N") return 1;   // likely — loyalty only normal
  return 0;
};
const isCaptain = (rec) => captainTier(rec) >= 1;

// Per-level roster caps (TOTAL players). Pitchers + lineup are placed first; the bench
// fills the remainder up to the cap. INT (complex) is left uncapped.
const MINOR_ROSTER_CAP = { AAA: 32, AA: 32, "A+": 35, "A-": 35, "R+": 40, "R-": 40, WL: 40 };
const BENCH_ELIG = { C: ["C"], IF: ["1B", "2B", "3B", "SS"], OF: ["LF", "CF", "RF"] };
const benchEligAt = (p, grp) => BENCH_ELIG[grp].some((pos) => eligibleAt(p, pos));

// Fill a minor bench position-FIRST: guarantee a backup C, two backup IF and two backup
// OF (the user's minimum) before padding depth, then the best remaining bats up to the
// roster-cap target. Coverage the level's own pool can't supply is returned as `need`
// (and a slot is RESERVED for it) so the completeness pass can source it from depth
// rather than the slot being burned on, say, a 5th first baseman.
function fillMinorBench(pool, used, target) {
  const bench = [];
  const take = (h) => { used.add(h); bench.push(h); };
  const avail = () => pool.filter((h) => !used.has(h)).sort((a, b) => benchScore(b) - benchScore(a));
  const takeOne = (grp) => { const h = avail().find((x) => benchEligAt(x.p, grp)); if (h) { take(h); return true; } return false; };
  const need = { C: 1, IF: 2, OF: 2 };
  if (takeOne("C")) need.C--;
  while (need.IF > 0 && takeOne("IF")) need.IF--;
  while (need.OF > 0 && takeOne("OF")) need.OF--;
  const reserve = need.C + need.IF + need.OF;             // hold slots open for the depth backfill
  for (const h of avail()) { if (bench.length >= target - reserve) break; take(h); }
  return { bench, need };
}

// Captains: give each affiliate a captain when a credible one is available. If
// neither the lineup, the bench, nor the pitching staff already has one, swap the
// best free captain in for the weakest bench bat — preferring a lock over a likely,
// and only when the downgrade is small ("if possible," not at all costs). The
// displaced bat is freed to cascade down.
function addCaptainIfMissing(roster, bench, staff, pool, used) {
  if ([...roster, ...bench, ...staff].some(isCaptain)) return;
  const cand = pool.filter((h) => !used.has(h) && isCaptain(h))
    .sort((a, b) => captainTier(b) - captainTier(a) || (b.cur ?? -99) - (a.cur ?? -99))[0];
  if (!cand || bench.length === 0) return;
  let wi = 0;
  for (let i = 1; i < bench.length; i++) if ((bench[i].cur ?? -99) < (bench[wi].cur ?? -99)) wi = i;
  // A lock captain (all three high) is a definite clubhouse leader — worth a roster
  // spot even with a weak bat, since he only displaces the weakest bench player and
  // the starters are untouched. A likely captain only bumps a bat if he's close.
  const tol = captainTier(cand) >= 2 ? 4.0 : 1.0;
  if ((cand.cur ?? -99) >= (bench[wi].cur ?? -99) - tol) {
    used.delete(bench[wi]); used.add(cand); bench[wi] = cand;
  }
}

export function buildRosters(org, hitters, pitchers, opts = {}) {
  const oFloors = offenseFloors(hitters, { ...opts, pct: FIT_PCT_HIT });
  const pFloors = pitcherFloors(pitchers, { ...opts, pct: FIT_PCT_PIT });
  const rpFloors = relieverFloors(pitchers, { ...opts, pct: FIT_PCT_PIT });   // relievers vs relievers
  // HYSTERESIS (user, 2026-08-30: "our rules are too strict — common sense way
  // to get players playing at A+"): PROMOTION still requires the top-third bar
  // above, but a player ALREADY AT a level only gets sent DOWN if he falls
  // below its BOTTOM third — a median guy HOLDS the job he has. Earn the jump,
  // don't lose the seat for being average. Ratings-only, same engine values —
  // just a looser bar for incumbency. Kills knife-edge yo-yoing and stops the
  // league's weak orgs from defining where a strong org's kids may stand.
  const HOLD_PCT = 1 / 3;
  const oHold = offenseFloors(hitters, { ...opts, pct: HOLD_PCT });
  const wFloors = waaFloors(hitters, { ...opts, pct: FIT_PCT_HIT });   // fillers: placed on WAA results
  const wHold = waaFloors(hitters, { ...opts, pct: HOLD_PCT });
  const pHold = pitcherFloors(pitchers, { ...opts, pct: HOLD_PCT });
  const rpHold = relieverFloors(pitchers, { ...opts, pct: HOLD_PCT });
  const holdLev = (p, val, holdFloors) => {
    let lev = p["Lev"];
    if (lev === "MLB") lev = "AAA";                 // MLB incumbency is the optimizer's call
    if (!isAffiliate(lev) || lev === "WL" || lev === "INT") return null;
    const f = holdFloors[lev];
    return (f != null && val != null && val >= f) ? lev : null;
  };
  const maxLev = (a, b) => (b && LEVEL_RANK[b] > LEVEL_RANK[a] ? b : a);
  // All owned players, including those currently in winter ball (Lev "WL") or
  // international / all-star duty (Lev "INT"): they're treated as ordinary minor
  // leaguers and placed at whatever level their ability fits, same as everyone
  // else. (Their actual WL/INT status is surfaced as a badge in the UI.)
  // WL is the league's lowest regular rung — the floor for everyone — with INT (the
  // international complex) one rung below it, reachable only by international-signed
  // players. floorRank = the higher of that holding floor and the player's AGE floor
  // (he can't sit on a rung he's too old for), and it guards both initial placement
  // AND the cascade. Promotion = a player whose ability places him above his current
  // level (↑ tag).
  // WL is NOT a summer placement level any more (user, 2026-08-30): the Winter
  // League plays at a different time of year and its roster overlays the
  // summer system (built separately below). R- is the summer floor for
  // everyone except international-complex players.
  const minLev = (p) => (p["Lev"] === "INT" ? "INT" : "R-");
  const floorRankOf = (p, age) => Math.max(LEVEL_RANK[minLev(p)], ageFloorRank(age));
  // Prospect arm = young with a chance; everyone else is a filler arm. Young
  // = 26 or under (turn-27 rule, DEV data, 2026-09-24; was 24). A chance =
  // not noChance (MLB % under 5% with Proj Potential under -1.0, user
  // 2026-09-24). The old "pot > 1.0" bar is gone: it dates from when pot
  // was the listed WAP; Proj Potential and the DEV shares replace it, and
  // the chance-first order below ranks the prospects among themselves.
  // Defined here because the play scores below need them: a filler arm gets
  // no something bonus.
  const isProspectArm = (x) => (x.age ?? 99) <= 26 && !noChance(x.p, x.pot);
  const isFillerArm = (x) => !isProspectArm(x);
  const chanceRec = (x) => x.chance || (x.chance = chanceOf(x.p, x.isPitcher));
  // Chance-first order for a staff (user, 2026-09-24): prospects first, by
  // MLB %, then Starter %, Star %, Proj Potential, then `tie` (the win+grow
  // blend); fillers after every prospect, by what they are worth NOW in the
  // role (`nowOf`). The same key builds rotations and pens.
  const chanceCmp = (nowOf, tie) => (a, b) => {
    const pa = isProspectArm(a), pb = isProspectArm(b);
    if (pa !== pb) return pa ? -1 : 1;
    if (!pa) return (nowOf(b) ?? -99) - (nowOf(a) ?? -99);
    const ca = chanceRec(a), cb = chanceRec(b);
    return (cb.mlb - ca.mlb) || ((cb.useful ?? 0) - (ca.useful ?? 0)) || ((cb.good ?? 0) - (ca.good ?? 0))
      || ((b.pot ?? -99) - (a.pot ?? -99)) || (tie(b) - tie(a));
  };
  // The same order as one number, for the fill passes that score a candidate:
  // a prospect = 1000 + 100 x MLB % + 10 x Starter % + 5 x Star % + Proj
  // Potential (always above a filler); a filler = what he is worth now in
  // the role.
  const chanceScore = (nowOf) => (x) => {
    if (!isProspectArm(x)) return nowOf(x) ?? -99;
    const c = chanceRec(x);
    return 1000 + 100 * c.mlb + 10 * (c.useful ?? 0) + 5 * (c.good ?? 0) + (x.pot ?? -99);
  };
  const H = hitters.filter((p) => p["ORG"] === org).map((p) => {
    const cur = currentValue(p, false), pot = potentialValue(p, false), woba = num(p["wOBA wtd"]), age = num(p["Age"]);
    // Placed where his CURRENT bat fits (median of the level), no reach: a hitter who
    // can't hit the level gets buried; one too good for it wastes the rep.
    // Placement basis: a developing hitter goes where his BAT holds up (the
    // hit gate); a filler (dev done) goes where his WAA helps win games.
    const filler = isFillerBat({ p, age, pot, cur });
    const ceiling = filler
      ? maxLev(highestClearing(cur, wFloors, minLev(p)) || minLev(p), holdLev(p, cur, wHold))
      : maxLev(highestClearing(woba, oFloors, minLev(p)) || minLev(p), holdLev(p, woba, oHold));
    // play = win+grow blend, plus the something bonus for a prospect (never a
    // filler): chance first, the guys who have one play (user, 2026-09-24).
    // chance = the MLB / Starter / Star chances (or the stand-in) for the card.
    return { p, isPitcher: false, cur, pot, woba, age,
             priority: (pot != null ? pot : cur) ?? -99, play: blendScore(cur, pot) + (filler ? 0 : somethingBonus(p)),
             chance: chanceOf(p, false),
             ceiling,
             floorRank: floorRankOf(p, age), bestPos: bestPosition(p) };
  });
  const P = pitchers.filter((p) => p["ORG"] === org).map((p) => {
    const cur = currentValue(p, true), pot = potentialValue(p, true), age = num(p["Age"]);
    // Level fit is judged on the role he'll DEVELOP in (a future starter on his STARTER
    // line, not the relief line he won't throw) and placed exactly at that ability — NO
    // reach. Overplacing a starter-prospect gets him shelled and tanks his potential; he
    // develops by succeeding where he belongs, then earning the next rung. role = MLB
    // usage (best-projected); devRole = how he's developed (starter-capable arm starts).
    // play = win+grow blend, plus the something bonus for a prospect arm (never
    // a filler arm); it is the last tiebreak of the chance-first rotation
    // order (user, 2026-09-24). chance = the shares (or the stand-in).
    return { p, isPitcher: true, cur, pot, age,
             priority: (pot != null ? pot : cur) ?? -99, play: blendScore(cur, pot) + (isProspectArm({ p, age, pot }) ? somethingBonus(p) : 0),
             chance: chanceOf(p, true),
             spPot: num(p["WAP"]),   // SP potential (WAP), kept for display; it no longer decides who starts (chance first, user 2026-09-24)
             ceiling: maxLev(highestClearing(devRoleValue(p), pFloors, minLev(p)) || minLev(p), holdLev(p, devRoleValue(p), pHold)),
             floorRank: floorRankOf(p, age),
             role: pitcherRole(p), devRole: pitcherRole(p, { developmental: true }) };
  });

  const usedH = new Set(), usedP = new Set();
  const levels = {};

  // ---- MLB: the actual team — EXACTLY the Roster Optimizer's answer ----
  // One brain for the big-league club: the same optimizeRoster call that powers
  // the Roster Optimizer page and Team Projections also builds this card
  // (blended vR/vL platoon objective, exact position assignment, bench
  // contract, rotation by SP line / pen by RP line). The org builder used to
  // re-derive the lineup with its own greedy fill and role rules, and the two
  // screens disagreed on lineups and depth (user, 2026-08-26). The card shows
  // the optimizer's EVERYDAY nine (weighted assignment of the final 13); the
  // vR/vL platoon lineups live on the Roster Optimizer page.
  {
    const key = (row) => String(row?.["ID"] ?? row?.["Name"] ?? "");
    const HM = new Map(H.map((r) => [key(r.p), r]));
    const PM = new Map(P.map((r) => [key(r.p), r]));
    let done = false;
    try {
      const R = optimizeRoster(hitters, pitchers, {
        teamOrg: org, league: opts.league || null, vrShare: opts.vrShare ?? null,
      });
      const roster = [], gaps = [];
      const seen = new Set();
      for (const [pos] of MLB_STARTER_SLOTS) {
        const rec = HM.get(key(R.starters?.[pos]));
        // seen guard: key() falls back to Name when ID is missing, so two
        // same-name ID-less players would collapse to one rec — never place
        // the same rec at two slots (the twin falls to the minors instead).
        if (rec && !seen.has(rec)) { rec.slot = pos; rec.slotPos = pos; seen.add(rec); roster.push(rec); usedH.add(rec); }
        else gaps.push(pos);
      }
      const bench = [];
      const pushBench = (row, label, pos = null) => {
        const rec = HM.get(key(row));
        if (!rec || seen.has(rec)) return;
        // pos = the position this bench ROLE covers, so the row can show the
        // WAA where he'd actually play (BU C -> his C line, UTIL IF -> SS).
        rec.slot = label; rec.slotPos = pos; seen.add(rec); bench.push(rec); usedH.add(rec);
      };
      pushBench(R.bench?.backupC, "BU C", "C");
      pushBench(R.bench?.utilityIF, "UTIL IF", "SS");
      pushBench(R.bench?.utilityOF, "UTIL OF", "CF");
      pushBench(R.bench?.flexBat, "BEST");
      for (const x of R.bench?.extraBench || []) pushBench(x, "DEPTH");
      const sp = (R.startingPitchers || []).map((row) => PM.get(key(row))).filter(Boolean);
      const rp = (R.reliefPitchers || []).map((row) => PM.get(key(row))).filter(Boolean);
      [...sp, ...rp].forEach((x) => usedP.add(x));
      levels.MLB = { SP: sp, RP: rp, hitters: roster, bench, gaps, counts: cnt(sp, rp, roster, bench) };
      done = true;
    } catch (e) {
      console.warn(`orgBuilder: optimizeRoster failed for ${org} — legacy MLB fill used`, e);
    }
    if (!done) {
      // Legacy fallback only (kept so one bad org can't blank the card):
      // rotation from starter-capable arms by SP line, pen by RP line, greedy
      // hardest-position-first lineup fill.
      const spLine = (x) => num(x.p["WAA wtd"]);
      const rpLine = (x) => num(x.p["WAA wtd RP"]);
      const sp = P.filter((x) => x.devRole === "SP" && spLine(x) !== null)
        .sort((a, b) => (spLine(b) ?? -99) - (spLine(a) ?? -99)).slice(0, 5);
      const spSet = new Set(sp);
      const rp = P.filter((x) => !spSet.has(x) && rpLine(x) !== null)
        .sort((a, b) => (rpLine(b) ?? -99) - (rpLine(a) ?? -99)).slice(0, 8);
      [...sp, ...rp].forEach((x) => usedP.add(x));
      const used = new Set();
      const vf = (h, pos) => posWAA(h.p, pos) ?? h.cur ?? -99;
      const { roster, gaps } = fillSlots(H, MLB_STARTER_SLOTS, used, vf);
      const { roster: bench } = fillSlots(H, MLB_BENCH_SLOTS, used, vf);
      [...roster, ...bench].forEach((h) => usedH.add(h));
      levels.MLB = { SP: sp, RP: rp, hitters: roster, bench, gaps, counts: cnt(sp, rp, roster, bench) };
    }
  }

  // ---- Minors: remaining players, hit-gated + development-prioritized ----
  const minors = LEVELS.filter((l) => l !== "MLB");           // R- .. AAA
  const cap = (c) => (c === "MLB" ? "AAA" : (c || "INT"));     // not-on-MLB tops out at AAA; default floor is INT (lowest)
  const hBy = {}; for (const l of minors) hBy[l] = [];
  // Bucket at the ability ceiling, but NEVER below the player's floor. A too-weak-but-
  // age-floored player (his bat fits a level he's too old for) lands at his floor as a
  // filler rather than vanishing to depth — a 20-yo with a 60 glove belongs on the R-
  // bench, not in a void. (cap() already holds non-MLB ceilings to AAA.)
  const bucketOf = (rec) => LEVELS[Math.max(LEVEL_RANK[cap(rec.ceiling)], rec.floorRank)];
  for (const h of H) if (!usedH.has(h)) { const b = bucketOf(h); if (b) hBy[b].push(h); }

  // ===== PITCHERS — two passes. All SPs are RP-eligible; not all RPs can start. =====
  // The RELIEF line for ANY arm (a leftover starter is judged as the reliever he'd be).
  const rpCur = (x) => num(x.p["WAA wtd RP"]);
  const rpPotV = (x) => num(x.p["WAP RP"]);
  // Pen order = chance first (user, 2026-09-24): prospect arms by MLB %,
  // Starter %, Star %, Proj Potential, then the RP win+grow blend; filler
  // arms after every prospect, by their relief line now. rpOrder sorts a
  // pen; rpPlay is the same order as one number for the fill passes.
  const rpOrder = chanceCmp(rpCur, (x) => blendScore(rpCur(x), rpPotV(x)));
  const rpPlay = chanceScore(rpCur);
  // Rotation order, same rule on the SP line: spNow = his starter line now.
  const spNow = (x) => num(x.p["WAA wtd"]) ?? x.cur;
  const spOrder = chanceCmp(spNow, (x) => x.play);
  const spScore = chanceScore(spNow);
  const rpCeil = (x) => maxLev(
    highestClearing(rpCur(x), rpFloors, minLev(x.p)) || minLev(x.p),
    holdLev(x.p, rpCur(x), rpHold)   // hysteresis: a median pen arm HOLDS his current level
  );

  // Pass 1 — SP rotations: the best SP-potential arms start; a blocked starter cascades
  // DOWN to keep starting at a level he fits, and only leaves the rotation track if he
  // can't crack ANY rotation. Relief-only arms (can't start) sit this pass out.
  const spBy = {}; for (const l of minors) spBy[l] = [];
  for (const x of P) if (!usedP.has(x) && x.devRole === "SP") { const b = bucketOf(x); if (b) spBy[b].push(x); }
  const SProt = {};
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], down = li > 0 ? minors[li - 1] : null, dr = down ? LEVEL_RANK[down] : -1;
    if (L === "WL") { SProt[L] = []; continue; }   // WL = overlay, built after the summer system
    // Rotation order = CHANCE first (user, 2026-09-24): prospect arms by
    // MLB %, then Starter %, Star %, Proj Potential, then the win+grow blend;
    // filler arms (no chance, or 27+) after every prospect, by their SP line
    // now. The old order was SP potential (WAP) first; WAP was the listed
    // potential and said nothing about whether he ever gets there ("if a
    // guy is 26 ... and they arent close to making it then whats the point").
    const sp = spBy[L].sort(spOrder);
    SProt[L] = sp.slice(0, 6); SProt[L].forEach((x) => usedP.add(x));
    // Cascade overflow down. A YOUNG starter-capable arm (dev not done) KEEPS
    // STARTING — he cascades rotation to rotation all the way to his age floor
    // before ever converting to relief (user, 2026-08-30: "we aren't
    // developing him as a starter if he's at A- as an RP" — Rocha case). A
    // 27+ arm (turn-27 rule, DEV data, 2026-09-24) gets one rung, then
    // converts to relief at his own ability (Pass 2): his development is
    // over, the pen is his honest job. The old one-rung-for-everyone guard
    // existed to stop multi-level slides into WL rotations; WL left the
    // summer chain, and age floors still bound the slide.
    if (down) for (const x of sp.slice(6)) if (dr >= x.floorRank && (!x._spDropped || (x.age ?? 99) < 27)) { x._spDropped = true; spBy[down].push(x); }
  }

  // Pass 2 — RP bullpens: everyone still unplaced. The lower-ceiling starters who never
  // cracked a rotation CONVERT to relief (a future as a reliever instead of rotting in
  // depth) and compete with the relief-only arms, ranked by RP potential, placed where
  // their relief arm fits with overflow cascading down. Fills the pens from the surplus.
  const rpBy = {}; for (const l of minors) rpBy[l] = [];
  for (const x of P) if (!usedP.has(x)) { const cr = LEVEL_RANK[cap(rpCeil(x))]; if (cr >= x.floorRank) rpBy[LEVELS[cr]].push(x); }
  const RPpen = {};
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], down = li > 0 ? minors[li - 1] : null, dr = down ? LEVEL_RANK[down] : -1;
    if (L === "WL") { RPpen[L] = []; continue; }   // WL = overlay
    const rp = rpBy[L].sort(rpOrder);   // chance first (user, 2026-09-24)
    RPpen[L] = rp.slice(0, 9); RPpen[L].forEach((x) => usedP.add(x));
    if (down) for (const x of rp.slice(9)) if (dr >= x.floorRank) rpBy[down].push(x);
  }

  // Pass 3 — completeness backfill. Prospects sit exactly at their ability (overplacing a
  // real future tanks it). But a FILLER (old or low-ceiling, no future to protect) may
  // stretch UP one rung to finish a roster — a no-future arm eating innings a level up
  // costs nothing. Top-down, so a filler pulled up leaves a vacancy the level below fills
  // next; the shortage lands at the bottom, absorbed by the young depth arms. SP slots
  // only take startable arms (all SPs are RP-eligible, not vice-versa). Stretched arms get
  // an `_stretch` flag so the UI can mark them as roster-fillers, not true level talent.
  const SP_TARGET = 6, RP_TARGET = 9;
  // isProspectArm / isFillerArm (young with a chance, or not) are defined
  // above the H/P records now; the play scores need them.
  // 27+ = development is over (the turn-27 rule, DEV data, 2026-09-24; it was
  // the turn-25 rule): the ONLY guys who should travel long distances as
  // roster fillers; a young low-pot arm still belongs near his own level
  // (user, 2026-08-30).
  const devDone = (x) => (x.age ?? 99) >= 27;
  // Fill preference (user, 2026-08-30, FINAL): "never place young players as
  // fillers, period: at A+ and higher."
  // At A+/AA/AAA only 27+ dev-done players fill/stash; below A+ young
  // no-future fillers may also move, and a cut-bound youngster may take a LOW
  // seat before hitting the street. A high seat nobody 27+ can take stays
  // open ("not enough players"): accepted.
  const fillPrefs = (lr) => lr >= LEVEL_RANK["A+"]
    ? [(x) => isFillerArm(x) && devDone(x)]
    : [(x) => isFillerArm(x) && devDone(x), isFillerArm];
  let unplaced = P.filter((x) => !usedP.has(x));
  const borrowFiller = (staff, prefs) => {                  // weakest allowed filler from a staff, for the chain
    for (const pref of prefs) {
      let wi = -1, wv = Infinity;
      for (let i = 0; i < staff.length; i++) { if (!pref(staff[i])) continue; const v = staff[i].pot ?? staff[i].cur ?? -99; if (v < wv) { wv = v; wi = i; } }
      if (wi >= 0) return staff.splice(wi, 1)[0];
    }
    return null;
  };
  const fillStaff = (staff, belowStaff, target, lr, ceilOf, scoreOf, roleOk, L) => {
    while (staff.length < target) {
      let cand = null, ci = -1;
      // allowed filler tiers for this level (27+ only at A+ and above), and
      // still at most a one-rung stretch in this pass.
      for (const pref of fillPrefs(lr)) {
        let cs = -Infinity;
        for (let i = 0; i < unplaced.length; i++) {
          const x = unplaced[i];
          if (!pref(x) || !roleOk(x) || x.floorRank > lr) continue;
          const r = LEVEL_RANK[ceilOf(x)];
          if (r < lr - 1 || r > lr) continue;               // at most a one-rung stretch up
          const s = scoreOf(x); if (s > cs) { cs = s; cand = x; ci = i; }
        }
        if (cand) break;
      }
      if (cand) { unplaced.splice(ci, 1); usedP.add(cand); }
      else if (belowStaff) cand = borrowFiller(belowStaff, fillPrefs(lr));   // chain: pull an allowed filler up from the level below
      if (!cand) break;
      if (LEVEL_RANK[ceilOf(cand)] < lr) cand._stretch = L;    // flag the overplacement
      staff.push(cand); usedP.add(cand);
    }
  };
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], lr = LEVEL_RANK[L], below = li > 0 ? minors[li - 1] : null;
    if (L === "WL") continue;   // WL = overlay, never force-filled
    fillStaff(SProt[L], below ? SProt[below] : null, SP_TARGET, lr, (x) => x.ceiling, (x) => x.cur ?? -99, (x) => x.devRole === "SP", L);
    fillStaff(RPpen[L], below ? RPpen[below] : null, RP_TARGET, lr, (x) => cap(rpCeil(x)), (x) => rpPlay(x), () => true, L);
  }

  // Pass 4 — HARD staffing minimums (user rule, 2026-08-30): every minor
  // system must carry at least 6 SP and 8 RP after MLB takes its best 26.
  // The pass above stretches only no-future fillers, at most one rung — a thin
  // level could stay short. Here a still-short staff takes ANY unplaced arm
  // the age floor allows (multi-rung stretches flagged), preferring fillers
  // and touching prospects only as the last resort (overplacing a real future
  // costs development, but a 4-man pen costs the whole level). A shortage
  // that survives this means the org genuinely has no more arms — the card's
  // "need N" note then says so honestly.
  // WL is exempt: the Winter League literally plays at a different time of
  // year than every other level (user, 2026-08-30), so it needs no staffed
  // roster during the season — it can run empty. INT is exempt too — the
  // complex is a holding pool, not a staffed affiliate; the hard pass would
  // otherwise drag arms DOWN into it.
  const SP_MIN = 6, RP_MIN = 8;
  const HARD_MIN_EXEMPT = new Set(["WL", "INT"]);
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], lr = LEVEL_RANK[L];
    if (HARD_MIN_EXEMPT.has(L)) continue;
    for (const [staff, min, roleOk, ceilOf, scoreOf] of [
      [SProt[L], SP_MIN, (x) => x.devRole === "SP", (x) => x.ceiling, spScore],   // chance first, not WAP first (user, 2026-09-24)
      [RPpen[L], RP_MIN, () => true, (x) => cap(rpCeil(x)), rpPlay],
    ]) {
      // candidate sources, in preference order: unplaced arms; the WL card
      // (Winter League plays at a DIFFERENT time of year — a WL spot must
      // never starve a summer affiliate); then LOWER affiliate staffs,
      // nearest level first — pulling up cascades the vacancy downward, and
      // the loop refills each lower level in turn, so any true shortage
      // lands at the bottom of the system instead of stranding AA at 1 RP.
      const sources = [unplaced, SProt["WL"] || [], RPpen["WL"] || []];
      for (let lj = li - 1; lj >= 0; lj--) {
        const LL = minors[lj];
        if (HARD_MIN_EXEMPT.has(LL)) continue;
        sources.push(SProt[LL], RPpen[LL]);
      }
      // filler tiers over every source; BELOW A+ only, a last resort over the
      // UNPLACED pool (a cut-bound young arm may fill a LOW hole — never a
      // high one). Nobody is pulled off a lower roster except via the tiers.
      const tiers = fillPrefs(lr).map((pref) => ({ pref, srcs: sources }));
      if (lr < LEVEL_RANK["A+"]) tiers.push({ pref: () => true, srcs: [unplaced] });
      for (const { pref, srcs } of tiers) {
        while (staff.length < min) {
          let cand = null, pool = null, ci = -1, cs = -Infinity;
          for (const src of srcs) {
            for (let i = 0; i < src.length; i++) {
              const x = src[i];
              if (!roleOk(x) || x.floorRank > lr || !pref(x)) continue;
              const s = scoreOf(x); if (s > cs) { cs = s; cand = x; ci = i; pool = src; }
            }
            if (cand) break;   // take from the closest source that has anyone
          }
          if (!cand) break;
          pool.splice(ci, 1);
          if (LEVEL_RANK[ceilOf(cand)] < lr) cand._stretch = L;
          staff.push(cand); usedP.add(cand);
        }
        if (staff.length >= min) break;
      }
    }
  }

  // ===== HITTERS per level (reads the SP/RP staffs built above) =====
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], down = li > 0 ? minors[li - 1] : null, dr = down ? LEVEL_RANK[down] : -1;
    if (L === "WL") continue;   // WL card = overlay, built after all summer passes
    const SP = SProt[L], RP = RPpen[L];
    const used = new Set();
    const pool = hBy[L].slice().sort((a, b) => b.play - a.play);          // best win+grow blend first
    // Starters get the most reps — chosen on the win+grow blend (emphasis win).
    const { roster, gaps } = assignLineup(pool, MINOR_LINEUP, used, minorSlotScore);
    // Bench fills position-coverage first (backup C / 2 IF / 2 OF) plus a few win-now bats —
    // a MODEST size, not the whole cap. The leftover roster-cap room is handed to the
    // development-depth pass to allocate by youth/ceiling (young arms vs. extra bats), so the
    // bench doesn't hog every spot and bury the lottery-ticket arms in cuts.
    const benchTarget = Math.max(5, Math.min(9, (MINOR_ROSTER_CAP[L] ?? 99) - SP.length - RP.length - MINOR_SLOTS.length));
    const { bench, need } = fillMinorBench(pool, used, benchTarget);
    addCaptainIfMissing(roster, bench, [...SP, ...RP], pool, used);
    if (down) for (const h of pool) if (!used.has(h) && dr >= h.floorRank) hBy[down].push(h);   // logjam extras cascade down (split)
    [...roster, ...bench].forEach((h) => usedH.add(h));   // sync placed minor hitters to the global set so the backfills don't re-grab them
    // INT is a holding complex for international signees — "sign a filler"
    // advice there is nonsense; its lineup shows whoever the complex holds.
    levels[L] = { SP, RP, hitters: roster, bench, gaps: L === "INT" ? [] : gaps, _benchNeed: need, counts: cnt(SP, RP, roster, bench) };
  }

  // Hitter completeness backfills (after the per-level loop). One shared unplaced pool —
  // LINEUPS fill FIRST (starters are the priority), then benches get the remainder.
  let unplacedH2 = H.filter((h) => !usedH.has(h));

  // (1) Lineup completeness — fill any empty lineup slot the level's own pool couldn't
  // cover from an age-relevant FILLER (never a prospect) who can play it, else chain from
  // the level below's bench. One-rung stretch, flagged, cap-bounded.
  const slotElig = Object.fromEntries(MINOR_SLOTS.map(([label, elig]) => [label, elig]));
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], lr = LEVEL_RANK[L], below = li > 0 ? minors[li - 1] : null;
    const lv = levels[L]; if (!lv || !lv.gaps || !lv.gaps.length) continue;
    const rosterCap = MINOR_ROSTER_CAP[L] ?? 99;
    const total = () => lv.SP.length + lv.RP.length + lv.hitters.length + lv.bench.length;
    const remaining = [];
    for (const slot of lv.gaps) {
      if (total() >= rosterCap) { remaining.push(slot); continue; }
      const eg = slotElig[slot] || [slot];
      // Fill from the ALLOWED filler tiers only (27+ dev-done only at A+ and
      // above; below A+ a young low-pot filler may also move; prospects are
      // never fill material). An org that can't supply an allowed body shows
      // "not enough players" — that's on them (user, 2026-08-30, Baltimore).
      // Then the borrow chain walks every lower level's bench, nearest first.
      let cand = null, ci = -1;
      const prefs = fillPrefs(lr);
      // unplaced pool: filler tiers; BELOW A+ a cut-bound bat may also fill
      // (young players never fill at A+ and higher — user rule)
      for (const pref of (lr < LEVEL_RANK["A+"] ? [...prefs, () => true] : prefs)) {
        let cs = -Infinity;
        for (let i = 0; i < unplacedH2.length; i++) {
          const x = unplacedH2[i];
          if (!pref(x) || x.floorRank > lr || !eg.some((pos) => eligibleAt(x.p, pos))) continue;
          const s = bestSlotScore(x, eg)[0]; if (s > cs) { cs = s; cand = x; ci = i; }
        }
        if (cand) break;
      }
      if (cand) { unplacedH2.splice(ci, 1); usedH.add(cand); }
      else {
        for (const pref of prefs) {
          for (let lj = li - 1; lj >= 0 && !cand; lj--) {
            const blv = levels[minors[lj]]; if (!blv) continue;   // WL/INT have no summer bench to raid
            const bb = blv.bench;
            let wi = -1, wv = Infinity;
            for (let i = 0; i < bb.length; i++) {
              if (!pref(bb[i]) || !eg.some((pos) => eligibleAt(bb[i].p, pos))) continue;
              const v = -bestSlotScore(bb[i], eg)[0]; if (v < wv) { wv = v; wi = i; }   // best at the slot
            }
            if (wi >= 0) cand = bb.splice(wi, 1)[0];
          }
          if (cand) break;
        }
      }
      // Last: pull a 27+ filler STARTER up from a lower lineup (nearest level
      // first). His old slot becomes a gap there, filled when the loop reaches
      // that level, so a true shortage lands at the bottom of the system.
      if (!cand) {
        for (let lj = li - 1; lj >= 0 && !cand; lj--) {
          const L2 = minors[lj], blv = levels[L2];
          if (!blv || L2 === "WL" || L2 === "INT") continue;
          let bi = -1, bv = -Infinity;
          for (let i = 0; i < blv.hitters.length; i++) {
            const x = blv.hitters[i];
            if (!devDone(x) || x.slot === "C" || !eg.some((pos) => eligibleAt(x.p, pos))) continue;
            const v = bestSlotScore(x, eg)[0]; if (v > bv) { bv = v; bi = i; }
          }
          if (bi >= 0) {
            cand = blv.hitters.splice(bi, 1)[0];
            blv.gaps.push(cand.slot);
            blv.counts = cnt(blv.SP, blv.RP, blv.hitters, blv.bench);
          }
        }
      }
      if (!cand) { remaining.push(slot); continue; }
      cand.slot = slot; cand.slotPos = bestSlotScore(cand, eg)[1] || eg.find((pos) => eligibleAt(cand.p, pos)) || slot;
      if (LEVEL_RANK[cand.ceiling] < lr) cand._stretch = L;
      lv.hitters.push(cand); usedH.add(cand);
    }
    lv.gaps = remaining;
    lv.counts = cnt(lv.SP, lv.RP, lv.hitters, lv.bench);
  }

  // (2) Bench completeness — guarantee a backup C, two IF and two OF at every level (the
  // user's minimum) from the REMAINING unplaced fillers (never prospects), else chain from
  // the level below's bench. Bounded by the roster cap; stretched fillers flagged.
  const benchNeedNow = (bench) => ({
    C: Math.max(0, 1 - bench.filter((x) => benchEligAt(x.p, "C")).length),
    IF: Math.max(0, 2 - bench.filter((x) => benchEligAt(x.p, "IF")).length),
    OF: Math.max(0, 2 - bench.filter((x) => benchEligAt(x.p, "OF")).length),
  });
  for (let li = minors.length - 1; li >= 0; li--) {
    const L = minors[li], lr = LEVEL_RANK[L], below = li > 0 ? minors[li - 1] : null;
    const lv = levels[L]; if (!lv) continue;
    const rosterCap = MINOR_ROSTER_CAP[L] ?? 99;
    const total = () => lv.SP.length + lv.RP.length + lv.hitters.length + lv.bench.length;
    for (const grp of ["C", "IF", "OF"]) {
      while (benchNeedNow(lv.bench)[grp] > 0 && total() < rosterCap) {
        let cand = null, ci = -1;
        // filler tiers, then anyone-from-unplaced (cut-bound bats cover bench
        // needs before hitting the street; the one-rung limit only binds the
        // filler tiers — a cut-bound bat can travel). CATCHERS are exempt from
        // the rung limit entirely (user, 2026-08-30: "we don't have a catcher
        // shortage" — 26 mitts for 14 jobs; a backup C's job is the mitt, so
        // any allowed catcher body may travel any distance).
        const anyDistance = grp === "C";
        const benchTiers = fillPrefs(lr).map((pref) => ({ pref, anyone: false }));
        if (lr < LEVEL_RANK["A+"]) benchTiers.push({ pref: () => true, anyone: true });
        for (const { pref, anyone } of benchTiers) {
          let cs = -Infinity;
          for (let i = 0; i < unplacedH2.length; i++) {
            const x = unplacedH2[i];
            if (!pref(x) || x.floorRank > lr || !benchEligAt(x.p, grp)) continue;
            const r = LEVEL_RANK[cap(x.ceiling)];
            if (!anyone && !anyDistance && (r < lr - 1 || r > lr)) continue;   // one-rung limit (non-catchers)
            const s = benchScore(x); if (s > cs) { cs = s; cand = x; ci = i; }
          }
          if (cand) break;
        }
        if (cand) { unplacedH2.splice(ci, 1); usedH.add(cand); }
        else {
          // borrow chain: catchers walk EVERY lower bench (nearest first);
          // other groups keep the one-level chain.
          const chain = anyDistance
            ? Array.from({ length: li }, (_, k) => minors[li - 1 - k]).filter((L2) => levels[L2])
            : (below && levels[below] ? [below] : []);
          for (const pref of fillPrefs(lr)) {
            for (const L2 of chain) {
              const bb = levels[L2].bench;
              let wi = -1, wv = Infinity;
              for (let i = 0; i < bb.length; i++) { if (!pref(bb[i]) || !benchEligAt(bb[i].p, grp)) continue; const v = benchScore(bb[i]); if (v < wv) { wv = v; wi = i; } }
              if (wi >= 0) { cand = bb.splice(wi, 1)[0]; break; }
            }
            if (cand) break;
          }
        }
        if (!cand) break;
        if (LEVEL_RANK[cand.ceiling] < lr) cand._stretch = L;
        lv.bench.push(cand); usedH.add(cand);
      }
    }
    // Backup C must be an actual BENCH catcher (user: "it can't be the person
    // starting at DH or 1B"). The import loop above tries 27+ mitts first:
    // benches are for dev-done guys. LAST RESORT, when no old catcher exists
    // anywhere: swap a catcher-eligible DH/1B starter to the bench and start
    // the bench's best bat in his slot (a young catcher losing reps beats an
    // empty backup job — barely; user: Varela is young and should develop).
    if (benchNeedNow(lv.bench).C > 0) {
      // Any non-C slot counts (the exact lineup can put a 2nd catcher in LF).
      // Bench a filler catcher before a prospect; the replacement is the bench
      // bat worth the most AT THAT SLOT.
      let best = null;
      for (let ci2 = 0; ci2 < lv.hitters.length; ci2++) {
        const cRec = lv.hitters[ci2];
        if (cRec.slot === "C" || !benchEligAt(cRec.p, "C")) continue;
        const slotPos = cRec.slotPos || cRec.slot;
        let bi = -1, bv = -Infinity;
        for (let i = 0; i < lv.bench.length; i++) {
          const b = lv.bench[i];
          if (benchEligAt(b.p, "C")) continue;               // don't burn another catcher on the swap
          if (!eligibleAt(b.p, slotPos)) continue;
          const s = minorSlotScore(b, slotPos) ?? -99; if (s > bv) { bv = s; bi = i; }
        }
        if (bi < 0) continue;
        const key = [isFillerBat(cRec) ? 0 : 1, (minorSlotScore(cRec, slotPos) ?? -99) - bv];
        if (!best || key[0] < best.key[0] || (key[0] === best.key[0] && key[1] < best.key[1])) best = { ci2, bi, key };
      }
      if (best) {
        const { ci2, bi } = best;
        const cRec = lv.hitters[ci2], bat = lv.bench[bi];
        const slot = cRec.slot, slotPos = cRec.slotPos || cRec.slot;
        bat.slot = slot; bat.slotPos = slotPos;
        cRec.slot = "BN"; cRec.slotPos = "C";
        lv.hitters[ci2] = bat; lv.bench[bi] = cRec;
      }
    }
    // HARD requirement (user, 2026-08-30): every minors level carries a
    // catcher ON THE BENCH — a second catcher starting at DH/1B does NOT count.
    if (L !== "WL" && L !== "INT" && benchNeedNow(lv.bench).C > 0 && !lv.gaps.includes("BU C")) {
      lv.gaps.push("BU C");
    }
    // User rule (2026-08-30, Hernández/Horiuchi case): a YOUNG bench C should
    // be STARTING one level down instead: swap him with a 27+ starting C
    // from the nearest level below. The vet takes the bench job up here (his
    // development is over; reps beat level for the kid's).
    if (L !== "WL" && L !== "INT") {
      const bi2 = lv.bench.findIndex((x) => benchEligAt(x.p, "C") && !isFillerBat(x));
      if (bi2 >= 0) {
        for (let lj = li - 1; lj >= 0; lj--) {
          const L2 = minors[lj], lv2 = levels[L2];
          if (!lv2 || L2 === "WL" || L2 === "INT") continue;
          const si = lv2.hitters.findIndex((x) => x.slot === "C" && (x.age ?? 99) >= 27);
          if (si < 0) continue;
          const young = lv.bench[bi2], vet = lv2.hitters[si];
          vet.slot = "BN"; vet.slotPos = "C";
          young.slot = "C"; young.slotPos = "C";
          lv.bench[bi2] = vet; lv2.hitters[si] = young;
          lv2.counts = cnt(lv2.SP, lv2.RP, lv2.hitters, lv2.bench);
          break;
        }
      }
    }
    // Advisory (user: real growth is not defined solely by potential rating —
    // benching ANY under-27 costs development; turn-27 rule, DEV data,
    // 2026-09-24): when an upper-minors bench C
    // is STILL young after the swap above (no vet starter below to trade with),
    // say the action out loud: one veteran catcher signing frees him.
    if (L !== "WL" && L !== "INT" && lr >= LEVEL_RANK["A+"]) {
      const bc = lv.bench.find((x) => benchEligAt(x.p, "C"));
      if (bc && !isFillerBat(bc) && !lv.gaps.some((g) => g.startsWith("BU C"))) {
        lv.gaps.push("BU C is " + (bc.age ?? "?") + " — to free him");
      }
    }
    lv.counts = cnt(lv.SP, lv.RP, lv.hitters, lv.bench);
  }

  // Fill each minor roster toward its cap (32/32/35/35/40/40/40) with AGE-APPROPRIATE
  // players only — a player is placed between his age floor and his ability ceiling, NEVER
  // below his floor (no 23-yo on the winter-league bench) and never above his ceiling. Best
  // Fill remaining roster spots STRICTLY by youth-weighted keep-value, regardless of position.
  // The core lineup/rotation/bullpen/bench are already set with their position minimums, so
  // depth is just "keep the best remaining lottery tickets that fit." No position cap here:
  // an earlier 18-arms-per-level soft cap was dropping a HIGHER-value young arm (Tavio Molina,
  // 21) and letting the level finish on LOWER-value bats — exactly the bad cut the user flagged.
  // keepValue (module level, above): Proj Potential + youthBonus, plus the
  // chance bonus for a prospect (2026-09-25), so the order is chance first. A
  // level that runs out of age-appropriate players just stays under cap.
  // What's left once maxed is the cut list; the Org page's cuts list uses the
  // same keepValue.
  const totalAt = (L) => levels[L].SP.length + levels[L].RP.length + levels[L].hitters.length + (levels[L].bench ? levels[L].bench.length : 0);
  {
    // User rule (2026-08-30): a 20-and-under with NO dev potential can live on
    // the WL card as a filler, so he takes a summer depth seat LAST, after
    // every player who needs the reps. But "at least doesn't mean at max":
    // with seats still open he fills one rather than being cut (WL only holds
    // 40; the org has room, use it).
    // "No dev potential" is decided by CHANCE since 2026-09-25 (user: "if you
    // think chance is better then yeah we can go with chance"): only a
    // no-chance U20 (noChance: MLB % under 5% and Proj Potential under -1)
    // goes last. The old test (Proj Potential <= 0) sent high-chance teen arms
    // to the cut list (Verhoeven 19 at 63% MLB, Taveras 20 at 60%, Akers 19 at
    // 57%) while 7-9% arms held R+ pen seats; after the ML most teens read
    // Proj Potential <= 0 because they are years from their peak.
    const noDevU20 = (x) => ((x.age ?? 99) <= 20 && noChance(x.p, x.pot)) ? 1 : 0;
    const pool = [...H, ...P].filter((x) => !(x.isPitcher ? usedP.has(x) : usedH.has(x)))
      .sort((a, b) => (noDevU20(a) - noDevU20(b)) || keepCmp(a, b));
    for (const x of pool) {
      for (let r = Math.max(LEVEL_RANK[cap(x.ceiling)], x.floorRank); r >= x.floorRank; r--) {   // floorRank = age floor; never below it
        const L = LEVELS[r];
        if (!levels[L] || L === "MLB") continue;
        if (totalAt(L) >= (MINOR_ROSTER_CAP[L] ?? 99)) continue;
        if (x.isPitcher) { levels[L].RP.push(x); usedP.add(x); } else { levels[L].bench.push(x); usedH.add(x); }
        x._devDepth = true;
        break;
      }
      if (x.isPitcher ? usedP.has(x) : usedH.has(x)) continue;
      // Keep-before-cut (user rules, FINAL): his own range is full. Rules for
      // who takes a distant open seat: 27+ dev-done players may stash at ANY
      // level; a YOUNG player may only take an open seat BELOW A+ himself, or
      // displace a weaker filler inside his own range — with the displaced
      // filler taking the distant seat ONLY if he's 27+ when that seat is at
      // A+ or above. "Never place young players as fillers at A+ and higher,
      // period." If none of that works, the youngster is a genuine cut (the
      // card's advice: sign a filler).
      const A_PLUS = LEVEL_RANK["A+"];
      const topRank = Math.max(LEVEL_RANK[cap(x.ceiling)], x.floorRank);
      const findOpen = (maxExcl) => {
        for (let r = topRank + 1; r < maxExcl; r++) {
          const L = LEVELS[r];
          if (!levels[L] || L === "WL") continue;
          if (totalAt(L) < (MINOR_ROSTER_CAP[L] ?? 99)) return L;
        }
        return null;
      };
      const seatAt = (rec, L, stretch) => {
        if (rec.isPitcher) { levels[L].RP.push(rec); usedP.add(rec); } else { levels[L].bench.push(rec); usedH.add(rec); }
        rec._devDepth = true; if (stretch) rec._stretch = L;
      };
      if (devDone(x)) {
        const open = findOpen(LEVEL_RANK["MLB"]);
        if (open) seatAt(x, open, true);
        continue;
      }
      const lowOpen = findOpen(Math.min(A_PLUS, LEVEL_RANK["MLB"]));   // seats a youngster may take himself
      const anyOpen = lowOpen || findOpen(LEVEL_RANK["MLB"]);
      if (!anyOpen) continue;   // no seat anywhere -> genuine cut
      const openHigh = LEVEL_RANK[anyOpen] >= A_PLUS;
      let disp = null, dispList = null, dispLev = null, di = -1, dv = Infinity;
      for (let r = topRank; r >= x.floorRank; r--) {
        const L = LEVELS[r], lv = levels[L];
        if (!lv || L === "MLB" || L === "WL") continue;
        const list = x.isPitcher ? lv.RP : lv.bench;
        for (let j = 0; j < list.length; j++) {
          const o = list[j];
          if (!isFillerArm(o)) continue;                    // never displace a prospect
          if (openHigh && !devDone(o)) continue;            // a high seat only takes a 27+ body
          const v = keepValue(o);
          if (v < keepValue(x) && v < dv) { dv = v; disp = o; dispList = list; dispLev = L; di = j; }
        }
      }
      if (disp) {
        dispList.splice(di, 1);
        seatAt(disp, anyOpen, true);                        // the dev-done guy makes the jump
        if (x.isPitcher) { levels[dispLev].RP.push(x); usedP.add(x); } else { levels[dispLev].bench.push(x); usedH.add(x); }
        x._devDepth = true;                                 // at his proper level — no stretch flag
      } else if (lowOpen) {
        seatAt(x, lowOpen, true);                           // a LOW seat he may take himself
      }
      // else: only high seats exist and no 27+ body to send, so he stays a cut.
    }
  }
  for (const L of minors) if (levels[L]) levels[L].counts = cnt(levels[L].SP, levels[L].RP, levels[L].hitters, levels[L].bench);

  // ---- WL OVERLAY (user rules, 2026-08-30) ----
  // The Winter League plays at a DIFFERENT time of year than every other
  // level, and a player can be rostered in the WL *and* at a summer affiliate
  // at the same time. So the WL card is an OVERLAY, not a placement: the
  // org's best age-20-and-under players by POTENTIAL winter here for extra
  // reps, without being consumed from any summer roster. Records are CLONED
  // so slot labels set here never clobber the summer cards'.
  {
    // Only leagues that actually HAVE a Winter League get the overlay (TGS
    // does; BLM has no WL level at all — never invent one for it).
    const leagueHasWL = hitters.some((p) => p["Lev"] === "WL") || pitchers.some((p) => p["Lev"] === "WL");
    const u20 = (x) => leagueHasWL && (x.age ?? 99) <= 20;
    const clone = (x) => ({ ...x });
    const arms = P.filter(u20);
    const SP = arms.filter((x) => x.devRole === "SP")
      .sort((a, b) => (b.spPot ?? -99) - (a.spPot ?? -99)).slice(0, 6).map(clone);
    const spIds = new Set(SP.map((x) => x.p["ID"]));
    const RP = arms.filter((x) => !spIds.has(x.p["ID"]))
      .sort((a, b) => (rpPotV(b) ?? -99) - (rpPotV(a) ?? -99)).slice(0, 9).map(clone);
    const bats = H.filter(u20)
      .sort((a, b) => (b.pot ?? b.cur ?? -99) - (a.pot ?? a.cur ?? -99)).map(clone);
    const used = new Set();
    const { roster, gaps } = fillSlots(bats, MINOR_SLOTS, used, (h) => h.pot ?? h.cur ?? -99);
    const capWL = MINOR_ROSTER_CAP.WL ?? 40;
    const room = Math.max(0, capWL - SP.length - RP.length - roster.length);
    const bench = bats.filter((h) => !used.has(h)).slice(0, room);
    levels.WL = { SP, RP, hitters: roster, bench,
                  // the WL overlay never nags "sign a filler" — it holds the
                  // best U20s the org HAS; an unfilled winter slot is not an
                  // actionable shortage (and a WL-less league shows nothing)
                  gaps: [],
                  counts: cnt(SP, RP, roster, bench) };
  }

  const placed = new Set();
  const placedAt = {};
  for (const l of LEVELS) for (const x of [...levels[l].SP, ...levels[l].RP, ...levels[l].hitters, ...(levels[l].bench || [])]) { placed.add(x.p["ID"]); placedAt[x.p["ID"]] = l; }
  const depth = [...H, ...P].filter((x) => !placed.has(x.p["ID"]));

  // Promote / overmatched lists derive from the SAME placement as the cards, so the
  // summary panels can never contradict them: a player whose ability placed him ABOVE
  // his current OOTP level is a promote (= the green ↑ chip); placed BELOW = he's
  // overmatched where he sits now. One source of truth (role-clean, place-at-ability).
  const promote = [], buried = [];
  for (const r of [...H, ...P]) {
    const pl = placedAt[r.p["ID"]];
    if (!pl || !isAffiliate(r.p["Lev"])) continue;
    const d = LEVEL_RANK[pl] - LEVEL_RANK[r.p["Lev"]];
    if (d > 0) promote.push({ p: r.p, lev: r.p["Lev"], placed: pl, cur: r.cur });
    else if (d < 0) buried.push({ p: r.p, lev: r.p["Lev"], placed: pl, cur: r.cur });
  }
  promote.sort((a, b) => (b.cur ?? -99) - (a.cur ?? -99));
  buried.sort((a, b) => (a.cur ?? 99) - (b.cur ?? 99));

  // Prospect pipeline by group: a placed, young player with positive-WAA upside, counted
  // toward the role he's developed in (a future SP → SP) so it matches the rosters.
  const pipeline = { C: 0, IF: 0, OF: 0, SP: 0, RP: 0 };
  for (const r of [...H, ...P]) {
    if (!placedAt[r.p["ID"]]) continue;
    if (!(r.age != null && r.age <= 26 && r.pot != null && r.pot > 0)) continue;   // young = 26 or under (turn-27 rule)
    const grp = r.isPitcher ? r.devRole : hitterBucket(r.p);
    if (grp in pipeline) pipeline[grp]++;
  }
  const needs = [];
  for (const [grp, c] of Object.entries(pipeline)) if (c === 0) needs.push({ grp, msg: `No ${grp} prospect in the system` });

  return { org, levels, depth, promote: promote.slice(0, 12), buried: buried.slice(0, 12), pipeline, needs };
}

// `known` (a Set from resolveLeagueClubs().known) limits the list to the league's
// own clubs; SSB rows also carry KBO and South African clubs. null = every org.
export function listOrgs(hitters, pitchers, known = null) {
  const s = new Set();
  for (const p of [...hitters, ...pitchers]) {
    const o = p["ORG"];
    if (o && o !== "-" && o !== "0" && (!known || known.has(o))) s.add(o);
  }
  return [...s].sort();
}
