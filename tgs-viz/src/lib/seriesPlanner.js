/**
 * Series Planner: one locked lineup vs RHP and one vs LHP for a whole playoff series.
 *
 * Online leagues do not let a lineup change in the middle of a series. The
 * series is played in two parks, so the best nine can differ by park. This
 * module weights each park by its games, picks the 13 and the two lineups on
 * that blended basis, and prices what the lock gives up in each park.
 *
 * Every hitter value comes from two engine files of ONE league:
 *   hitters.json              NEUTRAL basis (never the My Park variant)
 *   park_lineup_values.json   ingest/park_values.py: each hitter in each club
 *                             park at full weight, stored as park minus neutral
 * Nothing here is estimated. The leagues never mix: the caller passes one
 * league's files.
 *
 * Rebuild rule (the same rule park_values.py verifies against a fresh engine run):
 *   '<POS> WAA vR|vL' in a park = neutral value + dF (1B 2B 3B SS LF CF RF),
 *                                 + dC (C) or + dDH (DH)
 *   'wOBA vR|vL', 'OBP vR|vL'   = the file's park value
 *   any 'wtd' value             = s * vR + (1 - s) * vL, s = vr_share[bats]
 *   'Max WAA *'                 = max over eligible positions plus DH
 * A blend of parks is the weighted mean of the park rows. Every rebuilt column
 * is linear in the row, so the blend of the rebuilt values is the same number.
 *
 * Only the lineup columns are rebuilt. BatR, BSR, Off Runs and the P columns
 * stay on the neutral basis, so do not display them from these records.
 */

import { optimizeRoster } from './rosterOptimizer.js';

const LINEUP_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];
const SPLITS = ['vR', 'vL'];
// hitters.json keeps full precision, the file's neutral check values are rounded to 5 dp
const STALE_TOL = 1e-5;

// ============================================================
// (a) Chance each game is played
// ============================================================

/**
 * Chance that game 1..bestOf is played when each game is an even coin flip.
 * Exact dynamic programme over the live (wins, losses) states. A state leaves
 * the table when one side reaches the clinching win count.
 * bestOf 7 -> [1, 1, 1, 1, 0.875, 0.625, 0.3125].
 */
export function gameChances(bestOf) {
  const n = Number(bestOf);
  if (!Number.isInteger(n) || n < 1 || n % 2 === 0) {
    throw new Error(`Series length must be an odd whole number, got ${bestOf}.`);
  }
  const need = (n + 1) / 2;
  let live = new Map([['0,0', 1]]);
  const chances = [];
  for (let g = 1; g <= n; g++) {
    let played = 0;
    const next = new Map();
    for (const [key, p] of live) {
      played += p;
      const [a, b] = key.split(',').map(Number);
      for (const [na, nb] of [[a + 1, b], [a, b + 1]]) {
        if (na >= need || nb >= need) continue;   // series over, no more games from here
        const k = `${na},${nb}`;
        next.set(k, (next.get(k) || 0) + p / 2);
      }
    }
    chances.push(played);
    live = next;
  }
  return chances;
}

// ============================================================
// (b) Park weights
// ============================================================

// Home patterns the page offers. Blocks alternate between the two clubs,
// starting with the club that hosts game 1.
export const PATTERN_PRESETS = {
  '2-3-2': { bestOf: 7, blocks: [2, 3, 2] },
  '2-2-1': { bestOf: 5, blocks: [2, 2, 1] },
  '2-3': { bestOf: 5, blocks: [2, 3] },
  '1-1-1': { bestOf: 3, blocks: [1, 1, 1] },
};

/** Per-game host list for a preset. firstHost hosts game 1. */
export function presetPattern(presetId, firstHost, otherHost) {
  const preset = PATTERN_PRESETS[presetId];
  if (!preset) throw new Error(`Unknown home pattern "${presetId}".`);
  const out = [];
  preset.blocks.forEach((len, i) => {
    for (let k = 0; k < len; k++) out.push(i % 2 === 0 ? firstHost : otherHost);
  });
  return out;
}

