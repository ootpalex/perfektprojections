// ============================================================================
// viewFormat.js — formatting, search and intangibles helpers for the views
// ported from ootp-dashboard ("ours": app/src/utils/helpers.js).
//
// Every player read goes through lib/accessors.js (the Phase 4 adapter), never a
// raw column name. What differs from ours is noted per function.
// ============================================================================
import {
  num, getName, getOrg, getId, getPlayerType, isAmateur, getIntangible,
  getMlbServiceDays, getMlbServiceYears,
} from './accessors.js';

export { num };

// ours helpers.js fmt
export const fmt = (v, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(d));

// Signed, for value columns read against zero (WAA).
export const fmtSigned = (v, d = 2) => (v == null || !Number.isFinite(v) ? '—' : (v > 0 ? '+' : '') + v.toFixed(d));

// Ours shows ages to 0.1 year from DOB + game date. His rows carry a whole-year
// `Age` and no DOB, so a whole number is shown as a whole number: "22.0" would
// claim a precision the data does not have.
export const fmtAge = (v) => {
  if (v == null || !Number.isFinite(v)) return '—';
  if (Number.isInteger(v)) return String(v);
  return (Math.floor(v * 10) / 10).toFixed(1);
};

// ours helpers.js rankSuffix
export const rankSuffix = (n) => {
  if (n == null || !Number.isFinite(n)) return '—';
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

export function paginateRows(rows, page, perPage) {
  return { paged: rows.slice(page * perPage, (page + 1) * perPage), totalPages: Math.ceil(rows.length / perPage) };
}

export function searchFilter(rows, search) {
  if (!search) return rows;
  const s = search.toLowerCase();
  return rows.filter((r) => (getName(r) || '').toLowerCase().includes(s));
}

// Ours' orgLabel read meta.source/manual ("IAFA", "2042 Draft") for players
// without an org. His rows carry no such tag; Lev 'AMA' marks the draft pool.
export const orgLabel = (p) => {
  const org = getOrg(p);
  if (org !== '-') return org;
  return isAmateur(p) ? 'AMA' : 'FA';
};

// A key that is unique across both lists: a two-way player has a hitter row and
// a pitcher row with the same ID. Ours stamped `_uid` in processData.
export const playerUid = (p) => `${getPlayerType(p)}:${getId(p) ?? getName(p) ?? ''}`;

// Major-league service as the data states it: OOTP's own years figure and the
// total days. Ours printed `years.days` by splitting the days on a 172-day
// season (rosterPlanning DAYS_PER_SEASON), which re-derives an OOTP rule; the
// two fields here come straight from the pull.
export const fmtService = (p) => {
  const yrs = getMlbServiceYears(p);
  const days = getMlbServiceDays(p);
  if (yrs == null && days == null) return '—';
  if (yrs == null) return `${days} d`;
  if (days == null) return `${yrs} yr`;
  return `${yrs} yr · ${days} d`;
};

// ── intangibles composite (ours helpers.js calcRawIntangibles + Dashboard grade) ──
// OOTP grades personality H / N / L. Weights and the H/N/L scores are ours'
// (🟡 ours' constants). His rows carry Int, WrkEthic, Lead, Loy, Greed and no
// Adaptability, so 'ad' is skipped and the weights renormalise over what is
// present. Ours' 'fin' column is the one OOTP labels Greed (inverted: high
// greed is bad); here it reads Greed.
export const INT_WEIGHTS = { lea: 0.15, loy: 0.10, ad: 0.05, fin: 0.10, we: 0.35, int: 0.25 };
const INT_INVERTED = new Set(['fin']);
const INT_SOURCE_KEY = { fin: 'greed' };

function intangibleFieldScore(key, val) {
  if (!val || val === '-') return null;
  if (val === 'H') return INT_INVERTED.has(key) ? 4 : 17;
  if (val === 'L') return INT_INVERTED.has(key) ? 17 : 4;
  if (val === 'N') return 10;
  return null;
}

export function calcRawIntangibles(p) {
  let wSum = 0, wTotal = 0;
  for (const [k, w] of Object.entries(INT_WEIGHTS)) {
    const s = intangibleFieldScore(k, getIntangible(p, INT_SOURCE_KEY[k] ?? k));
    if (s != null) { wSum += s * w; wTotal += w; }
  }
  return wTotal === 0 ? null : wSum / wTotal;
}

// League-relative 20-80 grade, as ours' Dashboard enrich step: z-score of the
// raw composite over every hitter and pitcher row, 50 + 10z, clamped to 20-80.
// Returns Map(playerUid → grade).
export function intangibleGrades(players) {
  const raws = players.map((p) => [playerUid(p), calcRawIntangibles(p)]);
  const vals = raws.map(([, r]) => r).filter((v) => v != null);
  let mean = 0, std = 1;
  if (vals.length) {
    mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    std = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length) || 1;
  }
  const out = new Map();
  for (const [uid, raw] of raws) {
    out.set(uid, raw == null ? null : Math.round(Math.max(20, Math.min(80, 50 + 10 * (raw - mean) / std))));
  }
  return out;
}

// His FV engine's per-row source of the projected peak (usePlayersWithFV
// `_potentialSource`), in words for a column or a header.
export const FV_SOURCE_LABEL = {
  ML: 'ML model',
  'DEV cell': 'DEV cell',
  'measured curve': 'Measured curve',
  model: 'Assumed model',
};

// Counts of each source across a set of FV-enriched rows, in display order.
export function fvSourceCounts(rows) {
  const counts = {};
  for (const r of rows) {
    const s = r?._potentialSource ?? null;
    if (s == null) continue;
    counts[s] = (counts[s] || 0) + 1;
  }
  return Object.keys(FV_SOURCE_LABEL).filter((k) => counts[k]).map((k) => ({ key: k, label: FV_SOURCE_LABEL[k], n: counts[k] }));
}
