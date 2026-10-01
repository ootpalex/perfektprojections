/**
 * Measured development curve (engine/agecurve_fit.py output).
 *
 * age_curve.json holds per-age mean dWAA per year measured from a ratings
 * archive. curve[age].mean is the change from age to age+1 for ALL players at
 * that age. LEAGUE-WIDE numbers only: nothing player-specific feeds back into
 * any projection. futureValue.js walks this curve to build every player's
 * year-by-year path (growth shape to 27, measured decline after).
 */

const cache = new Map();

// The curve every league uses comes from the DEV league (user, 2026-09-23:
// "get the measured curve updated to what our dev tests show, on all the
// leagues"): an all-AI OOTP 27 league with TRUE ratings dumped once a
// game-year, so its curve is development and nothing else. A league's own
// curve (scouted archive) is the fallback when DEV's file is missing.
export const MEASURED_CURVE_LEAGUE = 'DEV';

// Growth shape window. Measured growth is about zero at 27 (DEV mean +0.01)
// and negative from 28, so the shape runs 16..27 and the path grows to 27.
export const GROWTH_START_AGE = 16;
export const GROWTH_END_AGE = 27;
// The path stops here. Ages past the curve's last entry reuse its last mean.
export const PATH_END_AGE = 40;

async function fetchCurve(league) {
  try {
    const res = await fetch(`/data/${league}/age_curve.json`);
    const ct = res.headers.get('content-type') || '';
    if (res.ok && !ct.includes('text/html')) return await res.json();
  } catch { /* absent */ }
  return null;
}

export async function loadAgeCurve(league) {
  if (cache.has(league)) return cache.get(league);
  let curve = await fetchCurve(MEASURED_CURVE_LEAGUE);
  if (curve) curve = { ...curve, source_league: MEASURED_CURVE_LEAGUE };
  else curve = await fetchCurve(league);
  cache.set(league, curve);
  return curve;
}

// ---------------------------------------------------------------------------
// Curve access: mean at an age, and the growth shape G(a).
// ---------------------------------------------------------------------------

const shapeCache = new WeakMap();

function rawMean(curve, a) {
  const c = curve[a] ?? curve[String(a)];
  return c && Number.isFinite(c.mean) ? c.mean : null;
}

function buildShape(ageCurve) {
  const curve = ageCurve.curve;
  const ages = Object.keys(curve)
    .map(Number)
    .filter(a => Number.isFinite(a) && rawMean(curve, a) !== null)
    .sort((x, y) => x - y);
  if (!ages.length) return null;
  const first = ages[0];
  const last = ages[ages.length - 1];

  // Mean dWAA from age a to a+1. Ages past the last entry use the last
  // available mean; ages before the first use the first. A hole inside the
  // range takes the nearest lower age.
  const mean = (age) => {
    const a = Math.floor(age);
    if (!Number.isFinite(a)) return null;
    if (a <= first) return rawMean(curve, first);
    if (a >= last) return rawMean(curve, last);
    for (let t = a; t >= first; t--) {
      const m = rawMean(curve, t);
      if (m !== null) return m;
    }
    return null;
  };

  // G(a) = sum(max(0, mean(t)) for t in 16..a-1) / sum(max(0, mean(t)) for t in 16..26)
  // G(16) = 0, G(27) = 1. Ages outside 16..27 clamp to the ends.
  const cum = {};
  let run = 0;
  for (let a = GROWTH_START_AGE; a <= GROWTH_END_AGE; a++) {
    cum[a] = run;
    if (a < GROWTH_END_AGE) run += Math.max(0, mean(a) ?? 0);
  }
  const total = run;
  if (!(total > 0)) return null;
  const G = (age) => {
    const a = Math.floor(age);
    if (!Number.isFinite(a) || a <= GROWTH_START_AGE) return 0;
    if (a >= GROWTH_END_AGE) return 1;
    return cum[a] / total;
  };

  // closable(a) = 1 - prod(1 - closure(t) for t in a..26): the share of a
  // (ceiling - current) gap that gap holders of age a still close by 27,
  // from the curve's measured per-age closure rates. A curve without
  // closure data closes everything (no cap).
  const rawClosure = (a) => {
    const c = curve[a] ?? curve[String(a)];
    return c && Number.isFinite(c.closure) ? Math.min(1, Math.max(0, c.closure)) : null;
  };
  const hasClosure = ages.some(a => rawClosure(a) !== null);
  const closableByAge = {};
  for (let a = GROWTH_START_AGE; a <= GROWTH_END_AGE; a++) {
    let open = 1;
    for (let t = a; t < GROWTH_END_AGE; t++) open *= 1 - (rawClosure(t) ?? 0);
    closableByAge[a] = 1 - open;
  }
  const closable = (age) => {
    if (!hasClosure) return 1;
    const a = Math.floor(age);
    if (!Number.isFinite(a) || a <= GROWTH_START_AGE) return closableByAge[GROWTH_START_AGE];
    if (a >= GROWTH_END_AGE) return 0;
    return closableByAge[a];
  };

  return { mean, G, closable, first, last };
}

/**
 * The curve as functions: mean(age), G(age) and closable(age) (see
 * buildShape). Built once per curve object. null when the curve is missing
 * or has no positive growth, which is the caller's signal to use the
 * assumed model.
 */
export function curveShape(ageCurve) {
  if (!ageCurve || typeof ageCurve !== 'object' || !ageCurve.curve) return null;
  if (shapeCache.has(ageCurve)) return shapeCache.get(ageCurve);
  const s = buildShape(ageCurve);
  shapeCache.set(ageCurve, s);
  return s;
}

/** Mean dWAA from age to age+1, or null. */
export function curveMean(ageCurve, age) {
  const s = curveShape(ageCurve);
  return s ? s.mean(age) : null;
}

/** Growth shape G(age) in 0..1, or null. */
export function growthShare(ageCurve, age) {
  const s = curveShape(ageCurve);
  return s ? s.G(age) : null;
}