/**
 * Games per park. `pattern` is the host club of each game, in order.
 *   mode 'expected'  (default) each game counts by the chance it is played
 *   mode 'scheduled' each game counts 1 (the series goes the distance)
 * Returns { games: [{game, host, chance, weight}], byClub: {club: weight}, total }.
 */
export function parkWeights(pattern, bestOf, mode = 'expected') {
  const chances = gameChances(bestOf);
  if (!Array.isArray(pattern) || pattern.length !== chances.length) {
    throw new Error(`The home pattern needs one host for each of the ${chances.length} games.`);
  }
  if (mode !== 'expected' && mode !== 'scheduled') {
    throw new Error(`Unknown weight mode "${mode}".`);
  }
  const games = pattern.map((host, i) => ({
    game: i + 1, host, chance: chances[i], weight: mode === 'scheduled' ? 1 : chances[i],
  }));
  const byClub = {};
  let total = 0;
  for (const g of games) {
    if (!g.host) throw new Error(`Game ${g.game} has no host.`);
    byClub[g.host] = (byClub[g.host] || 0) + g.weight;
    total += g.weight;
  }
  return { games, byClub, total };
}

// ============================================================
// (c) Park records
// ============================================================

const _indexCache = new WeakMap();
function indexOf(parkValues) {
  let ix = _indexCache.get(parkValues);
  if (!ix) {
    ix = {
      field: Object.fromEntries((parkValues.fields || []).map((k, i) => [k, i])),
      park: new Map((parkValues.parks || []).map((p, i) => [p.club, i])),
    };
    _indexCache.set(parkValues, ix);
  }
  return ix;
}

function normalizeWeights(weights) {
  const pairs = Array.isArray(weights) ? weights : Object.entries(weights || {});
  const kept = pairs.map(([club, w]) => [club, Number(w)]).filter(([, w]) => Number.isFinite(w) && w > 0);
  const total = kept.reduce((s, [, w]) => s + w, 0);
  if (!(total > 0)) throw new Error('Park weights are empty.');
  return kept.map(([club, w]) => [club, w / total]);
}

const isEligibleFlag = (v) => v === true || v === 'True' || v === 'TRUE';
const finite = (v) => typeof v === 'number' && Number.isFinite(v);

/**
 * Hitters on the games-weighted blend of parks. `weights` is [[club, games], ...]
 * or {club: games}; it is normalized here.
 *
 * Returns { records, missing, stale }:
 *   records  one record per input hitter, in the same order
 *   missing  hitters the file does not hold; they keep their neutral values
 *   stale    hitters whose neutral wOBA moved since the file was built; the
 *            file's deltas belong to an older projection, so they keep their
 *            neutral values too
 */
export function blendedRecords(hitters, parkValues, weights) {
  const ix = indexOf(parkValues);
  const w = normalizeWeights(weights).map(([club, share]) => {
    if (!ix.park.has(club)) throw new Error(`"${club}" is not a park in the park values file.`);
    return [ix.park.get(club), share];
  });
  const share = parkValues.vr_share || {};
  const records = [], missing = [], stale = [];

  for (const h of hitters) {
    const id = String(h.ID);
    const rows = parkValues.hitters ? parkValues.hitters[id] : null;
    if (!rows) { missing.push(h); records.push({ ...h, _parkBasis: 'neutral' }); continue; }
    const base = parkValues.neutral ? parkValues.neutral[id] : null;
    if (base && (Math.abs(Number(h['wOBA vR']) - base[0]) > STALE_TOL
              || Math.abs(Number(h['wOBA vL']) - base[1]) > STALE_TOL)) {
      stale.push(h); records.push({ ...h, _parkBasis: 'neutral' }); continue;
    }

    const mix = (field) => {
      const j = ix.field[field];
      let v = 0;
      for (const [pi, sh] of w) v += sh * rows[pi][j];
      return v;
    };
    const o = { ...h, _parkBasis: 'park' };
    for (const sp of SPLITS) {
      for (const pos of LINEUP_POSITIONS) {
        const col = `${pos} WAA ${sp}`;
        if (!finite(h[col])) continue;
        const d = pos === 'C' ? 'dC' : pos === 'DH' ? 'dDH' : 'dF';
        o[col] = h[col] + mix(`${d}_${sp}`);
      }
      o[`wOBA ${sp}`] = mix(`wOBA_${sp}`);
      o[`OBP ${sp}`] = mix(`OBP_${sp}`);
    }
    const bats = String(h.B || '').trim();
    const s = finite(share[bats]) ? share[bats] : share.R;
    for (const head of [...LINEUP_POSITIONS.map(p => `${p} WAA`), 'wOBA', 'OBP']) {
      const r = o[`${head} vR`], l = o[`${head} vL`];
      if (finite(r) && finite(l) && finite(s)) o[`${head} wtd`] = s * r + (1 - s) * l;
    }
    const eligible = LINEUP_POSITIONS.filter(p => p === 'DH' || isEligibleFlag(h[`${p} Eligible`]));
    for (const sp of [...SPLITS, 'wtd']) {
      const vals = eligible.map(p => o[`${p} WAA ${sp}`]).filter(finite);
      if (vals.length) o[`Max WAA ${sp}`] = Math.max(...vals);
    }
    records.push(o);
  }
  return { records, missing, stale };
}

/** Hitters projected FULLY in one club's park. Same return shape as blendedRecords. */
export function recordsInPark(hitters, parkValues, club) {
  return blendedRecords(hitters, parkValues, [[club, 1]]);
}

/**
 * Do the factors the file was built from still match parks.json? Returns the
 * clubs whose factors moved (run park_values.py again for those to be right).
 */
export function changedParkFactors(parkValues, parks, clubs) {
  const KEYS = ['avg_rhb', 'avg_lhb', 'avg', 'doubles', 'triples', 'hr_rhb', 'hr_lhb', 'hr'];
  const live = new Map((parks || []).map(p => [p.Name, p]));
  const out = [];
  for (const club of clubs) {
    const a = (parkValues.parks || []).find(p => p.club === club);
    const b = live.get(club);
    if (!a || !b) continue;
    if (KEYS.some(k => Math.abs(Number(a[k]) - Number(b[k])) > 1e-9)) out.push(club);
  }
  return out;
}

// ============================================================
// (d) The plan
// ============================================================

const idOf = (p) => String(p.ID ?? p.Name);

function lineupView(lineup, split) {
  const order = (lineup?.battingOrder || []).map(e => ({
    slot: e.slot, position: e.position, role: e.role, player: e.player,
    waa: e.waa, woba: e.woba, obp: e.obp,
  }));
  return {
    split,
    order,
    bench: lineup?.bench || [],
    totalWAA: order.reduce((s, e) => s + (e.waa || 0), 0),
  };
}

// Value of a lineup (who plays where) on a given set of park records.
function lineupValue(order, recById, split) {
  return order.reduce((s, e) => {
    const v = recById.get(idOf(e.player))?.[`${e.position} WAA ${split}`];
    return s + (finite(v) ? v : 0);
  }, 0);
}

// Position by position: where the park's own best nine differs from the locked nine.
function lineupSwaps(lockedOrder, parkOrder, recById, split) {
  const lockedAt = new Map(lockedOrder.map(e => [e.position, e.player]));
  const swaps = [];
  for (const e of parkOrder) {
    const was = lockedAt.get(e.position);
    if (was && idOf(was) === idOf(e.player)) continue;
    const col = `${e.position} WAA ${split}`;
    const parkWAA = recById.get(idOf(e.player))?.[col];
    const lockedWAA = was ? recById.get(idOf(was))?.[col] : null;
    swaps.push({
      position: e.position,
      parkPlayer: e.player,
      lockedPlayer: was || null,
      parkWAA: finite(parkWAA) ? parkWAA : null,
      lockedWAA: finite(lockedWAA) ? lockedWAA : null,
      gain: (finite(parkWAA) ? parkWAA : 0) - (finite(lockedWAA) ? lockedWAA : 0),
    });
  }
  return swaps;
}

/**
 * Plan a series.
 *
 * @param {Object} o
 *   hitters      NEUTRAL hitters.json rows of one league
 *   pitchers     that league's pitchers (the optimizer wants them; they do not
 *                change a batting lineup)
 *   parkValues   park_lineup_values.json of the same league
 *   team         my club (exact ORG / parks.json Name)
 *   pattern      host club of each game, in order (length = bestOf)
 *   bestOf       3 | 5 | 7 (any odd number works)
 *   weightMode   'expected' (default) | 'scheduled'
 *   level        'MLB' (default) | 'AAA' | null for every level in the file
 *   winNow       default true: starters only where the position rating has reached potential
 *   excludeInjured, clearedInjured, vrShare, league: passed to optimizeRoster
 *
 * @returns {Object}
 *   games, weights          the game strip and the games per park
 *   roster                  the 13, on the series-blended basis
 *   locked.vR / locked.vL   { order:[{slot, position, player, waa, woba, obp}], bench, totalWAA }
 *   parks[]                 per park: its own best vR / vL lineup from the same 13,
 *                           the locked lineup's value there, the cost of the lock
 *                           and the swaps the park alone would make
 *   missing, stale          hitters of the pool that kept neutral values
 */
export function planSeries({
  hitters, pitchers = [], parkValues, team, pattern, bestOf,
  weightMode = 'expected', level = 'MLB', winNow = true,
  excludeInjured = false, clearedInjured = null, vrShare = null, league = null,
}) {
  if (!parkValues || !parkValues.hitters) throw new Error('No park values file.');
  if (!team) throw new Error('Pick your club.');

  const w = parkWeights(pattern, bestOf, weightMode);
  const clubs = Object.keys(w.byClub);
  const weights = clubs.map(club => ({ club, games: w.byClub[club], share: w.byClub[club] / w.total }));

  // Exact club match (optimizeRoster's own org filter is a substring test).
  const pool = (hitters || []).filter(h => h.ORG === team && (!level || h.Lev === level));
  if (!pool.length) throw new Error(`No ${level || ''} hitters for ${team}.`.replace('  ', ' '));

  const opts = {
    teamOrg: team, levelFilter: level || null, league, winNow,
    excludeInjured, clearedInjured, vrShare,
  };

  // The 13 and the two locked lineups, on the games-weighted blend of the parks.
  const blend = blendedRecords(pool, parkValues, clubs.map(c => [c, w.byClub[c]]));
  const lockedRun = optimizeRoster(blend.records, pitchers, opts);
  const roster = lockedRun.rosteredHitters || [];
  const locked = {
    vR: lineupView(lockedRun.lineupVsRHP, 'vR'),
    vL: lineupView(lockedRun.lineupVsLHP, 'vL'),
  };

  // Each park alone: the same 13 men, projected fully in that park.
  const rosterIds = new Set(roster.map(idOf));
  const thirteen = pool.filter(h => rosterIds.has(idOf(h)));
  const parks = clubs.map(club => {
    const recs = recordsInPark(thirteen, parkValues, club).records;
    const recById = new Map(recs.map(r => [idOf(r), r]));
    const best = optimizeRoster(recs, pitchers, opts);
    const out = { club, games: w.byClub[club] };
    for (const [split, lineup] of [['vR', best.lineupVsRHP], ['vL', best.lineupVsLHP]]) {
      const view = lineupView(lineup, split);
      const bestValue = lineupValue(view.order, recById, split);
      const lockedValue = lineupValue(locked[split].order, recById, split);
      const swaps = lineupSwaps(locked[split].order, view.order, recById, split);
      out[split] = {
        order: view.order, bench: view.bench,
        bestValue, lockedValue,
        // the park's own nine is optimal there, so this cannot be negative beyond float noise
        cost: Math.max(0, bestValue - lockedValue),
        swaps,
      };
    }
    return out;
  });

  return {
    team, level, bestOf, weightMode,
    games: w.games, weights, totalGames: w.total,
    roster, locked, parks,
    missing: blend.missing, stale: blend.stale,
    poolSize: pool.length,
  };
}
